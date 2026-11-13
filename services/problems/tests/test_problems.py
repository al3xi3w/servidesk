"""Pruebas unitarias de PR-01: GET /problems."""

import json
import sys
import types
import unittest
import uuid

from pathlib import Path
from unittest.mock import MagicMock, patch


# 1. Agregar ms-problems al path de Python
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

    def error(message, status=400):
        return ok({"error": message}, status)

    http.tenant_ctx = tenant_ctx
    http.ok = ok
    http.error = error
    sys.modules["common.http"] = http

# Simular el módulo de eventos compartido de AWS
if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import problems


class TestProblems(unittest.TestCase):

    def setUp(self):
        self.user_id = str(uuid.uuid4())
        self.problem_id = str(uuid.uuid4())
        self.ci_id = str(uuid.uuid4())

        self.problem = {
            "id": self.problem_id,
            "key": "PRB-000001",
            "title": "Caídas recurrentes",
            "description": "Problemas de conexión",
            "status": "investigating",
            "priority": "P1",
            "root_cause": None,
            "ci_id": self.ci_id,
            "owner_id": self.user_id,
            "fix_change_id": None,
            "created_at": "2026-11-05T10:00:00Z",
        }

        self.mock_conn = MagicMock()

        self.mock_conn.columns = [
            {"name": field}
            for field in self.problem
        ]

        self.total = 1
        self.records = [tuple(self.problem.values())]

        def fake_run(sql, **params):
            if "SELECT COUNT(*) FROM problems" in sql:
                return [(self.total,)]

            if "SELECT * FROM problems" in sql:
                return self.records

            raise AssertionError(
                f"Consulta SQL inesperada: {sql}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.user_id,
                    }
                }
            },
            "queryStringParameters": None,
        }

        # Simular conexión a PostgreSQL
        self.db_patch = patch.object(
            problems,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1: Listado por defecto
    def test_listar_problemas(self):
        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["meta"]["page"], 1)
        self.assertEqual(body["meta"]["limit"], 20)
        self.assertEqual(body["meta"]["total"], 1)
        self.assertEqual(body["meta"]["total_pages"], 1)

    # TEST 2: Paginación
    def test_paginacion(self):
        self.total = 35

        self.event["queryStringParameters"] = {
            "page": "2",
            "limit": "10",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["meta"]["page"], 2)
        self.assertEqual(body["meta"]["limit"], 10)
        self.assertEqual(body["meta"]["total_pages"], 4)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertEqual(query.kwargs["limit"], 10)
        self.assertEqual(query.kwargs["offset"], 10)

    # TEST 3: Página fuera de rango
    def test_pagina_fuera_de_rango(self):
        self.total = 4
        self.records = []

        self.event["queryStringParameters"] = {
            "page": "50",
            "limit": "20",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["data"], [])
        self.assertEqual(body["meta"]["total"], 4)
        self.assertEqual(body["meta"]["page"], 50)

    # TEST 4: Filtro por estado
    def test_filtrar_estado(self):
        self.event["queryStringParameters"] = {
            "status": "new,investigating",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertIn("status IN", query.args[0])
        self.assertEqual(
            query.kwargs["status_0"], "new"
        )
        self.assertEqual(
            query.kwargs["status_1"], "investigating"
        )

    # TEST 5: Filtro por prioridad
    def test_filtrar_prioridad(self):
        self.event["queryStringParameters"] = {
            "priority": "P1,P2",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertIn("priority IN", query.args[0])
        self.assertEqual(
            query.kwargs["priority_0"], "P1"
        )
        self.assertEqual(
            query.kwargs["priority_1"], "P2"
        )

    # TEST 6: Filtro por CI
    def test_filtrar_ci(self):
        self.event["queryStringParameters"] = {
            "ci_id": self.ci_id,
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertIn("ci_id = :ci_id", query.args[0])
        self.assertEqual(
            query.kwargs["ci_id"], self.ci_id
        )

    # TEST 7: Filtro owner_id=me
    def test_filtrar_mis_problemas(self):
        self.event["queryStringParameters"] = {
            "owner_id": "me",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertIn(
            "owner_id = :owner_id",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["owner_id"],
            self.user_id,
        )

    # TEST 8: Filtro owner_id por UUID
    def test_filtrar_owner_uuid(self):
        owner_id = str(uuid.uuid4())

        self.event["queryStringParameters"] = {
            "owner_id": owner_id,
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertEqual(
            query.kwargs["owner_id"],
            owner_id,
        )

    # TEST 9: Búsqueda por clave o título
    def test_busqueda(self):
        self.event["queryStringParameters"] = {
            "search": "balanceador",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertIn(
            "key ILIKE :search",
            query.args[0],
        )
        self.assertIn(
            "title ILIKE :search",
            query.args[0],
        )
        self.assertEqual(
            query.kwargs["search"],
            "%balanceador%",
        )

    # TEST 10: Ordenamiento
    def test_ordenamiento(self):
        self.event["queryStringParameters"] = {
            "sort_by": "priority",
            "sort_order": "asc",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT * FROM problems"
        )[0]

        self.assertIn(
            "ORDER BY priority ASC",
            query.args[0],
        )

    # TEST 11: Customer sin permiso
    def test_customer_prohibido(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 12: Admin autorizado
    def test_admin_autorizado(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 13: Limit fuera de rango
    def test_limit_invalido(self):
        self.event["queryStringParameters"] = {
            "limit": "101",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 14: Página inválida
    def test_page_invalida(self):
        self.event["queryStringParameters"] = {
            "page": "0",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 15: Ordenamiento inválido
    def test_sort_invalido(self):
        self.event["queryStringParameters"] = {
            "sort_by": "DROP TABLE problems",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16: UUID de CI inválido
    def test_ci_uuid_invalido(self):
        self.event["queryStringParameters"] = {
            "ci_id": "CI-123",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17: Estado inválido
    def test_estado_invalido(self):
        self.event["queryStringParameters"] = {
            "status": "inventado",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18: Búsqueda demasiado corta
    def test_search_invalido(self):
        self.event["queryStringParameters"] = {
            "search": "a",
        }

        response = problems.listProblems(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    
    # ==========================================
    # PR-02: POST /problems
    # ==========================================

    def preparar_creacion(self, incident_ids=None):
        """Simular PostgreSQL para crear problemas."""

        if incident_ids is None:
            incident_ids = []

        self.event["body"] = json.dumps({
            "title": "Caídas recurrentes",
            "description": "Tres incidentes en 24 horas",
            "priority": "P1",
            "ci_id": self.ci_id,
            "incident_ids": incident_ids,
        })

        self.mock_conn.columns = [
            {"name": field}
            for field in self.problem
        ]

        self.mock_conn.run.reset_mock()

        def fake_create_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if "pg_advisory_xact_lock" in query:
                return [(None,)]

            if "MAX(SUBSTRING" in query:
                return [(0,)]

            if "INSERT INTO problems" in query:
                created = dict(self.problem)

                created["key"] = params["key"]
                created["title"] = params["title"]
                created["description"] = params["description"]
                created["status"] = "new"
                created["priority"] = params["priority"]
                created["ci_id"] = params["ci_id"]
                created["owner_id"] = params["owner_id"]

                return [tuple(created.values())]

            if "INSERT INTO problem_incidents" in query:
                return []

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_create_run

        # Simular SNS
        self.publish_patch = patch.object(
            problems,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()
        self.addCleanup(self.publish_patch.stop)

    def consultas_creacion(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 19: Crear problema correctamente
    def test_crear_problema(self):
        self.preparar_creacion()

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 201)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["key"],
            "PRB-000001",
        )
        self.assertEqual(
            body["data"]["status"],
            "new",
        )
        self.assertEqual(
            body["data"]["title"],
            "Caídas recurrentes",
        )
        self.assertEqual(
            body["data"]["incident_ids"],
            [],
        )
        self.assertIsNone(
            body["data"]["known_error"]
        )

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 20: Responsable por defecto
    def test_crear_owner_por_defecto(self):
        self.preparar_creacion()

        problems.createProblem(self.event, None)

        inserts = self.consultas_creacion(
            "INSERT INTO problems"
        )

        self.assertEqual(
            inserts[0].kwargs["owner_id"],
            self.user_id,
        )

    # TEST 21: Responsable explícito
    def test_crear_owner_explicito(self):
        self.preparar_creacion()

        otro_owner = str(uuid.uuid4())

        body = json.loads(self.event["body"])
        body["owner_id"] = otro_owner
        self.event["body"] = json.dumps(body)

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 201)

        inserts = self.consultas_creacion(
            "INSERT INTO problems"
        )

        self.assertEqual(
            inserts[0].kwargs["owner_id"],
            otro_owner,
        )

    # TEST 22: Vincular incidentes
    def test_crear_con_incidentes(self):
        ids = [
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        ]

        self.preparar_creacion(incident_ids=ids)

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 201)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["incident_ids"],
            ids,
        )

        links = self.consultas_creacion(
            "INSERT INTO problem_incidents"
        )

        self.assertEqual(len(links), 2)

        self.assertEqual(
            links[0].kwargs["problem_id"],
            self.problem_id,
        )

        self.assertEqual(
            links[0].kwargs["incident_id"],
            ids[0],
        )

        # Crear con incidentes publica dos eventos
        self.assertEqual(
            self.mock_publish.call_count,
            2,
        )

    # TEST 23: Evitar vínculos duplicados
    def test_crear_incidentes_duplicados(self):
        incident_id = str(uuid.uuid4())

        self.preparar_creacion(
            incident_ids=[incident_id, incident_id]
        )

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 201)

        links = self.consultas_creacion(
            "INSERT INTO problem_incidents"
        )

        self.assertEqual(len(links), 1)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["incident_ids"],
            [incident_id],
        )

    # TEST 24: Publicar ProblemCreated
    def test_publicar_problem_created(self):
        self.preparar_creacion()

        problems.createProblem(self.event, None)

        self.mock_publish.assert_called_once()

        params = self.mock_publish.call_args.kwargs

        self.assertEqual(
            params["event_type"],
            "ProblemCreated",
        )

        self.assertEqual(
            params["tenant_id"],
            "andina",
        )

        self.assertEqual(
            params["data"]["problemId"],
            self.problem_id,
        )

        self.assertEqual(
            params["source"],
            "ms-problems",
        )

    # TEST 25: Publicar ProblemIncidentsLinked
    def test_publicar_problem_incidents_linked(self):
        incident_id = str(uuid.uuid4())

        self.preparar_creacion(
            incident_ids=[incident_id]
        )

        problems.createProblem(self.event, None)

        tipos = [
            call.kwargs["event_type"]
            for call in self.mock_publish.call_args_list
        ]

        self.assertEqual(
            tipos,
            ["ProblemCreated", "ProblemIncidentsLinked"],
        )

        segundo_evento = (
            self.mock_publish.call_args_list[1].kwargs
        )

        self.assertEqual(
            segundo_evento["data"]["incidentIds"],
            [incident_id],
        )

    # TEST 26: Customer no puede crear
    def test_crear_customer_prohibido(self):
        self.preparar_creacion()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 403)

        self.mock_db.assert_not_called()
        self.mock_publish.assert_not_called()

    # TEST 27: Título inválido
    def test_crear_titulo_invalido(self):
        self.preparar_creacion()

        body = json.loads(self.event["body"])
        body["title"] = "AB"
        self.event["body"] = json.dumps(body)

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()
        self.mock_publish.assert_not_called()

    # TEST 28: Prioridad inválida
    def test_crear_prioridad_invalida(self):
        self.preparar_creacion()

        body = json.loads(self.event["body"])
        body["priority"] = "P5"
        self.event["body"] = json.dumps(body)

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 29: Más de 50 incidentes
    def test_crear_demasiados_incidentes(self):
        self.preparar_creacion(
            incident_ids=[
                str(uuid.uuid4())
                for _ in range(51)
            ]
        )

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 30: UUID de incidente inválido
    def test_crear_incidente_uuid_invalido(self):
        self.preparar_creacion(
            incident_ids=["INC-000001"]
        )

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 31: Campos no permitidos
    def test_crear_campos_no_permitidos(self):
        self.preparar_creacion()

        body = json.loads(self.event["body"])
        body["status"] = "closed"
        self.event["body"] = json.dumps(body)

        response = problems.createProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 32: Error en BD provoca rollback
    def test_crear_error_bd_rollback(self):
        self.preparar_creacion()

        original_run = self.mock_conn.run.side_effect

        def fake_error(sql, **params):
            if "INSERT INTO problems" in sql:
                raise RuntimeError(
                    "Error de PostgreSQL"
                )
            return original_run(sql, **params)

        self.mock_conn.run.side_effect = fake_error

        with self.assertRaises(RuntimeError):
            problems.createProblem(
                self.event, None
            )

        self.assertEqual(
            len(self.consultas_creacion("ROLLBACK")),
            1,
        )

        self.assertEqual(
            len(self.consultas_creacion("COMMIT")),
            0,
        )

        self.mock_publish.assert_not_called()


    # ==========================================
    # PR-03: GET /problems/{id}
    # ==========================================

    def preparar_consulta_problema(
        self,
        encontrado=True,
        incident_ids=None,
        known_error=None,
    ):
        """Simular las consultas PostgreSQL de PR-03."""

        if incident_ids is None:
            incident_ids = []

        self.event["pathParameters"] = {
            "id": self.problem_id
        }

        self.mock_conn.run.reset_mock()

        problem = dict(self.problem)

        def fake_get_run(sql, **params):
            query = sql.strip()

            if (
                "SELECT *" in query
                and "FROM problems" in query
            ):
                self.mock_conn.columns = [
                    {"name": field}
                    for field in problem
                ]

                if not encontrado:
                    return []

                return [tuple(problem.values())]

            if "FROM problem_incidents" in query:
                self.mock_conn.columns = [
                    {"name": "incident_id"}
                ]

                return [
                    (incident_id,)
                    for incident_id in incident_ids
                ]

            if "FROM known_errors" in query:
                if known_error is None:
                    return []

                self.mock_conn.columns = [
                    {"name": field}
                    for field in known_error
                ]

                return [tuple(known_error.values())]

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_get_run

    def consultas_detalle(self, fragment):
        """Buscar consultas SQL ejecutadas."""
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 33: Admin consulta problema
    def test_get_problema_admin(self):
        self.preparar_consulta_problema()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["id"],
            self.problem_id,
        )

        self.assertEqual(
            body["data"]["key"],
            "PRB-000001",
        )

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 34: Agent consulta problema
    def test_get_problema_agent(self):
        self.preparar_consulta_problema()

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        queries = self.consultas_detalle(
            "FROM problems"
        )

        self.assertEqual(len(queries), 1)

        self.assertIn(
            "WHERE id = :problem_id",
            queries[0].args[0],
        )

        self.assertEqual(
            queries[0].kwargs["problem_id"],
            self.problem_id,
        )

    # TEST 35: Respuesta ProblemDetail
    def test_get_problem_detail(self):
        self.preparar_consulta_problema()

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])
        data = body["data"]

        self.assertEqual(data["title"], "Caídas recurrentes")
        self.assertEqual(data["priority"], "P1")

        self.assertIn("incident_ids", data)
        self.assertIn("known_error", data)

        self.assertEqual(data["incident_ids"], [])
        self.assertIsNone(data["known_error"])

    # TEST 36: Incidentes vinculados
    def test_get_problema_con_incidentes(self):
        incident_ids = [
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        ]

        self.preparar_consulta_problema(
            incident_ids=incident_ids
        )

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["incident_ids"],
            incident_ids,
        )

        queries = self.consultas_detalle(
            "FROM problem_incidents"
        )

        self.assertEqual(len(queries), 1)

        self.assertEqual(
            queries[0].kwargs["problem_id"],
            self.problem_id,
        )

    # TEST 37: Problema con error conocido
    def test_get_problema_con_known_error(self):
        known_error_id = str(uuid.uuid4())

        known_error = {
            "id": known_error_id,
            "problem_id": self.problem_id,
            "symptom": "Error 502 recurrente",
            "workaround": "Reiniciar conexiones",
        }

        self.preparar_consulta_problema(
            known_error=known_error
        )

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(
            body["data"]["known_error"]["id"],
            known_error_id,
        )

        self.assertEqual(
            body["data"]["known_error"]["symptom"],
            "Error 502 recurrente",
        )

        self.assertEqual(
            body["data"]["known_error"]["workaround"],
            "Reiniciar conexiones",
        )

    # TEST 38: Problema inexistente
    def test_get_problema_no_existe(self):
        self.preparar_consulta_problema(
            encontrado=False
        )

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 404)

        body = json.loads(response["body"])

        self.assertIn("error", body)

        # No consultar relaciones si el problema no existe
        self.assertEqual(
            len(self.consultas_detalle("FROM problem_incidents")),
            0,
        )

        self.assertEqual(
            len(self.consultas_detalle("FROM known_errors")),
            0,
        )

    # TEST 39: UUID inválido
    def test_get_problema_uuid_invalido(self):
        self.event["pathParameters"] = {
            "id": "PRB-000001"
        }

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 400)

        self.mock_db.assert_not_called()

    # TEST 40: Customer no autorizado
    def test_get_problema_customer_prohibido(self):
        self.event["pathParameters"] = {
            "id": self.problem_id
        }

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 403)

        self.mock_db.assert_not_called()

    # TEST 41: Consulta únicamente dentro del tenant
    def test_get_problema_tenant(self):
        self.preparar_consulta_problema()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = problems.getProblem(
            self.event, None
        )

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

        # Un problema existente realiza tres consultas
        self.assertEqual(
            self.mock_conn.run.call_count,
            3,
        )
