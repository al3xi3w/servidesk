# ms-incidents — ServiDesk

## Descripción

Microservicio encargado de gestionar **incidentes, prioridades, políticas SLA, estados y comentarios** dentro de ServiDesk.

Utiliza PostgreSQL con aislamiento multi-tenant mediante esquemas (`schemas`) y se integra con otros microservicios mediante eventos SNS/SQS.

## Estado de implementación

**Estado actual:** lógica Python de los 7 endpoints implementada y **90 pruebas unitarias aprobadas**.

| Funcionalidad | Estado |
|---|---|
| IN-01 · `GET /incidents` | Implementado y probado |
| IN-02 · `POST /incidents` | Implementado y probado |
| IN-03 · `GET /incidents/{id}` | Implementado y probado |
| IN-04 · `PATCH /incidents/{id}` | Implementado y probado |
| IN-05 · `PUT /incidents/{id}/status` | Implementado y probado |
| IN-06 · `GET /incidents/{id}/comments` | Implementado y probado |
| IN-07 · `POST /incidents/{id}/comments` | Implementado y probado |
| Consumidor SQS `CIStatusChanged` | Implementado y probado |
| Publicación de eventos SNS | Implementada; probada con mocks |
| Migraciones SQL | `001_init.sql` y `002_events.sql` preparadas |

Los siete endpoints tienen lógica Python implementada. Esto no significa que todas las rutas estén configuradas o desplegadas en AWS.

## 1. Endpoints implementados

### IN-01 — Listar incidentes

**`GET /incidents`**

Permite consultar incidentes con paginación, filtros y ordenamiento.

Funcionalidades:

- Paginación mediante `page` y `limit`.
- Límite predeterminado de 20 registros y máximo de 100.
- Filtros por estado, prioridad, impacto y urgencia.
- Filtros por CI, equipo, responsable y problema relacionado.
- Búsqueda por clave o título.
- Ordenamiento por fecha, prioridad, vencimiento SLA, estado o clave.
- Filtro de incidentes con SLA incumplido.
- Restricción de visibilidad para `customer`.

**Permisos:** `admin`, `agent` y `customer`.

Los usuarios `customer` únicamente pueden consultar incidentes donde sean el reportante.

Respuesta exitosa: `200 OK`.

### IN-02 — Crear incidente

**`POST /incidents`**

Permite registrar incidentes manualmente.

Validaciones principales:

- `title`: obligatorio, entre 3 y 200 caracteres.
- `description`: máximo 5000 caracteres.
- `impact`: `high`, `medium` o `low`.
- `urgency`: `high`, `medium` o `low`.
- `ci_id`, `team_id` y `assignee_id`: UUID opcionales.

El backend calcula automáticamente:

- Clave correlativa, por ejemplo `INC-000001`.
- Estado inicial `new`.
- Prioridad mediante la matriz de impacto y urgencia.
- Política SLA correspondiente.
- Fecha límite de resolución.
- Usuario reportante.
- Canal `portal`.

Los usuarios `customer` no pueden asignar directamente un equipo ni un agente.

La operación utiliza una transacción PostgreSQL y publica el evento `IncidentCreated`.

Respuesta exitosa: `201 Created`.

### IN-03 — Consultar incidente

**`GET /incidents/{id}`**

Permite consultar el detalle de un incidente mediante su UUID.

Validaciones:

- UUID válido.
- Existencia del incidente.
- Aislamiento por tenant.
- Restricción por reportante para `customer`.

Si el incidente no existe o un `customer` intenta consultar uno ajeno, devuelve `404 Not Found`.

Respuesta exitosa: `200 OK`.

### IN-04 — Actualizar incidente

**`PATCH /incidents/{id}`**

Permite actualizar los campos:

- `title`
- `description`
- `impact`
- `urgency`
- `ci_id`
- `team_id`
- `assignee_id`
- `problem_id`

**Permisos:** `admin` y `agent`.

Reglas:

- Se rechazan campos no permitidos.
- Se validan textos y UUID.
- No se permite actualizar incidentes cerrados.
- Si cambia el impacto o la urgencia, se recalculan la prioridad y el SLA.
- La actualización utiliza una transacción PostgreSQL.
- Publica el evento `IncidentUpdated`.

