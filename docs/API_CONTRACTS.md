# Contratos API de ServiDesk

**Versión:** 0.9 (propuesta) · **Fecha:** 2026-11-05 · **Estado:** pendiente de aprobación del equipo

Este documento fija las rutas, los JSON de entrada y salida, los roles y las reglas multi-tenant de los
6 microservicios. La especificación formal es [`openapi.yaml`](./openapi.yaml); los eventos están en
[`EVENT_CONTRACTS.md`](./EVENT_CONTRACTS.md) y los tipos del frontend en
[`frontend/src/types/api.ts`](../frontend/src/types/api.ts).

> Ningún contrato se considera cerrado hasta que el equipo apruebe las decisiones de la
> [sección 9](#9-decisiones-que-necesitan-aprobación-del-equipo). Mientras tanto, el frontend puede trabajar con
> datos simulados (MSW) sobre esta versión.

Fuentes analizadas: el código de `main` en el commit `6ec59ac` y el documento de diseño
([Diseño SaaS ITSM multi-tenant en AWS](https://claude.ai/artifact/TqFFnkxBizjXX4qsQezTWR)), que contiene los
diagramas ER. Cuando el código y el documento difieren, se indica.

---

## 1. Estado actual del repositorio

### 1.1 Qué hay en `main`

| Pieza | Archivo | Estado real |
| --- | --- | --- |
| Lambda Authorizer | `infra/authorizer/handler.py` | Implementado: valida JWT HS256 con `JWT_SECRET` y devuelve `tenant_id`, `schema`, `role`, `user_id` en el contexto. |
| Conexión a RDS por tenant | `infra/layers/common/python/common/db.py` | Implementado: `tenant_conn(schema)` valida `^tenant_[a-z0-9_]+$` y hace `SET search_path`. |
| Publicación de eventos | `infra/layers/common/python/common/events.py` | Implementado (`publish()`), pero ningún handler lo llama todavía. |
| Utilidades HTTP | `infra/layers/common/python/common/http.py` | Implementado: `tenant_ctx`, `ok(body, status)`, `error(message, status)` → `{"error": "<texto>"}`. |
| SNS, S3, RDS | `infra/serverless.yml` | Declarados: tópico `servidesk-itsm-events-<stage>`, 3 buckets, RDS PostgreSQL 16. |
| Migraciones | `services/*/migrations/001_init.sql` | Solo **incidents** tiene tablas (`sla_policies`, `incidents`, `incident_comments`). Las otras 5 están vacías. |
| Cola SQS + DLQ | `services/incidents/serverless.yml` | Declaradas: `CiStatusQueue`, `CiStatusDLQ` (maxReceiveCount 3) y suscripción con filtro `eventType: [CIStatusChanged]`. |
| Consumidor SQS | `services/incidents/handlers/consumers.py` | Esqueleto: lee el mensaje y abre la conexión, la creación del incidente es `TODO`. |

Cada microservicio declara **su propia HTTP API** en API Gateway (`provider.httpApi`), así que hay
**6 URLs base distintas**, una por servicio. Las rutas no llevan prefijo.

### 1.2 Clasificación de endpoints

**A. Implementados (con handler que consulta la BD):**

| Ruta | Observación |
| --- | --- |
| `GET /incidents` | Funciona si se corre `migrate`. Devuelve un arreglo plano con `SELECT *`, `LIMIT 50`, sin paginación ni filtros. |
| `GET /users`, `GET /cis`, `GET /problems`, `GET /changes`, `GET /requests` | El handler existe, pero **fallaría con error 500** porque las migraciones de esos servicios están vacías y la tabla no existe. `GET /users` además devolvería `password_hash` por usar `SELECT *`. |

**B. Declarados pero no implementados:**

| Ruta / pieza | Observación |
| --- | --- |
| `POST /auth/login` | Declarada en `identity/serverless.yml`, responde `501`. |
| `POST /incidents` | Declarada, responde `501`. |
| Consumidor `onCiStatusChanged` | Cola, DLQ y suscripción declaradas; lógica `TODO`. Nadie publica `CIStatusChanged` todavía. |
| Tablas de identity, cmdb, problems, changes, requests | Solo existen en los diagramas ER del documento de diseño. |
| Tablas `incident_attachments` e `incident_events` | Están en el ER, no en `incidents/migrations/001_init.sql`. |

**C. Nuevos (definidos en este contrato):** todos los demás endpoints de la [sección 8](#8-contratos-por-microservicio),
marcados con estado **C** en cada ficha.

### 1.3 Problemas encontrados que afectan a los contratos

1. **Fechas mal serializadas.** `ok()` usa `json.dumps(..., default=str)`; un `datetime` sale como
   `"2026-11-05 19:20:25.123456"` (con espacio, sin zona). El contrato exige ISO 8601 UTC: `"2026-11-05T19:20:25Z"`.
2. **Formato de error.** `error()` devuelve `{"error": "texto"}`; el contrato necesita un código estable para el frontend.
3. **Respuestas de API Gateway.** Si falta el header `Authorization`, API Gateway responde `401 {"message":"Unauthorized"}`
   sin invocar al authorizer. Si el authorizer responde `isAuthorized: false` (token inválido o vencido), API Gateway
   responde `403 {"message":"Forbidden"}`. Las HTTP API no permiten personalizar esas respuestas, así que el frontend
   debe reconocer ambos formatos (ver [sección 4](#4-estándar-de-respuestas)).
4. **El authorizer no exige `exp`.** PyJWT verifica `exp` solo si viene en el token. Debe usarse
   `options={"require": ["exp", "sub", "tenant_id", "schema", "role"]}` y comprobar que `schema == "tenant_" + tenant_id`.
5. **Caché del authorizer.** `resultTtlInSeconds: 300`: un token vencido puede seguir aceptándose hasta 5 minutos. Es
   aceptable para el curso; se documenta.
6. **bcrypt en el layer.** El diseño menciona bcrypt, pero bcrypt trae binarios compilados y el layer se instala desde la
   máquina de cada integrante (Mac/Windows). Se propone PBKDF2 de la librería estándar (decisión D7).
7. **`configuration_items` no tiene `created_at`** en el ER, pero `listCis` ordena por `created_at` (decisión D9).

---

## 2. Convenciones generales

| Tema | Regla |
| --- | --- |
| URL base | Una por servicio: `VITE_API_IDENTITY_URL`, `VITE_API_CMDB_URL`, `VITE_API_INCIDENTS_URL`, `VITE_API_PROBLEMS_URL`, `VITE_API_CHANGES_URL`, `VITE_API_REQUESTS_URL`. Ejemplo: `https://a1b2c3d4e5.execute-api.us-east-1.amazonaws.com`. |
| Formato | JSON UTF-8, `Content-Type: application/json`. |
| Nombres de campos HTTP | `snake_case`, igual que las columnas SQL (decisión D1). |
| Identificadores | UUID v4 en texto, salvo catálogos pequeños con `SERIAL` (`ci_types.id`, `catalog_categories.id`, `sla_policies.id`). |
| Claves legibles | `INC-000123`, `PRB-000045`, `CHG-000210`, `REQ-000987`. Las genera el backend; correlativas por tenant. |
| Fechas | ISO 8601 en UTC con `Z`: `"2026-11-05T19:20:25Z"`. Las columnas `TIMESTAMP` se guardan en UTC. |
| Nulos | Un campo sin valor se devuelve como `null`, nunca se omite. |
| Actualización parcial | `PATCH /{recurso}/{id}`: solo los campos enviados cambian; `null` borra un campo opcional. |
| Cambio de estado | Siempre `PUT /{recurso}/{id}/status` (nunca por `PATCH`), porque valida transiciones, registra historial y publica eventos. |
| Campos desconocidos | El body se valida de forma estricta: un campo no definido (incluidos `tenant_id`, `schema`, `reporter_id`, `key`, `status` en un `PATCH`) produce `400 VALIDATION_ERROR` (decisión D12). |
| Filtros con varios valores | Separados por comas: `?status=new,in_progress`. |
| Métodos | `GET`, `POST`, `PATCH`, `PUT`, `DELETE`. `cors: true` de Serverless v3 ya permite todos y el header `Authorization`. |

---

## 3. Autenticación JWT y aislamiento multi-tenant

### 3.1 Flujo

```mermaid
sequenceDiagram
  participant U as Usuario
  participant FE as Frontend (React)
  participant ID as ms-identity
  participant GW as API Gateway (servicio X)
  participant AU as Lambda Authorizer
  participant MS as Lambda del servicio X
  participant DB as RDS (db_x)
  U->>FE: código de organización + email + contraseña
  FE->>ID: POST /auth/login {tenant_code, email, password}
  ID->>DB: public.tenants (code → schema_name) y luego <schema>.users
  ID-->>FE: 200 {access_token, expires_in, user}
  FE->>GW: GET /incidents  Authorization: Bearer <token>
  GW->>AU: evento con headers.authorization
  AU-->>GW: isAuthorized + context {tenant_id, schema, role, user_id}
  GW->>MS: requestContext.authorizer.lambda = context
  MS->>DB: SET search_path TO <schema del contexto>; SELECT ...
  MS-->>FE: 200 {data, meta}
```

1. El usuario escribe el **código de organización** (`andina`, `pacifico`, `unitec`), su email y su contraseña.
2. `ms-identity` busca el código en `public.tenants` (db_identity), obtiene `schema_name`, busca al usuario en
   `<schema>.users`, comprueba `active = true` y verifica el hash de la contraseña.
3. `ms-identity` firma un JWT HS256 con `JWT_SECRET` (variable ya presente en `identity/serverless.yml`), válido 1 hora.
4. El frontend guarda el token en `sessionStorage` (decisión D11) y los datos del usuario en memoria.
5. Toda petición a una ruta protegida lleva `Authorization: Bearer <access_token>` (interceptor de Axios).
6. API Gateway de cada servicio invoca el Lambda Authorizer compartido (`identitySource: $request.header.Authorization`).
7. El authorizer valida firma, expiración y claims obligatorios.
8. El handler lee `event.requestContext.authorizer.lambda` con `tenant_ctx(event)`.
9. El handler llama `tenant_conn(ctx["schema"])`; el schema **solo** sale de ese contexto.

### 3.2 Contenido del JWT

| Claim | Tipo | Ejemplo | Descripción |
| --- | --- | --- | --- |
| `sub` | string (UUID) | `"3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90"` | `users.id` dentro del schema del tenant. |
| `tenant_id` | string | `"andina"` | Código del tenant (`public.tenants.code`). Es el mismo valor que `tenantId` en los eventos y en las claves S3 `tenants/<tenant_id>/…` (decisión D3). |
| `schema` | string | `"tenant_andina"` | `public.tenants.schema_name`. Siempre `"tenant_" + tenant_id`. |
| `role` | `"admin" \| "agent" \| "customer"` | `"agent"` | Rol del usuario en ese tenant. |
| `iat` | número (epoch s) | `1793906400` | Emisión. |
| `exp` | número (epoch s) | `1793910000` | Expiración: `iat + 3600`. |

Ejemplo de payload decodificado:

```json
{
  "sub": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
  "tenant_id": "andina",
  "schema": "tenant_andina",
  "role": "agent",
  "iat": 1793906400,
  "exp": 1793910000
}
```

Header: `{"alg": "HS256", "typ": "JWT"}`. No se usa refresh token: al vencer, el usuario vuelve a iniciar sesión.

### 3.3 Cambios necesarios en el authorizer (José)

```python
claims = jwt.decode(
    token, os.environ["JWT_SECRET"], algorithms=["HS256"],
    options={"require": ["exp", "sub", "tenant_id", "schema", "role"]},
)
if claims["schema"] != f"tenant_{claims['tenant_id']}" or claims["role"] not in ("admin", "agent", "customer"):
    return {"isAuthorized": False}
```

El contexto que entrega se mantiene igual: `tenant_id`, `schema`, `role`, `user_id` (= `sub`).

### 3.4 Cómo se evita el acceso entre tenants

1. **El cliente no elige el tenant.** Solo envía `tenant_code` en el login. Después, el tenant y el schema viajan dentro de
   un JWT firmado que el navegador no puede modificar sin invalidar la firma.
2. **El backend ignora cualquier tenant enviado por el cliente.** Los bodies se validan de forma estricta: si llega
   `tenant_id` o `schema` en un body, la respuesta es `400 VALIDATION_ERROR`. Ningún query param elige tenant.
3. **Una sola fuente de verdad.** Todo handler obtiene el schema con `tenant_ctx(event)["schema"]` y lo pasa a
   `tenant_conn()`, que valida la expresión regular antes del `SET search_path`.
4. **Los IDs de otro tenant no existen.** Como las consultas corren dentro del schema del token, pedir
   `GET /incidents/<id de otro tenant>` devuelve `404 NOT_FOUND` (no `403`), así no se revela que el recurso existe.
5. **Eventos.** Todo evento lleva `tenantId`; el consumidor usa `tenant_conn("tenant_" + tenantId)` y nunca mezcla
   mensajes de tenants distintos en una misma transacción.
6. **S3.** Las claves siempre empiezan por `tenants/<tenant_id del token>/`; las URLs prefirmadas las genera el backend.
7. **Dentro del tenant**, los `customer` solo ven sus propios incidentes y solicitudes (`reporter_id` / `requester_id` = `sub`).

### 3.5 Matriz de roles

| Recurso | admin | agent | customer |
| --- | --- | --- | --- |
| Usuarios (`/users`) | CRUD | lectura | — (solo `/auth/me`) |
| Equipos (`/teams`) | lectura | lectura | — |
| CMDB (`/cis`, `/ci-types`) | CRUD | crear, leer, editar, cambiar estado | — |
| Incidentes | todo | todo | crear, leer y comentar **los propios**; cerrar o reabrir los propios resueltos |
| Problemas | todo | todo | — |
| Cambios | todo, **aprobar/rechazar** | crear, leer, editar, cambiar estado | — |
| Catálogo (`/catalog`) | lectura | lectura | lectura |
| Solicitudes | todo, **aprobar/rechazar** | leer, asignar, atender | crear y leer **las propias**, editar `form_data` antes de atenderse |

Un rol no autorizado recibe `403 FORBIDDEN`. Un recurso de otro tenant o, para `customer`, de otro usuario, recibe `404 NOT_FOUND`.

---

## 4. Estándar de respuestas

### 4.1 Formatos

| Caso | Código | Body |
| --- | --- | --- |
| Lectura o actualización de un recurso | 200 | `{"data": { ... }}` |
| Listado paginado | 200 | `{"data": [ ... ], "meta": {"page", "limit", "total", "total_pages"}}` |
| Catálogo corto sin paginar (`/ci-types`, `/catalog`) | 200 | `{"data": [ ... ]}` |
| Creación | 201 | `{"data": { ... }}` con el recurso completo |
| Eliminación | 204 | sin body |
| Error de validación | 400 | `{"error": {"code": "VALIDATION_ERROR", "message", "details": [{"field", "issue"}]}}` |
| Credenciales inválidas (login) | 401 | `{"error": {"code": "INVALID_CREDENTIALS", ...}}` |
| Sin token (API Gateway) | 401 | `{"message": "Unauthorized"}` |
| Token inválido o vencido (API Gateway) | 403 | `{"message": "Forbidden"}` |
| Rol sin permiso | 403 | `{"error": {"code": "FORBIDDEN", ...}}` |
| Recurso inexistente o de otro tenant | 404 | `{"error": {"code": "NOT_FOUND", ...}}` |
| Conflicto de estado o duplicado | 409 | `{"error": {"code": "INVALID_STATUS_TRANSITION" \| "EMAIL_ALREADY_EXISTS" \| "CONFLICT", ...}}` |
| Ruta declarada sin implementar | 501 | `{"error": {"code": "NOT_IMPLEMENTED", ...}}` |
| Error interno | 500 | `{"error": {"code": "INTERNAL_ERROR", "message": "Error interno", "request_id"}}` |

Todo error de la aplicación incluye `request_id` (`context.aws_request_id`) para buscarlo en CloudWatch.

Ejemplo de error de validación:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "La solicitud tiene campos inválidos",
    "details": [
      { "field": "title", "issue": "Debe tener entre 3 y 200 caracteres" },
      { "field": "tenant_id", "issue": "Campo no permitido" }
    ],
    "request_id": "c0a8e3f4-1b2d-4e5f-9a6b-7c8d9e0f1a2b"
  }
}
```

Códigos de error estables (`error.code`): `VALIDATION_ERROR`, `INVALID_CREDENTIALS`, `UNAUTHENTICATED`, `FORBIDDEN`,
`NOT_FOUND`, `CONFLICT`, `EMAIL_ALREADY_EXISTS`, `INVALID_STATUS_TRANSITION`, `NOT_IMPLEMENTED`, `INTERNAL_ERROR`.

### 4.2 Compatibilidad con `common/http.py` y cambios necesarios

`ok(body, status)` sirve si el handler arma `{"data": ...}`; `error(message, status)` **no** es compatible.
Cambios propuestos (no se aplican en esta rama, solo se documentan):

```python
import datetime, decimal, json, uuid

def _default(o):
    if isinstance(o, datetime.datetime):
        return o.replace(microsecond=0).isoformat() + "Z"   # TIMESTAMP en UTC, sin zona
    if isinstance(o, (uuid.UUID, decimal.Decimal)):
        return str(o)
    return str(o)

def _resp(status, body=None):
    r = {"statusCode": status, "headers": {"Content-Type": "application/json"}}
    if body is not None:
        r["body"] = json.dumps(body, default=_default)
    return r

def ok(data, status=200):                 # compatible con la firma actual
    return _resp(status, {"data": data})

def created(data):
    return _resp(201, {"data": data})

def no_content():
    return _resp(204)

def paginated(items, page, limit, total):
    return _resp(200, {"data": items, "meta": {
        "page": page, "limit": limit, "total": total,
        "total_pages": (total + limit - 1) // limit}})

def error(code, message, status=400, details=None, request_id=None):
    body = {"code": code, "message": message}
    if details: body["details"] = details
    if request_id: body["request_id"] = request_id
    return _resp(status, {"error": body})
```

Los handlers actuales (`listX`) llaman `ok([...])` y `error("no implementado", 501)`; al cambiar la firma hay que
actualizarlos a `paginated(...)` y `error("NOT_IMPLEMENTED", "No implementado", 501)`.

---

## 5. Paginación, filtros y ordenamiento

Parámetros comunes de todo `GET` de listado paginado:

| Parámetro | Tipo | Defecto | Regla |
| --- | --- | --- | --- |
| `page` | entero ≥ 1 | `1` | Fuera de rango devuelve `data: []` con el `total` real. |
| `limit` | entero 1–100 | `20` | Más de 100 → `400`. |
| `search` | texto 2–100 | — | `ILIKE '%texto%'` sobre los campos indicados en cada recurso. |
| `sort_by` | enum por recurso | ver tabla | Valor fuera de la lista → `400` (evita inyección en `ORDER BY`). |
| `sort_order` | `asc` \| `desc` | `desc` | |

Respuesta:

```json
{
  "data": [ { "id": "…" } ],
  "meta": { "page": 2, "limit": 20, "total": 10000, "total_pages": 500 }
}
```

Filtros por recurso:

| Recurso | Filtros | `search` sobre | `sort_by` (defecto en negrita) |
| --- | --- | --- | --- |
| `GET /users` | `role`, `active`, `ids` (hasta 100 UUID) | `email`, `full_name` | **`created_at`**, `full_name`, `email` |
| `GET /teams` | — | `name` | **`name`** |
| `GET /cis` | `status`, `environment`, `type_id`, `owner_team_id` | `name` | **`created_at`**, `updated_at`, `name`, `status` |
| `GET /incidents` | `status`, `priority`, `impact`, `urgency`, `assignee_id` (`me` \| `none` \| UUID), `team_id`, `ci_id`, `problem_id`, `channel`, `sla_breached` | `key`, `title` | **`created_at`**, `priority`, `sla_due_at`, `status`, `key` |
| `GET /incidents/{id}/comments` | — | — | **`created_at`** (defecto `asc`) |
| `GET /problems` | `status`, `priority`, `ci_id`, `owner_id` (`me` \| UUID) | `key`, `title` | **`created_at`**, `priority`, `status`, `key` |
| `GET /changes` | `status`, `type`, `risk`, `requester_id` (`me` \| UUID), `planned_from`, `planned_to` | `key`, `title` | **`created_at`**, `planned_start`, `risk`, `status`, `key` |
| `GET /requests` | `status`, `catalog_item_id`, `requester_id` (`me` \| UUID), `assignee_id` (`me` \| `none` \| UUID) | `key` | **`created_at`**, `status`, `key` |

`status`, `priority`, `impact`, `urgency`, `type`, `risk`, `environment` y `role` aceptan varios valores separados por comas.
`planned_from`/`planned_to` (ISO 8601) filtran por solapamiento con `[planned_start, planned_end]`: es el calendario de cambios.

---

## 6. Valores enumerados (iguales en SQL, OpenAPI y TypeScript)

| Dominio | Valores | Origen |
| --- | --- | --- |
| `role` | `admin`, `agent`, `customer` | ER identity |
| `ci.status` | `operational`, `degraded`, `down`, `retired` | ER cmdb |
| `ci.environment` | `prod`, `qa`, `dev` | ER cmdb |
| `ci_relation.relation` | `depends_on`, `runs_on`, `connects_to` | ER cmdb |
| `incident.status` | `new`, `in_progress`, `on_hold`, `resolved`, `closed` | ER + migración |
| `impact`, `urgency` | `high`, `medium`, `low` | **Propuesto** (D6): el ER solo dice `varchar` |
| `priority` | `P1`, `P2`, `P3`, `P4` | ER (`sla_policies.priority`) |
| `incident.channel` | `portal`, `email`, `auto` | ER |
| `problem.status` | `new`, `investigating`, `known_error`, `resolved`, `closed` | ER |
| `change.type` | `standard`, `normal`, `emergency` | ER |
| `change.risk` | `low`, `medium`, `high` | ER |
| `change.status` | `draft`, `submitted`, `approved`, `rejected`, `scheduled`, `implemented`, `failed` | ER |
| `approval.decision` | `pending`, `approved`, `rejected` | ER (`change_approvals`) |
| `request.status` | `submitted`, `pending_approval`, `approved`, `in_fulfillment`, `fulfilled`, `rejected` | ER |

Prioridad de incidentes (D6), calculada por el backend a partir de impacto × urgencia:

| impacto \ urgencia | high | medium | low |
| --- | --- | --- | --- |
| **high** | P1 | P2 | P3 |
| **medium** | P2 | P3 | P4 |
| **low** | P3 | P4 | P4 |

---

## 7. Transiciones de estado

| Recurso | Desde → hacia | Quién | Efectos |
| --- | --- | --- | --- |
| Incidente | `new` → `in_progress`, `on_hold`, `resolved` | agent, admin | fila en `incident_events` |
| | `in_progress` → `on_hold`, `resolved` | agent, admin | |
| | `on_hold` → `in_progress`, `resolved` | agent, admin | |
| | `resolved` → `closed`, `in_progress` (reabrir) | agent, admin, customer dueño | |
| | `closed` → (final) | — | |
| | a `resolved` | | exige `comment` (nota de resolución, se guarda como comentario público); fija `resolved_at`; evento `IncidentResolved` |
| CI | cualquiera → `operational`, `degraded`, `down`, `retired` | agent, admin (`retired` también por `DELETE`, solo admin) | fila en `ci_history`; evento `CIStatusChanged` |
| Problema | `new` → `investigating` | agent, admin | |
| | `investigating` → `resolved` | agent, admin | exige `root_cause` no vacío |
| | `investigating` → `known_error` | solo con `POST /problems/{id}/known-error` | evento `KnownErrorPublished` |
| | `known_error` → `resolved` | agent, admin | |
| | `resolved` → `closed`, `investigating` | agent, admin | |
| Cambio | `draft` → `submitted` | agent, admin | exige `planned_start`, `planned_end` y, si no es `standard`, `rollback_plan`; un `standard` pasa directo a `approved` (D14) |
| | `submitted` → `approved` / `rejected` | admin, con `/approve` o `/reject` | fila en `change_approvals` |
| | `rejected` → `draft` | agent, admin | para corregir y reenviar |
| | `approved` → `scheduled` | agent, admin | |
| | `scheduled` → `implemented`, `failed` | agent, admin | `implemented` publica `ChangeImplemented` |
| Solicitud | al crear: `pending_approval` si `needs_approval`, si no `submitted` | backend | evento `RequestSubmitted` |
| | `pending_approval` → `approved`, `rejected` | admin | fila en `request_approvals` |
| | `submitted` → `in_fulfillment`, `rejected` | agent, admin | |
| | `approved` → `in_fulfillment` | agent, admin | |
| | `in_fulfillment` → `fulfilled` | agent, admin | fija `fulfilled_at` |

Una transición no listada devuelve `409 INVALID_STATUS_TRANSITION` con `details: [{"field": "status", "issue": "De 'closed' no se puede pasar a 'in_progress'"}]`.

---

## 8. Contratos por microservicio

Notación de cada ficha: **Estado** A (implementado) / B (declarado, no implementado) / C (nuevo) ·
**Roles** autorizados · **Errores** además de los comunes. Errores comunes a toda ruta protegida: `401` y `403` de
API Gateway, `403 FORBIDDEN` por rol, `500 INTERNAL_ERROR`. Toda ruta con `{id}` puede devolver `404 NOT_FOUND`
(y `400` si el id no es un UUID).

### 8.1 ms-identity

- **Responsabilidad:** tenants, login y emisión del JWT, usuarios, equipos.
- **Base:** `VITE_API_IDENTITY_URL` · **BD:** `db_identity` (`public.tenants` + `users`, `teams`, `team_members`, `notifications` por schema).
- **Multi-tenancy:** el login es la única ruta que resuelve el tenant a partir de un dato del cliente (`tenant_code`), y lo hace contra `public.tenants`. Las demás usan el schema del token.

Entidad `User` (nunca incluye `password_hash`):

```json
{
  "id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
  "email": "lucia.paredes@andina.pe",
  "full_name": "Lucía Paredes Quispe",
  "role": "agent",
  "active": true,
  "created_at": "2026-03-14T13:05:41Z"
}
```

#### ID-01 · `POST /auth/login` — Iniciar sesión
**Estado:** B (declarada, responde 501) · **Auth:** pública · **Roles:** —

Body:

```json
{ "tenant_code": "andina", "email": "lucia.paredes@andina.pe", "password": "Andina#2026" }
```

Validaciones: `tenant_code` `^[a-z0-9_]{2,30}$`; `email` formato email, máx. 254, se compara en minúsculas;
`password` 8–128 caracteres.

Respuesta `200`:

```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIzZjlhMWM1Mi0…",
    "token_type": "Bearer",
    "expires_in": 3600,
    "user": {
      "id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
      "email": "lucia.paredes@andina.pe",
      "full_name": "Lucía Paredes Quispe",
      "role": "agent",
      "active": true,
      "created_at": "2026-03-14T13:05:41Z",
      "tenant": { "id": "andina", "name": "Andina Retail" }
    }
  }
}
```

Errores: `400 VALIDATION_ERROR`; `401 INVALID_CREDENTIALS` con el mismo mensaje para tenant inexistente, usuario
inexistente, usuario inactivo o contraseña errónea (no revela cuál falló).

#### ID-02 · `GET /auth/me` — Usuario autenticado
**Estado:** C · **Roles:** admin, agent, customer

Respuesta `200`: `{"data": AuthUser}` (mismo objeto `user` del login). Sirve para restaurar la sesión al recargar la página.
Errores: `404 NOT_FOUND` si el usuario fue eliminado.

#### ID-03 · `GET /users` — Listar usuarios
**Estado:** A parcial (handler existe; tabla no migrada; usa `SELECT *`) · **Roles:** admin, agent

Query: comunes + `role`, `active` (`true`/`false`), `ids` (UUID separados por comas, máx. 100; para mostrar nombres de
reportantes y asignados). Ejemplo: `GET /users?role=agent&active=true&search=paredes&page=1&limit=20`.

Respuesta `200`: `{"data": User[], "meta": {...}}`.

#### ID-04 · `GET /users/{id}` — Consultar usuario
**Estado:** C · **Roles:** admin, agent · Respuesta `200`: `{"data": User}`.

#### ID-05 · `POST /users` — Crear usuario
**Estado:** C · **Roles:** admin

```json
{ "email": "jorge.huaman@andina.pe", "full_name": "Jorge Huamán Ríos", "role": "customer", "password": "Temporal#2026", "active": true }
```

Validaciones: `email` obligatorio, único en el tenant; `full_name` 3–150; `role` enum; `password` 8–128; `active` opcional (defecto `true`).
Respuesta `201`: `{"data": User}`. Errores: `400`; `409 EMAIL_ALREADY_EXISTS`. Publica `UserCreated`.

#### ID-06 · `PATCH /users/{id}` — Actualizar usuario
**Estado:** C · **Roles:** admin

```json
{ "role": "agent", "active": false }
```

Campos permitidos: `full_name`, `role`, `active`, `password` (restablecer). El email no se puede cambiar.
Regla: un admin no puede quitarse a sí mismo el rol `admin` ni desactivarse (`409 CONFLICT`).
Respuesta `200`: `{"data": User}`.

#### ID-07 · `GET /teams` — Listar equipos
**Estado:** C · **Roles:** admin, agent · Query: comunes.
Respuesta `200`: `{"data": [{"id": "b6f0…", "name": "Mesa de ayuda N1", "description": "Primer nivel de soporte"}], "meta": {...}}`.

### 8.2 ms-cmdb

- **Responsabilidad:** elementos de configuración (CI), tipos, relaciones e historial.
- **Base:** `VITE_API_CMDB_URL` · **BD:** `db_cmdb` (`ci_types`, `configuration_items`, `ci_relations`, `ci_history`).
- **Multi-tenancy:** todo por `search_path` del token. Los tipos de CI son propios de cada tenant.

Entidad `ConfigurationItem`:

```json
{
  "id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f",
  "type_id": 1,
  "type_name": "Servidor",
  "name": "srv-historias-01",
  "status": "operational",
  "environment": "prod",
  "version": "2.4.1",
  "owner_team_id": "b6f0a2d4-5c7e-4f81-9a3b-2d4c6e8f0a1b",
  "attributes": { "ip": "10.20.1.15", "os": "Ubuntu 22.04", "ubicacion": "Data center Lima" },
  "created_at": "2026-01-10T09:00:00Z",
  "updated_at": "2026-10-28T16:42:10Z"
}
```

`type_name` es derivado (JOIN con `ci_types` en la misma BD). `created_at` depende de la decisión D9.

#### CM-01 · `GET /cis` — Listar CI
**Estado:** A parcial · **Roles:** admin, agent
Query: comunes + `status`, `environment`, `type_id`, `owner_team_id`. Ejemplo: `GET /cis?status=down,degraded&environment=prod&sort_by=updated_at`.
Respuesta `200`: `{"data": ConfigurationItem[], "meta": {...}}`.

#### CM-02 · `POST /cis` — Registrar CI
**Estado:** C · **Roles:** admin, agent

```json
{
  "type_id": 1,
  "name": "srv-historias-02",
  "environment": "prod",
  "version": "2.4.1",
  "owner_team_id": "b6f0a2d4-5c7e-4f81-9a3b-2d4c6e8f0a1b",
  "attributes": { "ip": "10.20.1.16", "os": "Ubuntu 22.04" }
}
```

Validaciones: `type_id` existente; `name` 2–150; `environment` enum; `version` máx. 50; `attributes` objeto JSON de máx. 8 KB.
El backend fija `status = "operational"`. Respuesta `201`: `{"data": ConfigurationItem}`. Errores: `400`.

#### CM-03 · `GET /cis/{id}` — Consultar CI
**Estado:** C · **Roles:** admin, agent · Respuesta `200`: `{"data": ConfigurationItem}`.

#### CM-04 · `PATCH /cis/{id}` — Actualizar CI
**Estado:** C · **Roles:** admin, agent
Campos: `type_id`, `name`, `environment`, `version`, `owner_team_id`, `attributes` (reemplaza el objeto completo).
Cada campo cambiado se registra en `ci_history`. Un CI `retired` no se edita (`409 CONFLICT`).
Respuesta `200`: `{"data": ConfigurationItem}`.

#### CM-05 · `PUT /cis/{id}/status` — Cambiar estado del CI
**Estado:** C (el diseño lo menciona) · **Roles:** admin, agent

```json
{ "status": "down" }
```

Respuesta `200`: `{"data": ConfigurationItem}`. Registra `ci_history` y publica `CIStatusChanged` (si pasa a `down`,
ms-incidents crea un incidente P2 automático). Errores: `409 INVALID_STATUS_TRANSITION` si ya está en ese estado o está `retired`.

#### CM-06 · `DELETE /cis/{id}` — Eliminar CI
**Estado:** C · **Roles:** admin
Baja lógica: pone `status = "retired"` (otros servicios guardan `ci_id` y no hay FK entre bases). Respuesta `204`.
Repetirla sobre un CI ya retirado también devuelve `204`. Publica `CIStatusChanged`.

#### CM-07 · `GET /cis/{id}/relations` — Relaciones del CI
**Estado:** C (el diseño lo menciona) · **Roles:** admin, agent

```json
{
  "data": [
    {
      "id": "1d2e3f40-5a6b-4c7d-8e9f-0a1b2c3d4e5f",
      "relation": "runs_on",
      "direction": "outgoing",
      "ci": { "id": "a7b8c9d0-…", "name": "vm-cluster-02", "status": "operational", "type_name": "Servidor" }
    }
  ]
}
```

`direction` = `outgoing` si el CI es `source_ci_id`, `incoming` si es `target_ci_id`. Sin paginar.

#### CM-08 · `GET /ci-types` — Tipos de CI
**Estado:** C · **Roles:** admin, agent · Respuesta `200`: `{"data": [{"id": 1, "name": "Servidor"}, {"id": 2, "name": "Aplicación"}]}`.

### 8.3 ms-incidents

- **Responsabilidad:** incidentes, prioridad y SLA, comentarios.
- **Base:** `VITE_API_INCIDENTS_URL` · **BD:** `db_incidents` (`sla_policies`, `incidents`, `incident_comments`; `incident_events` e `incident_attachments` pendientes de migrar).
- **Multi-tenancy:** schema del token. Para `customer`, el backend agrega `reporter_id = sub` a toda consulta.

Entidad `Incident`:

```json
{
  "id": "5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d",
  "key": "INC-004512",
  "title": "No carga el sistema de historias clínicas",
  "description": "Desde las 8:10 la aplicación muestra error 502 en todas las sedes.",
  "status": "in_progress",
  "impact": "high",
  "urgency": "high",
  "priority": "P1",
  "sla_policy_id": 1,
  "sla_due_at": "2026-11-05T12:10:00Z",
  "sla_breached": false,
  "reporter_id": "c4d5e6f7-8a9b-4c0d-9e1f-2a3b4c5d6e7f",
  "assignee_id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
  "team_id": "b6f0a2d4-5c7e-4f81-9a3b-2d4c6e8f0a1b",
  "ci_id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f",
  "problem_id": null,
  "channel": "portal",
  "created_at": "2026-11-05T08:10:00Z",
  "resolved_at": null
}
```

`reporter_id`, `assignee_id`, `team_id` (identity), `ci_id` (cmdb) y `problem_id` (problems) son referencias por ID a
otros servicios, sin FK. Para mostrar nombres, el frontend usa `GET /users?ids=…` y `GET /cis/{id}`.

#### IN-01 · `GET /incidents` — Listar incidentes
**Estado:** A (sin paginación ni formato del contrato) · **Roles:** admin, agent, customer (solo los suyos)
Query: comunes + filtros de la [sección 5](#5-paginación-filtros-y-ordenamiento). Colas de agente:
- Sin asignar: `?assignee_id=none&status=new,in_progress`
- Míos: `?assignee_id=me&status=new,in_progress,on_hold`
- SLA en riesgo: `?status=new,in_progress&sort_by=sla_due_at&sort_order=asc`

Respuesta `200`: `{"data": Incident[], "meta": {...}}`.

#### IN-02 · `POST /incidents` — Crear incidente
**Estado:** B (declarada, responde 501) · **Roles:** admin, agent, customer

```json
{
  "title": "No carga el sistema de historias clínicas",
  "description": "Desde las 8:10 la aplicación muestra error 502 en todas las sedes.",
  "impact": "high",
  "urgency": "high",
  "ci_id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f",
  "team_id": "b6f0a2d4-5c7e-4f81-9a3b-2d4c6e8f0a1b",
  "assignee_id": null
}
```

Validaciones: `title` 3–200 (obligatorio); `description` máx. 5000; `impact` y `urgency` obligatorios (enum);
`ci_id`, `team_id`, `assignee_id` UUID opcionales; `customer` no puede enviar `team_id` ni `assignee_id` (`400`).
El backend fija: `key`, `status = "new"`, `priority` (matriz D6), `sla_policy_id` y `sla_due_at` (según `sla_policies`
de esa prioridad), `sla_breached = false`, `reporter_id = sub`, `channel = "portal"`, `created_at`.
Respuesta `201`: `{"data": Incident}`. Publica `IncidentCreated`.

#### IN-03 · `GET /incidents/{id}` — Consultar incidente
**Estado:** C · **Roles:** admin, agent, customer (solo si es el reportante; si no, `404`) · Respuesta `200`: `{"data": Incident}`.

#### IN-04 · `PATCH /incidents/{id}` — Actualizar incidente
**Estado:** C (el diseño decía `PUT /incidents/{id}`, ver D5) · **Roles:** admin, agent

```json
{ "assignee_id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90", "team_id": "b6f0a2d4-5c7e-4f81-9a3b-2d4c6e8f0a1b", "urgency": "medium" }
```

Campos: `title`, `description`, `impact`, `urgency`, `ci_id`, `team_id`, `assignee_id`, `problem_id` (los cuatro últimos
admiten `null`). Si cambia `impact` o `urgency`, el backend recalcula `priority` y `sla_due_at`. Un incidente `closed`
no se edita (`409 CONFLICT`). Respuesta `200`: `{"data": Incident}`. Publica `IncidentUpdated`.

#### IN-05 · `PUT /incidents/{id}/status` — Cambiar estado
**Estado:** C · **Roles:** admin, agent; customer solo `resolved → closed` o `resolved → in_progress` en los suyos

```json
{ "status": "resolved", "comment": "Se reinició el pool de conexiones del balanceador. Servicio normal desde las 9:02." }
```

Validaciones: `status` enum; `comment` 1–5000, obligatorio al pasar a `resolved`. Ver [sección 7](#7-transiciones-de-estado).
Respuesta `200`: `{"data": Incident}`. Errores: `409 INVALID_STATUS_TRANSITION`. Publica `IncidentUpdated` y, si pasa a `resolved`, `IncidentResolved`.

#### IN-06 · `GET /incidents/{id}/comments` — Listar comentarios
**Estado:** C · **Roles:** admin, agent, customer (solo en los suyos y sin comentarios `internal`)

```json
{
  "data": [
    {
      "id": "e1f2a3b4-c5d6-4e7f-8a9b-0c1d2e3f4a5b",
      "incident_id": "5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d",
      "author_id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
      "body": "Estamos revisando el balanceador de la sede central.",
      "internal": false,
      "created_at": "2026-11-05T08:25:13Z"
    }
  ],
  "meta": { "page": 1, "limit": 20, "total": 1, "total_pages": 1 }
}
```

#### IN-07 · `POST /incidents/{id}/comments` — Agregar comentario
**Estado:** C · **Roles:** admin, agent, customer (solo en los suyos)

```json
{ "body": "Adjunto captura del error en la sede San Isidro.", "internal": false }
```

Validaciones: `body` 1–5000; `internal` booleano opcional (defecto `false`); `customer` no puede enviar `internal: true` (`400`).
No se comenta un incidente `closed` (`409 CONFLICT`). Respuesta `201`: `{"data": IncidentComment}`.

### 8.4 ms-problems

- **Responsabilidad:** problemas, causa raíz, vínculo con incidentes, base de errores conocidos (KEDB).
- **Base:** `VITE_API_PROBLEMS_URL` · **BD:** `db_problems` (`problems`, `problem_incidents`, `known_errors`, `problem_tasks`).
- **Multi-tenancy:** schema del token. Solo `admin` y `agent`.

Entidad `Problem` y su detalle:

```json
{
  "id": "7d8e9f0a-1b2c-4d3e-8f4a-5b6c7d8e9f0a",
  "key": "PRB-000045",
  "title": "Caídas recurrentes del balanceador de historias clínicas",
  "description": "Tres incidentes P1 en 24 h sobre srv-historias-01.",
  "status": "investigating",
  "priority": "P1",
  "root_cause": null,
  "ci_id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f",
  "owner_id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
  "fix_change_id": null,
  "created_at": "2026-11-05T10:00:00Z",
  "incident_ids": ["5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d"],
  "known_error": null
}
```

`incident_ids` y `known_error` solo vienen en `GET /problems/{id}` (`ProblemDetail`); el listado devuelve `Problem`.

#### PR-01 · `GET /problems` — Listar problemas
**Estado:** A parcial · **Roles:** admin, agent · Query: comunes + `status`, `priority`, `ci_id`, `owner_id`.
Respuesta `200`: `{"data": Problem[], "meta": {...}}`.

#### PR-02 · `POST /problems` — Crear problema
**Estado:** C · **Roles:** admin, agent

```json
{
  "title": "Caídas recurrentes del balanceador de historias clínicas",
  "description": "Tres incidentes P1 en 24 h sobre srv-historias-01.",
  "priority": "P1",
  "ci_id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f",
  "owner_id": null,
  "incident_ids": ["5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d"]
}
```

Validaciones: `title` 3–200; `description` máx. 5000; `priority` enum obligatorio; `owner_id` defecto `sub`; `incident_ids` máx. 50.
El backend fija `key`, `status = "new"`, `created_at`. Respuesta `201`: `{"data": ProblemDetail}`. Publica `ProblemCreated`
y, si hay `incident_ids`, `ProblemIncidentsLinked`.

#### PR-03 · `GET /problems/{id}` — Consultar problema
**Estado:** C · **Roles:** admin, agent · Respuesta `200`: `{"data": ProblemDetail}`.

#### PR-04 · `PATCH /problems/{id}` — Actualizar problema
**Estado:** C · **Roles:** admin, agent
Campos: `title`, `description`, `priority`, `root_cause` (máx. 5000), `ci_id`, `owner_id`, `fix_change_id`.
Un problema `closed` no se edita (`409`). Respuesta `200`: `{"data": ProblemDetail}`.

#### PR-05 · `PUT /problems/{id}/status` — Cambiar estado
**Estado:** C · **Roles:** admin, agent

```json
{ "status": "resolved" }
```

`status` ∈ `investigating`, `resolved`, `closed`. `known_error` solo con PR-06. Pasar a `resolved` exige `root_cause`.
Respuesta `200`: `{"data": ProblemDetail}`. Errores: `409 INVALID_STATUS_TRANSITION`.

#### PR-06 · `POST /problems/{id}/known-error` — Publicar error conocido
**Estado:** C (el diseño lo menciona) · **Roles:** admin, agent

```json
{
  "symptom": "Error 502 al abrir historias clínicas en todas las sedes.",
  "workaround": "Reiniciar el pool de conexiones desde la consola del balanceador (5 minutos)."
}
```

Validaciones: `symptom` y `workaround` 3–5000. El problema debe estar `investigating` y no tener error conocido (`409`).
Crea `known_errors`, pasa el problema a `known_error`. Respuesta `201`: `{"data": ProblemDetail}`. Publica `KnownErrorPublished`.

#### PR-07 · `POST /problems/{id}/incidents` — Vincular incidentes
**Estado:** C (el diseño lo menciona) · **Roles:** admin, agent

```json
{ "incident_ids": ["5b1e9d7a-2c4f-4e8b-a6d3-9f0e1c2b3a4d", "6c2f0e8b-3d5a-4f9c-b7e4-0a1f2d3c4b5e"] }
```

Inserta en `problem_incidents` (ignora los ya vinculados). No se comprueba que el incidente exista porque vive en otra
base y los servicios no se llaman por HTTP; ms-incidents ignora IDs desconocidos al consumir el evento.
Respuesta `200`: `{"data": ProblemDetail}`. Publica `ProblemIncidentsLinked` (ms-incidents actualiza `incidents.problem_id`).

### 8.5 ms-changes

- **Responsabilidad:** solicitudes de cambio (RFC), riesgo, aprobación CAB, calendario.
- **Base:** `VITE_API_CHANGES_URL` · **BD:** `db_changes` (`changes`, `change_approvals`, `change_cis`, `change_tasks`).
- **Multi-tenancy:** schema del token. Solo `admin` y `agent`; aprueba o rechaza solo `admin`.

Entidad `ChangeDetail`:

```json
{
  "id": "2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d",
  "key": "CHG-000210",
  "title": "Actualizar firmware del balanceador a 15.1.8",
  "description": "Corrige la fuga de conexiones identificada en PRB-000045.",
  "type": "normal",
  "risk": "medium",
  "status": "submitted",
  "rollback_plan": "Restaurar la imagen 15.1.5 desde el respaldo del 04/11.",
  "planned_start": "2026-11-08T03:00:00Z",
  "planned_end": "2026-11-08T05:00:00Z",
  "requester_id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90",
  "problem_id": "7d8e9f0a-1b2c-4d3e-8f4a-5b6c7d8e9f0a",
  "created_at": "2026-11-05T11:30:00Z",
  "cis": [ { "ci_id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f", "new_version": "15.1.8" } ],
  "approvals": []
}
```

`cis` y `approvals` solo vienen en el detalle y en las respuestas de escritura. `ChangeApproval`:
`{"id", "change_id", "approver_id", "decision", "comment", "decided_at"}`.

#### CH-01 · `GET /changes` — Listar cambios
**Estado:** A parcial · **Roles:** admin, agent
Query: comunes + `status`, `type`, `risk`, `requester_id`, `planned_from`, `planned_to`.
Calendario de la semana: `GET /changes?planned_from=2026-11-09T00:00:00Z&planned_to=2026-11-16T00:00:00Z&status=approved,scheduled&sort_by=planned_start&sort_order=asc&limit=100`
(reemplaza `GET /changes/calendar` del diseño, D13). Respuesta `200`: `{"data": Change[], "meta": {...}}`.

#### CH-02 · `POST /changes` — Crear solicitud de cambio
**Estado:** C · **Roles:** admin, agent

```json
{
  "title": "Actualizar firmware del balanceador a 15.1.8",
  "description": "Corrige la fuga de conexiones identificada en PRB-000045.",
  "type": "normal",
  "risk": "medium",
  "rollback_plan": "Restaurar la imagen 15.1.5 desde el respaldo del 04/11.",
  "planned_start": "2026-11-08T03:00:00Z",
  "planned_end": "2026-11-08T05:00:00Z",
  "problem_id": "7d8e9f0a-1b2c-4d3e-8f4a-5b6c7d8e9f0a",
  "cis": [ { "ci_id": "8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f", "new_version": "15.1.8" } ]
}
```

Validaciones: `title` 3–200; `description` máx. 5000; `type` y `risk` enum obligatorios; `rollback_plan` máx. 5000;
`planned_end > planned_start` si vienen ambos; `cis` máx. 50 sin `ci_id` repetidos; `new_version` máx. 50.
El backend fija `key`, `status = "draft"`, `requester_id = sub`, `created_at`. Respuesta `201`: `{"data": ChangeDetail}`.

#### CH-03 · `GET /changes/{id}` — Consultar cambio
**Estado:** C · **Roles:** admin, agent · Respuesta `200`: `{"data": ChangeDetail}`.

#### CH-04 · `PATCH /changes/{id}` — Actualizar cambio
**Estado:** C · **Roles:** admin, agent
Campos: los mismos de CH-02 (`cis` reemplaza la lista completa). Solo en estado `draft` (`409 CONFLICT` en otro caso).
Respuesta `200`: `{"data": ChangeDetail}`.

#### CH-05 · `PUT /changes/{id}/status` — Cambiar estado
**Estado:** C (el diseño lo menciona) · **Roles:** admin, agent

```json
{ "status": "submitted" }
```

`status` ∈ `draft`, `submitted`, `scheduled`, `implemented`, `failed` (`approved`/`rejected` solo con CH-06/CH-07).
Respuesta `200`: `{"data": ChangeDetail}`. Publica `ChangeSubmitted` o `ChangeImplemented` según el caso.

#### CH-06 · `POST /changes/{id}/approve` — Aprobar cambio
**Estado:** C (el diseño tenía `POST /changes/{id}/approvals`) · **Roles:** admin

```json
{ "comment": "Aprobado en CAB del 06/11. Ejecutar en ventana nocturna." }
```

Validaciones: `comment` opcional, máx. 2000. El cambio debe estar `submitted` (`409`). El solicitante no puede aprobar
su propio cambio (`403 FORBIDDEN`). Inserta en `change_approvals` (`decision = "approved"`, `decided_at = now()`) y pasa a `approved`.
Respuesta `200`: `{"data": ChangeDetail}`. Publica `ChangeApproved`.

#### CH-07 · `POST /changes/{id}/reject` — Rechazar cambio
**Estado:** C · **Roles:** admin

```json
{ "comment": "Falta el plan de pruebas posterior a la actualización." }
```

Igual que CH-06, pero `comment` es obligatorio (3–2000) y el cambio pasa a `rejected`. Publica `ChangeRejected`.

### 8.6 ms-requests

- **Responsabilidad:** catálogo de servicios y solicitudes del portal con su aprobación.
- **Base:** `VITE_API_REQUESTS_URL` · **BD:** `db_requests` (`catalog_categories`, `catalog_items`, `service_requests`, `request_approvals`, `fulfillment_tasks`).
- **Multi-tenancy:** schema del token. Para `customer`, el backend agrega `requester_id = sub`.

Entidad `CatalogItem`:

```json
{
  "id": "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b",
  "category_id": 1,
  "category_name": "Accesos",
  "name": "Acceso VPN",
  "form_schema": {
    "fields": [
      { "name": "motivo", "label": "Motivo", "type": "textarea", "required": true },
      { "name": "fecha_fin", "label": "Válido hasta", "type": "date", "required": false },
      { "name": "perfil", "label": "Perfil", "type": "select", "required": true, "options": ["Básico", "Administrador"] }
    ]
  },
  "needs_approval": true,
  "sla_hours": 24
}
```

`form_schema` usa el formato propuesto en D15 (`type` ∈ `text`, `textarea`, `number`, `date`, `select`, `boolean`).

Entidad `ServiceRequestDetail`:

```json
{
  "id": "0f1e2d3c-4b5a-4968-8776-5a4b3c2d1e0f",
  "key": "REQ-000987",
  "catalog_item_id": "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b",
  "catalog_item_name": "Acceso VPN",
  "form_data": { "motivo": "Trabajo remoto los viernes", "perfil": "Básico", "fecha_fin": null },
  "status": "pending_approval",
  "requester_id": "c4d5e6f7-8a9b-4c0d-9e1f-2a3b4c5d6e7f",
  "assignee_id": null,
  "created_at": "2026-11-05T14:12:00Z",
  "fulfilled_at": null,
  "approvals": []
}
```

`catalog_item_name` es derivado (JOIN). `approvals` (`{"id", "request_id", "approver_id", "decision", "decided_at"}`) solo viene en el detalle.

#### RQ-01 · `GET /catalog` — Catálogo de servicios
**Estado:** C (el diseño lo menciona) · **Roles:** admin, agent, customer
Query: `category_id`, `search` (sobre `name`). Sin paginar (≈50 ítems por tenant). Respuesta `200`: `{"data": CatalogItem[]}`.

#### RQ-02 · `GET /requests` — Listar solicitudes
**Estado:** A parcial · **Roles:** admin, agent, customer (solo las suyas)
Query: comunes + `status`, `catalog_item_id`, `requester_id`, `assignee_id`. Respuesta `200`: `{"data": ServiceRequest[], "meta": {...}}`.

#### RQ-03 · `POST /requests` — Crear solicitud
**Estado:** C · **Roles:** admin, agent, customer

```json
{
  "catalog_item_id": "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b",
  "form_data": { "motivo": "Trabajo remoto los viernes", "perfil": "Básico" }
}
```

Validaciones: `catalog_item_id` existente; `form_data` cumple `form_schema` del ítem (obligatorios presentes, tipos
correctos, `select` dentro de `options`, sin campos extra), máx. 8 KB. El backend fija `key`, `requester_id = sub`,
`status` (`pending_approval` si `needs_approval`, si no `submitted`), `created_at`.
Respuesta `201`: `{"data": ServiceRequestDetail}`. Publica `RequestSubmitted`.

#### RQ-04 · `GET /requests/{id}` — Consultar solicitud
**Estado:** C · **Roles:** admin, agent, customer (solo si es el solicitante) · Respuesta `200`: `{"data": ServiceRequestDetail}`.

#### RQ-05 · `PATCH /requests/{id}` — Actualizar solicitud
**Estado:** C (el diseño tenía `PUT /tasks/{id}` para tareas; quedan fuera de esta versión) · **Roles:** admin, agent, customer

- admin, agent: `assignee_id` (UUID o `null`).
- customer (solo las suyas): `form_data`, mientras el estado sea `submitted` o `pending_approval`.

Respuesta `200`: `{"data": ServiceRequestDetail}`. Errores: `400` si un rol envía un campo que no le corresponde; `409 CONFLICT` si ya no es editable.

#### RQ-06 · `PUT /requests/{id}/status` — Cambiar estado
**Estado:** C (el diseño tenía `POST /requests/{id}/approve`) · **Roles:** admin, agent (aprobar o rechazar desde `pending_approval`: solo admin)

```json
{ "status": "approved" }
```

`status` ∈ `approved`, `rejected`, `in_fulfillment`, `fulfilled`. Al aprobar o rechazar desde `pending_approval` se
inserta en `request_approvals`. **El ER no tiene columna de comentario** en `request_approvals`, por eso este endpoint no
recibe `comment`. Respuesta `200`: `{"data": ServiceRequestDetail}`. Publica `RequestApproved`, `RequestRejected` o `RequestFulfilled`.

---

## 9. Decisiones que necesitan aprobación del equipo

Cada fila tiene una recomendación; el contrato está escrito asumiéndola. Si el equipo elige otra opción, se actualiza
este documento, `openapi.yaml` y `api.ts` en el mismo PR.

| # | Decisión | Recomendación | Alternativa | Afecta a |
| --- | --- | --- | --- | --- |
| D1 | Estilo de nombres | HTTP en `snake_case` (igual que SQL y los handlers actuales); eventos en `camelCase` (igual que `events.py` y el consumidor actual) | Todo en `camelCase` con conversión en cada handler | Todos |
| D2 | Nombres de eventos | `PascalCase` (`IncidentCreated`), ya usado en el filtro SNS de incidents | Notación con punto (`incident.created`); obliga a cambiar el filtro | Eventos |
| D3 | Valor de `tenant_id` | Código del tenant (`andina`); el schema es `tenant_andina` | UUID de `public.tenants.id` | JWT, eventos, S3 |
| D4 | Envoltura de respuestas | `{data, meta}` y `{error: {code, message, details}}`; cambia `common/http.py` | Mantener arreglo plano y `{"error": "texto"}` | Todos |
| D5 | Métodos de escritura | `PATCH` parcial + `PUT /{id}/status`; el diseño usaba `PUT /{id}` | `PUT /{id}` con objeto completo | Todos |
| D6 | Impacto, urgencia y prioridad | `high/medium/low` y matriz de la sección 6, prioridad calculada por el backend | Que el agente elija la prioridad a mano | incidents |
| D7 | Hash de contraseñas | PBKDF2-SHA256 (`hashlib`, 310 000 iteraciones), sin binarios en el layer | bcrypt, instalando el layer con `--platform manylinux2014_x86_64` | identity, seed |
| D8 | Roles por endpoint | Matriz de la sección 3.5 (CAB y aprobación de solicitudes = `admin`) | Agregar un rol `approver` | Todos |
| D9 | `configuration_items.created_at` y baja de CI | Agregar `created_at` al ER (el handler ya lo usa); `DELETE` = baja lógica a `retired` | Ordenar por `updated_at`; borrado físico | cmdb |
| D10 | Mensajes duplicados | Tabla `processed_events(event_id uuid PK, processed_at)` en cada schema de los servicios consumidores | Confiar en operaciones idempotentes caso por caso | Eventos |
| D11 | Sesión en el frontend | Token de 1 h en `sessionStorage`, sin refresh token (permite 2 tenants en 2 pestañas en la demo) | `localStorage` (una sola sesión por navegador) | frontend |
| D12 | Campos desconocidos en el body | Rechazar con `400` | Ignorarlos | Todos |
| D13 | Calendario de cambios | `GET /changes` con `planned_from`/`planned_to` | Ruta propia `GET /changes/calendar` | changes |
| D14 | Cambios `standard` | Se aprueban solos al enviarse | Pasan por CAB como los demás | changes |
| D15 | Formato de `catalog_items.form_schema` | `{"fields": [{name, label, type, required, options?}]}` | JSON Schema completo | requests |
| D16 | Alcance de esta versión | Fuera: adjuntos S3, exportes CSV, notificaciones, alta de tenants, tareas (`problem_tasks`, `change_tasks`, `fulfillment_tasks`) e historial `incident_events` por HTTP | Incluirlos ya | Todos |

---

## 10. Validación final

| Comprobación | Resultado |
| --- | --- |
| Todos los endpoints tienen request y response | Sí: 42 operaciones en `openapi.yaml`, cada una con body (si aplica) y respuestas 2xx y de error. |
| OpenAPI coincide con este documento | Sí: comprobado por script (mismas 42 rutas y métodos). |
| TypeScript coincide con OpenAPI | Sí: las 42 operaciones tienen función en `frontend/src/api/`; `tsc --noEmit --strict` sin errores. |
| Campos compatibles con SQL | Sí para `incidents` (migración real). Para los otros 5 servicios se usaron los ER del diseño porque las migraciones están vacías. Excepciones: `created_at` en CI (D9); tabla `processed_events` (D10). |
| Rutas coinciden con API Gateway | Las 6 `GET` de listado y `POST /auth/login`, `POST /incidents` coinciden con los `serverless.yml`. Las otras 34 rutas hay que declararlas. |
| JWT y authorizer compatibles | Sí, con los 2 cambios de la sección 3.3 (exigir `exp` y validar `schema`). |
| Aislamiento multi-tenant | Todas las rutas usan el schema del token; ningún body o query acepta tenant. |

| Microservicio | Contrato definido | Backend compatible | Frontend compatible | Pendientes |
| --- | --- | --- | --- | --- |
| Identity | Sí (7 rutas) | Parcial: falta migración; `GET /users` usa `SELECT *` (expone `password_hash`); login en 501 | Sí (`authService.ts`, `userService.ts`) | D3, D7, D8, D11; cambios del authorizer |
| CMDB | Sí (8 rutas) | Parcial: falta migración; falta `created_at` | Sí (`cmdbService.ts`) | D9; declarar 7 rutas; publicar `CIStatusChanged` |
| Incidents | Sí (7 rutas) | Parcial: migración sin `incident_events`/`incident_attachments`; `POST` en 501; listado sin paginación | Sí (`incidentService.ts`) | D6; terminar consumidor `onCiStatusChanged` |
| Problems | Sí (7 rutas) | Parcial: falta migración | Sí (`problemService.ts`) | D10 (consume eventos) |
| Changes | Sí (7 rutas) | Parcial: falta migración | Sí (`changeService.ts`) | D13, D14 |
| Requests | Sí (6 rutas) | Parcial: falta migración | Sí (`requestService.ts`) | D15; sin comentario en `request_approvals` |
| Transversal | Sí | `common/http.py` no cumple el formato | Sí (`http.ts`) | D1, D2, D4, D5, D12, D16 |

**Estado:** contratos propuestos, **no cerrados**. Se cierran cuando el equipo apruebe D1–D16 (por ejemplo, con un
comentario de aprobación de cada responsable en el PR).
