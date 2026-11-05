# Guía de integración frontend ↔ backend

**Versión:** 0.9 · **Fecha:** 2026-11-05

Cómo usar los contratos de [`API_CONTRACTS.md`](./API_CONTRACTS.md) para que el frontend (Mía) y los backends
(José, Ian, Daniel) avancen en paralelo.

## 1. Archivos y quién los mantiene

| Archivo | Qué es | Quién lo cambia |
| --- | --- | --- |
| `docs/API_CONTRACTS.md` | Contrato en prosa, reglas y decisiones | Cualquiera, por PR aprobado por el equipo |
| `docs/openapi.yaml` | Especificación OpenAPI 3.1 (fuente de verdad de rutas y campos) | Igual que arriba, en el mismo PR |
| `docs/EVENT_CONTRACTS.md` | Eventos SNS/SQS | Igual que arriba |
| `frontend/src/types/api.ts` | Tipos TypeScript que reflejan `openapi.yaml` | Mía, en el mismo PR que cambie el contrato |
| `frontend/src/api/*` | Clientes Axios por microservicio | Mía |

**Regla de cambio:** nadie cambia una ruta, un campo o un estado solo en su código. Primero un PR que toque
`openapi.yaml` + `API_CONTRACTS.md` + `api.ts`, con aprobación de quien consume ese endpoint.

## 2. Preparar el frontend

La carpeta `frontend/` solo tiene `README.md` y los archivos de esta rama. Para crear el proyecto Vite sin perderlos:

```bash
npm create vite@latest frontend -- --template react-ts
# Si pregunta "Current directory is not empty", elegir "Ignore files and continue"
cd frontend
npm install
npm install axios
```

Variables de entorno en `frontend/.env.local` para desarrollo. El `.gitignore` que crea Vite en `frontend/` ignora
`*.local`; compruébenlo antes del primer commit, porque el `.gitignore` de la raíz solo ignora `.env`:

```
VITE_API_IDENTITY_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
VITE_API_CMDB_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
VITE_API_INCIDENTS_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
VITE_API_PROBLEMS_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
VITE_API_CHANGES_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
VITE_API_REQUESTS_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com
```

Las URLs salen de `npx serverless info` de cada servicio (campo `endpoint: GET - https://…/incidents`, sin la ruta).
En Amplify Hosting se cargan en *App settings → Environment variables*. No son secretos: terminan en el bundle público.

`src/api/env.d.ts` ya declara esas variables para TypeScript. Si el proyecto Vite crea `src/vite-env.d.ts`, ambos conviven.

## 3. Uso desde React

### 3.1 Login y sesión

```tsx
import { authService, setUnauthorizedHandler, ApiError } from './api';

// Una sola vez, al iniciar la app (p. ej. en main.tsx):
setUnauthorizedHandler(() => {
  queryClient.clear();
  window.location.assign('/login?expired=1');
});

async function onSubmit(form: { tenant: string; email: string; password: string }) {
  try {
    const { user } = await authService.login({ tenant_code: form.tenant, email: form.email, password: form.password });
    // user.tenant.id ("andina") sirve para el tema y el logo; user.role para el menú
  } catch (e) {
    if (e instanceof ApiError && e.code === 'INVALID_CREDENTIALS') setError('Organización, email o contraseña incorrectos');
    else if (e instanceof ApiError && e.code === 'VALIDATION_ERROR') setFieldErrors(e.details);
    else setError('No se pudo iniciar sesión');
  }
}

// Al recargar la página:
if (authService.hasValidSession()) {
  const user = await authService.me();   // si el token venció, el handler de arriba redirige
}
```

- El token se guarda en `sessionStorage`: cada pestaña tiene su propia sesión, así la demo puede mostrar Andina y
  Pacífico lado a lado en el mismo navegador.
- El interceptor agrega `Authorization: Bearer …` a todas las peticiones; no hay que hacerlo a mano.
- `authService.currentClaims()` devuelve el payload del JWT **solo para la UI**. Ocultar un botón no es seguridad: el
  backend vuelve a comprobar el rol.

### 3.2 Llamadas con TanStack Query

