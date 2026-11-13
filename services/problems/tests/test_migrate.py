"""Pruebas unitarias de migraciones de ms-problems."""

import importlib.util
import sys
import types
import unittest

from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
MIGRATE_PATH = ROOT / "handlers" / "migrate.py"
SQL_PATH = ROOT / "migrations" / "001_init.sql"


class TestMigrate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Importar migrate.py sin requerir PostgreSQL."""

        fake_common = types.ModuleType("common")
        fake_common.__path__ = []

        fake_db = types.ModuleType("common.db")
        fake_db.ensure_database = MagicMock()
        fake_db.get_conn = MagicMock()

        spec = importlib.util.spec_from_file_location(
            "problems_migrate_under_test",
            MIGRATE_PATH,
        )

        cls.migrate = importlib.util.module_from_spec(spec)

        with patch.dict(sys.modules, {
            "common": fake_common,
            "common.db": fake_db,
        }):
            spec.loader.exec_module(cls.migrate)

    def setUp(self):
        self.mock_conn = MagicMock()

        self.ensure_patch = patch.object(
            self.migrate,
            "ensure_database",
        )

        self.get_conn_patch = patch.object(
            self.migrate,
            "get_conn",
            return_value=self.mock_conn,
        )

        self.mock_ensure = self.ensure_patch.start()
        self.mock_get_conn = self.get_conn_patch.start()

        self.addCleanup(self.ensure_patch.stop)
        self.addCleanup(self.get_conn_patch.stop)

    def sql_ejecutado(self):
        """Obtener todas las sentencias SQL enviadas."""
        return [
            call.args[0].strip()
            for call in self.mock_conn.run.call_args_list
        ]

    # TEST 1: Existe el archivo SQL
    def test_archivo_migracion_existe(self):
        self.assertTrue(SQL_PATH.is_file())

        sql = SQL_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "CREATE TABLE IF NOT EXISTS problems",
            sql,
        )

    # TEST 2: Define las cuatro tablas
    def test_migracion_define_cuatro_tablas(self):
        sql = SQL_PATH.read_text(encoding="utf-8")

        tablas = [
            "problems",
            "problem_incidents",
            "known_errors",
            "problem_tasks",
        ]

        for tabla in tablas:
            with self.subTest(tabla=tabla):
                self.assertIn(
                    f"CREATE TABLE IF NOT EXISTS {tabla}",
                    sql,
                )

    # TEST 3: Preparar base de datos
    def test_asegurar_base_datos(self):
        self.migrate.handle({}, None)

        self.mock_ensure.assert_called_once_with()
        self.mock_get_conn.assert_called_once_with()

    # TEST 4: Crear schemas de tenants
    def test_crear_schemas(self):
        self.migrate.handle({}, None)

        queries = self.sql_ejecutado()

        for schema in self.migrate.TENANTS:
            self.assertIn(
                f"CREATE SCHEMA IF NOT EXISTS {schema}",
                queries,
            )

    # TEST 5: Seleccionar schema de cada tenant
    def test_configurar_search_path(self):
        self.migrate.handle({}, None)

        queries = self.sql_ejecutado()

        for schema in self.migrate.TENANTS:
            self.assertIn(
                f"SET search_path TO {schema}",
                queries,
            )

    # TEST 6: Ejecutar migración en todos los tenants
    def test_ejecutar_sql_en_cada_tenant(self):
        self.migrate.handle({}, None)

        queries = self.sql_ejecutado()

        for schema in self.migrate.TENANTS:
            create_schema = (
                f"CREATE SCHEMA IF NOT EXISTS {schema}"
            )

            set_schema = (
                f"SET search_path TO {schema}"
            )

            start = queries.index(create_schema)

            self.assertEqual(
                queries[start + 1],
                set_schema,
            )

            # Después de elegir el schema,
            # debe comenzar la ejecución de la migración.
            self.assertIn(
                "CREATE TABLE IF NOT EXISTS problems",
                queries[start + 2],
            )

    # TEST 7: Respuesta correcta
    def test_respuesta_migracion(self):
        result = self.migrate.handle({}, None)

        self.assertEqual(
            result["ok"],
            True,
        )

        self.assertEqual(
            result["schemas"],
            self.migrate.TENANTS,
        )

    # TEST 8: Propagar errores SQL
    def test_error_sql(self):
        self.mock_conn.run.side_effect = RuntimeError(
            "Error simulado de PostgreSQL"
        )

        with self.assertRaises(RuntimeError):
            self.migrate.handle({}, None)

    # TEST 9: Ejecutar todas las sentencias SQL
    def test_ejecutar_todas_las_sentencias(self):
        sql = SQL_PATH.read_text(encoding="utf-8")

        statements = [
            stmt.strip()
            for stmt in sql.split(";")
            if stmt.strip()
        ]

        self.migrate.handle({}, None)

        # Por tenant: CREATE SCHEMA + SET search_path
        # + todas las sentencias del archivo.
        expected_calls = (
            len(self.migrate.TENANTS)
            * (2 + len(statements))
        )

        self.assertEqual(
            self.mock_conn.run.call_count,
            expected_calls,
        )

    # TEST 10: Aislamiento por schema
    def test_orden_de_schemas(self):
        self.migrate.handle({}, None)

        queries = self.sql_ejecutado()

        positions = [
            queries.index(
                f"CREATE SCHEMA IF NOT EXISTS {schema}"
            )
            for schema in self.migrate.TENANTS
        ]

        self.assertEqual(
            positions,
            sorted(positions),
        )

        self.assertEqual(
            len(positions),
            len(set(positions)),
        )
