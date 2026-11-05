"""Conexión a RDS con aislamiento por schema de tenant (Patrón 2)."""
import os
import re
import ssl

import pg8000.native

_SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]+$")
_conn = None  # se reutiliza entre invocaciones de la misma Lambda

# RDS PostgreSQL 16 exige SSL. Para el laboratorio no verificamos el certificado;
# en producción se usaría el bundle de CA de RDS.
_ssl = ssl.create_default_context()
_ssl.check_hostname = False
_ssl.verify_mode = ssl.CERT_NONE


def get_conn():
    global _conn
    if _conn is None:
        _conn = pg8000.native.Connection(
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            database=os.environ["DB_NAME"],
            port=5432,
            ssl_context=_ssl,
        )
    return _conn


def tenant_conn(schema: str):
    """Devuelve una conexión con search_path apuntando al schema del tenant.

    El schema SIEMPRE viene del contexto del authorizer, nunca del body o query.
    """
    if not _SCHEMA_RE.match(schema or ""):
        raise PermissionError("schema de tenant inválido")
    conn = get_conn()
    conn.run(f"SET search_path TO {schema}")
    return conn


def ensure_database():
    """Crea la base lógica del microservicio (DB_NAME) si aún no existe."""
    admin = pg8000.native.Connection(
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        database="postgres",
        port=5432,
        ssl_context=_ssl,
    )
    name = os.environ["DB_NAME"]
    if not admin.run("SELECT 1 FROM pg_database WHERE datname = :n", n=name):
        admin.run(f"CREATE DATABASE {name}")
    admin.close()
