"""Consumidores SQS de ms-incidents para eventos de ms-problems.

- incidents-problem-q  · ProblemIncidentsLinked -> fija incidents.problem_id
- incidents-kedb-q     · KnownErrorPublished    -> comenta el workaround en los incidentes vinculados

Ambos son idempotentes (processed_events, decisión D10) y devuelven batchItemFailures.
"""

import json
import uuid

from common.db import tenant_conn


def _uuid_or_none(value):
    try:
        return str(uuid.UUID(str(value))) if value else None
    except ValueError:
        return None


def _uuid_list(values):
    return sorted({u for u in (_uuid_or_none(v) for v in (values or [])) if u})


def _parse_message(body):
    msg = json.loads(body)
    if msg.get("Type") == "Notification" and "Message" in msg:
        msg = json.loads(msg["Message"])
    return msg


def _consume(event, expected_type, apply):
    """Bucle común: deduplica, ejecuta apply(conn, data) en una transacción por mensaje."""
    failures = []
    for record in event.get("Records", []):
        conn = None
        in_tx = False
        try:
            msg = _parse_message(record["body"])
            if msg.get("eventType") != expected_type:
                continue
            event_id = str(uuid.UUID(msg["eventId"]))

            conn = tenant_conn(f"tenant_{msg['tenantId']}")
            conn.run("BEGIN")
            in_tx = True

            fresh = conn.run(
                "INSERT INTO processed_events (event_id, event_type) "
                "VALUES (CAST(:event_id AS uuid), :event_type) "
                "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                event_id=event_id,
                event_type=expected_type,
            )
            if fresh:
                summary = apply(conn, msg.get("data") or {})
                print(f"{expected_type} {event_id}: {summary}")
            else:
                print(f"Evento duplicado ignorado: {event_id}")

            conn.run("COMMIT")
            in_tx = False
        except Exception as exc:  # noqa: BLE001 - se reintenta vía SQS
            if conn is not None and in_tx:
                try:
                    conn.run("ROLLBACK")
                except Exception:  # noqa: BLE001
                    print("No se pudo revertir la transacción")
            print(f"Error procesando mensaje {record.get('messageId')}: {exc}")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


# ------------------------------------------------------------------ incidents-problem-q


def _link_incidents(conn, data):
    problem_id = _uuid_or_none(data.get("problemId"))
    ids = _uuid_list(data.get("incidentIds"))
    if not problem_id or not ids:
        return "sin problema o sin incidentes"
    rows = conn.run(
        "UPDATE incidents SET problem_id = CAST(:problem_id AS uuid) "
        "WHERE id = ANY(CAST(:ids AS uuid[])) "
        "AND problem_id IS DISTINCT FROM CAST(:problem_id AS uuid) RETURNING id",
        problem_id=problem_id,
        ids=ids,
    )
    return f"problem_id fijado en {len(rows)} incidente(s)"


def on_problem_incidents_linked(event, context):
    return _consume(event, "ProblemIncidentsLinked", _link_incidents)


# ------------------------------------------------------------------ incidents-kedb-q


def _comment_workaround(conn, data):
    problem_id = _uuid_or_none(data.get("problemId"))
    workaround = (data.get("workaround") or "").strip()
    if not problem_id or not workaround:
        return "sin problema o sin workaround"
    rows = conn.run(
        "INSERT INTO incident_comments (incident_id, author_id, body, internal) "
        "SELECT i.id, CAST(:author_id AS uuid), CAST(:body AS text), FALSE FROM incidents i "
        "WHERE (i.problem_id = CAST(:problem_id AS uuid) OR i.id = ANY(CAST(:ids AS uuid[]))) "
        "AND i.status <> 'closed' RETURNING id",
        author_id=_uuid_or_none(data.get("actorId")),
        body=f"Solución temporal mientras se corrige: {workaround}",
        problem_id=problem_id,
        ids=_uuid_list(data.get("incidentIds")),
    )
    return f"workaround comentado en {len(rows)} incidente(s)"


def on_known_error_published(event, context):
    return _consume(event, "KnownErrorPublished", _comment_workaround)
