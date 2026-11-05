"""Crea/actualiza las tablas de db_requests en cada schema de tenant."""
import pathlib

from common.db import ensure_database, get_conn

TENANTS = ["tenant_andina", "tenant_pacifico", "tenant_unitec"]  # luego: leer de public.tenants


def handle(event, context):
    sql = (pathlib.Path(__file__).parent.parent / "migrations" / "001_init.sql").read_text()
    ensure_database()
    conn = get_conn()
    for schema in TENANTS:
        conn.run(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.run(f"SET search_path TO {schema}")
        for stmt in filter(str.strip, sql.split(";")):
            conn.run(stmt)
    return {"ok": True, "schemas": TENANTS}
