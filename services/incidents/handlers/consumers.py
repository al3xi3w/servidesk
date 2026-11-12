"""Consumidores SQS de ms-incidents."""

import json
import uuid

from common.db import tenant_conn
from common.events import publish


def on_ci_status_changed(event, context):
    failures = []

    for record in event["Records"]:
        conn = None
        transaction_started = False

        try:
            # 1. Leer el evento de SQS
            msg = json.loads(record["body"])

            if msg["eventType"] != "CIStatusChanged":
                continue

            # 2. Procesar únicamente los CI caídos
            if msg["data"].get("status") != "down":
                continue

            # 3. Obtener los identificadores del evento
            event_id = str(uuid.UUID(msg["eventId"]))
            tenant_id = msg["tenantId"]
            ci_id = str(uuid.UUID(msg["data"]["ciId"]))

            # 4. Conectarse al schema del tenant
            conn = tenant_conn(f"tenant_{tenant_id}")

            # 5. Iniciar transacción
            conn.run("BEGIN")
            transaction_started = True

            # 6. Evitar procesar el mismo evento dos veces
            processed = conn.run(
                """
                INSERT INTO processed_events (
                    event_id,
                    event_type
                )
                VALUES (
                    :event_id,
                    :event_type
                )
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                event_id=event_id,
                event_type="CIStatusChanged",
            )

            if not processed:
                conn.run("COMMIT")
                transaction_started = False
                print(f"Evento duplicado ignorado: {event_id}")
                continue

            # 7. Buscar la política SLA de P2
            policies = conn.run(
                """
                SELECT id, resolution_minutes
                FROM sla_policies
                WHERE priority = 'P2'
                ORDER BY id
                LIMIT 1
                """
            )

            if not policies:
                raise ValueError(
                    "No existe una política SLA para P2"
                )

            sla_policy_id = policies[0][0]
            resolution_minutes = policies[0][1]

            # 8. Bloquear la generación de claves
            conn.run(
                """
                SELECT pg_advisory_xact_lock(
                    hashtext(current_schema() || ':incident_key')
                )
                """
            )

            # 9. Obtener el siguiente número de incidente
            rows = conn.run(
                """
                SELECT COALESCE(
                    MAX(SUBSTRING(key FROM 5)::integer),
                    0
                )
                FROM incidents
                WHERE key ~ '^INC-[0-9]{6}$'
                """
            )

            next_number = rows[0][0] + 1

            if next_number > 999999:
                raise RuntimeError(
                    "Se agotó el rango de claves de incidentes"
                )

            incident_key = f"INC-{next_number:06d}"

            # 10. Crear incidente automático P2
            rows = conn.run(
                """
                INSERT INTO incidents (
                    key,
                    title,
                    description,
                    status,
                    priority,
                    sla_policy_id,
                    sla_due_at,
                    sla_breached,
                    ci_id,
                    channel,
                    created_at
                )
                VALUES (
                    :key,
                    :title,
                    :description,
                    'new',
                    'P2',
                    :sla_policy_id,
                    (
                        CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                        + :resolution_minutes * INTERVAL '1 minute'
                    ),
                    FALSE,
                    :ci_id,
                    'auto',
                    CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                )
                RETURNING id, key, title, priority,
                          ci_id, channel
                """,
                key=incident_key,
                title=f"CI caído: {ci_id}",
                description=(
                    f"Se detectó automáticamente que el CI "
                    f"{ci_id} cambió a estado down."
                ),
                sla_policy_id=sla_policy_id,
                resolution_minutes=resolution_minutes,
                ci_id=ci_id,
            )

            cols = [c["name"] for c in conn.columns]
            incident = dict(zip(cols, rows[0]))

            # 11. Confirmar la transacción
            conn.run("COMMIT")
            transaction_started = False

            # 12. Publicar IncidentCreated
            publish(
                event_type="IncidentCreated",
                tenant_id=tenant_id,
                data={
                    "incidentId": str(incident["id"]),
                    "key": incident["key"],
                    "title": incident["title"],
                    "priority": "P2",
                    "ciId": ci_id,
                    "teamId": None,
                    "assigneeId": None,
                    "reporterId": None,
                    "channel": "auto",
                    "actorId": None,
                },
                source="ms-incidents",
            )

            print(
                f"Incidente automático creado: "
                f"{incident_key} para CI {ci_id}"
            )

        except Exception as exc:
            # 13. Revertir transacción si hubo error
            if conn is not None and transaction_started:
                try:
                    conn.run("ROLLBACK")
                except Exception:
                    print("No se pudo revertir la transacción")

            print(
                f"Error procesando mensaje "
                f"{record.get('messageId')}: {exc}"
            )

            failures.append({
                "itemIdentifier": record["messageId"]
            })

    # 14. Informar los mensajes fallidos a Lambda
    return {"batchItemFailures": failures}
