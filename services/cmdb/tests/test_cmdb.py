"""Pruebas unitarias de ms-cmdb (CM-01..CM-08, consumidor cmdb-changes-q y migración)."""

import datetime
import json
import unittest
import uuid
from unittest.mock import patch

from support import Ctx, FakeConn, make_event, parse  # noqa: E402  (prepara sys.path y mocks)

from handlers import cis, consumers, migrate  # noqa: E402

CI_ID = uuid.UUID("8c2d4e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f")
TEAM = "b6f0a2d4-5c7e-4f81-9a3b-2d4c6e8f0a1b"
TS = datetime.datetime(2026, 10, 28, 16, 42, 10, 999)


def ci_row(status="operational", attributes=None, name="srv-ventas-01", ci_id=CI_ID):
    return [ci_id, 1, "Servidor", name, status, "prod", "2.4.1", uuid.UUID(TEAM),
            attributes if attributes is not None else {"ip": "10.0.0.1"}, TS, TS]


def detail_conn(*extra_rules, row=None):
    conn = FakeConn(*extra_rules)
    conn.on("FROM configuration_items c JOIN ci_types t", [row or ci_row()])
    return conn


# ------------------------------------------------------------------ CM-01


class TestListCis(unittest.TestCase):
    def call(self, as_role="agent", **query):
        self.conn = FakeConn().on("SELECT COUNT(*)", [[41]]).on("FROM configuration_items c JOIN", [ci_row()])
        with patch.object(cis, "tenant_conn", return_value=self.conn) as tc:
            self.tenant_conn = tc
            return parse(cis.listCis(make_event(role=as_role, query=query or None), Ctx()))

    def test_listado(self):
        status, body = self.call(limit="20")
        self.assertEqual(status, 200)
        ci = body["data"][0]
        self.assertEqual(ci["type_name"], "Servidor")
        self.assertEqual(ci["owner_team_id"], TEAM)
        self.assertEqual(ci["attributes"], {"ip": "10.0.0.1"})
        self.assertEqual(ci["updated_at"], "2026-10-28T16:42:10Z")
        self.assertEqual(body["meta"], {"page": 1, "limit": 20, "total": 41, "total_pages": 3})
        self.tenant_conn.assert_called_once_with("tenant_andina")

    def test_filtros(self):
        status, _ = self.call(status="down,degraded", environment="prod", type_id="2", owner_team_id=TEAM,
                              search="srv_1", sort_by="updated_at", sort_order="asc")
        self.assertEqual(status, 200)
        sql, params = self.conn.find("SELECT COUNT(*)")[0]
        self.assertEqual(params["status"], ["down", "degraded"])
        self.assertEqual(params["environment"], ["prod"])
        self.assertEqual(params["type_id"], 2)
        self.assertEqual(params["owner_team_id"], TEAM)
        self.assertEqual(params["search"], "%srv\\_1%")
        self.assertIn("ORDER BY c.updated_at asc", self.conn.find("LIMIT")[0][0])

    def test_validaciones(self):
        for query, field in (({"status": "roto"}, "status"), ({"environment": "prd"}, "environment"),
                             ({"type_id": "x"}, "type_id"), ({"owner_team_id": "x"}, "owner_team_id"),
                             ({"sort_by": "version"}, "sort_by"), ({"limit": "500"}, "limit")):
            with self.subTest(field=field):
                status, body = self.call(**query)
                self.assertEqual(status, 400)
                self.assertEqual(body["error"]["details"][0]["field"], field)

    def test_cliente_403(self):
        self.assertEqual(self.call(as_role="customer")[0], 403)


# ------------------------------------------------------------------ CM-02


