"""ms-identity · Consumidor SQS identity-notify-q.

Recibe los eventos de dominio de los demás microservicios (SNS -> SQS) y crea
notificaciones en la bandeja de cada usuario. Las reglas de destinatarios son las
mismas que simula el modo demo del frontend (frontend/src/mocks/adapter.ts).

Idempotencia: processed_events (decisión D10). Los mensajes fallidos se devuelven en
batchItemFailures para que SQS los reintente y, tras 3 intentos, vayan a la DLQ.
"""

import json
import uuid

from common.db import tenant_conn

RISK_ES = {"low": "bajo", "medium": "medio", "high": "alto"}
REQUEST_VERB = {
    "RequestApproved": "aprobado",
    "RequestRejected": "rechazado",
    "RequestFulfilled": "entregado",
}

# Tipos de evento que este consumidor convierte en notificaciones (también es el
# FilterPolicy de la suscripción SNS en serverless.yml).
NOTIFY_EVENT_TYPES = (
    "IncidentCreated",
    "IncidentUpdated",
    "IncidentResolved",
    "ProblemCreated",
    "KnownErrorPublished",
    "ChangeSubmitted",
    "ChangeApproved",
    "ChangeRejected",
    "RequestSubmitted",
    "RequestApproved",
    "RequestRejected",
    "RequestFulfilled",
)


def _uuid_or_none(value):
    try:
        return str(uuid.UUID(str(value))) if value else None
    except ValueError:
        return None


def _admins(conn):
    return [str(r[0]) for r in conn.run("SELECT id FROM users WHERE role = 'admin' AND active")]


def _team_members(conn, team_id):
    if not team_id:
        return []
    rows = conn.run(
        "SELECT u.id FROM team_members tm JOIN users u ON u.id = tm.user_id "
        "WHERE tm.team_id = CAST(:team_id AS uuid) AND u.role <> 'customer' AND u.active",
        team_id=team_id,
    )
    return [str(r[0]) for r in rows]


def build_notifications(conn, event_type, data):
    """Devuelve una lista de (destinatarios, título, cuerpo, resource_type, resource_id)."""
    key = data.get("key") or ""
    out = []

    if event_type == "IncidentCreated":
        assignee = _uuid_or_none(data.get("assigneeId"))
        if assignee:
            to = [assignee]
        else:
            to = _team_members(conn, _uuid_or_none(data.get("teamId")))
            if data.get("priority") in ("P1", "P2"):
                to += _admins(conn)
        if not to:
            to = _admins(conn)
        out.append((to, f"Nueva falla {key} ({data.get('priority')})", data.get("title"),
                    "incident", data.get("incidentId")))

    elif event_type == "IncidentUpdated":
        if "assignee_id" in (data.get("changedFields") or []) and data.get("assigneeId"):
            out.append(([data["assigneeId"]], f"Te asignaron la falla {key}",
                        "Revísala en tu lista de fallas.", "incident", data.get("incidentId")))

    elif event_type == "IncidentResolved":
        out.append(([data.get("reporterId")], f"Resolvimos tu falla {key}",
                    "Confírmalo o avísanos si sigue pasando.", "incident", data.get("incidentId")))

    elif event_type == "ProblemCreated":
        body = "Busca la causa de fondo." if data.get("actorId") else \
            "Se detectaron varias fallas iguales en poco tiempo."
        out.append(([data.get("ownerId")], f"Te asignaron el problema recurrente {key}",
                    body, "problem", data.get("problemId")))

    elif event_type == "KnownErrorPublished":
        # identity no conoce a los asignados de los incidentes: se avisa a los administradores.
        out.append((_admins(conn), "Hay una solución temporal publicada", data.get("workaround"),
                    "problem", data.get("problemId")))

    elif event_type == "ChangeSubmitted":
        risk = RISK_ES.get(data.get("risk"), data.get("risk"))
        out.append((_admins(conn), f"La actualización {key} espera tu aprobación",
                    f"Riesgo {risk}.", "change", data.get("changeId")))

    elif event_type in ("ChangeApproved", "ChangeRejected"):
        approved = event_type == "ChangeApproved"
        default = "Ya puedes programarlo." if approved else "Revisa el motivo."
        out.append(([data.get("requesterId")],
                    f"La actualización {key} fue {'aprobada' if approved else 'rechazada'}",
                    data.get("comment") or default, "change", data.get("changeId")))

    elif event_type == "RequestSubmitted":
        item = data.get("catalogItemName") or "Solicitud de servicio"
        out.append(([data.get("requesterId")], f"Recibimos tu pedido {key}", item,
                     "request", data.get("requestId")))
        if data.get("status") == "pending_approval":
            out.append((_admins(conn), f"El pedido {key} necesita tu aprobación", item,
                        "request", data.get("requestId")))

    elif event_type in REQUEST_VERB:
        item = data.get("catalogItemName") or "Solicitud de servicio"
        out.append(([data.get("requesterId")], f"Tu pedido {key} fue {REQUEST_VERB[event_type]}",
                    item, "request", data.get("requestId")))

    return out