Respuestas principales:

- `200`: actualización exitosa.
- `400`: datos inválidos.
- `403`: usuario sin permisos.
- `404`: incidente inexistente.
- `409`: incidente cerrado.

### IN-05 — Cambiar estado

**`PUT /incidents/{id}/status`**

Permite administrar el ciclo de vida de un incidente.

Estados disponibles:

- `new`
- `in_progress`
- `on_hold`
- `resolved`
- `closed`

Reglas principales:

- Solo se permiten las transiciones definidas en el contrato.
- Para resolver un incidente es obligatorio registrar un comentario.
- Un `customer` únicamente puede cerrar o reabrir sus propios incidentes resueltos.
- Los cambios de estado se registran en `incident_events`.
- Al resolver un incidente se registra un comentario público.
- Las transiciones inválidas devuelven `409 Conflict`.

Eventos publicados:

- `IncidentUpdated`
- `IncidentResolved`, cuando el incidente pasa a `resolved`.

Respuesta exitosa: `200 OK`.

### IN-06 — Listar comentarios

**`GET /incidents/{id}/comments`**

Permite consultar los comentarios asociados a un incidente.

**Permisos:** `admin`, `agent` y `customer`.

Funcionalidades implementadas:

- Validación del UUID del incidente.
- Comprobación de existencia del incidente.
- Paginación con `page` y `limit`.
- Límite predeterminado de 20 comentarios y máximo de 100.
- Orden cronológico por `created_at` e `id`.
- Aislamiento por tenant.
- Control de visibilidad de comentarios internos.

**Reglas para `customer`:**

- Solo puede consultar comentarios de sus propios incidentes.
- No puede visualizar comentarios con `internal = true`.
- La restricción se aplica directamente en PostgreSQL.

Ejemplo de respuesta:

```json
{
  "data": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "incident_id": "550e8400-e29b-41d4-a716-446655440000",
      "author_id": "550e8400-e29b-41d4-a716-446655440001",
      "body": "Estamos revisando el incidente",
      "internal": false,
      "created_at": "2026-11-05T08:25:13Z"
    }
  ],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "total_pages": 1
  }
}
```

Respuesta exitosa: `200 OK`.

Se implementaron 12 pruebas unitarias para este endpoint.

### IN-07 — Agregar comentario

**`POST /incidents/{id}/comments`**

Permite registrar comentarios públicos o internos.

Ejemplo de solicitud:

```json
{
  "body": "Estamos revisando el incidente",
  "internal": false
}
```

**Permisos:** `admin`, `agent` y `customer`.

Validaciones:

- `body`: texto obligatorio de 1 a 5000 caracteres.
- `internal`: booleano opcional, por defecto `false`.
- Se rechazan campos adicionales no permitidos.
- El identificador del incidente debe ser un UUID válido.
- El autor se obtiene del contexto autenticado, no del cuerpo de la solicitud.

Reglas:

- `admin` y `agent` pueden registrar comentarios públicos o internos.
- `customer` únicamente puede comentar sus propios incidentes.
- `customer` no puede crear comentarios internos.
- No se permite agregar comentarios a incidentes `closed`.
- La operación utiliza una transacción PostgreSQL con bloqueo de fila.
- Ante errores de base de datos se ejecuta `ROLLBACK`.

Ejemplo de respuesta:

```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440010",
    "incident_id": "550e8400-e29b-41d4-a716-446655440000",
    "author_id": "550e8400-e29b-41d4-a716-446655440001",
    "body": "Estamos revisando el incidente",
    "internal": false,
    "created_at": "2026-11-05T08:25:13Z"
  }
}
```

Respuesta exitosa: `201 Created`.

Se implementaron 18 pruebas unitarias para este endpoint.

## 2. Prioridades y políticas SLA

La prioridad de los incidentes se calcula automáticamente mediante una matriz de impacto y urgencia.

| Impacto / Urgencia | High | Medium | Low |
|---|---|---|---|
| High | P1 | P2 | P3 |
| Medium | P2 | P3 | P4 |
| Low | P3 | P4 | P4 |

