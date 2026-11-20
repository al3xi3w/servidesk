"""Consumidores SQS de ms-problems.

- problems-incidents-q · IncidentCreated   -> con 3+ incidentes del mismo CI en 24 h crea un
                                              problema (o los vincula al problema abierto del CI)
- problems-changes-q   · ChangeImplemented -> cierra el problema corregido por ese cambio

Idempotentes (processed_events, D10). Los eventos resultantes (ProblemCreated,
ProblemIncidentsLinked) se publican después del COMMIT.
"""

import json
import uuid

from common.db import tenant_conn
from common.events import publish

RECURRENCE_THRESHOLD = 3
RECURRENCE_WINDOW_HOURS = 24
PRIORITIES = ("P1", "P2", "P3", "P4")


def _uuid_or_none(value):
    try:
        return str(uuid.UUID(str(value))) if value else None
    except ValueError:
        return None


def _parse_message(body):
    msg = json.loads(body)
    if msg.get("Type") == "Notification" and "Message" in msg:
        msg = json.loads(msg["Message"])
    return msg


def _consume(event, expected_type, apply):
    """apply(conn, msg) -> (resumen, [eventos a publicar como dict(event_type, data)])."""
    failures = []
    for record in event.get("Records", []):
        conn = None
        in_tx = False
        try:
            msg = _parse_message(record["body"])
            if msg.get("eventType") != expected_type:
                continue
            event_id = str(uuid.UUID(msg["eventId"]))
            tenant_id = msg["tenantId"]

            conn = tenant_conn(f"tenant_{tenant_id}")
            conn.run("BEGIN")
            in_tx = True

            fresh = conn.run(
                "INSERT INTO processed_events (event_id, event_type) "
                "VALUES (CAST(:event_id AS uuid), :event_type) "
                "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                event_id=event_id,
                event_type=expected_type,
            )
            outgoing = []
            if fresh:
                summary, outgoing = apply(conn, msg)
                print(f"{expected_type} {event_id}: {summary}")
            else:
                print(f"Evento duplicado ignorado: {event_id}")

            conn.run("COMMIT")
            in_tx = False

            for out in outgoing:
                publish(
                    event_type=out["event_type"],
                    tenant_id=tenant_id,
                    data=out["data"],
                    source="ms-problems",
                )
        except Exception as exc:  # noqa: BLE001 - se reintenta vía SQS
            if conn is not None and in_tx:
                try:
                    conn.run("ROLLBACK")
                except Exception:  # noqa: BLE001
                    print("No se pudo revertir la transacción")
            print(f"Error procesando mensaje {record.get('messageId')}: {exc}")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


# ------------------------------------------------------------------ problems-incidents-q


def _next_problem_key(conn):
    conn.run("SELECT pg_advisory_xact_lock(hashtext(current_schema() || ':problem_key'))")
    rows = conn.run(
        "SELECT COALESCE(MAX(SUBSTRING(key FROM 5)::integer), 0) "
        "FROM problems WHERE key ~ '^PRB-[0-9]{6}$'"
    )
    next_number = rows[0][0] + 1
    if next_number > 999999:
        raise RuntimeError("Se agotó el rango de claves de problemas")
    return f"PRB-{next_number:06d}"


def _link(conn, problem_id, incident_ids):
    for incident_id in incident_ids:
        conn.run(
            "INSERT INTO problem_incidents (problem_id, incident_id) "
            "VALUES (CAST(:problem_id AS uuid), CAST(:incident_id AS uuid)) "
            "ON CONFLICT (problem_id, incident_id) DO NOTHING",
            problem_id=problem_id,
            incident_id=incident_id,
        )