class TestCreateCi(unittest.TestCase):
    def setUp(self):
        self.conn = detail_conn().on("SELECT 1 FROM ci_types", [[1]]).on("INSERT INTO configuration_items",
                                                                         [[CI_ID]])
        patch.object(cis, "tenant_conn", return_value=self.conn).start()
        self.addCleanup(patch.stopall)

    def call(self, as_role="agent", **over):
        body = {"type_id": 1, "name": "srv-ventas-01", "environment": "prod", "version": "2.4.1",
                "owner_team_id": TEAM, "attributes": {"ip": "10.0.0.1"}}
        body.update(over)
        body = {k: v for k, v in body.items() if v is not ...}
        return parse(cis.createCi(make_event(role=as_role, body=body), Ctx()))

    def test_crea_operational_201(self):
        status, body = self.call()
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["id"], str(CI_ID))
        sql, params = self.conn.find("INSERT INTO configuration_items")[0]
        self.assertIn("'operational'", sql)
        self.assertEqual(json.loads(params["attributes"]), {"ip": "10.0.0.1"})
        self.assertTrue(self.conn.find("INSERT INTO ci_history"))
        self.assertIn("COMMIT", self.conn.sql())

    def test_campos_opcionales(self):
        status, _ = self.call(version=..., owner_team_id=..., attributes=...)
        self.assertEqual(status, 201)
        params = self.conn.find("INSERT INTO configuration_items")[0][1]
        self.assertIsNone(params["version"])
        self.assertIsNone(params["owner_team_id"])
        self.assertEqual(params["attributes"], "{}")

    def test_tipo_inexistente_400(self):
        self.conn.rules.insert(0, ("SELECT 1 FROM ci_types", []))
        status, body = self.call(type_id=99)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["details"][0]["field"], "type_id")
        self.assertFalse(self.conn.find("INSERT"))

    def test_validaciones(self):
        cases = [({"type_id": "1"}, "type_id"), ({"type_id": True}, "type_id"), ({"name": "a"}, "name"),
                 ({"environment": "stage"}, "environment"), ({"version": "x" * 51}, "version"),
                 ({"owner_team_id": "abc"}, "owner_team_id"), ({"attributes": [1]}, "attributes"),
                 ({"attributes": {"k": "x" * 9000}}, "attributes"), ({"status": "down"}, "status"),
                 ({"name": ...}, "name"), ({"environment": ...}, "environment"), ({"type_id": ...}, "type_id")]
        for over, field in cases:
            with self.subTest(field=field, over=str(over)[:40]):
                status, body = self.call(**over)
                self.assertEqual(status, 400)
                self.assertIn(field, [d["field"] for d in body["error"]["details"]])

    def test_cliente_403(self):
        self.assertEqual(self.call(as_role="customer")[0], 403)


# ------------------------------------------------------------------ CM-03


class TestGetCi(unittest.TestCase):
    def call(self, conn, ci_id=str(CI_ID), as_role="agent"):
        with patch.object(cis, "tenant_conn", return_value=conn):
            return parse(cis.getCi(make_event(role=as_role, path={"id": ci_id}), Ctx()))

    def test_ok(self):
        status, body = self.call(detail_conn())
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["name"], "srv-ventas-01")

    def test_404_y_400(self):
        self.assertEqual(self.call(FakeConn())[0], 404)
        self.assertEqual(self.call(FakeConn(), ci_id="nope")[0], 400)

    def test_attributes_como_texto(self):
        status, body = self.call(detail_conn(row=ci_row(attributes='{"os": "Linux"}')))
        self.assertEqual(body["data"]["attributes"], {"os": "Linux"})


# ------------------------------------------------------------------ CM-04


