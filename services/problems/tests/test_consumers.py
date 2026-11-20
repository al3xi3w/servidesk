"""Pruebas unitarias de consumers.py de ms-problems (problems-incidents-q y problems-changes-q)."""

import json
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "common" not in sys.modules:
    common = types.ModuleType("common")
    common.__path__ = []
    sys.modules["common"] = common

if "common.db" not in sys.modules:
    db = types.ModuleType("common.db")
    db.tenant_conn = MagicMock()
    db.ensure_database = MagicMock()
    db.get_conn = MagicMock()
    sys.modules["common.db"] = db

if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import consumers  # noqa: E402

CI = str(uuid.uuid4())
PROBLEM = uuid.uuid4()


def record(event_type, data, message_id="m-1"):
    return {"messageId": message_id, "body": json.dumps({
        "eventId": str(uuid.uuid4()), "eventType": event_type, "tenantId": "andina",
        "occurredAt": "2026-11-20T10:00:00Z", "source": "ms-incidents", "data": data})}


def incident(priority="P3", ci=CI):
    return {"incidentId": str(uuid.uuid4()), "key": "INC-1", "title": "Caja caída", "priority": priority,
            "ciId": ci}


class FakeConn:
    """group: filas (incident_id, priority, title, linked); open_problem: [(id, key)] o []."""

    def __init__(self, group=(), open_problem=(), duplicate=False, max_key=0, closed=()):
        self.calls = []
        self.group = list(group)
        self.open_problem = list(open_problem)
        self.duplicate = duplicate
        self.max_key = max_key
        self.closed = list(closed)

    def run(self, sql, **params):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        if sql.startswith("INSERT INTO processed_events"):
            return [] if self.duplicate else [["ok"]]
        if "FROM ci_incident_log l" in sql:
            return self.group
        if sql.startswith("SELECT id, key FROM problems"):
            return self.open_problem
        if "MAX(SUBSTRING(key" in sql:
            return [[self.max_key]]
        if sql.startswith("INSERT INTO problems"):
            return [[PROBLEM]]
        if sql.startswith("UPDATE problems"):
            return self.closed
        return []

    def find(self, prefix):
        return [c for c in self.calls if c[0].startswith(prefix)]


def group_rows(n, linked=0, priorities=None):
    priorities = priorities or ["P3"] * n
    return [[uuid.uuid4(), priorities[i], f"Falla {i}", i < linked] for i in range(n)]


