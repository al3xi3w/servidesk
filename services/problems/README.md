# ms-problems — ServiDesk

Microservicio de **gestión de problemas**, análisis de causa raíz, vinculación con incidentes y base de errores conocidos (**KEDB**) de ServiDesk.

> **Estado del desarrollo (noviembre de 2026):** lógica Python de PR-01 a PR-07 implementada. **94 pruebas unitarias de endpoints aprobadas**. La migración inicial cuenta con 10 pruebas unitarias aprobadas en una ejecución anterior. `GET /problems` fue probado en AWS con respuesta HTTP 200. Los otros seis endpoints todavía no cuentan con validación HTTP real y su configuración en Serverless corresponde al equipo de integración.

## 1. Referencia y alcance

Referencia funcional: `docs/API_CONTRACTS.md`, sección **8.4 — ms-problems**.

- **Base de datos:** PostgreSQL, `db_problems`.
- **Multitenancy:** aislamiento mediante esquemas PostgreSQL obtenidos del contexto autenticado (`tenant_ctx`), por ejemplo `tenant_andina`.
- **Roles autorizados:** `admin` y `agent`. El rol `customer` no accede a estos endpoints.
- **Listado:** respuesta `{ "data": Problem[], "meta": {...} }`.
- **Detalle y operaciones de escritura:** respuesta `{ "data": ProblemDetail }`, que incluye `incident_ids` y `known_error`.
- **Responsabilidad del backend:** handlers Python, persistencia, validaciones, reglas de negocio, migraciones y publicación de eventos.
- **Responsabilidad del equipo de integración:** configuración de Serverless, API Gateway, Authorizer y despliegue conjunto.

## 2. Endpoints y estado actual

| ID | Método y ruta | Handler | Estado |
|---|---|---|---|
| PR-01 | `GET /problems` | `listProblems` | Implementado y probado en AWS |
| PR-02 | `POST /problems` | `createProblem` | Lógica implementada |
| PR-03 | `GET /problems/{id}` | `getProblem` | Lógica implementada |
| PR-04 | `PATCH /problems/{id}` | `updateProblem` | Lógica implementada |
| PR-05 | `PUT /problems/{id}/status` | `changeProblemStatus` | Lógica implementada |
| PR-06 | `POST /problems/{id}/known-error` | `publishKnownError` | Lógica implementada |
| PR-07 | `POST /problems/{id}/incidents` | `linkProblemIncidents` | Lógica implementada |

**Importante:** los siete handlers tienen pruebas unitarias aprobadas, pero únicamente PR-01 se ha comprobado mediante una petición HTTP real en AWS. Las rutas PR-02 a PR-07 están pendientes de integración con API Gateway.

## 3. Funcionalidades implementadas

### PR-01 — Listar problemas

Permite consultar los problemas del tenant autenticado.

Funcionalidades:

- Paginación con `page` y `limit`.
- Límite predeterminado de 20 registros y máximo de 100.
- Filtros por estado, prioridad, CI y responsable.
- Búsqueda por clave o título.
- Ordenamiento por fecha, prioridad, estado o clave.
- Validación de parámetros.
- Consultas SQL parametrizadas.
- Acceso exclusivo a `admin` y `agent`.

Respuesta exitosa: `200 OK`.

### PR-02 — Crear problema

Permite registrar un problema nuevo.

Validaciones:

- `title`: obligatorio, de 3 a 200 caracteres.
- `description`: máximo 5000 caracteres.
- `priority`: `P1`, `P2`, `P3` o `P4`.
- `ci_id`: UUID válido o `null`.
- `owner_id`: UUID válido; por defecto, el usuario autenticado.
- `incident_ids`: máximo 50 incidentes.

El backend genera automáticamente:

- Una clave correlativa, por ejemplo `PRB-000001`.
- Estado inicial `new`.
- Fecha de creación.

La operación utiliza una transacción PostgreSQL y evita vínculos duplicados.

Publica los eventos `ProblemCreated` y, cuando corresponde, `ProblemIncidentsLinked`.

