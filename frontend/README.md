# ServiDesk · Frontend (responsable: Mía)

React 19 + TypeScript + Vite. Plataforma ITSM: incidentes, problemas, cambios, catálogo/solicitudes y CMDB.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # genera dist/ (lo que publica Amplify)
```

## Enfoque

ServiDesk es una página para el **cliente** (empresas y sus trabajadores), por eso la interfaz usa lenguaje simple:
Fallas (incidentes), Problemas recurrentes (problemas), Actualizaciones (cambios), Pedidos (solicitudes),
Equipos y sistemas (CMDB), Plazo (SLA), Comité (CAB). En el código y la API se mantienen los nombres ITIL del contrato.

## Rutas

| Ruta | Quién | Qué |
| --- | --- | --- |
| `/` | público | Página de producto ITSM |
| `/login` | público | Login por código de organización (`andina`, `pacifico`, `unitec`) |
| `/app` | todos | Tablero (admin/agent) o portal de autoservicio (customer) |
| `/app/incidents` | todos | Incidentes con SLA, matriz impacto × urgencia, comentarios e internos |
| `/app/problems` | admin, agent | Causa raíz, errores conocidos, incidentes vinculados |
| `/app/changes`, `/app/changes/calendar` | admin, agent | RFC, aprobación CAB (admin), calendario |
| `/app/catalog`, `/app/requests` | todos | Catálogo con formularios dinámicos (`form_schema`) y solicitudes con aprobación |
| `/app/cmdb` | admin, agent | CIs, relaciones; marcar "Caído" genera un incidente automático |
| `/app/users` | admin, agent | Usuarios (CRUD solo admin) y equipos |
| `/demo/plataforma` | admin, agent | **Solo para la presentación** (no está en el menú): los 6 microservicios, diagrama SNS → SQS en vivo y bitácora de eventos |

Además: campana de notificaciones (bandeja de ms-identity), tema y logo por tenant, colas del agente
(sin asignar, míos, SLA en riesgo, SLA vencido) y animaciones (se desactivan con `prefers-reduced-motion`).

## Backend real vs. modo demo

Los clientes de `src/api` usan una URL por microservicio (`VITE_API_*_URL`, ver `.env.example`).
**Si falta la URL de un servicio, ese servicio se simula en el navegador** (`src/mocks`), respetando el contrato
(`docs/API_CONTRACTS.md`): formatos, errores, roles, transiciones y aislamiento por tenant. `VITE_USE_MOCKS=true`
fuerza el simulador en todos. Así se puede ir conectando cada backend a medida que se despliega.

En modo demo, la pantalla de login muestra cuentas de prueba por tenant y rol. Los cambios se guardan en
`localStorage` (compartidos entre pestañas: un agente crea un cambio y el admin lo aprueba en otra pestaña) y se
borran con "Restablecer datos de demo".

## Eventos en modo demo

El simulador publica los eventos de `docs/EVENT_CONTRACTS.md` con el mismo sobre y las mismas colas, y los consumidores
aplican sus efectos con unos segundos de retraso (como SQS):

| Evento | Cola → efecto |
| --- | --- |
| `CIStatusChanged` (down) | `incidents-ci-q` → incidente automático P2, canal `auto` |
| `IncidentCreated` | `problems-incidents-q` → con 3+ incidentes del mismo CI en 24 h crea un problema y los vincula |
| `KnownErrorPublished` | `incidents-kedb-q` → comenta el workaround en los incidentes vinculados |
| `ChangeImplemented` | `cmdb-changes-q` → aplica `new_version` al CI; `problems-changes-q` → cierra el problema con ese `fix_change_id` |
| Incidentes, cambios, solicitudes | `identity-notify-q` → notificaciones en la campana |

En `/demo/plataforma`, "Simular CI caído" y "3 incidentes en un CI" disparan estos flujos con llamadas normales a la API.

**Pendiente de contrato (D16):** `GET /notifications` y `POST /notifications/read` (tipos en `src/types/api.ts`,
cliente en `src/api/notificationService.ts`). Si el backend real no tiene la ruta, la campana se oculta sola.

## Despliegue en Amplify

`amplify.yml` (en la raíz del repo) compila `frontend/` y publica `dist/`. Configurar en Amplify las variables
`VITE_API_*_URL` y la regla de rewrite SPA indicada en ese archivo.