class TestUpdateCi(unittest.TestCase):
    def setUp(self):
        current = [[1, "srv-ventas-01", "prod", "2.4.1", uuid.UUID(TEAM), {"ip": "10.0.0.1"}, "operational"]]
        self.conn = detail_conn().on("FOR UPDATE", current).on("SELECT 1 FROM ci_types", [[1]])
        patch.object(cis, "tenant_conn", return_value=self.conn).start()
        self.addCleanup(patch.stopall)

    def call(self, body, as_role="agent"):
        return parse(cis.updateCi(make_event(role=as_role, body=body, path={"id": str(CI_ID)}), Ctx()))

    def test_actualiza_solo_campos_cambiados_y_registra_historial(self):
        status, _ = self.call({"name": "srv-ventas-02", "version": "2.4.1", "attributes": {"ip": "10.0.0.2"},
                               "owner_team_id": TEAM.upper()})
        self.assertEqual(status, 200)
        sql, params = self.conn.find("UPDATE configuration_items")[0]
        self.assertIn("name = :name", sql)
        self.assertIn("attributes = CAST(:attributes AS jsonb)", sql)
        self.assertNotIn("version", params)
        self.assertNotIn("owner_team_id", params)
        history = [p for s, p in self.conn.calls if s.startswith("INSERT INTO ci_history")]
        self.assertEqual(sorted(h["field"] for h in history), ["attributes", "name"])
        name_h = next(h for h in history if h["field"] == "name")
        self.assertEqual((name_h["old"], name_h["new"]), ("srv-ventas-01", "srv-ventas-02"))
        self.assertIn("COMMIT", self.conn.sql())

    def test_sin_cambios_no_actualiza(self):
        status, _ = self.call({"version": "2.4.1"})
        self.assertEqual(status, 200)
        self.assertFalse(self.conn.find("UPDATE configuration_items SET"))

    def test_version_null(self):
        self.call({"version": None})
        self.assertIsNone(self.conn.find("UPDATE configuration_items")[0][1]["version"])

    def test_retirado_409(self):
        self.conn.rules.insert(0, ("FOR UPDATE", [[1, "x", "prod", None, None, {}, "retired"]]))
        status, body = self.call({"name": "nuevo"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "CONFLICT")
        self.assertEqual(self.conn.sql()[-1], "ROLLBACK")

    def test_404(self):
        self.conn.rules.insert(0, ("FOR UPDATE", []))
        self.assertEqual(self.call({"name": "nuevo"})[0], 404)

    def test_tipo_inexistente(self):
        self.conn.rules.insert(0, ("SELECT 1 FROM ci_types", []))
        self.assertEqual(self.call({"type_id": 7})[0], 400)

    def test_validaciones(self):
        for body in ({}, {"status": "down"}, {"name": "x"}, {"type_id": 0}):
            with self.subTest(body=body):
                self.assertEqual(self.call(body)[0], 400)


# ------------------------------------------------------------------ CM-05 y CM-06


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.conn = detail_conn(row=ci_row(status="down")).on("SELECT status FROM configuration_items",
                                                               [["operational"]])
        patch.object(cis, "tenant_conn", return_value=self.conn).start()
        self.publish = patch.object(cis, "publish").start()
        self.addCleanup(patch.stopall)

    def put(self, status, as_role="agent"):
        return parse(cis.changeCiStatus(make_event(role=as_role, body={"status": status},
                                                   path={"id": str(CI_ID)}), Ctx()))

    def test_down_publica_ci_status_changed(self):
        status, body = self.put("down")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "down")
        kwargs = self.publish.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "CIStatusChanged")
        self.assertEqual(kwargs["source"], "ms-cmdb")
        self.assertEqual(kwargs["data"], {"ciId": str(CI_ID), "name": "srv-ventas-01",
                                          "previousStatus": "operational", "status": "down",
                                          "actorId": "11111111-1111-4111-8111-111111111111"})
        hist = self.conn.find("INSERT INTO ci_history")[0][1]
        self.assertEqual((hist["field"], hist["old"], hist["new"]), ("status", "operational", "down"))

    def test_publica_despues_del_commit(self):
        order = []
        run = self.conn.run
        self.conn.run = lambda sql, **p: (order.append(sql.split()[0]), run(sql, **p))[1]
        self.publish.side_effect = lambda **kw: order.append("PUBLISH")
        self.put("down")
        self.assertLess(order.index("COMMIT"), order.index("PUBLISH"))

    def test_mismo_estado_409(self):
        status, body = self.put("operational")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "INVALID_STATUS_TRANSITION")
        self.publish.assert_not_called()

    def test_retirado_409(self):
        self.conn.rules.insert(0, ("SELECT status FROM configuration_items", [["retired"]]))
        self.assertEqual(self.put("operational")[0], 409)

    def test_estado_invalido_y_rol(self):
        self.assertEqual(self.put("caido")[0], 400)
        self.assertEqual(self.put("down", as_role="customer")[0], 403)

    def test_404(self):
        self.conn.rules.insert(0, ("SELECT status FROM configuration_items", []))
        self.assertEqual(self.put("down")[0], 404)

    def delete(self, as_role="admin"):
        return cis.deleteCi(make_event(role=as_role, path={"id": str(CI_ID)}), Ctx())

    def test_delete_baja_logica_204_y_evento(self):
        self.conn.rules.insert(0, ("FROM configuration_items c JOIN ci_types t", [ci_row(status="retired")]))
        response = self.delete()
        self.assertEqual(response["statusCode"], 204)
        self.assertNotIn("body", response)
        self.assertEqual(self.conn.find("UPDATE configuration_items")[0][1]["status"], "retired")
        self.assertEqual(self.publish.call_args.kwargs["data"]["status"], "retired")

    def test_delete_idempotente(self):
        self.conn.rules.insert(0, ("SELECT status FROM configuration_items", [["retired"]]))
        self.assertEqual(self.delete()["statusCode"], 204)
        self.assertFalse(self.conn.find("UPDATE configuration_items SET"))
        self.publish.assert_not_called()

    def test_delete_solo_admin_y_404(self):
        self.assertEqual(self.delete(as_role="agent")["statusCode"], 403)
        self.conn.rules.insert(0, ("SELECT status FROM configuration_items", []))
        self.assertEqual(self.delete()["statusCode"], 404)