```tsx
const { data, isLoading } = useQuery({
  queryKey: ['incidents', filters],
  queryFn: () => incidentService.list({ ...filters, page, limit: 20 }),
  placeholderData: keepPreviousData,
});
// data.data: Incident[]; data.meta.total_pages para el paginador

const resolve = useMutation({
  mutationFn: (comment: string) => incidentService.changeStatus(id, { status: 'resolved', comment }),
  onSuccess: (inc) => queryClient.setQueryData(['incident', inc.id], inc),
  onError: (e: ApiError) => {
    if (e.code === 'INVALID_STATUS_TRANSITION') toast.error(e.fieldError('status') ?? e.message);
  },
});
```

Filtros con varios valores se pasan como arreglo: `{ status: ['new', 'in_progress'] }` → `?status=new,in_progress`
(lo hace `serializeParams`).

### 3.3 Mostrar nombres de otros servicios

Los incidentes, problemas, cambios y solicitudes guardan `reporter_id`, `assignee_id`, `team_id`, `ci_id` como IDs.
Para mostrar nombres:

```ts
const ids = page.data.flatMap((i) => [i.reporter_id, i.assignee_id]).filter(Boolean) as string[];
const users = await userService.byIds(ids);        // una sola llamada por página
```

`customer` no puede listar usuarios: en el portal se muestra "Agente asignado" sin nombre (o se decide otra cosa en D8).

### 3.4 Manejo de errores en la UI

| `ApiError.code` | Qué hacer |
| --- | --- |
| `VALIDATION_ERROR` | Marcar cada campo con `e.details` (`field`, `issue`). |
| `INVALID_CREDENTIALS` | Mensaje genérico en el login. |
| `SESSION_EXPIRED` | Lo maneja el interceptor (limpia el token y llama al handler). |
| `FORBIDDEN` | "No tienes permiso para esta acción". |
| `NOT_FOUND` | Página 404 (también aparece al abrir por URL un recurso de otro tenant). |
| `INVALID_STATUS_TRANSITION`, `CONFLICT`, `EMAIL_ALREADY_EXISTS` | Toast con `e.message`; refrescar el recurso. |
| `NOT_IMPLEMENTED` | Mientras el backend no exista: usar mocks. |
| `NETWORK_ERROR`, `INTERNAL_ERROR` | Toast genérico; mostrar `e.requestId` si existe para buscarlo en CloudWatch. |

## 4. Trabajar sin backend: mocks con MSW

