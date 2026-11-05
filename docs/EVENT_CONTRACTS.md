# Contratos de eventos (SNS + SQS)

**Versión:** 0.9 (propuesta) · **Fecha:** 2026-11-05 · **Estado:** pendiente de aprobación del equipo

Todos los microservicios publican en un único tópico SNS (`servidesk-itsm-events-<stage>`, declarado en
`infra/serverless.yml`). Cada consumidor tiene su propia cola SQS con DLQ, suscrita al tópico con un filtro por
`eventType`. Los servicios nunca se llaman entre sí por HTTP.

## 1. Qué está implementado hoy

| Pieza | Estado | Dónde |
| --- | --- | --- |
| Tópico SNS | Declarado | `infra/serverless.yml` (`EventsTopic`) |
| Función `publish()` con sobre y atributos `eventType`/`tenantId` | Implementada, sin uso | `infra/layers/common/python/common/events.py` |
| Cola `CiStatusQueue` + `CiStatusDLQ` (maxReceiveCount 3) + suscripción `eventType: [CIStatusChanged]`, `RawMessageDelivery: true` | Declaradas | `services/incidents/serverless.yml` |
| Consumidor `on_ci_status_changed` | Esqueleto (`TODO`) | `services/incidents/handlers/consumers.py` |
| Cualquier publicación de evento | **No existe** | ningún handler llama a `publish()` |
| Resto de colas y consumidores | **No existen** | solo en el documento de diseño |

## 2. Sobre del mensaje (envelope)

Este formato **ya está implementado** en `events.py` y no se cambia:

```json
{
  "eventId": "0d3c6a1e-7b2f-4c59-9e84-5a1f2b3c4d5e",
  "eventType": "IncidentCreated",
  "tenantId": "pacifico",
  "occurredAt": "2026-11-05T15:04:05.123456Z",
  "source": "ms-incidents",
  "data": { "incidentId": "5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d" }
}
```

| Campo | Tipo | Regla |
| --- | --- | --- |
| `eventId` | UUID v4 | Único por evento. Es la clave de deduplicación. |
| `eventType` | string PascalCase | Uno de la tabla de la sección 3 (decisión D2). |
| `tenantId` | string | Código del tenant (`andina`), el mismo `tenant_id` del JWT. Se toma **siempre** del contexto del authorizer o del evento que se está procesando, nunca de un body. |
| `occurredAt` | ISO 8601 UTC | Fecha de creación del evento. |
| `source` | string | `SERVICE_NAME` del publicador (`ms-identity`, `ms-cmdb`, …). |
| `data` | objeto | Carga del evento, en `camelCase` (decisión D1). El identificador del recurso va siempre en `data.<recurso>Id`. |

Atributos SNS (para los filtros): `eventType` y `tenantId`, ambos `String`. Las suscripciones usan
`RawMessageDelivery: true`, así que el `body` del mensaje SQS **es** el sobre (no viene envuelto por SNS).

Regla para quien publica: llamar a `publish()` **después** de confirmar la transacción en la BD, nunca antes.

## 3. Catálogo de eventos

Equivalencias con los nombres pedidos: `incident.created` = `IncidentCreated`, `incident.updated` = `IncidentUpdated`,
`problem.created` = `ProblemCreated`, `change.approved` = `ChangeApproved`, `request.created` = `RequestSubmitted`.