def _detect_recurrence(conn, msg):
    data = msg.get("data") or {}
    incident_id = _uuid_or_none(data.get("incidentId"))
    ci_id = _uuid_or_none(data.get("ciId"))
    if not incident_id or not ci_id:
        return "sin CI: no aplica la regla de recurrencia", []

    priority = data.get("priority") if data.get("priority") in PRIORITIES else None
    conn.run(
        "INSERT INTO ci_incident_log (incident_id, ci_id, priority, title, occurred_at) "
        "VALUES (CAST(:incident_id AS uuid), CAST(:ci_id AS uuid), :priority, :title, "
        "COALESCE(CAST(:occurred_at AS timestamptz) AT TIME ZONE 'UTC', CURRENT_TIMESTAMP AT TIME ZONE 'UTC')) "
        "ON CONFLICT (incident_id) DO NOTHING",
        incident_id=incident_id,
        ci_id=ci_id,
        priority=priority,
        title=(data.get("title") or "")[:200] or None,
        occurred_at=msg.get("occurredAt"),
    )

    # Serializa la decisión por CI: dos mensajes simultáneos no crean dos problemas.
    conn.run("SELECT pg_advisory_xact_lock(hashtext(current_schema() || ':ci_problem:' || :ci_id))",
             ci_id=ci_id)

    group = conn.run(
        "SELECT l.incident_id, l.priority, l.title, "
        "EXISTS (SELECT 1 FROM problem_incidents pi WHERE pi.incident_id = l.incident_id) AS linked "
        "FROM ci_incident_log l "
        "WHERE l.ci_id = CAST(:ci_id AS uuid) "
        "AND l.occurred_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
        f"- interval '{int(RECURRENCE_WINDOW_HOURS)} hours' "
        "ORDER BY l.occurred_at",
        ci_id=ci_id,
    )
    if len(group) < RECURRENCE_THRESHOLD:
        return f"{len(group)} incidente(s) del CI en 24 h (umbral: {RECURRENCE_THRESHOLD})", []

    free = [str(row[0]) for row in group if not row[3]]
    if not free:
        return "los incidentes ya estaban vinculados", []

    open_problem = conn.run(
        "SELECT id, key FROM problems WHERE ci_id = CAST(:ci_id AS uuid) "
        "AND status NOT IN ('resolved', 'closed') ORDER BY created_at DESC LIMIT 1",
        ci_id=ci_id,
    )
    if open_problem:
        problem_id, key = str(open_problem[0][0]), open_problem[0][1]
        _link(conn, problem_id, free)
        return f"vinculó {len(free)} incidente(s) a {key}", [{
            "event_type": "ProblemIncidentsLinked",
            "data": {"problemId": problem_id, "incidentIds": free, "actorId": None},
        }]

    priorities = [row[1] for row in group if row[1] in PRIORITIES]
    worst = min(priorities, key=PRIORITIES.index) if priorities else "P3"
    latest_title = next((row[2] for row in reversed(group) if row[2]), "falla sin título")
    title = f"[Automático] {len(group)} fallas en 24 h en el mismo CI: {latest_title}"[:200]
    key = _next_problem_key(conn)

    rows = conn.run(
        "INSERT INTO problems (key, title, description, status, priority, ci_id, owner_id, created_at) "
        "VALUES (:key, :title, :description, 'new', :priority, CAST(:ci_id AS uuid), NULL, "
        "CURRENT_TIMESTAMP AT TIME ZONE 'UTC') RETURNING id",
        key=key,
        title=title,
        description=(
            f"ServiDesk detectó {len(group)} incidentes del mismo elemento de configuración en las "
            f"últimas {RECURRENCE_WINDOW_HOURS} horas y abrió este problema para buscar la causa raíz."
        ),
        priority=worst,
        ci_id=ci_id,
    )
    problem_id = str(rows[0][0])
    _link(conn, problem_id, free)

    return f"creó {key} con {len(free)} incidente(s)", [
        {"event_type": "ProblemCreated", "data": {
            "problemId": problem_id, "key": key, "title": title, "priority": worst, "ciId": ci_id,
            "ownerId": None, "incidentIds": free, "actorId": None}},
        {"event_type": "ProblemIncidentsLinked", "data": {
            "problemId": problem_id, "incidentIds": free, "actorId": None}},
    ]


def on_incident_created(event, context):
    return _consume(event, "IncidentCreated", _detect_recurrence)


# ------------------------------------------------------------------ problems-changes-q


def _close_fixed_problem(conn, msg):
    data = msg.get("data") or {}
    change_id = _uuid_or_none(data.get("changeId"))
    if not change_id:
        return "evento sin changeId", []
    rows = conn.run(
        "UPDATE problems SET status = 'closed', "
        "fix_change_id = COALESCE(fix_change_id, CAST(:change_id AS uuid)), "
        "root_cause = COALESCE(NULLIF(trim(root_cause), ''), :root_cause) "
        "WHERE (fix_change_id = CAST(:change_id AS uuid) OR id = CAST(:problem_id AS uuid)) "
        "AND status <> 'closed' RETURNING key",
        change_id=change_id,
        problem_id=_uuid_or_none(data.get("problemId")),
        root_cause=f"Corregido con la actualización {data.get('key') or change_id}.",
    )
    if not rows:
        return "ningún problema esperaba este cambio", []
    return f"cerró {', '.join(r[0] for r in rows)}", []


def on_change_implemented(event, context):
    return _consume(event, "ChangeImplemented", _close_fixed_problem)
