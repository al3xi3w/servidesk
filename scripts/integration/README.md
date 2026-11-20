# Pruebas de integración contra PostgreSQL real

Ejecutan los handlers y consumidores **reales** (con el `common.db` del layer y pg8000) contra
PostgreSQL 16, la misma versión de RDS. SNS se simula: los eventos publicados se capturan y se verifican.
Detectan errores de SQL que las pruebas unitarias con mocks no ven (tipos de parámetros, migraciones,
transacciones, aislamiento entre schemas).

```bash
# 1. Base de prueba (puerto 55432 para no chocar con un PostgreSQL local)
docker run -d --name servidesk-pg -e POSTGRES_USER=servidesk_admin \
  -e POSTGRES_PASSWORD=localpass123 -p 55432:5432 postgres:16

# 2. Dependencias del layer (pg8000, PyJWT)
npm run layer

# 3. Pruebas (cada una recrea su base db_<servicio>)
python scripts/integration/it_identity.py
python scripts/integration/it_services.py incidents
python scripts/integration/it_services.py problems
python scripts/integration/it_services.py changes
python scripts/integration/it_services.py requests

# 4. Limpieza
docker rm -f servidesk-pg
```

En Windows, si la consola no muestra bien las tildes: `set PYTHONIOENCODING=utf-8` (cmd) o
`$env:PYTHONIOENCODING="utf-8"` (PowerShell).