# ------------------------------------------------------------------ CM-07 y CM-08


class TestRelationsAndTypes(unittest.TestCase):
    def test_relaciones(self):
        other = uuid.uuid4()
        conn = FakeConn().on("SELECT 1 FROM configuration_items", [[1]]).on("FROM ci_relations", [
            [uuid.uuid4(), "runs_on", "outgoing", other, "vm-cluster-02", "operational", "Servidor"]])
        with patch.object(cis, "tenant_conn", return_value=conn):
            status, body = parse(cis.listCiRelations(make_event(path={"id": str(CI_ID)}), Ctx()))
        self.assertEqual(status, 200)
        rel = body["data"][0]
        self.assertEqual(rel["direction"], "outgoing")
        self.assertEqual(rel["ci"], {"id": str(other), "name": "vm-cluster-02", "status": "operational",
                                     "type_name": "Servidor"})

    def test_relaciones_404(self):
        with patch.object(cis, "tenant_conn", return_value=FakeConn()):
            self.assertEqual(cis.listCiRelations(make_event(path={"id": str(CI_ID)}), Ctx())["statusCode"], 404)

    def test_tipos(self):
        conn = FakeConn().on("FROM ci_types", [[1, "Servidor"], [2, "Base de datos"]])
        with patch.object(cis, "tenant_conn", return_value=conn):
            status, body = parse(cis.listCiTypes(make_event(role="admin"), Ctx()))
        self.assertEqual(body, {"data": [{"id": 1, "name": "Servidor"}, {"id": 2, "name": "Base de datos"}]})
        with patch.object(cis, "tenant_conn", return_value=conn):
            self.assertEqual(cis.listCiTypes(make_event(role="customer"), Ctx())["statusCode"], 403)


# ------------------------------------------------------------------ cmdb-changes-q


def change_record(cis_payload, message_id="m-1", tenant="andina"):
    return {"messageId": message_id, "body": json.dumps({
        "eventId": str(uuid.uuid4()), "eventType": "ChangeImplemented", "tenantId": tenant,
        "source": "ms-changes", "data": {"changeId": str(uuid.uuid4()), "key": "CHG-000010",
                                         "cis": cis_payload, "actorId": str(uuid.uuid4())}})}


