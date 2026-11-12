"""Crea y actualiza las tablas de db_incidents por tenant."""

import pathlib
import re

from common.db import ensure_database, get_conn


# Temporalmente definidos aquí.
# En el futuro se obtendrán de public.tenants.
TENANTS = [
    "tenant_andina",
    "tenant_pacifico",
    "tenant_unitec",
]


def handle(event, context):
    """Ejecuta las migraciones SQL en cada schema."""

    # 1. Localizar la carpeta de migraciones
    migrations_dir = (
        pathlib.Path(__file__).resolve().parent.parent
        / "migrations"
    )

    # 2. Encontrar los archivos SQL en orden
    migrations = sorted(
        migrations_dir.glob("[0-9][0-9][0-9]_*.sql")
    )

    if not migrations:
        raise RuntimeError(
            "No se encontraron migraciones SQL"
        )

    # 3. Asegurar la existencia de la base de datos
    ensure_database()
    conn = get_conn()

    executed = {}

    try:
        # 4. Ejecutar migraciones para cada tenant
        for schema in TENANTS:

            # Validar el nombre antes de utilizarlo en SQL
            if not re.fullmatch(
                r"tenant_[a-z0-9_]+", schema
            ):
                raise ValueError(
                    f"Nombre de schema inválido: {schema}"
                )

            conn.run("BEGIN")

            try:
                conn.run(
                    f"CREATE SCHEMA IF NOT EXISTS {schema}"
                )

                conn.run(
                    f"SET LOCAL search_path TO {schema}"
                )

                executed[schema] = []

                # 5. Ejecutar cada archivo SQL
                for migration in migrations:
                    sql = migration.read_text(
                        encoding="utf-8"
                    )

                    # Los archivos actuales contienen
                    # sentencias SQL separadas por ';'
                    statements = [
                        stmt.strip()
                        for stmt in sql.split(";")
                        if stmt.strip()
                    ]

                    for statement in statements:
                        conn.run(statement)

                    executed[schema].append(
                        migration.name
                    )

                # 6. Confirmar cambios del tenant
                conn.run("COMMIT")

            except Exception:
                conn.run("ROLLBACK")
                raise

    finally:
        conn.close()

    return {
        "ok": True,
        "schemas": TENANTS,
        "migrations": executed,
    }
