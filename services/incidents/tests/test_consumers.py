"""Pruebas unitarias de consumers.py."""

import sys
import json
import types
import unittest
import uuid

from pathlib import Path
from unittest.mock import MagicMock, patch

# 1. Configurar ruta del microservicio
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 2. Simular el Layer común de AWS
if "common" not in sys.modules:
    common = types.ModuleType("common")
    common.__path__ = []
    sys.modules["common"] = common

if "common.db" not in sys.modules:
    db = types.ModuleType("common.db")
    db.tenant_conn = MagicMock()
    sys.modules["common.db"] = db

if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import consumers


class TestConsumers(unittest.TestCase):

    def setUp(self):
        self.mock_conn = MagicMock()

        self.event_id = str(uuid.uuid4())
        self.ci_id = str(uuid.uuid4())
        self.incident_id = str(uuid.uuid4())

        # Columnas devueltas por RETURNING
        self.mock_conn.columns = [
            {"name": "id"},
            {"name": "key"},
            {"name": "title"},
            {"name": "priority"},
            {"name": "ci_id"},
            {"name": "channel"},
        ]

        # Simular consultas PostgreSQL
        def fake_run(sql, **params):
            query = sql.strip()

            if query == "BEGIN":
                return []

            if query == "COMMIT":
                return []

            if query == "ROLLBACK":
                return []

            if "INSERT INTO processed_events" in query:
                return [(self.event_id,)]

            if "FROM sla_policies" in query:
                # SLA ficticio solo para pruebas
                return [(2, 180)]

            if "pg_advisory_xact_lock" in query:
                return [(None,)]

            if "MAX(SUBSTRING" in query:
                return [(0,)]

            if "INSERT INTO incidents" in query:
                return [(
                    self.incident_id,
                    params["key"],
                    params["title"],
                    "P2",
                    params["ci_id"],
                    "auto",
                )]

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        # Evento SQS simulado
        self.message = {
            "eventId": self.event_id,
            "eventType": "CIStatusChanged",
            "tenantId": "andina",
            "source": "ms-cmdb",
            "data": {
                "ciId": self.ci_id,
                "status": "down",
            },
        }

        self.event = {
            "Records": [
                {
                    "messageId": "mensaje-001",
                    "body": json.dumps(self.message),
                }
            ]
        }

        # Simular conexión PostgreSQL
        self.db_patch = patch.object(
            consumers,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()

        # Simular publicación SNS
        self.publish_patch = patch.object(
            consumers,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()

        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.publish_patch.stop)

    def get_queries(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1: Crear incidente si CI está down
    def test_crear_incidente_down(self):
        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result, {
            "batchItemFailures": []
        })

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

        inserts = self.get_queries(
            "INSERT INTO incidents"
        )

        self.assertEqual(len(inserts), 1)
        self.assertEqual(
            inserts[0].kwargs["ci_id"],
            self.ci_id,
        )
        self.assertIn("'P2'", inserts[0].args[0])
        self.assertIn("'auto'", inserts[0].args[0])

    # TEST 2: No crear incidente si CI está up
    def test_no_crear_si_ci_up(self):
        self.message["data"]["status"] = "up"
        self.event["Records"][0]["body"] = json.dumps(
            self.message
        )

        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result["batchItemFailures"], [])
        self.mock_db.assert_not_called()
        self.mock_publish.assert_not_called()

    # TEST 3: Evitar eventos duplicados
    def test_evento_duplicado(self):
        original_run = self.mock_conn.run.side_effect

        def fake_duplicate(sql, **params):
            if "INSERT INTO processed_events" in sql:
                return []
            return original_run(sql, **params)

        self.mock_conn.run.side_effect = fake_duplicate

        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result["batchItemFailures"], [])
        self.assertEqual(
            len(self.get_queries("INSERT INTO incidents")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 4: Consultar política SLA P2
    def test_sla_p2(self):
        consumers.on_ci_status_changed(
            self.event, None
        )

        policies = self.get_queries(
            "FROM sla_policies"
        )

        self.assertEqual(len(policies), 1)
        self.assertIn("'P2'", policies[0].args[0])

        inserts = self.get_queries(
            "INSERT INTO incidents"
        )

        self.assertEqual(
            inserts[0].kwargs["sla_policy_id"],
            2,
        )
        self.assertEqual(
            inserts[0].kwargs["resolution_minutes"],
            180,
        )

    # TEST 5: Publicar IncidentCreated
    def test_publicar_incident_created(self):
        consumers.on_ci_status_changed(
            self.event, None
        )

        self.mock_publish.assert_called_once()

        params = self.mock_publish.call_args.kwargs

        self.assertEqual(
            params["event_type"],
            "IncidentCreated",
        )
        self.assertEqual(
            params["tenant_id"],
            "andina",
        )
        self.assertEqual(
            params["data"]["incidentId"],
            self.incident_id,
        )
        self.assertEqual(
            params["data"]["channel"],
            "auto",
        )
        self.assertEqual(
            params["data"]["priority"],
            "P2",
        )

    # TEST 6: Ignorar otros tipos de eventos
    def test_ignorar_otro_evento(self):
        self.message["eventType"] = "IncidentUpdated"
        self.event["Records"][0]["body"] = json.dumps(
            self.message
        )

        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result["batchItemFailures"], [])
        self.mock_db.assert_not_called()

    # TEST 7: Manejar JSON inválido
    def test_json_invalido(self):
        self.event["Records"][0]["body"] = "{invalido}"

        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result["batchItemFailures"], [
            {"itemIdentifier": "mensaje-001"}
        ])
        self.mock_publish.assert_not_called()

    # TEST 8: SLA no configurado
    def test_sla_no_configurado(self):
        original_run = self.mock_conn.run.side_effect

        def fake_no_sla(sql, **params):
            if "FROM sla_policies" in sql:
                return []
            return original_run(sql, **params)

        self.mock_conn.run.side_effect = fake_no_sla

        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result["batchItemFailures"], [
            {"itemIdentifier": "mensaje-001"}
        ])

        self.assertEqual(
            len(self.get_queries("ROLLBACK")),
            1,
        )
        self.mock_publish.assert_not_called()

    # TEST 9: Error al insertar incidente
    def test_error_base_datos(self):
        original_run = self.mock_conn.run.side_effect

        def fake_error(sql, **params):
            if "INSERT INTO incidents" in sql:
                raise RuntimeError("Error PostgreSQL")
            return original_run(sql, **params)

        self.mock_conn.run.side_effect = fake_error

        result = consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(result["batchItemFailures"], [
            {"itemIdentifier": "mensaje-001"}
        ])

        self.assertEqual(
            len(self.get_queries("ROLLBACK")),
            1,
        )
        self.mock_publish.assert_not_called()

    # TEST 10: Confirmar transacción
    def test_transaccion_commit(self):
        consumers.on_ci_status_changed(
            self.event, None
        )

        self.assertEqual(
            len(self.get_queries("BEGIN")),
            1,
        )
        self.assertEqual(
            len(self.get_queries("COMMIT")),
            1,
        )
        self.assertEqual(
            len(self.get_queries("ROLLBACK")),
            0,
        )
