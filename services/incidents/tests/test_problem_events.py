"""Pruebas unitarias de problem_events.py (incidents-problem-q e incidents-kedb-q)."""

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
    sys.modules["common.db"] = db

if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import problem_events  # noqa: E402

PROBLEM = str(uuid.uuid4())
INC_A = str(uuid.uuid4())
INC_B = str(uuid.uuid4())


def record(event_type, data, message_id="m-1", event_id=None, tenant="andina"):
    return {"messageId": message_id, "body": json.dumps({
        "eventId": event_id or str(uuid.uuid4()), "eventType": event_type, "tenantId": tenant,
        "occurredAt": "2026-11-20T10:00:00Z", "source": "ms-problems", "data": data})}


class FakeConn:
    def __init__(self, duplicate=False, fail_on=None, returned=2):
        self.calls = []
        self.duplicate = duplicate
        self.fail_on = fail_on
        self.returned = returned

    def run(self, sql, **params):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("db")
        if sql.startswith("INSERT INTO processed_events"):
            return [] if self.duplicate else [["ok"]]
        if "RETURNING id" in sql:
            return [[uuid.uuid4()] for _ in range(self.returned)]
        return []

    def sqls(self):
        return [c[0] for c in self.calls]


class TestProblemIncidentsLinked(unittest.TestCase):
    def run_with(self, conn, records):
        with patch.object(problem_events, "tenant_conn", return_value=conn) as tc:
            result = problem_events.on_problem_incidents_linked({"Records": records}, None)
        return result, tc

    def test_fija_problem_id(self):
        conn = FakeConn()
        result, tc = self.run_with(conn, [record("ProblemIncidentsLinked", {
            "problemId": PROBLEM, "incidentIds": [INC_B, INC_A, INC_A, "no-uuid"]})])
        self.assertEqual(result, {"batchItemFailures": []})
        tc.assert_called_once_with("tenant_andina")
        sql, params = next(c for c in conn.calls if c[0].startswith("UPDATE incidents"))
        self.assertEqual(params["problem_id"], PROBLEM)
        self.assertEqual(params["ids"], sorted([INC_A, INC_B]))
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertEqual(conn.sqls()[-1], "COMMIT")

    def test_duplicado_no_actualiza(self):
        conn = FakeConn(duplicate=True)
        result, _ = self.run_with(conn, [record("ProblemIncidentsLinked", {"problemId": PROBLEM,
                                                                           "incidentIds": [INC_A]})])
        self.assertEqual(result, {"batchItemFailures": []})
        self.assertFalse(any(s.startswith("UPDATE") for s in conn.sqls()))
        self.assertEqual(conn.sqls()[-1], "COMMIT")

    def test_sin_incidentes_no_actualiza(self):
        conn = FakeConn()
        self.run_with(conn, [record("ProblemIncidentsLinked", {"problemId": PROBLEM, "incidentIds": []})])
        self.assertFalse(any(s.startswith("UPDATE") for s in conn.sqls()))

    def test_otro_tipo_se_ignora(self):
        conn = FakeConn()
        result, tc = self.run_with(conn, [record("ProblemCreated", {"problemId": PROBLEM})])
        self.assertEqual(result, {"batchItemFailures": []})
        tc.assert_not_called()

    def test_fallo_rollback_y_batch_item_failure(self):
        conn = FakeConn(fail_on="UPDATE incidents")
        result, _ = self.run_with(conn, [record("ProblemIncidentsLinked", {
            "problemId": PROBLEM, "incidentIds": [INC_A]}, message_id="bad")])
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "bad"}]})
        self.assertEqual(conn.sqls()[-1], "ROLLBACK")


class TestKnownErrorPublished(unittest.TestCase):
    def run_with(self, conn, records):
        with patch.object(problem_events, "tenant_conn", return_value=conn):
            return problem_events.on_known_error_published({"Records": records}, None)

    def test_comenta_workaround_publico(self):
        conn = FakeConn(returned=3)
        actor = str(uuid.uuid4())
        result = self.run_with(conn, [record("KnownErrorPublished", {
            "problemId": PROBLEM, "workaround": "  Reiniciar el pool  ", "actorId": actor})])
        self.assertEqual(result, {"batchItemFailures": []})
        sql, params = next(c for c in conn.calls if c[0].startswith("INSERT INTO incident_comments"))
        self.assertIn("FALSE", sql)
        self.assertIn("status <> 'closed'", sql)
        self.assertEqual(params["body"], "Solución temporal mientras se corrige: Reiniciar el pool")
        self.assertEqual(params["author_id"], actor)
        self.assertEqual(params["ids"], [])

    def test_usa_incident_ids_si_vienen(self):
        conn = FakeConn()
        self.run_with(conn, [record("KnownErrorPublished", {
            "problemId": PROBLEM, "workaround": "x" * 5, "incidentIds": [INC_A]})])
        params = next(c[1] for c in conn.calls if c[0].startswith("INSERT INTO incident_comments"))
        self.assertEqual(params["ids"], [INC_A])
        self.assertIsNone(params["author_id"])

    def test_sin_workaround_no_comenta(self):
        conn = FakeConn()
        self.run_with(conn, [record("KnownErrorPublished", {"problemId": PROBLEM, "workaround": " "})])
        self.assertFalse(any("incident_comments" in s for s in conn.sqls()))

    def test_mensaje_malformado(self):
        conn = FakeConn()
        result = self.run_with(conn, [
            {"messageId": "roto", "body": "{x"},
            record("KnownErrorPublished", {"problemId": PROBLEM, "workaround": "abcd"}, message_id="ok"),
        ])
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "roto"}]})

    def test_sobre_sns(self):
        conn = FakeConn()
        inner = record("KnownErrorPublished", {"problemId": PROBLEM, "workaround": "abcd"})
        wrapped = {"messageId": "m", "body": json.dumps({"Type": "Notification", "Message": inner["body"]})}
        self.assertEqual(self.run_with(conn, [wrapped]), {"batchItemFailures": []})
        self.assertTrue(any("incident_comments" in s for s in conn.sqls()))


if __name__ == "__main__":
    unittest.main()