def _insert_notifications(conn, event_type, notifications, actor_id):
    """Inserta solo para usuarios existentes y activos. No se notifica al propio actor."""
    count = 0
    for recipients, title, body, resource_type, resource_id in notifications:
        ids = sorted({r for r in (_uuid_or_none(x) for x in recipients) if r and r != actor_id})
        if not ids:
            continue
        rows = conn.run(
            "INSERT INTO notifications (user_id, event_type, title, body, resource_type, resource_id) "
            "SELECT u.id, CAST(:event_type AS varchar), CAST(:title AS varchar), CAST(:body AS text), "
            "CAST(:resource_type AS varchar), CAST(:resource_id AS uuid) "
            "FROM users u WHERE u.id = ANY(CAST(:ids AS uuid[])) AND u.active "
            "RETURNING id",
            event_type=event_type,
            title=str(title)[:200],
            body=None if body is None else str(body),
            resource_type=resource_type,
            resource_id=_uuid_or_none(resource_id),
            ids=ids,
        )
        count += len(rows)
    return count


def _parse_message(body):
    msg = json.loads(body)
    # Si la suscripción no usa RawMessageDelivery, el evento viene dentro del sobre de SNS.
    if msg.get("Type") == "Notification" and "Message" in msg:
        msg = json.loads(msg["Message"])
    return msg


def on_notify_event(event, context):
    failures = []

    for record in event.get("Records", []):
        conn = None
        in_tx = False
        try:
            msg = _parse_message(record["body"])
            event_type = msg["eventType"]
            if event_type not in NOTIFY_EVENT_TYPES:
                continue

            event_id = str(uuid.UUID(msg["eventId"]))
            data = msg.get("data") or {}
            actor_id = _uuid_or_none(data.get("actorId"))

            conn = tenant_conn(f"tenant_{msg['tenantId']}")
            conn.run("BEGIN")
            in_tx = True

            fresh = conn.run(
                "INSERT INTO processed_events (event_id, event_type) "
                "VALUES (CAST(:event_id AS uuid), :event_type) "
                "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                event_id=event_id,
                event_type=event_type,
            )
            if not fresh:
                conn.run("COMMIT")
                in_tx = False
                print(f"Evento duplicado ignorado: {event_id}")
                continue

            notifications = build_notifications(conn, event_type, data)
            created = _insert_notifications(conn, event_type, notifications, actor_id)

            conn.run("COMMIT")
            in_tx = False
            print(f"{event_type} {event_id}: {created} notificación(es)")

        except Exception as exc:  # noqa: BLE001 - se reintenta vía SQS
            if conn is not None and in_tx:
                try:
                    conn.run("ROLLBACK")
                except Exception:  # noqa: BLE001
                    print("No se pudo revertir la transacción")
            print(f"Error procesando mensaje {record.get('messageId')}: {exc}")
            failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failures}