Mientras las rutas respondan `501` o no existan, el frontend usa [MSW](https://mswjs.io/) con los ejemplos de
`API_CONTRACTS.md`:

```bash
npm install -D msw
npx msw init public/ --save
```

```ts
// src/mocks/handlers.ts
import { http, HttpResponse } from 'msw';
const INC = import.meta.env.VITE_API_INCIDENTS_URL;

export const handlers = [
  http.get(`${INC}/incidents`, () =>
    HttpResponse.json({ data: [/* Incident de ejemplo */], meta: { page: 1, limit: 20, total: 1, total_pages: 1 } })),
  http.put(`${INC}/incidents/:id/status`, async ({ request }) => {
    const body = (await request.json()) as { status: string };
    if (body.status === 'in_progress') return HttpResponse.json({ error: { code: 'INVALID_STATUS_TRANSITION', message: 'Transición no permitida' } }, { status: 409 });
    return HttpResponse.json({ data: { /* Incident actualizado */ } });
  }),
];
```

Activarlo solo en desarrollo (`if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCKS === 'true')`). Así, cuando
cada backend esté desplegado, basta con apagar el mock de ese servicio.

## 5. Para quien implementa un endpoint (backend)

Checklist por endpoint:

1. Declarar la ruta en el `serverless.yml` del servicio con `authorizer: { name: jwtAuthorizer }` (todas menos `POST /auth/login`).
2. Leer el contexto: `ctx = tenant_ctx(event)` → `ctx["schema"]`, `ctx["role"]`, `ctx["user_id"]`, `ctx["tenant_id"]`.
3. Comprobar el rol según la ficha (`403 FORBIDDEN` si no corresponde).
4. Validar el body según el schema de `openapi.yaml` (campos desconocidos → `400`). Nunca leer `tenant_id` ni `schema` del body o la query.
5. `conn = tenant_conn(ctx["schema"])` y consultar **solo** con parámetros (`:nombre` de pg8000), nunca formateando
   valores en el SQL. `sort_by` se valida contra la lista blanca antes de ponerlo en `ORDER BY`.
6. Para `customer`, agregar `reporter_id = :sub` / `requester_id = :sub` en incidentes y solicitudes.
7. Responder con `ok()`, `created()`, `paginated()`, `no_content()` o `error()` del `common/http.py` propuesto
   (sección 4.2 del contrato). Fechas en ISO 8601 UTC.
8. Publicar el evento que indique la ficha, después del `COMMIT`.

Ejemplo de handler de listado con el contrato:

```python
SORTABLE = {"created_at", "priority", "sla_due_at", "status", "key"}

def listIncidents(event, context):
    ctx = tenant_ctx(event)
    q = event.get("queryStringParameters") or {}
    page, limit = int(q.get("page", 1)), int(q.get("limit", 20))
    sort_by = q.get("sort_by", "created_at")
    order = "ASC" if q.get("sort_order") == "asc" else "DESC"
    if sort_by not in SORTABLE or not (1 <= limit <= 100) or page < 1:
        return error("VALIDATION_ERROR", "Parámetros inválidos", 400, request_id=context.aws_request_id)

    where, args = [], {}
    if ctx["role"] == "customer":
        where.append("reporter_id = :me"); args["me"] = ctx["user_id"]
    if q.get("status"):
        where.append("status = ANY(:status)"); args["status"] = q["status"].split(",")
    # … resto de filtros
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""

    conn = tenant_conn(ctx["schema"])
    total = conn.run(f"SELECT count(*) FROM incidents {sql_where}", **args)[0][0]
    rows = conn.run(f"SELECT * FROM incidents {sql_where} ORDER BY {sort_by} {order} "
                    f"LIMIT :limit OFFSET :offset", limit=limit, offset=(page - 1) * limit, **args)
    cols = [c["name"] for c in conn.columns]
    return paginated([dict(zip(cols, r)) for r in rows], page, limit, total)
```

Probar un endpoint desplegado:

```bash
TOKEN=$(curl -s -X POST "$IDENTITY_URL/auth/login" -H 'Content-Type: application/json' \
  -d '{"tenant_code":"andina","email":"lucia.paredes@andina.pe","password":"Andina#2026"}' | jq -r .data.access_token)
curl -s "$INCIDENTS_URL/incidents?status=new,in_progress&limit=5" -H "Authorization: Bearer $TOKEN" | jq
```

## 6. Prueba de aislamiento para la demo

1. Pestaña A: login en `andina`; pestaña B: login en `pacifico`.
2. Copiar el `id` de un incidente de A y abrir `/incidents/<id>` en B → la API responde `404 NOT_FOUND`.
3. En B, enviar `POST /incidents` con `"tenant_id": "andina"` en el body → `400 VALIDATION_ERROR` (campo no permitido).
4. Modificar a mano el payload del JWT en `sessionStorage` → API Gateway responde `403` (firma inválida) y la app vuelve al login.

## 7. Orden sugerido de integración

| Paso | Backend | Frontend |
| --- | --- | --- |
| 1 | José: `common/http.py` nuevo, authorizer con `require`, `POST /auth/login`, `GET /auth/me` | Login real, sesión, layout por rol; el resto con MSW |
| 2 | Ian: `GET/POST /incidents`, detalle, estado, comentarios | Colas de agente y portal de incidentes |
| 3 | José: `GET /users?ids=`, `GET /teams`, CMDB | Nombres reales, CMDB |
| 4 | Ian: problemas; Daniel: cambios y solicitudes | Pantallas de problemas, cambios (calendario, CAB), catálogo y solicitudes |
| 5 | Todos: eventos y consumidores | Ver efectos (incidente automático, notificaciones) en la demo |
