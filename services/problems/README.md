# ms-problems — ServiDesk

Microservicio de **gestión de problemas**, análisis de causa raíz, vinculación con incidentes y base de errores conocidos (**KEDB**) de ServiDesk.

> **Estado del avance (12 de noviembre de 2026):** PR-01, PR-02 y PR-03 implementados y probados mediante mocks; migración inicial definida y probada a nivel unitario. **No se ha desplegado ni validado contra PostgreSQL o AWS reales.** Este README documenta el avance de la rama `feature/ms-problems`, no indica que todos los contratos estén terminados.

## 1. Referencia y alcance

Referencia: `docs/API_CONTRACTS.md`, sección **8.4 — ms-problems**.

- Base de datos: `db_problems`.
- Aislamiento multitenant: esquema PostgreSQL obtenido del contexto autenticado (`tenant_ctx`), por ejemplo `tenant_andina`.
- Roles autorizados: `admin` y `agent`. El rol `customer` no accede a los endpoints de problemas.
- Contrato de listado: `{"data": Problem[], "meta": {...}}`.
- Contrato de detalle y creación: `{"data": ProblemDetail}`.
- `ProblemDetail` incluye los campos de `Problem`, además de `incident_ids` y `known_error`.

## 2. Estado de los endpoints

| ID | Método y ruta | Función | Estado de implementación | Pruebas |
|---|---|---|---|---|
| PR-01 | `GET /problems` | `listProblems` | Implementado | Unitarias con mocks |
| PR-02 | `POST /problems` | `createProblem` | Implementado en handler; ruta de API Gateway pendiente | Unitarias con mocks |
| PR-03 | `GET /problems/{id}` | `getProblem` | Implementado en handler; ruta de API Gateway pendiente | Unitarias con mocks |
| PR-04 | `PATCH /problems/{id}` | Actualizar problema | Pendiente | — |
| PR-05 | `PUT /problems/{id}/status` | Cambiar estado | Pendiente | — |
| PR-06 | `POST /problems/{id}/known-error` | Publicar error conocido | Pendiente | — |
| PR-07 | `POST /problems/{id}/incidents` | Vincular incidentes | Pendiente | — |

**Nota sobre el contrato:** las marcas `A parcial` y `C` de `docs/API_CONTRACTS.md` son clasificaciones del documento; la tabla anterior muestra **el avance real de implementación**. No deben confundirse.

## 3. Funcionalidades implementadas y mejoras técnicas

### PR-01 — Listar problemas

- Acceso exclusivo a `admin` y `agent`.
- Aislamiento por esquema del tenant autenticado.
- Paginación mediante `page` (desde 1) y `limit` (1–100, valor por defecto 20), con respuesta `meta`.
- Filtros por `status`, `priority`, `ci_id` y `owner_id`; este último admite UUID o `me` para el usuario autenticado.
- Búsqueda por `key` y `title` (parámetro `search`).
- Ordenamiento por `created_at`, `priority`, `status` o `key`, ascendente o descendente.
- Validación de estados, prioridades, UUID, página, límite, búsqueda y campos de ordenamiento.
- Consultas parametrizadas; los campos de ordenamiento se seleccionan exclusivamente de una lista permitida.

### PR-02 — Crear problema

- Acceso exclusivo a `admin` y `agent` y validación del cuerpo JSON.
- Validación de `title` (3–200 caracteres), `description` (máximo 5000), `priority` (`P1`–`P4`) y UUID opcionales.
- `owner_id` predeterminado al identificador del usuario del contexto autenticado.
- Hasta 50 `incident_ids`, comprobados como UUID y deduplicados.
- Generación de clave `PRB-000001`, `PRB-000002`, etc., y estado inicial `new`.
- Transacción de base de datos con `BEGIN`, `COMMIT` y `ROLLBACK` ante errores; bloqueo consultivo transaccional para evitar colisiones al generar la clave dentro del mismo esquema.
- Inserción de vínculos en `problem_incidents` mediante `ON CONFLICT DO NOTHING`.
- Respuesta `201` con `ProblemDetail`, incluyendo `incident_ids` y `known_error: null`.
- Publicación de `ProblemCreated` y, cuando se vinculan incidentes, `ProblemIncidentsLinked` mediante el mecanismo compartido de eventos.

**Límite de esta implementación:** la publicación de eventos se realiza después del `COMMIT`; todavía no hay patrón *outbox* ni una estrategia implementada para garantizar entrega ante fallos de SNS posteriores a la confirmación en base de datos.

### PR-03 — Consultar problema

- Acceso exclusivo a `admin` y `agent`.
- Validación del UUID recibido en `{id}`.
- Consulta del problema en el esquema del tenant.
- Respuesta `404` cuando no se encuentra el registro; `400` para identificador inválido y `403` para rol no autorizado.
- Construcción de `ProblemDetail` consultando `problems`, `problem_incidents` y `known_errors`.
- `incident_ids` como arreglo y `known_error` como objeto o `null`.
- Serialización de UUID y fechas para la respuesta JSON.

### Mejoras de implementación frente al contrato resumido

El contrato especifica las rutas, roles, entidades, formatos de respuesta y validaciones principales. Como decisiones de implementación se agregaron: validaciones explícitas de parámetros de consulta y UUID, deduplicación de incidentes, consultas SQL parametrizadas, generación protegida de claves, transacción con reversión, respuestas de error para consulta por ID y serialización de datos. Estas decisiones **no modifican el contrato funcional oficial**.