class TestRecurrence(unittest.TestCase):
    def setUp(self):
        self.publish = patch.object(consumers, "publish").start()
        self.addCleanup(patch.stopall)

    def run_with(self, conn, records):
        with patch.object(consumers, "tenant_conn", return_value=conn):
            return consumers.on_incident_created({"Records": records}, None)

    def test_bajo_umbral_solo_registra(self):
        conn = FakeConn(group=group_rows(2))
        self.assertEqual(self.run_with(conn, [record("IncidentCreated", incident())]), {"batchItemFailures": []})
        self.assertEqual(len(conn.find("INSERT INTO ci_incident_log")), 1)
        self.assertFalse(conn.find("INSERT INTO problems"))
        self.publish.assert_not_called()

    def test_tres_incidentes_crean_problema_con_peor_prioridad(self):
        conn = FakeConn(group=group_rows(3, priorities=["P4", "P2", "P3"]), max_key=41)
        self.run_with(conn, [record("IncidentCreated", incident())])
        (sql, params), = conn.find("INSERT INTO problems")
        self.assertEqual(params["key"], "PRB-000042")
        self.assertEqual(params["priority"], "P2")
        self.assertEqual(params["ci_id"], CI)
        self.assertTrue(params["title"].startswith("[Automático] 3 fallas en 24 h"))
        self.assertEqual(len(conn.find("INSERT INTO problem_incidents")), 3)
        types_published = [c.kwargs["event_type"] for c in self.publish.call_args_list]
        self.assertEqual(types_published, ["ProblemCreated", "ProblemIncidentsLinked"])
        created = self.publish.call_args_list[0].kwargs
        self.assertEqual(created["source"], "ms-problems")
        self.assertEqual(created["tenant_id"], "andina")
        self.assertIsNone(created["data"]["actorId"])

    def test_publica_despues_del_commit(self):
        conn = FakeConn(group=group_rows(3))
        order = []
        conn_run = conn.run
        conn.run = lambda sql, **p: (order.append(sql.strip().split()[0]), conn_run(sql, **p))[1]
        self.publish.side_effect = lambda **kw: order.append("PUBLISH")
        self.run_with(conn, [record("IncidentCreated", incident())])
        self.assertLess(order.index("COMMIT"), order.index("PUBLISH"))

    def test_vincula_al_problema_abierto_del_ci(self):
        conn = FakeConn(group=group_rows(4, linked=3), open_problem=[[PROBLEM, "PRB-000007"]])
        self.run_with(conn, [record("IncidentCreated", incident())])
        self.assertFalse(conn.find("INSERT INTO problems"))
        self.assertEqual(len(conn.find("INSERT INTO problem_incidents")), 1)
        (call,) = self.publish.call_args_list
        self.assertEqual(call.kwargs["event_type"], "ProblemIncidentsLinked")
        self.assertEqual(call.kwargs["data"]["problemId"], str(PROBLEM))

    def test_todos_ya_vinculados(self):
        conn = FakeConn(group=group_rows(3, linked=3))
        self.run_with(conn, [record("IncidentCreated", incident())])
        self.assertFalse(conn.find("INSERT INTO problem_incidents"))
        self.publish.assert_not_called()

    def test_sin_ci_no_aplica(self):
        conn = FakeConn(group=group_rows(5))
        self.run_with(conn, [record("IncidentCreated", incident(ci=None))])
        self.assertFalse(conn.find("INSERT INTO ci_incident_log"))

    def test_bloqueo_por_ci(self):
        conn = FakeConn(group=group_rows(1))
        self.run_with(conn, [record("IncidentCreated", incident())])
        locks = [c for c in conn.calls if "pg_advisory_xact_lock" in c[0]]
        self.assertEqual(locks[0][1], {"ci_id": CI})

    def test_duplicado_no_publica(self):
        conn = FakeConn(group=group_rows(3), duplicate=True)
        self.assertEqual(self.run_with(conn, [record("IncidentCreated", incident())]), {"batchItemFailures": []})
        self.assertFalse(conn.find("INSERT INTO ci_incident_log"))
        self.publish.assert_not_called()

    def test_fallo_en_publish_reporta_el_mensaje(self):
        conn = FakeConn(group=group_rows(3))
        self.publish.side_effect = RuntimeError("sns")
        result = self.run_with(conn, [record("IncidentCreated", incident(), message_id="x")])
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "x"}]})


class TestChangeImplemented(unittest.TestCase):
    def run_with(self, conn, data):
        with patch.object(consumers, "tenant_conn", return_value=conn):
            return consumers.on_change_implemented({"Records": [record("ChangeImplemented", data)]}, None)

    def test_cierra_por_problem_id_o_fix_change_id(self):
        change = str(uuid.uuid4())
        conn = FakeConn(closed=[["PRB-000003"]])
        result = self.run_with(conn, {"changeId": change, "key": "CHG-000210", "problemId": str(PROBLEM)})
        self.assertEqual(result, {"batchItemFailures": []})
        (sql, params), = conn.find("UPDATE problems")
        self.assertIn("status = 'closed'", sql)
        self.assertIn("status <> 'closed'", sql)
        self.assertEqual(params["change_id"], change)
        self.assertEqual(params["problem_id"], str(PROBLEM))
        self.assertIn("CHG-000210", params["root_cause"])

    def test_sin_problem_id(self):
        conn = FakeConn()
        self.run_with(conn, {"changeId": str(uuid.uuid4()), "key": "CHG-1"})
        self.assertIsNone(conn.find("UPDATE problems")[0][1]["problem_id"])

    def test_sin_change_id_no_actualiza(self):
        conn = FakeConn()
        self.run_with(conn, {"key": "CHG-1"})
        self.assertFalse(conn.find("UPDATE problems"))


if __name__ == "__main__":
    unittest.main()
