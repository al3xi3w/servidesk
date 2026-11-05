# ServiDesk — SaaS de gestión de servicios TI (multi-tenant, serverless, EDA)

Proyecto final de Cloud Computing. Monorepo con:

| Carpeta | Qué hay | Responsable |
| --- | --- | --- |
| `infra/` | RDS PostgreSQL, SNS, S3, layer común, Lambda Authorizer | Vannia (+ José el authorizer) |
| `services/identity`, `services/cmdb` | Identidad (login/JWT) y CMDB | José |
| `services/incidents`, `services/problems` | Incidentes y Problemas | Ian |
| `services/changes`, `services/requests` | Cambios y Solicitudes | Daniel |
| `seed/` | Generador de 30 000 registros por servicio | Daniel |
| `frontend/` | React + Vite + TS, desplegado en Amplify | Mía |
| `docs/` | Diagramas | Vannia |

## Despliegue (AWS Academy Learner Lab)
1. Copiar credenciales de *AWS Details* a `~/.aws/credentials` (caducan cada ~4 h).
2. `cp .env.example .env`, poner claves propias y cargarlas en la terminal:
   - Mac/Linux: `set -a; source .env; set +a`
   - Windows PowerShell: `Get-Content .env | % { $k,$v = $_ -split '=',2; if ($k -and $k -notmatch '^#') { Set-Item "env:$k" $v } }`
3. `npm install`
4. `npm run deploy`  (instala el layer y despliega infra + 6 servicios con serverless-compose)
5. Ejecutar la función `migrate` de cada servicio:
   `npx serverless incidents:invoke --function migrate` (igual para identity, cmdb, problems, changes, requests).