## 4. Modelo de datos y migración inicial

Archivo: `migrations/001_init.sql`.

| Tabla | Responsabilidad |
|---|---|
| `problems` | Datos de problema: clave, título, descripción, estado, prioridad, causa raíz, CI, responsable y cambio correctivo. |
| `problem_incidents` | Relación entre problemas e IDs de incidentes de otro microservicio. Clave compuesta para evitar duplicados. |
| `known_errors` | Registro KEDB con síntoma y solución temporal (*workaround*); un registro por problema. |
| `problem_tasks` | Estructura preparatoria para tareas futuras; sus endpoints están fuera del alcance de esta versión. |

El SQL propuesto incluye restricciones de estados (`new`, `investigating`, `known_error`, `resolved`, `closed`), prioridades (`P1`–`P4`), longitudes de campos, claves foráneas **internas al microservicio** e índices de consulta.

**Sin FK entre microservicios:** `problem_incidents.incident_id` se almacena como UUID sin referencia a `incidents`, porque los incidentes viven en otra base de datos.

El script `handlers/migrate.py` carga `001_init.sql` y lo ejecuta para los esquemas incluidos en `TENANTS` (`tenant_andina`, `tenant_pacifico`, `tenant_unitec`). **Los tenants aún están definidos en el código**; más adelante deberán obtenerse de un registro central. El migrador todavía no registra versiones aplicadas ni contiene un mecanismo propio de recuperación ante migraciones parciales.

## 5. Eventos e integración entre microservicios

| Evento | Cuándo se emite en el avance actual | Estado |
|---|---|---|
| `ProblemCreated` | Después de crear el problema | Implementado en PR-02, probado con mock |
| `ProblemIncidentsLinked` | Si PR-02 recibe incidentes relacionados | Implementado en PR-02, probado con mock |
| `KnownErrorPublished` | Al publicar un error conocido mediante PR-06 | Pendiente |

PR-07 también deberá emitir `ProblemIncidentsLinked` al añadir incidentes posteriormente. La sincronización con `ms-incidents` y la entrega real de eventos **no se han probado como integración extremo a extremo**.

## 6. Pruebas y resultados

Pruebas realizadas durante el desarrollo en Python 3.11 y pytest, usando mocks de base de datos, contexto de autenticación y publicación de eventos.

| Archivo | Cobertura principal | Resultado comunicado |
|---|---|---:|
| `tests/test_problems.py` | PR-01 (18), PR-02 (14), PR-03 (9) | **41 aprobadas** |
| `tests/test_migrate.py` | Archivo SQL, 4 tablas, esquemas, ejecución de sentencias, manejo de errores simulado | **10 aprobadas** |
| **Total** | **Pruebas unitarias de ms-problems** | **51 aprobadas** |

Ejecutar desde la raíz de `servidesk`:

```powershell
python -m pytest .\services\problems\tests\ -v
```

Para ejecutar cada archivo individualmente:

```powershell
python -m pytest .\services\problems\tests\test_problems.py -v
python -m pytest .\services\problems\tests\test_migrate.py -v
```

**Alcance de los resultados:** estas 51 pruebas pasaron según la ejecución local comunicada durante el desarrollo. No sustituyen pruebas de integración con PostgreSQL, SNS, API Gateway, el authorizer o un despliegue AWS.

## 7. Estructura relevante

```text
services/problems/
├── handlers/
│   ├── problems.py             # PR-01, PR-02 y PR-03
│   └── migrate.py              # Migración por schema de tenant
├── migrations/
│   └── 001_init.sql            # Tablas e índices iniciales
├── tests/
│   ├── test_problems.py        # 41 pruebas unitarias
│   └── test_migrate.py         # 10 pruebas unitarias
├── serverless.yml
└── README.md
```

## 8. Infraestructura y puntos pendientes

Actualmente, `serverless.yml` declara la ruta **`GET /problems`** y la función `migrate`. Aunque los handlers de PR-02 y PR-03 están escritos y probados, **faltan las rutas** `POST /problems` y `GET /problems/{id}` en API Gateway.

Antes de considerar este servicio listo para integración o despliegue:

1. Registrar en `serverless.yml` las rutas PR-02 y PR-03 con su autorización.
2. Implementar PR-04, PR-05, PR-06 y PR-07 y sus pruebas.
3. Probar las migraciones y los endpoints contra PostgreSQL real, especialmente `gen_random_uuid()`, restricciones SQL, transacciones y datos devueltos por `RETURNING`.
4. Comprobar envío y consumo real de eventos a través de SNS y la interoperabilidad con `ms-incidents`.
5. Revisar confiabilidad de eventos publicados después del `COMMIT` (por ejemplo, patrón *outbox* o reintentos controlados).
6. Revisar migraciones versionadas, recuperación ante errores y administración de tenants.
7. Completar pruebas de integración, API Gateway y autorización antes de desplegar.

## 9. Resumen de entrega parcial

**Entregado a nivel de implementación local:** tres operaciones del contrato (PR-01, PR-02 y PR-03), validaciones y controles de acceso, consultas multitenant, creación transaccional, vinculación inicial de incidentes, publicación de eventos simulada, migración inicial de cuatro tablas y **51 pruebas unitarias aprobadas**.

**No entregado todavía:** PR-04 a PR-07, exposición HTTP de PR-02 y PR-03, integración comprobada con servicios AWS/PostgreSQL reales y despliegue.
