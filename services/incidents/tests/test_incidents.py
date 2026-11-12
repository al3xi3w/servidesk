
"""Pruebas unitarias de incidents.py."""

import sys
import json
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ruta del microservicio
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Simular el Layer común de AWS
if "common" not in sys.modules:
    common = types.ModuleType("common")
    common.__path__ = []
    sys.modules["common"] = common

if "common.db" not in sys.modules:
    db = types.ModuleType("common.db")
    db.tenant_conn = MagicMock()
    sys.modules["common.db"] = db

if "common.http" not in sys.modules:
    http = types.ModuleType("common.http")

    def tenant_ctx(event):
        return event["requestContext"]["authorizer"]["lambda"]

    def ok(body, status=200):
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, default=str),
        }

    http.tenant_ctx = tenant_ctx
    http.ok = ok
    sys.modules["common.http"] = http

if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import incidents


class TestIncidents(unittest.TestCase):

    def setUp(self):
        self.mock_conn = MagicMock()

        self.reporter_id = (
            "550e8400-e29b-41d4-a716-446655440001"
        )

        self.incident_id = (
            "550e8400-e29b-41d4-a716-446655440000"
        )

        # Datos que simularán una fila de PostgreSQL
        self.incident = {
            "id": self.incident_id,
            "key": "INC-000001",
            "title": "Servidor caído",
            "description": "El servidor no responde",
            "status": "new",
            "impact": "high",
            "urgency": "high",
            "priority": "P1",
            "sla_policy_id": 1,
            "sla_due_at": None,
            "sla_breached": False,
            "reporter_id": self.reporter_id,
            "assignee_id": None,
            "team_id": None,
            "ci_id": None,
            "problem_id": None,
            "channel": "portal",
            "created_at": None,
            "resolved_at": None,
        }

        self.mock_conn.columns = [
            {"name": name}
            for name in self.incident.keys()
        ]

        # Simular las consultas SQL
        def fake_run(sql, **params):
            query = sql.strip()

            if "FROM sla_policies" in query:
                # Política ficticia: ID 1, 180 minutos
                return [(1, 180)]

            if query == "BEGIN":
                return []

            if "pg_advisory_xact_lock" in query:
                return [(None,)]

            if "MAX(SUBSTRING" in query:
                return [(0,)]

            if "INSERT INTO incidents" in query:
                self.incident["priority"] = params["priority"]
                self.incident["impact"] = params["impact"]
                self.incident["urgency"] = params["urgency"]
                return [tuple(self.incident.values())]

            if query == "COMMIT":
                return []

            if query == "ROLLBACK":
                return []

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        # Simular contexto del authorizer
        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.reporter_id,
                    }
                }
            },
            "body": json.dumps({
                "title": "Servidor caído",
                "description": "El servidor no responde",
                "impact": "high",
                "urgency": "high",
            }),
        }

        # Simular conexión PostgreSQL
        self.db_patch = patch.object(
            incidents,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()

        # Simular publicación SNS
        self.publish_patch = patch.object(
            incidents,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()

        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.publish_patch.stop)

    # TEST 1: Creación correcta
    def test_crear_incidente(self):
        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 201)

        body = json.loads(response["body"])

        self.assertIn("data", body)
        self.assertEqual(
            body["data"]["key"],
            "INC-000001",
        )

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 2: Matriz D6
    def test_prioridad_automatica(self):
        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 201)

        inserts = [
            call for call in self.mock_conn.run.call_args_list
            if "INSERT INTO incidents" in call.args[0]
        ]

        self.assertEqual(len(inserts), 1)
        self.assertEqual(
            inserts[0].kwargs["priority"],
            "P1",
        )

    # TEST 3: SLA obtenido de PostgreSQL
    def test_calculo_sla(self):
        incidents.createIncident(self.event, None)

        inserts = [
            call for call in self.mock_conn.run.call_args_list
            if "INSERT INTO incidents" in call.args[0]
        ]

        self.assertEqual(len(inserts), 1)

        params = inserts[0].kwargs
        sql = inserts[0].args[0]

        self.assertEqual(params["sla_policy_id"], 1)
        self.assertEqual(params["resolution_minutes"], 180)
        self.assertIn("INTERVAL '1 minute'", sql)

    # TEST 4: Reporter obtenido del token
    def test_reporter_id(self):
        incidents.createIncident(self.event, None)

        inserts = [
            call for call in self.mock_conn.run.call_args_list
            if "INSERT INTO incidents" in call.args[0]
        ]

        self.assertEqual(
            inserts[0].kwargs["reporter_id"],
            self.reporter_id,
        )

    # TEST 5: Validación de título
    def test_titulo_invalido(self):
        self.event["body"] = json.dumps({
            "title": "AB",
            "impact": "high",
            "urgency": "high",
        })

        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_conn.run.assert_not_called()

    # TEST 6: Restricciones customer
    def test_customer_no_asigna_equipo(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        self.event["body"] = json.dumps({
            "title": "Servidor caído",
            "impact": "high",
            "urgency": "high",
            "team_id": None,
        })

        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_conn.run.assert_not_called()

    # TEST 7: Publicación IncidentCreated
    def test_publicar_evento(self):
        incidents.createIncident(self.event, None)

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

    # TEST 8: JSON inválido
    def test_json_invalido(self):
        self.event["body"] = "{json incorrecto}"

        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_conn.run.assert_not_called()

    # TEST 9: Campos desconocidos
    def test_rechazar_campos_desconocidos(self):
        self.event["body"] = json.dumps({
            "title": "Servidor caído",
            "impact": "high",
            "urgency": "high",
            "tenant_id": "otro_tenant",
        })

        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_conn.run.assert_not_called()

    # TEST 10: SLA no configurado
    def test_sla_no_configurado(self):
        def fake_run_no_sla(sql, **params):
            if "FROM sla_policies" in sql:
                return []
            raise AssertionError(
                "No debe continuar sin política SLA"
            )

        self.mock_conn.run.side_effect = fake_run_no_sla

        response = incidents.createIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 500)
        self.mock_publish.assert_not_called()

    # ==========================================
    # IN-01: GET /incidents
    # ==========================================

    def preparar_listado(self, total=1, registros=None):
        """Simular COUNT y SELECT de PostgreSQL."""

        if registros is None:
            registros = [
                (
                    self.incident_id,
                    "INC-000001",
                    "Servidor caído",
                    self.reporter_id,
                )
            ]

        self.mock_conn.columns = [
            {"name": "id"},
            {"name": "key"},
            {"name": "title"},
            {"name": "reporter_id"},
        ]

        def fake_list_run(sql, **params):
            if "COUNT(*)" in sql:
                return [(total,)]

            if "SELECT * FROM incidents" in sql:
                return registros

            raise AssertionError(
                f"Consulta SQL inesperada: {sql}"
            )

        self.mock_conn.run.side_effect = fake_list_run

    def consultas_listado(self):
        """Obtener consultas SQL del listado."""
        return [
            call for call in self.mock_conn.run.call_args_list
            if "SELECT * FROM incidents" in call.args[0]
        ]

    # TEST 11: Listado con paginación por defecto
    def test_listado_paginacion_defecto(self):
        self.preparar_listado(total=1)

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["meta"]["page"], 1)
        self.assertEqual(body["meta"]["limit"], 20)
        self.assertEqual(body["meta"]["total"], 1)
        self.assertEqual(body["meta"]["total_pages"], 1)

    # TEST 12: Segunda página
    def test_listado_pagina_dos(self):
        self.preparar_listado(total=50)

        self.event["queryStringParameters"] = {
            "page": "2",
            "limit": "10",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["meta"]["page"], 2)
        self.assertEqual(body["meta"]["limit"], 10)
        self.assertEqual(body["meta"]["total"], 50)
        self.assertEqual(body["meta"]["total_pages"], 5)

        queries = self.consultas_listado()
        self.assertEqual(queries[0].kwargs["limit"], 10)
        self.assertEqual(queries[0].kwargs["offset"], 10)

    # TEST 13: Customer solo ve sus incidentes
    def test_listado_customer_solo_propios(self):
        self.preparar_listado()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        # Debe filtrar tanto COUNT como SELECT
        consultas = self.mock_conn.run.call_args_list

        self.assertEqual(len(consultas), 2)

        for consulta in consultas:
            self.assertIn(
                "reporter_id = :reporter_id",
                consulta.args[0],
            )
            self.assertEqual(
                consulta.kwargs["reporter_id"],
                self.reporter_id,
            )

    # TEST 14: Agent puede consultar su tenant
    def test_listado_agent(self):
        self.preparar_listado()

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

        for consulta in self.mock_conn.run.call_args_list:
            self.assertNotIn(
                "reporter_id = :reporter_id",
                consulta.args[0],
            )

    # TEST 15: Cola de incidentes sin asignar
    def test_cola_sin_asignar(self):
        self.preparar_listado()

        self.event["queryStringParameters"] = {
            "assignee_id": "none",
            "status": "new,in_progress",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.consultas_listado()
        sql = queries[0].args[0]

        self.assertIn("assignee_id IS NULL", sql)
        self.assertIn("status IN", sql)

        self.assertEqual(
            queries[0].kwargs["status_0"],
            "new",
        )
        self.assertEqual(
            queries[0].kwargs["status_1"],
            "in_progress",
        )

    # TEST 16: Cola de mis incidentes
    def test_cola_mis_incidentes(self):
        self.preparar_listado()

        self.event["queryStringParameters"] = {
            "assignee_id": "me",
            "status": "new,in_progress,on_hold",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.consultas_listado()
        sql = queries[0].args[0]

        self.assertIn(
            "assignee_id = :assignee_id",
            sql,
        )

        self.assertEqual(
            queries[0].kwargs["assignee_id"],
            self.reporter_id,
        )
        self.assertEqual(
            queries[0].kwargs["status_2"],
            "on_hold",
        )

    # TEST 17: Cola SLA en riesgo
    def test_cola_sla_en_riesgo(self):
        self.preparar_listado()

        self.event["queryStringParameters"] = {
            "status": "new,in_progress",
            "sort_by": "sla_due_at",
            "sort_order": "asc",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.consultas_listado()

        self.assertIn(
            "ORDER BY sla_due_at ASC",
            queries[0].args[0],
        )

    # TEST 18: Filtro de prioridad
    def test_listado_filtrar_prioridad(self):
        self.preparar_listado()

        self.event["queryStringParameters"] = {
            "priority": "P1,P2",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.consultas_listado()

        self.assertIn(
            "priority IN",
            queries[0].args[0],
        )

        self.assertEqual(
            queries[0].kwargs["priority_0"],
            "P1",
        )
        self.assertEqual(
            queries[0].kwargs["priority_1"],
            "P2",
        )

    # TEST 19: Búsqueda por título o clave
    def test_listado_busqueda(self):
        self.preparar_listado()

        self.event["queryStringParameters"] = {
            "search": "servidor",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.consultas_listado()
        sql = queries[0].args[0]

        self.assertIn("key ILIKE :search", sql)
        self.assertIn("title ILIKE :search", sql)

        self.assertEqual(
            queries[0].kwargs["search"],
            "%servidor%",
        )

    # TEST 20: Página fuera de rango
    def test_listado_pagina_fuera_rango(self):
        self.preparar_listado(
            total=5,
            registros=[],
        )

        self.event["queryStringParameters"] = {
            "page": "99",
            "limit": "20",
        }

        response = incidents.listIncidents(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["data"], [])
        self.assertEqual(body["meta"]["total"], 5)
        self.assertEqual(body["meta"]["total_pages"], 1)
        self.assertEqual(body["meta"]["page"], 99)


    # ==========================================
    # IN-03: GET /incidents/{id}
    # ==========================================

    def preparar_consulta_incidente(self, encontrado=True):
        """Simular la consulta de un incidente en PostgreSQL."""

        self.mock_conn.columns = [
            {"name": name}
            for name in self.incident.keys()
        ]

        def fake_get_run(sql, **params):
            if "SELECT *" in sql and "FROM incidents" in sql:
                if encontrado:
                    return [tuple(self.incident.values())]
                return []

            raise AssertionError(
                f"Consulta SQL inesperada: {sql}"
            )

        self.mock_conn.run.side_effect = fake_get_run

        self.event["pathParameters"] = {
            "id": self.incident_id
        }

    # TEST 21: Admin puede consultar incidente
    def test_get_incidente_admin(self):
        self.preparar_consulta_incidente()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["id"],
            self.incident_id,
        )
        self.assertEqual(
            body["data"]["key"],
            "INC-000001",
        )

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 22: Agent puede consultar incidente
    def test_get_incidente_agent(self):
        self.preparar_consulta_incidente()

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.mock_conn.run.call_args_list
        self.assertEqual(len(queries), 1)

        self.assertIn(
            "WHERE id = :incident_id",
            queries[0].args[0],
        )

        self.assertEqual(
            queries[0].kwargs["incident_id"],
            self.incident_id,
        )

    # TEST 23: Customer puede consultar incidente propio
    def test_get_incidente_customer_propio(self):
        self.preparar_consulta_incidente()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.mock_conn.run.call_args

        self.assertIn(
            "reporter_id = :reporter_id",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["reporter_id"],
            self.reporter_id,
        )

    # TEST 24: Customer no puede consultar incidente ajeno
    def test_get_incidente_customer_ajeno(self):
        self.preparar_consulta_incidente(encontrado=False)

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 404)

        query = self.mock_conn.run.call_args

        self.assertIn(
            "reporter_id = :reporter_id",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["reporter_id"],
            self.reporter_id,
        )

    # TEST 25: Incidente inexistente
    def test_get_incidente_no_existe(self):
        self.preparar_consulta_incidente(encontrado=False)

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 404)

        body = json.loads(response["body"])
        self.assertIn("error", body)

    # TEST 26: UUID inválido
    def test_get_incidente_uuid_invalido(self):
        self.event["pathParameters"] = {
            "id": "INC-000001"
        }

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        # No debe consultar PostgreSQL
        self.mock_db.assert_not_called()

    # TEST 27: Rol no autorizado
    def test_get_incidente_rol_no_autorizado(self):
        self.event["pathParameters"] = {
            "id": self.incident_id
        }

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "guest"

        response = incidents.getIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 403)

        self.mock_db.assert_not_called()

    # ==========================================
    # IN-04: PATCH /incidents/{id}
    # ==========================================

    def preparar_actualizacion(self, encontrado=True, cerrado=False,
                               sla_configurado=True):
        """Simular PostgreSQL para actualizar incidentes."""

        self.event["pathParameters"] = {
            "id": self.incident_id
        }

        self.event["body"] = json.dumps({
            "title": "Servidor actualizado"
        })

        # Copia para no modificar el incidente original
        current = dict(self.incident)

        if cerrado:
            current["status"] = "closed"

        self.mock_conn.columns = [
            {"name": name}
            for name in current.keys()
        ]

        def fake_update_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if "SELECT *" in query and "FOR UPDATE" in query:
                if encontrado:
                    return [tuple(current.values())]
                return []

            if "FROM sla_policies" in query:
                if not sla_configurado:
                    return []

                # Tiempo ficticio exclusivamente para tests
                return [(2, 180)]

            if query.startswith("UPDATE incidents SET"):
                # Simular cambios realizados por PostgreSQL
                for field, value in params.items():
                    if field in current:
                        current[field] = value

                return [tuple(current.values())]

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_update_run

    def consultas_update(self):
        """Obtener las consultas UPDATE ejecutadas."""
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if call.args[0].strip().startswith(
                "UPDATE incidents SET"
            )
        ]

    # TEST 28: Actualización correcta
    def test_actualizar_incidente(self):
        self.preparar_actualizacion()

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["title"],
            "Servidor actualizado",
        )

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

        self.assertEqual(len(self.consultas_update()), 1)

    # TEST 29: Recalcular prioridad y SLA
    def test_actualizar_prioridad_y_sla(self):
        self.preparar_actualizacion()

        self.event["body"] = json.dumps({
            "urgency": "medium"
        })

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        # high + medium = P2
        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["priority"],
            "P2",
        )

        sla_queries = [
            call
            for call in self.mock_conn.run.call_args_list
            if "FROM sla_policies" in call.args[0]
        ]

        self.assertEqual(len(sla_queries), 1)

        self.assertEqual(
            sla_queries[0].kwargs["priority"],
            "P2",
        )

        updates = self.consultas_update()

        self.assertEqual(
            updates[0].kwargs["sla_policy_id"],
            2,
        )

        self.assertEqual(
            updates[0].kwargs["resolution_minutes"],
            180,
        )

        self.assertIn(
            "sla_due_at",
            updates[0].args[0],
        )

    # TEST 30: No recalcular SLA si no cambia prioridad
    def test_actualizar_sin_cambiar_impacto_urgencia(self):
        self.preparar_actualizacion()

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        sla_queries = [
            call
            for call in self.mock_conn.run.call_args_list
            if "FROM sla_policies" in call.args[0]
        ]

        self.assertEqual(len(sla_queries), 0)

        updates = self.consultas_update()

        self.assertNotIn(
            "sla_due_at",
            updates[0].args[0],
        )

    # TEST 31: Permitir desasignar agente
    def test_actualizar_assignee_null(self):
        self.preparar_actualizacion()

        self.event["body"] = json.dumps({
            "assignee_id": None
        })

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        updates = self.consultas_update()

        self.assertIsNone(
            updates[0].kwargs["assignee_id"]
        )

    # TEST 32: Customer no puede actualizar
    def test_actualizar_customer_prohibido(self):
        self.preparar_actualizacion()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 403)

        self.mock_db.assert_not_called()
        self.mock_publish.assert_not_called()

    # TEST 33: UUID inválido
    def test_actualizar_uuid_invalido(self):
        self.preparar_actualizacion()

        self.event["pathParameters"] = {
            "id": "INC-000001"
        }

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 34: Campos no permitidos
    def test_actualizar_campos_prohibidos(self):
        self.preparar_actualizacion()

        self.event["body"] = json.dumps({
            "priority": "P1"
        })

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 35: Incidente cerrado
    def test_actualizar_incidente_cerrado(self):
        self.preparar_actualizacion(cerrado=True)

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 409)

        self.assertEqual(
            len(self.consultas_update()),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 36: Incidente inexistente
    def test_actualizar_incidente_no_existe(self):
        self.preparar_actualizacion(encontrado=False)

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 404)

        self.assertEqual(
            len(self.consultas_update()),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 37: SLA no configurado
    def test_actualizar_sla_no_configurado(self):
        self.preparar_actualizacion(
            sla_configurado=False
        )

        self.event["body"] = json.dumps({
            "urgency": "medium"
        })

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 500)

        self.assertEqual(
            len(self.consultas_update()),
            0,
        )

        rollbacks = [
            call
            for call in self.mock_conn.run.call_args_list
            if call.args[0].strip() == "ROLLBACK"
        ]

        self.assertEqual(len(rollbacks), 1)

        self.mock_publish.assert_not_called()

    # TEST 38: Publicar IncidentUpdated
    def test_actualizar_publicar_evento(self):
        self.preparar_actualizacion()

        response = incidents.updateIncident(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        self.mock_publish.assert_called_once()

        params = self.mock_publish.call_args.kwargs

        self.assertEqual(
            params["event_type"],
            "IncidentUpdated",
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
            params["data"]["actorId"],
            self.reporter_id,
        )

        # SNS debe publicarse después del COMMIT
        commits = [
            call
            for call in self.mock_conn.run.call_args_list
            if call.args[0].strip() == "COMMIT"
        ]

        self.assertEqual(len(commits), 1)


    # ==========================================
    # IN-05: PUT /incidents/{id}/status
    # ==========================================

    def preparar_cambio_estado(
        self,
        estado_actual="new",
        encontrado=True,
        error_historial=False,
    ):
        """Simular PostgreSQL para cambios de estado."""

        self.event["pathParameters"] = {
            "id": self.incident_id
        }

        self.event["body"] = json.dumps({
            "status": "in_progress"
        })

        current = dict(self.incident)
        current["status"] = estado_actual

        self.mock_conn.columns = [
            {"name": name}
            for name in current
        ]

        def fake_status_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if (
                query.startswith("SELECT *")
                and "FROM incidents" in query
                and "FOR UPDATE" in query
            ):
                if not encontrado:
                    return []
                return [tuple(current.values())]

            if query.startswith("UPDATE incidents"):
                current["status"] = params["new_status"]

                if params["new_status"] == "resolved":
                    current["resolved_at"] = (
                        "2026-11-05T12:10:00Z"
                    )

                elif (
                    estado_actual == "resolved"
                    and params["new_status"] == "in_progress"
                ):
                    current["resolved_at"] = None

                return [tuple(current.values())]

            if "INSERT INTO incident_events" in query:
                if error_historial:
                    raise RuntimeError(
                        "Error insertando historial"
                    )
                return []

            if "INSERT INTO incident_comments" in query:
                return []

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_status_run

    def consultas_estado(self, fragment):
        """Buscar consultas ejecutadas por el handler."""
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 39: Cambiar new a in_progress
    def test_estado_new_a_in_progress(self):
        self.preparar_cambio_estado()

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["status"],
            "in_progress",
        )

        self.assertEqual(
            len(self.consultas_estado("UPDATE incidents")),
            1,
        )

        self.assertEqual(
            len(self.consultas_estado("INSERT INTO incident_events")),
            1,
        )

        self.assertEqual(
            len(self.consultas_estado("COMMIT")),
            1,
        )

    # TEST 40: Resolver con comentario
    def test_estado_resolver_con_comentario(self):
        self.preparar_cambio_estado(
            estado_actual="in_progress"
        )

        self.event["body"] = json.dumps({
            "status": "resolved",
            "comment": "Servicio restablecido",
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["status"],
            "resolved",
        )

        self.assertIsNotNone(
            body["data"]["resolved_at"]
        )

        comentarios = self.consultas_estado(
            "INSERT INTO incident_comments"
        )

        self.assertEqual(len(comentarios), 1)

        self.assertEqual(
            comentarios[0].kwargs["body"],
            "Servicio restablecido",
        )

        self.assertIn(
            "FALSE",
            comentarios[0].args[0],
        )

        self.assertEqual(
            self.mock_publish.call_count,
            2,
        )

        tipos = [
            call.kwargs["event_type"]
            for call in self.mock_publish.call_args_list
        ]

        self.assertEqual(
            tipos,
            ["IncidentUpdated", "IncidentResolved"],
        )

    # TEST 41: Comentario obligatorio al resolver
    def test_estado_resolver_sin_comentario(self):
        self.preparar_cambio_estado()

        self.event["body"] = json.dumps({
            "status": "resolved"
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.assertEqual(
            len(self.consultas_estado("UPDATE incidents")),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 42: Transición inválida
    def test_estado_transicion_invalida(self):
        self.preparar_cambio_estado(
            estado_actual="new"
        )

        self.event["body"] = json.dumps({
            "status": "closed"
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 409)

        self.assertEqual(
            len(self.consultas_estado("UPDATE incidents")),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 43: Customer cierra incidente resuelto
    def test_estado_customer_cerrar_propio(self):
        self.preparar_cambio_estado(
            estado_actual="resolved"
        )

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        self.event["body"] = json.dumps({
            "status": "closed"
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        consulta = self.consultas_estado(
            "SELECT *"
        )[0]

        self.assertIn(
            "reporter_id = :reporter_id",
            consulta.args[0],
        )

        self.assertEqual(
            consulta.kwargs["reporter_id"],
            self.reporter_id,
        )

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["status"],
            "closed",
        )

    # TEST 44: Customer reabre incidente resuelto
    def test_estado_customer_reabrir_propio(self):
        self.preparar_cambio_estado(
            estado_actual="resolved"
        )

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        self.event["body"] = json.dumps({
            "status": "in_progress"
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["status"],
            "in_progress",
        )

        self.assertIsNone(
            body["data"]["resolved_at"]
        )

        updates = self.consultas_estado(
            "UPDATE incidents"
        )

        self.assertIn(
            "resolved_at = NULL",
            updates[0].args[0],
        )

    # TEST 45: Customer no consulta incidente ajeno
    def test_estado_customer_incidente_ajeno(self):
        self.preparar_cambio_estado(
            encontrado=False
        )

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        self.event["body"] = json.dumps({
            "status": "closed"
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 404)

        consulta = self.consultas_estado(
            "SELECT *"
        )[0]

        self.assertIn(
            "reporter_id = :reporter_id",
            consulta.args[0],
        )

        self.assertEqual(
            len(self.consultas_estado("UPDATE incidents")),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 46: Customer no puede resolver
    def test_estado_customer_transicion_prohibida(self):
        self.preparar_cambio_estado(
            estado_actual="new"
        )

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        self.event["body"] = json.dumps({
            "status": "resolved",
            "comment": "Intento de resolución",
        })

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 403)

        self.assertEqual(
            len(self.consultas_estado("UPDATE incidents")),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 47: Incidente inexistente
    def test_estado_incidente_no_existe(self):
        self.preparar_cambio_estado(
            encontrado=False
        )

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 404)

        self.assertEqual(
            len(self.consultas_estado("UPDATE incidents")),
            0,
        )

        self.mock_publish.assert_not_called()

    # TEST 48: UUID inválido
    def test_estado_uuid_invalido(self):
        self.preparar_cambio_estado()

        self.event["pathParameters"] = {
            "id": "INC-000001"
        }

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 49: JSON inválido
    def test_estado_json_invalido(self):
        self.preparar_cambio_estado()

        self.event["body"] = "{incorrecto}"

        response = incidents.changeIncidentStatus(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 50: Error de BD revierte transacción
    def test_estado_error_historial_rollback(self):
        self.preparar_cambio_estado(
            error_historial=True
        )

        with self.assertRaises(RuntimeError):
            incidents.changeIncidentStatus(
                self.event, None
            )

        self.assertEqual(
            len(self.consultas_estado("ROLLBACK")),
            1,
        )

        self.assertEqual(
            len(self.consultas_estado("COMMIT")),
            0,
        )

        self.mock_publish.assert_not_called()
