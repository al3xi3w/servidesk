"""Migraciones de db_identity. Se invoca a mano tras el deploy (es idempotente):

    npx serverless identity:invoke --function migrate

1. Crea public.tenants y registra los 3 tenants.
2. En cada schema tenant_*: crea las tablas (001_init.sql), los equipos base y las
   3 cuentas demo (admin, agent, customer) para poder iniciar sesión de inmediato.
   El volumen de 30 000 registros lo carga el seed (seed/).
"""

import pathlib
import re

from common.db import ensure_database, get_conn
from handlers.identity_common import hash_password
from handlers.tenant_data import TEAMS, TENANTS, demo_users, schema_of, team_id

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]+$")


def _statements(filename):
    sql = (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
    return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]


def _run_public(conn):
    conn.run("BEGIN")
    try:
        for stmt in _statements("000_public.sql"):
            conn.run(stmt)
        for tenant in TENANTS:
            conn.run(
                "INSERT INTO public.tenants (code, schema_name, name) VALUES (:code, :schema, :name) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name",
                code=tenant["code"],
                schema=schema_of(tenant["code"]),
                name=tenant["name"],
            )
        conn.run("COMMIT")
    except Exception:
        conn.run("ROLLBACK")
        raise


def _seed_base(conn, tenant):
    code = tenant["code"]
    for name, description in TEAMS:
        conn.run(
            "INSERT INTO teams (id, name, description) VALUES (CAST(:id AS uuid), :name, :description) "
            "ON CONFLICT DO NOTHING",
            id=team_id(code, name),
            name=name,
            description=description,
        )

    existing = {r[0] for r in conn.run("SELECT email FROM users")}
    created = 0
    for user in demo_users(tenant):
        if user["email"] not in existing:
            conn.run(
                "INSERT INTO users (id, email, full_name, role, password_hash) "
                "VALUES (CAST(:id AS uuid), :email, :full_name, :role, :password_hash) "
                "ON CONFLICT DO NOTHING",
                id=user["id"],
                email=user["email"],
                full_name=user["full_name"],
                role=user["role"],
                password_hash=hash_password(user["password"]),
            )
            created += 1
        if user["role"] != "customer":
            for team_name, _ in TEAMS[:2]:
                conn.run(
                    "INSERT INTO team_members (team_id, user_id, is_lead) "
                    "SELECT CAST(:team_id AS uuid), u.id, :is_lead FROM users u WHERE u.email = :email "
                    "ON CONFLICT DO NOTHING",
                    team_id=team_id(code, team_name),
                    email=user["email"],
                    is_lead=user["role"] == "admin",
                )
    return created


def handle(event, context):
    ensure_database()
    conn = get_conn()

    _run_public(conn)

    tenant_sql = _statements("001_init.sql")
    result = {}
    for tenant in TENANTS:
        schema = schema_of(tenant["code"])
        if not SCHEMA_RE.match(schema):
            raise ValueError(f"Nombre de schema inválido: {schema}")

        conn.run("BEGIN")
        try:
            conn.run(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.run(f"SET LOCAL search_path TO {schema}")
            for stmt in tenant_sql:
                conn.run(stmt)
            created = _seed_base(conn, tenant)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        result[schema] = {"demo_users_created": created}

    return {"ok": True, "schemas": result}
