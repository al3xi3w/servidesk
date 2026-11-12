# ms-incidents — ServiDesk

## Descripción

Microservicio encargado de gestionar incidentes, prioridades, políticas SLA y comentarios dentro de ServiDesk.

Utiliza PostgreSQL con aislamiento multi-tenant mediante schemas y se integra con otros microservicios mediante eventos SNS/SQS.

## Estado de implementación

| Funcionalidad | Estado |
|---|---|
| IN-01 · `GET /incidents` | Implementado y probado |
| IN-02 · `POST /incidents` | Implementado y probado |
| IN-03 · `GET /incidents/{id}` | Implementado y probado |
| IN-04 · `PATCH /incidents/{id}` | Implementado y probado |
| IN-05 · `PUT /incidents/{id}/status` | Implementado y probado |
| IN-06 · `GET /incidents/{id}/comments` | Pendiente |
| IN-07 · `POST /incidents/{id}/comments` | Pendiente |
| Consumidor SQS `CIStatusChanged` | Implementado y probado |
| Publicación de eventos SNS | Implementada; probada con mocks |
| Migraciones SQL | `001_init.sql` y `002_events.sql` preparadas |

### Funcionalidades implementadas

- Creación manual de incidentes con validaciones y restricciones según el rol.
- Listado de incidentes con paginación, filtros, búsqueda y ordenamiento.
- Consulta individual de incidentes con aislamiento por tenant y usuario.
- Actualización de incidentes y recálculo automático de prioridad y SLA.
- Transiciones de estado según las reglas del contrato.
- Registro de cambios de estado en `incident_events`.
- Creación de comentarios públicos al resolver incidentes.
- Creación automática de incidentes P2 cuando un CI cambia a `down`.
- Deduplicación de mensajes mediante `processed_events`.
- Publicación de `IncidentCreated`, `IncidentUpdated` e `IncidentResolved`.

## Pruebas unitarias

Se ejecutaron **62 pruebas unitarias exitosas** con `pytest` y mocks.

Las pruebas cubren los handlers de incidentes y el consumidor de eventos SQS. No requieren conexión real a AWS ni PostgreSQL.

Para ejecutarlas desde la raíz del repositorio:

```bash
python -m pytest services/incidents/tests/ -v
```

## Base de datos y migraciones

**Base de datos:** `db_incidents`

Las tablas se crean dentro del schema correspondiente a cada tenant.

| Archivo | Contenido |
|---|---|
| `001_init.sql` | `sla_policies`, `incidents`, `incident_comments` |
| `002_events.sql` | `incident_events`, `processed_events` |

El archivo `handlers/migrate.py` fue actualizado para detectar y ejecutar ambas migraciones en orden.

**Estado:** implementación preparada, pendiente de validación contra PostgreSQL real.

## Pendientes para completar el microservicio

### 1. Implementar IN-06 e IN-07

- IN-06: listar comentarios de un incidente, con paginación y restricciones de visibilidad.
- IN-07: agregar comentarios, validando permisos, contenido y estado del incidente.

### 2. Configurar los endpoints en `serverless.yml`

Registrar las rutas restantes y vincularlas a sus respectivos handlers con el Lambda Authorizer.

Verificar también la configuración de permisos y eventos SQS.

### 3. Definir y registrar políticas SLA

El equipo debe confirmar los valores oficiales de `response_minutes` y `resolution_minutes` para las prioridades P1, P2, P3 y P4.

Los handlers ya consultan la tabla `sla_policies`, pero necesitan que existan políticas configuradas para crear y recalcular incidentes.

Los valores deberán registrarse mediante una migración SQL.

### 4. Completar la integración de eventos

- Habilitar `ReportBatchItemFailures` para el consumidor SQS.
- Verificar los permisos y la publicación SNS.
- Validar los formatos definitivos de los eventos con los microservicios consumidores.

### 5. Validar las migraciones e integración

- Probar las migraciones en PostgreSQL.
- Verificar el aislamiento de datos entre tenants.
- Ejecutar pruebas de integración de los endpoints.
- Verificar la comunicación con API Gateway, Lambda, RDS, SNS y SQS.

### 6. Tablas pendientes del contrato

La tabla `incident_attachments` está pendiente de definición e implementación según el alcance del contrato.

La tabla `incident_events` ya fue contemplada en `002_events.sql`.

## Observaciones

- El microservicio está en desarrollo y aún no se ha desplegado.
- Las 62 pruebas exitosas son unitarias y utilizan mocks.
- Las migraciones nuevas todavía no se han validado en una base de datos real.
- Las políticas SLA oficiales siguen pendientes de aprobación.
- Los contratos del equipo corresponden a la propuesta `v0.9`.