class TestChangeImplementedConsumer(unittest.TestCase):
    def run_with(self, conn, records):
        with patch.object(consumers, "tenant_conn", return_value=conn):
            return consumers.on_change_implemented({"Records": records}, None)

    def test_aplica_version_y_historial(self):
        conn = FakeConn().on("INSERT INTO processed_events", [["ok"]]).on("SELECT version", [["2.4.1"]])
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        result = self.run_with(conn, [change_record([{"ciId": a, "newVersion": " 2.5.0 "},
                                                     {"ciId": b, "newVersion": None}])])
        self.assertEqual(result, {"batchItemFailures": []})
        (update,) = conn.find("UPDATE configuration_items")
        self.assertEqual(update[1], {"version": "2.5.0", "id": a})
        (hist,) = conn.find("INSERT INTO ci_history")
        self.assertIn("'ms-changes'", hist[0])
        self.assertEqual((hist[1]["old"], hist[1]["new"]), ("2.4.1", "2.5.0"))
        self.assertEqual(conn.sql()[-1], "COMMIT")

    def test_misma_version_o_retirado_no_cambia(self):
        conn = FakeConn().on("INSERT INTO processed_events", [["ok"]]).on("SELECT version", [["2.5.0"]])
        self.run_with(conn, [change_record([{"ciId": str(uuid.uuid4()), "newVersion": "2.5.0"}])])
        self.assertFalse(conn.find("UPDATE configuration_items SET"))
        conn = FakeConn().on("INSERT INTO processed_events", [["ok"]]).on("SELECT version", [])
        self.run_with(conn, [change_record([{"ciId": str(uuid.uuid4()), "newVersion": "3"}])])
        self.assertFalse(conn.find("UPDATE configuration_items SET"))

    def test_duplicado(self):
        conn = FakeConn().on("INSERT INTO processed_events", [])
        self.run_with(conn, [change_record([{"ciId": str(uuid.uuid4()), "newVersion": "3"}])])
        self.assertFalse(conn.find("SELECT version"))

    def test_fallo_y_mensaje_malformado(self):
        conn = FakeConn().on("INSERT INTO processed_events", [["ok"]]).on("SELECT version", RuntimeError("db"))
        result = self.run_with(conn, [
            change_record([{"ciId": str(uuid.uuid4()), "newVersion": "3"}], message_id="bad"),
            {"messageId": "roto", "body": "{x"},
        ])
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "bad"}, {"itemIdentifier": "roto"}]})
        self.assertIn("ROLLBACK", conn.sql())


# ------------------------------------------------------------------ migración


class TestMigrate(unittest.TestCase):
    def test_tablas_y_tipos_por_tenant(self):
        conn = FakeConn().on("INSERT INTO ci_types", [[1]])
        with patch.object(migrate, "get_conn", return_value=conn), patch.object(migrate, "ensure_database"):
            result = migrate.handle({}, None)
        self.assertEqual(result["schemas"]["tenant_pacifico"], {"ci_types_created": 6})
        sql = conn.sql()
        for table in ("ci_types", "configuration_items", "ci_relations", "ci_history", "processed_events"):
            self.assertTrue(any(f"CREATE TABLE IF NOT EXISTS {table}" in s for s in sql), table)
        self.assertEqual(sql.count("COMMIT"), 3)
        self.assertIn("SET LOCAL search_path TO tenant_unitec", sql)

    def test_rollback(self):
        conn = FakeConn().on("CREATE TABLE IF NOT EXISTS ci_history", RuntimeError("x"))
        with patch.object(migrate, "get_conn", return_value=conn), patch.object(migrate, "ensure_database"):
            with self.assertRaises(RuntimeError):
                migrate.handle({}, None)
        self.assertEqual(conn.sql()[-1], "ROLLBACK")


if __name__ == "__main__":
    unittest.main()
