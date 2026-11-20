"""Migraciones de db_cmdb. Se invoca a mano tras el deploy (es idempotente):

    npx serverless cmdb:invoke --function migrate

En cada schema tenant_* ejecuta migrations/NNN_*.sql en orden y registra los tipos de CI base.
"""

import pathlib
import re

from common.db import ensure_database, get_conn

TENANTS = ["tenant_andina", "tenant_pacifico", "tenant_unitec"]
SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]+$")
MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"

# Mismos tipos que el modo demo del frontend (frontend/src/mocks/db.ts): ids 1..6 en este orden.
CI_TYPES = ["Servidor", "Base de datos", "Aplicación", "Red", "Estación de trabajo", "Servicio cloud"]


def _statements():
    statements = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        sql = path.read_text(encoding="utf-8")
        statements += [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    if not statements:
        raise RuntimeError("No se encontraron migraciones SQL")
    return statements


def handle(event, context):
    statements = _statements()
    ensure_database()
    conn = get_conn()  # no se cierra: Lambda la reutiliza entre invocaciones

    result = {}
    for schema in TENANTS:
        if not SCHEMA_RE.match(schema):
            raise ValueError(f"Nombre de schema inválido: {schema}")
        conn.run("BEGIN")
        try:
            conn.run(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.run(f"SET LOCAL search_path TO {schema}")
            for stmt in statements:
                conn.run(stmt)
            created = 0
            for name in CI_TYPES:
                created += len(conn.run(
                    "INSERT INTO ci_types (name) VALUES (:name) ON CONFLICT (name) DO NOTHING RETURNING id",
                    name=name,
                ))
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        result[schema] = {"ci_types_created": created}

    return {"ok": True, "schemas": result}
