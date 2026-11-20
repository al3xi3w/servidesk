"""ms-cmdb · Consumidor SQS cmdb-changes-q.

ChangeImplemented (ms-changes) trae cis: [{ciId, newVersion}]. Para cada CI con versión nueva
se actualiza configuration_items.version y se registra en ci_history (source = ms-changes,
change_id = el cambio). Idempotente (processed_events, D10); fallos en batchItemFailures.
"""

import json
import uuid

from common.db import tenant_conn


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


def _apply_versions(conn, data):
    change_id = _uuid_or_none(data.get("changeId"))
    actor_id = _uuid_or_none(data.get("actorId"))
    updated = 0
    for item in data.get("cis") or []:
        ci_id = _uuid_or_none((item or {}).get("ciId"))
        new_version = ((item or {}).get("newVersion") or "").strip()[:50]
        if not ci_id or not new_version:
            continue
        rows = conn.run(
            "SELECT version FROM configuration_items "
            "WHERE id = CAST(:id AS uuid) AND status <> 'retired' FOR UPDATE",
            id=ci_id,
        )
        if not rows or rows[0][0] == new_version:
            continue
        conn.run(
            "UPDATE configuration_items SET version = CAST(:version AS varchar), "
            "updated_at = (now() AT TIME ZONE 'utc') WHERE id = CAST(:id AS uuid)",
            version=new_version,
            id=ci_id,
        )
        conn.run(
            "INSERT INTO ci_history (ci_id, field, old_value, new_value, actor_id, source, change_id) "
            "VALUES (CAST(:ci_id AS uuid), 'version', CAST(:old AS text), CAST(:new AS text), "
            "CAST(:actor_id AS uuid), 'ms-changes', CAST(:change_id AS uuid))",
            ci_id=ci_id,
            old=rows[0][0],
            new=new_version,
            actor_id=actor_id,
            change_id=change_id,
        )
        updated += 1
    return updated


def on_change_implemented(event, context):
    failures = []
    for record in event.get("Records", []):
        conn = None
        in_tx = False
        try:
            msg = _parse_message(record["body"])
            if msg.get("eventType") != "ChangeImplemented":
                continue
            event_id = str(uuid.UUID(msg["eventId"]))

            conn = tenant_conn(f"tenant_{msg['tenantId']}")
            conn.run("BEGIN")
            in_tx = True
            fresh = conn.run(
                "INSERT INTO processed_events (event_id, event_type) "
                "VALUES (CAST(:event_id AS uuid), 'ChangeImplemented') "
                "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                event_id=event_id,
            )
            if fresh:
                updated = _apply_versions(conn, msg.get("data") or {})
                print(f"ChangeImplemented {event_id}: versión aplicada en {updated} CI")
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