La tabla `sla_policies` almacena:

- Prioridad.
- Tiempo de respuesta (`response_minutes`).
- Tiempo de resolución (`resolution_minutes`).

La fecha límite de resolución se calcula utilizando la política correspondiente.

**Pendiente:** definir y registrar los valores SLA oficiales para P1, P2, P3 y P4.

## 3. Integración mediante eventos SNS/SQS

### Eventos publicados

| Evento | Descripción |
|---|---|
| `IncidentCreated` | Se registra un incidente nuevo |
| `IncidentUpdated` | Se actualiza un incidente o su estado |
| `IncidentResolved` | Un incidente pasa al estado `resolved` |

La publicación se realiza mediante el helper compartido `common.events.publish`.

### Consumidor `CIStatusChanged`

El consumidor SQS `on_ci_status_changed` está implementado.

Cuando recibe un evento `CIStatusChanged` cuyo estado es `down`:

1. Valida los identificadores del evento.
2. Selecciona el esquema correspondiente al tenant.
3. Comprueba si el evento ya fue procesado.
4. Busca la política SLA de prioridad P2.
5. Genera una clave correlativa.
6. Crea automáticamente un incidente P2.
7. Confirma la transacción.
8. Publica `IncidentCreated`.

Los eventos procesados se registran en `processed_events` para evitar duplicaciones.

El consumidor devuelve los identificadores de mensajes fallidos mediante `batchItemFailures`, permitiendo reintentos.

**Pendiente de integración:** verificar la conexión SNS/SQS, los permisos correspondientes y la configuración de `ReportBatchItemFailures` en AWS.

## 4. Base de datos y migraciones

**Base de datos:** `db_incidents`.

Las tablas se crean dentro del esquema PostgreSQL correspondiente a cada tenant.

| Archivo | Tablas |
|---|---|
| `001_init.sql` | `sla_policies`, `incidents`, `incident_comments` |
| `002_events.sql` | `incident_events`, `processed_events` |

### Tablas principales

**`incidents`**

Almacena la información principal de los incidentes, incluyendo:

- Identificadores y clave.
- Título y descripción.
- Estado, impacto, urgencia y prioridad.
- Política SLA y fecha de vencimiento.
- Reportante y responsable.
- Equipo y CI asociados.
- Problema relacionado.
- Fechas de creación y resolución.

**`incident_comments`**

Almacena los comentarios:

- `id`
- `incident_id`
- `author_id`
- `body`
- `internal`
- `created_at`

La columna `incident_id` tiene una clave foránea hacia `incidents`.

**`incident_events`**

Registra el historial de cambios de estado.

**`processed_events`**

Permite identificar mensajes ya procesados por los consumidores SQS.

### Migraciones

El archivo `handlers/migrate.py` está preparado para ejecutar `001_init.sql` y `002_events.sql` en orden.

**Estado:** las migraciones todavía requieren validación contra una instancia real de PostgreSQL.

## 5. Pruebas unitarias

Las pruebas utilizan:

- Python.
- `unittest`.
- `unittest.mock`.
- `MagicMock`.
- `pytest` como ejecutor.

Las dependencias externas se simulan mediante mocks, por lo que las pruebas no requieren AWS ni PostgreSQL real.

### Resultado actual

**90 pruebas unitarias aprobadas**, confirmadas mediante una ejecución local completa el 20 de noviembre de 2026.

Las pruebas incluyen:

- Listado, creación y consulta de incidentes.
- Actualización y cambios de estado.
- Validación de permisos.
- Cálculo de prioridad y políticas SLA.
- Transacciones y manejo de errores.
- Publicación de eventos.
- Procesamiento de mensajes SQS.
- Paginación y privacidad de comentarios.
- Creación de comentarios públicos e internos.

De las pruebas nuevas:

| Endpoint | Pruebas agregadas |
|---|---:|
| IN-06 · Listar comentarios | 12 |
| IN-07 · Agregar comentarios | 18 |

### Ejecutar todas las pruebas

Desde la raíz del repositorio:

```powershell
python -m pytest services/incidents/tests/ -v
```

