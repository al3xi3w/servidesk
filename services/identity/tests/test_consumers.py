"""Pruebas del consumidor identity-notify-q."""

import json
import unittest
import uuid
from unittest.mock import patch

from support import FakeConn  # noqa: E402

from handlers import consumers  # noqa: E402

ADMIN = str(uuid.uuid4())
AGENT = str(uuid.uuid4())
REQUESTER = str(uuid.uuid4())


def record(event_type, data, tenant="andina", event_id=None, message_id="m-1", raw=True):
    envelope = {
        "eventId": event_id or str(uuid.uuid4()),
        "eventType": event_type,
        "tenantId": tenant,
        "occurredAt": "2026-11-20T10:00:00Z",
        "source": "ms-test",
        "data": data,
    }
    body = json.dumps(envelope)
    if not raw:
        body = json.dumps({"Type": "Notification", "Message": body})
    return {"messageId": message_id, "body": body}


def base_conn():
    return (
        FakeConn()
        .on("INSERT INTO processed_events", [["ok"]])
        .on("FROM team_members", [[AGENT]])
        .on("WHERE role = 'admin'", [[ADMIN]])
        .on("INSERT INTO notifications", lambda p: [[uuid.uuid4()] for _ in p["ids"]])
    )


class TestNotifyConsumer(unittest.TestCase):
    def run_records(self, records, conn=None):
        self.conn = conn or base_conn()
        with patch.object(consumers, "tenant_conn", return_value=self.conn) as tc:
            result = consumers.on_notify_event({"Records": records}, None)
        self.tenant_conn = tc
        return result

    def inserts(self):
        return [params for sql, params in self.conn.calls if "INSERT INTO notifications" in sql]

    def test_change_approved_notifica_al_solicitante(self):
        result = self.run_records([record("ChangeApproved", {
            "changeId": str(uuid.uuid4()), "key": "CHG-000210", "requesterId": REQUESTER,
            "approverId": ADMIN, "comment": "Aprobado en CAB", "actorId": ADMIN})])
        self.assertEqual(result, {"batchItemFailures": []})
        (params,) = self.inserts()
        self.assertEqual(params["ids"], [REQUESTER])
        self.assertEqual(params["title"], "La actualización CHG-000210 fue aprobada")
        self.assertEqual(params["body"], "Aprobado en CAB")
        self.assertEqual(params["resource_type"], "change")
        self.tenant_conn.assert_called_once_with("tenant_andina")
        self.assertEqual(self.conn.sql()[-1], "COMMIT")

    def test_change_submitted_notifica_admins(self):
        self.run_records([record("ChangeSubmitted", {"changeId": str(uuid.uuid4()), "key": "CHG-1",
                                                     "risk": "high", "actorId": AGENT})])
        (params,) = self.inserts()
        self.assertEqual(params["ids"], [ADMIN])
        self.assertEqual(params["body"], "Riesgo alto.")

    def test_no_notifica_al_actor(self):
        self.run_records([record("ChangeSubmitted", {"changeId": str(uuid.uuid4()), "key": "CHG-1",
                                                     "risk": "low", "actorId": ADMIN})])
        self.assertEqual(self.inserts(), [])

    def test_incidente_sin_asignado_va_al_equipo_y_admins_si_p1(self):
        self.run_records([record("IncidentCreated", {
            "incidentId": str(uuid.uuid4()), "key": "INC-000001", "title": "Caída", "priority": "P1",
            "teamId": str(uuid.uuid4()), "assigneeId": None, "actorId": REQUESTER})])
        (params,) = self.inserts()
        self.assertEqual(params["ids"], sorted([AGENT, ADMIN]))
        self.assertEqual(params["title"], "Nueva falla INC-000001 (P1)")

    def test_incidente_con_asignado(self):
        assignee = str(uuid.uuid4())
        self.run_records([record("IncidentCreated", {"incidentId": str(uuid.uuid4()), "key": "INC-2",
                                                     "priority": "P4", "assigneeId": assignee})])
        self.assertEqual(self.inserts()[0]["ids"], [assignee])

    def test_incidente_auto_sin_equipo_va_a_admins(self):
        self.run_records([record("IncidentCreated", {"incidentId": str(uuid.uuid4()), "key": "INC-3",
                                                     "priority": "P4", "teamId": None, "assigneeId": None,
                                                     "actorId": None})])
        self.assertEqual(self.inserts()[0]["ids"], [ADMIN])

    def test_incident_updated_solo_si_cambia_asignado(self):
        assignee = str(uuid.uuid4())
        self.run_records([
            record("IncidentUpdated", {"key": "INC-1", "changedFields": ["title"], "assigneeId": assignee},
                   message_id="a"),
            record("IncidentUpdated", {"key": "INC-1", "changedFields": ["assignee_id"], "assigneeId": assignee},
                   message_id="b"),
        ])
        inserts = self.inserts()
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0]["ids"], [assignee])

    def test_request_submitted_pendiente_notifica_solicitante_y_admins(self):
        self.run_records([record("RequestSubmitted", {
            "requestId": str(uuid.uuid4()), "key": "REQ-000001", "catalogItemName": "Acceso VPN",
            "requesterId": REQUESTER, "status": "pending_approval", "actorId": REQUESTER})])
        inserts = self.inserts()
        # El solicitante es el actor: solo reciben los admins.
        self.assertEqual([p["ids"] for p in inserts], [[ADMIN]])
        self.assertEqual(inserts[0]["body"], "Acceso VPN")

    def test_request_fulfilled(self):
        self.run_records([record("RequestFulfilled", {"requestId": str(uuid.uuid4()), "key": "REQ-9",
                                                      "requesterId": REQUESTER, "actorId": AGENT})])
        self.assertEqual(self.inserts()[0]["title"], "Tu pedido REQ-9 fue entregado")

    def test_evento_duplicado_se_ignora(self):
        conn = base_conn()
        conn.rules.insert(0, ("INSERT INTO processed_events", []))
        result = self.run_records([record("ChangeSubmitted", {"key": "x", "actorId": AGENT})], conn)
        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(self.inserts(), [])
        self.assertEqual(conn.sql()[-1], "COMMIT")

    def test_evento_no_manejado_se_descarta_sin_tocar_bd(self):
        self.run_records([record("ChangeImplemented", {"key": "x"})])
        self.tenant_conn.assert_not_called()

    def test_sobre_sns_sin_raw_delivery(self):
        self.run_records([record("RequestRejected", {"key": "REQ-1", "requesterId": REQUESTER}, raw=False)])
        self.assertEqual(len(self.inserts()), 1)

    def test_fallo_devuelve_batch_item_failure_y_rollback(self):
        conn = base_conn()
        conn.rules.insert(0, ("INSERT INTO notifications", RuntimeError("db")))
        result = self.run_records([
            record("ChangeApproved", {"key": "a", "requesterId": REQUESTER}, message_id="bad"),
        ], conn)
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "bad"}]})
        self.assertEqual(conn.sql()[-1], "ROLLBACK")

    def test_mensaje_malformado_falla_solo_ese(self):
        result = self.run_records([
            {"messageId": "roto", "body": "{no json"},
            record("RequestFulfilled", {"key": "REQ-1", "requesterId": REQUESTER}, message_id="ok"),
        ])
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "roto"}]})
        self.assertEqual(len(self.inserts()), 1)

    def test_tenant_invalido_falla(self):
        with patch.object(consumers, "tenant_conn", side_effect=PermissionError("schema")):
            result = consumers.on_notify_event({"Records": [
                record("RequestFulfilled", {"key": "x"}, tenant="X; DROP")]}, None)
        self.assertEqual(len(result["batchItemFailures"]), 1)


if __name__ == "__main__":
    unittest.main()
