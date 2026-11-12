# ms-incidents — ServiDesk

## Estado actual

Se implementaron las funcionalidades principales de creación de incidentes del microservicio `ms-incidents`, siguiendo los contratos `API_CONTRACTS.md` y `EVENT_CONTRACTS.md`.

### Funcionalidades implementadas

- Creación de incidentes mediante `POST /incidents`.
- Cálculo automático de prioridad según impacto y urgencia (matriz D6).
- Consulta de políticas SLA para calcular la fecha límite de resolución.
- Asignación del reportante desde el contexto del usuario autenticado.
- Generación de claves correlativas por tenant.
- Publicación del evento `IncidentCreated`.
- Creación automática de incidentes P2 mediante eventos `CIStatusChanged` recibidos por SQS.
- Detección de eventos duplicados y manejo de fallos parciales.

## Pruebas unitarias

Se realizaron 20 pruebas unitarias con `pytest` y mocks:

- `test_incidents.py`: 10 pruebas exitosas.
- `test_consumers.py`: 10 pruebas exitosas.

Para ejecutar todas las pruebas desde la raíz del repositorio:

```bash
python -m pytest services/incidents/tests/ -v
```

Las pruebas fueron realizadas localmente, sin conexiones reales a AWS ni PostgreSQL.

## Pendientes necesarios para integración

### 1. Configurar políticas SLA

Definir con el equipo los valores oficiales de `response_minutes` y `resolution_minutes` para P1, P2, P3 y P4.

Registrar las políticas mediante una migración SQL y asegurar su ejecución para cada tenant.

**Necesario:** los handlers consultan `sla_policies` antes de crear un incidente.

### 2. Crear tabla `processed_events`

Agregar esta tabla mediante una migración SQL en los schemas de los tenants.

**Necesario:** `consumers.py` la utiliza para evitar procesar dos veces el mismo evento SQS.

### 3. Configurar SQS

Agregar `functionResponseType: ReportBatchItemFailures` al evento SQS de `onCiStatusChanged` en `serverless.yml`.

**Necesario:** permite que AWS Lambda interprete los fallos individuales de los mensajes procesados.

### 4. Completar seguridad de `GET /incidents`

Implementar el filtrado por `reporter_id` para que los usuarios `customer` únicamente puedan consultar sus propios incidentes.

Incorporar la paginación y los filtros definidos en IN-01 para cumplir el contrato de API.

**Necesario antes de habilitar el endpoint para usuarios reales.**

### 5. Integración con AWS

Cuando la infraestructura compartida esté disponible, verificar:

- Conectividad con RDS PostgreSQL.
- Ejecución de las migraciones.
- Funcionamiento de API Gateway y Lambda Authorizer.
- Permisos de publicación en SNS.
- Recepción y procesamiento de eventos SQS.

## Observaciones

El microservicio se encuentra implementado y probado a nivel unitario. No se ha realizado un despliegue ni pruebas de integración en AWS.

Los tiempos SLA oficiales están pendientes de definición por parte del equipo.

Los contratos utilizados corresponden a la propuesta v0.9, pendiente de aprobación definitiva.