Respuesta exitosa: `201 Created` con `ProblemDetail`.

### PR-03 — Consultar problema

Permite obtener el detalle de un problema mediante su UUID.

Incluye:

- Información principal del problema.
- Incidentes relacionados.
- Error conocido, si existe.

Devuelve `404` si el problema no existe y `400` si el UUID es inválido.

Respuesta exitosa: `200 OK` con `ProblemDetail`.

### PR-04 — Actualizar problema

Permite modificar los siguientes campos:

- `title`
- `description`
- `priority`
- `root_cause`
- `ci_id`
- `owner_id`
- `fix_change_id`

Reglas:

- Rechaza campos no permitidos.
- Rechaza cuerpos JSON vacíos o inválidos.
- Valida las longitudes y los UUID.
- No permite modificar directamente `id`, `key`, `status` ni `created_at`.
- No permite actualizar problemas en estado `closed`.
- Utiliza una transacción y bloqueo de fila mediante `SELECT ... FOR UPDATE`.
- Ejecuta `ROLLBACK` ante errores de PostgreSQL.

Respuestas principales:

- `200`: actualización correcta.
- `400`: datos inválidos.
- `403`: usuario sin permisos.
- `404`: problema inexistente.
- `409`: problema cerrado.

La respuesta exitosa contiene `ProblemDetail`.

### PR-05 — Cambiar estado

Permite cambiar el estado de un problema siguiendo el flujo de negocio aprobado.

Recibe:

```json
{
  "status": "investigating"
}
```

Solo acepta solicitudes para cambiar a:

- `investigating`
- `resolved`
- `closed`

El estado `known_error` se establece exclusivamente mediante PR-06.

Reglas:

- No permite saltar estados.
- No permite repetir el mismo estado.
- Para resolver un problema, debe existir una causa raíz (`root_cause`) no vacía.
- Un problema `closed` no admite nuevas transiciones.
- Utiliza una transacción con bloqueo de fila.

Respuestas principales:

- `200`: transición correcta.
- `400`: estado o cuerpo inválido.
- `403`: usuario sin permisos.
- `404`: problema inexistente.
- `409`: transición inválida.

### PR-06 — Publicar error conocido (KEDB)

Permite documentar un error conocido y su solución temporal.

Recibe:

```json
{
  "symptom": "Error 502 recurrente",
  "workaround": "Reiniciar el pool de conexiones"
}
```

Validaciones:

- `symptom`: obligatorio, de 3 a 5000 caracteres.
- `workaround`: obligatorio, de 3 a 5000 caracteres.
- El problema debe estar en estado `investigating`.
- El problema no debe tener otro error conocido registrado.

La operación:

1. Comprueba el estado del problema.
2. Verifica que no exista otro error conocido.
3. Inserta el registro en `known_errors`.
4. Cambia el estado del problema a `known_error`.
5. Confirma la transacción.
6. Publica `KnownErrorPublished`.

Respuesta exitosa: `201 Created` con `ProblemDetail`.

### PR-07 — Vincular incidentes

Permite asociar incidentes existentes a un problema.

Recibe:

```json
{
  "incident_ids": [
    "5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d"
  ]
}
```

Validaciones y reglas:

- Solo `admin` y `agent` pueden ejecutar la operación.
- Requiere entre 1 y 50 identificadores.
- Todos los identificadores deben ser UUID válidos.
- Elimina UUID duplicados dentro de la solicitud.
- Ignora relaciones ya existentes mediante `ON CONFLICT DO NOTHING`.
- Comprueba que el problema exista.
- Utiliza una transacción PostgreSQL.
- Publica `ProblemIncidentsLinked` únicamente cuando se crean vínculos nuevos.
- No verifica directamente la existencia del incidente en `ms-incidents`, porque cada microservicio mantiene su propia base de datos.

Respuesta exitosa: `200 OK` con `ProblemDetail`.

## 4. Flujo definitivo de estados

El flujo de estados acordado para `ms-problems` es:

```text
new
  |
  v
investigating
  |
  +---------> known_error
  |                |
  v                |
resolved <---------+
  |
  v
closed
```