| Evento | Publica | Cuándo | Cola consumidora (servicio) | Qué hace el consumidor | Estado |
| --- | --- | --- | --- | --- | --- |
| `TenantCreated` | ms-identity | alta de tenant | `<servicio>-tenant-provisioning-q` (los 6) | crea el schema y corre las migraciones | C |
| `UserCreated` | ms-identity | `POST /users` | — | (sin consumidor en esta versión) | C |
| `CIStatusChanged` | ms-cmdb | `PUT /cis/{id}/status`, `DELETE /cis/{id}` | `CiStatusQueue` (incidents) | si `status = down`, crea incidente P2 con `channel = auto` | B |
| `IncidentCreated` | ms-incidents | `POST /incidents` y consumidor de CI | `problems-incidents-q` (problems), `identity-notify-q` (identity) | problems: 3+ incidentes del mismo CI en 24 h → crea problema; identity: notifica al equipo | C |
| `IncidentUpdated` | ms-incidents | `PATCH /incidents/{id}`, `PUT …/status` | `identity-notify-q` | notifica al nuevo asignado | C (nuevo) |
| `IncidentResolved` | ms-incidents | paso a `resolved` | `identity-notify-q` | notifica al reportante | C |
| `IncidentSlaBreached` | ms-incidents (Lambda programada) | SLA vencido | `identity-notify-q` | avisa al líder del equipo | C |
| `ProblemCreated` | ms-problems | `POST /problems` o creación automática | `identity-notify-q` | notifica al responsable | C |
| `ProblemIncidentsLinked` | ms-problems | `POST /problems/{id}/incidents` o creación con `incident_ids` | `incidents-problem-q` (incidents) | fija `incidents.problem_id` | C (nuevo) |
| `KnownErrorPublished` | ms-problems | `POST /problems/{id}/known-error` | `incidents-kedb-q` (incidents), `identity-notify-q` | agrega el workaround como comentario en los incidentes vinculados | C |
| `ChangeSubmitted` | ms-changes | paso a `submitted` | `identity-notify-q` | notifica a los admin (CAB) | C |
| `ChangeApproved` | ms-changes | `POST /changes/{id}/approve` o `standard` enviado | `identity-notify-q` | notifica al solicitante | C |
| `ChangeRejected` | ms-changes | `POST /changes/{id}/reject` | `identity-notify-q` | notifica al solicitante con el motivo | C (nuevo) |
| `ChangeImplemented` | ms-changes | paso a `implemented` | `cmdb-changes-q` (cmdb), `problems-changes-q` (problems) | cmdb: aplica `new_version` y registra `ci_history`; problems: cierra el problema con ese `fix_change_id` | C |
| `RequestSubmitted` | ms-requests | `POST /requests` | `identity-notify-q` | notifica a aprobadores o al equipo | C |
| `RequestApproved` | ms-requests | aprobación | `requests-fulfillment-q` (requests), `identity-notify-q` | crea `fulfillment_tasks`; notifica | C |
| `RequestRejected` | ms-requests | rechazo | `identity-notify-q` | notifica al solicitante | C (nuevo) |
| `RequestFulfilled` | ms-requests | paso a `fulfilled` | `identity-notify-q` | notifica al solicitante | C |

Estado: B = declarado sin implementar; C = propuesto. "Nuevo" = no estaba en el documento de diseño.

## 4. Carga (`data`) de cada evento

Los IDs son UUID salvo que se indique. `actorId` es el `sub` del usuario que causó el evento (`null` si lo causó el sistema).

```jsonc
// TenantCreated
{ "tenantCode": "unitec", "schema": "tenant_unitec", "name": "UniTec Campus" }

// UserCreated
{ "userId": "…", "email": "jorge.huaman@andina.pe", "role": "customer", "actorId": "…" }

// CIStatusChanged
{ "ciId": "8c2d…", "name": "srv-historias-01", "previousStatus": "operational", "status": "down", "actorId": "…" }

// IncidentCreated
{ "incidentId": "5b1e…", "key": "INC-004512", "title": "No carga el sistema de historias clínicas",
  "priority": "P1", "ciId": "8c2d…", "teamId": "b6f0…", "assigneeId": null, "reporterId": "c4d5…",
  "channel": "portal", "actorId": "c4d5…" }

// IncidentUpdated
{ "incidentId": "5b1e…", "key": "INC-004512", "changedFields": ["assignee_id", "status"],
  "status": "in_progress", "assigneeId": "3f9a…", "teamId": "b6f0…", "actorId": "3f9a…" }

// IncidentResolved
{ "incidentId": "5b1e…", "key": "INC-004512", "reporterId": "c4d5…", "resolvedAt": "2026-11-05T09:02:00Z", "actorId": "3f9a…" }

// IncidentSlaBreached
{ "incidentId": "5b1e…", "key": "INC-004512", "priority": "P1", "teamId": "b6f0…", "slaDueAt": "2026-11-05T12:10:00Z" }

// ProblemCreated
{ "problemId": "7d8e…", "key": "PRB-000045", "priority": "P1", "ciId": "8c2d…", "ownerId": "3f9a…",
  "incidentIds": ["5b1e…"], "actorId": "3f9a…" }

// ProblemIncidentsLinked
{ "problemId": "7d8e…", "incidentIds": ["5b1e…", "6c2f…"], "actorId": "3f9a…" }

// KnownErrorPublished
{ "problemId": "7d8e…", "knownErrorId": "1a2b…", "symptom": "Error 502 al abrir historias clínicas…",
  "workaround": "Reiniciar el pool de conexiones…", "incidentIds": ["5b1e…", "6c2f…"], "actorId": "3f9a…" }

// ChangeSubmitted
{ "changeId": "2a3b…", "key": "CHG-000210", "type": "normal", "risk": "medium",
  "plannedStart": "2026-11-08T03:00:00Z", "requesterId": "3f9a…", "actorId": "3f9a…" }

// ChangeApproved / ChangeRejected
{ "changeId": "2a3b…", "key": "CHG-000210", "requesterId": "3f9a…", "approverId": "9b8a…",
  "comment": "Aprobado en CAB del 06/11.", "actorId": "9b8a…" }

// ChangeImplemented
{ "changeId": "2a3b…", "key": "CHG-000210", "problemId": "7d8e…",
  "cis": [{ "ciId": "8c2d…", "newVersion": "15.1.8" }], "actorId": "3f9a…" }

// RequestSubmitted / RequestApproved / RequestRejected / RequestFulfilled
{ "requestId": "0f1e…", "key": "REQ-000987", "catalogItemId": "9e8d…", "catalogItemName": "Acceso VPN",
  "status": "pending_approval", "requesterId": "c4d5…", "actorId": "c4d5…" }
```