Resultado de la última ejecución local:

```text
90 passed
```

### Ejecutar únicamente IN-06

```powershell
python -m pytest services/incidents/tests/test_incidents.py::TestListIncidentComments -v
```

### Ejecutar únicamente IN-07

```powershell
python -m pytest services/incidents/tests/test_incidents.py::TestAddIncidentComment -v
```

## 6. Estructura del microservicio

```text
services/incidents/
├── handlers/
│   ├── incidents.py
│   ├── consumers.py
│   └── migrate.py
├── migrations/
│   ├── 001_init.sql
│   └── 002_events.sql
├── tests/
│   └── ...
├── serverless.yml
└── README.md
```

- `incidents.py`: lógica HTTP de los siete endpoints.
- `consumers.py`: consumidor SQS de eventos `CIStatusChanged`.
- `migrate.py`: ejecución de migraciones.
- `migrations/`: definiciones SQL.
- `tests/`: pruebas unitarias.
- `serverless.yml`: configuración de infraestructura y despliegue.

## 7. Pendientes antes de completar la integración

### Backend

- Revisar la lógica de los siete endpoints y detectar casos límite que las pruebas con mocks no cubren.
- Confirmar y registrar las políticas SLA oficiales.
- Validar las migraciones contra PostgreSQL real.
- Revisar las necesidades de la tabla `incident_attachments`, pendiente de definición e implementación según el alcance acordado.
- Verificar la consistencia de los contratos de eventos entre microservicios.
- Completar y probar los consumidores adicionales que requiera la integración con otros servicios.

### Equipo de infraestructura e integración

- Configurar las rutas HTTP pendientes en `serverless.yml`.
- Vincular los handlers con el Lambda Authorizer.
- Desplegar las funciones Lambda.
- Verificar conexiones a RDS.
- Configurar y validar la comunicación SNS/SQS.
- Habilitar `ReportBatchItemFailures`.
- Ejecutar pruebas de integración y extremo a extremo.

La configuración de Serverless y AWS se realiza por el equipo responsable de infraestructura, de forma separada al desarrollo de la lógica Python.

## 8. Observaciones

- Los siete endpoints de `ms-incidents` están implementados a nivel de lógica Python.
- Se aprobaron **90 pruebas unitarias**.
- IN-06 e IN-07 están implementados y probados con mocks.
- El consumidor SQS `CIStatusChanged` está implementado.
- Las migraciones todavía requieren validación en PostgreSQL real.
- Las políticas SLA oficiales siguen pendientes.
- El microservicio aún no cuenta con una validación de despliegue completo.
- Los contratos del proyecto corresponden a la propuesta `v0.9`.

## 9. Resumen final

| Componente | Estado |
|---|---|
| Endpoints IN-01 a IN-07 | 7 de 7 implementados |
| Pruebas unitarias | 90 aprobadas |
| Comentarios públicos e internos | Implementados |
| Permisos y aislamiento por tenant | Probados unitariamente |
| Consumidor `CIStatusChanged` | Implementado |
| Migraciones SQL | Preparadas |
| Integración AWS | Pendiente |
| Políticas SLA oficiales | Pendientes |

**Estado del microservicio:** lógica principal implementada y probada unitariamente. Pendiente de validación de base de datos, configuración de infraestructura y pruebas de integración.
## Consumidores SQS (F3)

| Cola | Evento | Efecto | Handler |
|---|---|---|---|
| `incidents-ci-q` | `CIStatusChanged` (down) | incidente automático P2, canal `auto` | `consumers.on_ci_status_changed` |
| `incidents-problem-q` | `ProblemIncidentsLinked` | fija `incidents.problem_id` | `problem_events.on_problem_incidents_linked` |
| `incidents-kedb-q` | `KnownErrorPublished` | comenta el workaround (público) en los incidentes vinculados no cerrados | `problem_events.on_known_error_published` |

Todas con DLQ (`maxReceiveCount: 3`), `ReportBatchItemFailures` e idempotencia por `processed_events`.
La migración `003_sla_policies.sql` carga las políticas SLA base (P1 4 h, P2 8 h, P3 24 h, P4 72 h).