| Estado actual | Estado siguiente | Condición |
|---|---|---|
| `new` | `investigating` | Permitido |
| `investigating` | `resolved` | Requiere causa raíz |
| `investigating` | `known_error` | Solo mediante PR-06 |
| `known_error` | `resolved` | Requiere causa raíz |
| `resolved` | `closed` | Permitido |
| `closed` | Ninguno | Estado final |

**Reglas definitivas:**

- Solo se permiten las transiciones indicadas.
- Las transiciones inválidas devuelven `409 Conflict`.
- No se puede cambiar a un estado idéntico al actual.
- `known_error` únicamente se establece mediante la publicación de un error conocido.
- Para pasar a `resolved`, debe haberse registrado `root_cause`.
- `closed` es un estado final.

## 5. Modelo de datos

La migración `migrations/001_init.sql` define cuatro tablas.

| Tabla | Responsabilidad |
|---|---|
| `problems` | Información principal de los problemas |
| `problem_incidents` | Relación entre problemas e incidentes |
| `known_errors` | Base de errores conocidos KEDB |
| `problem_tasks` | Tabla preparada para ampliaciones futuras |

La migración incluye:

- Claves primarias UUID.
- Restricciones de estados y prioridades.
- Claves foráneas internas al microservicio.
- Índices para consultas frecuentes.
- Restricciones de unicidad.

Los incidentes vinculados se identifican mediante UUID, sin claves foráneas hacia la base de datos de `ms-incidents`.

### Multitenancy

Los datos se aíslan mediante esquemas PostgreSQL.

Actualmente se contemplan:

- `tenant_andina`
- `tenant_pacifico`
- `tenant_unitec`

El esquema utilizado por cada operación procede del contexto autenticado y no de los datos enviados por el cliente.

La función `migrate` prepara las tablas en los esquemas indicados.

**Pendiente:** sustituir la lista fija de tenants por un registro central y mejorar el control de versiones de las migraciones.

## 6. Eventos e integración con SNS

`ms-problems` publica los siguientes eventos:

| Evento | Operación | Descripción |
|---|---|---|
| `ProblemCreated` | PR-02 | Se creó un problema |
| `ProblemIncidentsLinked` | PR-02 y PR-07 | Se vincularon incidentes a un problema |
| `KnownErrorPublished` | PR-06 | Se publicó un error conocido |

Los eventos se publican mediante `common.events.publish`.

La publicación se realiza después de confirmar las transacciones PostgreSQL.

**Limitación actual:** si la publicación a SNS falla después de un `COMMIT`, los datos podrían quedar guardados sin que se entregue el evento. No se ha implementado todavía un patrón *outbox* ni una garantía equivalente de entrega.

La integración real con los consumidores de `ms-incidents` deberá verificarse durante las pruebas conjuntas.

## 7. Pruebas unitarias

Las pruebas utilizan:

- Python.
- `unittest`.
- `unittest.mock`.
- `MagicMock`.
- `pytest` como ejecutor.

Se simulan PostgreSQL, el contexto de autenticación, el Layer común y la publicación de eventos.

### Resultados

| Endpoint | Pruebas aprobadas |
|---|---:|
| PR-01 · Listar problemas | 18 |
| PR-02 · Crear problema | 14 |
| PR-03 · Consultar problema | 9 |
| PR-04 · Actualizar problema | 10 |
| PR-05 · Cambiar estado | 14 |
| PR-06 · Publicar error conocido | 13 |
| PR-07 · Vincular incidentes | 16 |
| **Total** | **94** |

Las 94 pruebas de endpoints fueron aprobadas en la última ejecución local comunicada.

Adicionalmente, `test_migrate.py` cuenta con **10 pruebas de migración** aprobadas en una ejecución anterior.

El total potencial es de **104 pruebas**, pendiente de confirmación mediante una ejecución conjunta.

### Ejecutar todas las pruebas

Desde PowerShell, ubicado en la raíz del repositorio:

```powershell
python -m pytest services/problems/tests/ -v
```