Ejemplo completo de `ChangeApproved` tal como llega al `body` de SQS:

```json
{
  "eventId": "6f7a8b9c-0d1e-4f2a-8b3c-4d5e6f7a8b9c",
  "eventType": "ChangeApproved",
  "tenantId": "andina",
  "occurredAt": "2026-11-06T17:45:12.000000Z",
  "source": "ms-changes",
  "data": {
    "changeId": "2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d",
    "key": "CHG-000210",
    "requesterId": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
    "approverId": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
    "comment": "Aprobado en CAB del 06/11.",
    "actorId": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
  }
}
```

## 5. Reintentos, DLQ y duplicados

| Tema | Regla |
| --- | --- |
| Entrega | SNS → SQS estándar: **al menos una vez**, sin orden garantizado. |
| Reintentos | Si la Lambda falla, el mensaje vuelve a la cola al vencer el `VisibilityTimeout`. Tras **3 recepciones** (`maxReceiveCount: 3`, ya configurado en `CiStatusQueue`) pasa a la DLQ. |
| VisibilityTimeout | Propuesto: `60` s en cada cola (la de hoy usa el valor por defecto de 30 s; AWS recomienda al menos 6 veces el timeout de la Lambda, que en Serverless v3 es 6 s por defecto). |
| Fallos parciales | Propuesto: `functionResponseType: ReportBatchItemFailures` en el evento `sqs` y devolver `{"batchItemFailures": [{"itemIdentifier": messageId}]}`, para no reintentar los mensajes que sí se procesaron. |
| DLQ | Una por cola, retención propuesta de 14 días (`MessageRetentionPeriod: 1209600`). En la demo se muestra con 0 mensajes. Para reprocesar: "Start DLQ redrive" en la consola de SQS. |
| Duplicados | Cada servicio consumidor tiene, en cada schema, `processed_events(event_id UUID PRIMARY KEY, event_type VARCHAR(60), processed_at TIMESTAMP DEFAULT now())` (decisión D10). En la misma transacción del efecto: `INSERT INTO processed_events … ON CONFLICT DO NOTHING`; si no insertó ninguna fila, el evento ya se procesó y se descarta. |
| Aislamiento | El consumidor abre `tenant_conn("tenant_" + tenantId)` por mensaje; `tenant_conn` valida el nombre del schema. Un mensaje con `tenantId` desconocido va a la DLQ. |
| Orden | No se asume orden. Ej.: si `ProblemIncidentsLinked` llega antes que el incidente exista, el consumidor ignora ese ID. |

Plantilla de consumidor propuesta:

```python
def handle(event, context):
    failures = []
    for record in event["Records"]:
        conn = None
        try:
            msg = json.loads(record["body"])            # RawMessageDelivery
            conn = tenant_conn(f"tenant_{msg['tenantId']}")
            conn.run("BEGIN")
            done = conn.run(
                "INSERT INTO processed_events (event_id, event_type) VALUES (:id, :t) "
                "ON CONFLICT DO NOTHING RETURNING event_id", id=msg["eventId"], t=msg["eventType"])
            if done:
                apply_effect(conn, msg)                  # lógica del servicio
            conn.run("COMMIT")
        except Exception:
            if conn is not None:
                conn.run("ROLLBACK")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
```

## 6. Cambios necesarios para cumplir este contrato

1. `services/incidents/handlers/consumers.py`: terminar el `TODO`, aplicar la plantilla anterior.
2. ms-cmdb: publicar `CIStatusChanged` desde `PUT /cis/{id}/status` y `DELETE /cis/{id}`.
3. Cada servicio consumidor: declarar su cola, DLQ, `QueuePolicy` y suscripción con `FilterPolicy` (copiar el bloque de
   `services/incidents/serverless.yml`).
4. Agregar `processed_events` a las migraciones de identity, cmdb, incidents, problems y requests (D10).