### Ejecutar únicamente las pruebas de endpoints

```powershell
python -m pytest services/problems/tests/test_problems.py -v
```

### Ejecutar únicamente las pruebas de migración

```powershell
python -m pytest services/problems/tests/test_migrate.py -v
```

Las pruebas unitarias no requieren AWS ni PostgreSQL real.

## 8. Validación realizada en AWS

Se realizó una prueba real del endpoint `GET /problems`, utilizando:

- AWS API Gateway.
- Lambda Authorizer.
- AWS Lambda.
- PostgreSQL RDS.
- Esquema `tenant_andina`.

La respuesta obtenida fue:

```http
HTTP/2 200
Content-Type: application/json
```

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 0,
    "total_pages": 0
  }
}
```

Esta prueba confirmó que PR-01 podía consultar PostgreSQL correctamente desde AWS.

**Importante:** los endpoints PR-02 a PR-07 todavía no se han probado mediante HTTP real en AWS. Su integración y exposición mediante Serverless corresponde al equipo encargado del despliegue.

## 9. Estructura del microservicio

```text
services/problems/
├── handlers/
│   ├── problems.py
│   └── migrate.py
├── migrations/
│   └── 001_init.sql
├── tests/
│   ├── test_problems.py
│   └── test_migrate.py
├── serverless.yml
└── README.md
```

Descripción:

- `problems.py`: lógica de PR-01 a PR-07.
- `migrate.py`: inicialización de las tablas por esquema.
- `001_init.sql`: definición de las tablas y restricciones.
- `test_problems.py`: 94 pruebas unitarias de endpoints.
- `test_migrate.py`: 10 pruebas de migración realizadas anteriormente.
- `serverless.yml`: configuración de despliegue, gestionada por el equipo de integración.

## 10. Pendientes antes de la integración completa

Aunque la lógica principal está implementada, todavía quedan tareas para integrar todo ServiDesk.

### Equipo de integración

- Declarar las rutas PR-02 a PR-07 en Serverless.
- Verificar la autorización de cada endpoint.
- Desplegar las funciones en AWS.
- Realizar pruebas reales contra PostgreSQL.
- Comprobar publicación y consumo de eventos SNS.
- Integrar `ms-problems` con `ms-incidents`.

### Backend

- Revisar casos límite y consistencia de las respuestas.
- Mejorar la confiabilidad de la publicación de eventos.
- Revisar migraciones versionadas y administración dinámica de tenants.
- Ejecutar nuevamente todas las pruebas unitarias.
- Mantener sincronizados los contratos del backend y frontend.

## 11. Resumen final

**Lógica implementada:**

- PR-01: listar problemas.
- PR-02: crear problemas.
- PR-03: consultar problemas.
- PR-04: actualizar problemas.
- PR-05: cambiar estados.
- PR-06: publicar errores conocidos.
- PR-07: vincular incidentes.

**Pruebas realizadas:**

- 94 pruebas unitarias de endpoints aprobadas.
- 10 pruebas de migración aprobadas anteriormente.
- Una prueba real exitosa de PR-01 en AWS.

**Estado del microservicio:** lógica principal implementada y probada unitariamente. Pendiente de pruebas de integración completas y exposición HTTP de PR-02 a PR-07 por parte del equipo responsable de Serverless.
## Consumidores SQS (F3)

| Cola | Evento | Efecto | Handler |
|---|---|---|---|
| `problems-incidents-q` | `IncidentCreated` | registra el incidente en `ci_incident_log`; con **3 o más incidentes del mismo CI en 24 h** crea un problema automático (prioridad = la peor del grupo) o vincula los nuevos al problema abierto del CI; publica `ProblemCreated` / `ProblemIncidentsLinked` | `consumers.on_incident_created` |
| `problems-changes-q` | `ChangeImplemented` | cierra el problema con ese `fix_change_id` o el `problemId` del cambio y completa `root_cause` | `consumers.on_change_implemented` |

DLQ, `ReportBatchItemFailures` e idempotencia por `processed_events` (tablas nuevas al final de `001_init.sql`).
