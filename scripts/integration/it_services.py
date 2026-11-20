"""Integración contra PostgreSQL 16 real (Docker, puerto 55432) de incidents, problems, changes y requests.

Uso: python scripts/integration/it_services.py <servicio>
Requiere el contenedor de scripts/integration/README.md (PostgreSQL 16 en el puerto IT_PG_PORT, 55432 por defecto).
Usa el common.db real; SNS simulado (captura los eventos publicados).
"""
import json
import os
import sys
import types
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("IT_PG_PORT", "55432"))
SERVICE = sys.argv[1]
sys.path[:0] = [str(REPO / "services" / SERVICE), str(REPO / "infra" / "layers" / "common" / "python")]
os.environ.update({"DB_HOST": "localhost", "DB_USER": "servidesk_admin", "DB_PASSWORD": "localpass123",
                   "DB_NAME": f"db_{SERVICE}"})

import pg8000.native  # noqa: E402

_Orig = pg8000.native.Connection


class _Conn(_Orig):
    def __init__(self, *a, **kw):
        kw["port"] = PORT
        kw["ssl_context"] = None
        super().__init__(*a, **kw)


pg8000.native.Connection = _Conn

PUBLISHED = []
events = types.ModuleType("common.events")
events.publish = lambda **kw: PUBLISHED.append(kw)
sys.modules["common.events"] = events

from common.db import get_conn, tenant_conn  # noqa: E402

FAILS = []
ADMIN = str(uuid.uuid4())
AGENT = str(uuid.uuid4())
CUSTOMER = str(uuid.uuid4())


class Ctx:
    aws_request_id = "it"


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond:
        FAILS.append(name)


def ev(role="agent", user=AGENT, tenant="andina", body=None, query=None, path=None):
    return {"requestContext": {"authorizer": {"lambda": {"tenant_id": tenant, "schema": f"tenant_{tenant}",
                                                         "role": role, "user_id": user}}},
            "body": None if body is None else json.dumps(body), "queryStringParameters": query,
            "pathParameters": path}


def res(r):
    return r["statusCode"], (json.loads(r["body"]) if r.get("body") else None)


def sqs(event_type, data, tenant="andina", event_id=None):
    msg = {"eventId": event_id or str(uuid.uuid4()), "eventType": event_type, "tenantId": tenant,
           "occurredAt": "2026-11-20T10:00:00Z", "source": "it", "data": data}
    return {"messageId": str(uuid.uuid4()), "body": json.dumps(msg)}


def run_migrate():
    from handlers import migrate
    migrate.handle({}, None)
    migrate.handle({}, None)
    check("migrate x2 sin error", True)


def scalar(sql, tenant="andina", **params):
    return tenant_conn(f"tenant_{tenant}").run(sql, **params)[0][0]


# ======================================================================= incidents
def t_incidents():
    run_migrate()
    from handlers import consumers, incidents, problem_events
    check("sla_policies = 4 (idempotente)", scalar("SELECT COUNT(*) FROM sla_policies") == 4)

    ci = str(uuid.uuid4())
    s, b = res(incidents.createIncident(ev(role="customer", user=CUSTOMER, body={
        "title": "No carga el sistema de ventas", "description": "Error 502", "impact": "high",
        "urgency": "high", "ci_id": ci}), Ctx()))
    check("createIncident 201 (con SLA real)", s == 201, b)
    inc = b["data"]
    check("prioridad P1 y sla_due_at", inc.get("priority") == "P1" and inc.get("sla_due_at"), inc)
    check("publica IncidentCreated", PUBLISHED and PUBLISHED[-1]["event_type"] == "IncidentCreated")

    s, b = res(incidents.listIncidents(ev(query={"priority": "P1,P2", "limit": "10"}), Ctx()))
    check("listIncidents 200", s == 200 and b["meta"]["total"] >= 1, b)
    s, b = res(incidents.changeIncidentStatus(ev(body={"status": "in_progress"}, path={"id": inc["id"]}), Ctx()))
    check("changeIncidentStatus 200", s == 200, b)
    s, b = res(incidents.addIncidentComment(ev(body={"body": "Revisando", "internal": True}, path={"id": inc["id"]}), Ctx()))
    check("addIncidentComment 201", s == 201, b)

    out = consumers.on_ci_status_changed({"Records": [sqs("CIStatusChanged", {
        "ciId": ci, "name": "srv-ventas", "previousStatus": "operational", "status": "down"})]}, None)
    check("incidents-ci-q crea incidente P2 auto", out == {"batchItemFailures": []}
          and scalar("SELECT COUNT(*) FROM incidents WHERE channel = 'auto'") == 1, out)

    problem_id = str(uuid.uuid4())
    ids = [str(r[0]) for r in tenant_conn("tenant_andina").run("SELECT id FROM incidents")]
    rec = sqs("ProblemIncidentsLinked", {"problemId": problem_id, "incidentIds": ids, "actorId": None})
    out = problem_events.on_problem_incidents_linked({"Records": [rec, rec]}, None)
    check("incidents-problem-q fija problem_id", out == {"batchItemFailures": []}
          and scalar("SELECT COUNT(*) FROM incidents WHERE problem_id = CAST(:p AS uuid)", p=problem_id) == len(ids), out)

    out = problem_events.on_known_error_published({"Records": [sqs("KnownErrorPublished", {
        "problemId": problem_id, "knownErrorId": str(uuid.uuid4()), "symptom": "502",
        "workaround": "Reiniciar el pool", "actorId": AGENT})]}, None)
    n = scalar("SELECT COUNT(*) FROM incident_comments WHERE body LIKE 'Solución temporal%'")
    check("incidents-kedb-q comenta workaround (sin incidentIds)", out == {"batchItemFailures": []} and n == len(ids), (out, n))
    s, b = res(incidents.listIncidentComments(ev(path={"id": inc["id"]}), Ctx()))
    check("comentario visible por API", s == 200 and any("Reiniciar" in c["body"] for c in b["data"]), b)
    check("aislamiento: pacifico no ve incidentes de andina",
          res(incidents.getIncident(ev(tenant="pacifico", path={"id": inc["id"]}), Ctx()))[0] == 404)


# ======================================================================= problems
def t_problems():
    run_migrate()
    from handlers import consumers, problems
    ci = str(uuid.uuid4())
    incs = [str(uuid.uuid4()) for _ in range(4)]
    for i, inc in enumerate(incs[:2]):
        out = consumers.on_incident_created({"Records": [sqs("IncidentCreated", {
            "incidentId": inc, "key": f"INC-{i}", "title": "Caída de caja", "priority": "P3", "ciId": ci})]}, None)
    check("2 incidentes: no crea problema", scalar("SELECT COUNT(*) FROM problems") == 0)
    PUBLISHED.clear()
    rec = sqs("IncidentCreated", {"incidentId": incs[2], "key": "INC-2", "title": "Caja no imprime",
                                  "priority": "P2", "ciId": ci})
    out = consumers.on_incident_created({"Records": [rec, rec]}, None)
    check("3er incidente crea problema", out == {"batchItemFailures": []} and scalar("SELECT COUNT(*) FROM problems") == 1, out)
    key, prio, status = tenant_conn("tenant_andina").run("SELECT key, priority, status FROM problems")[0]
    check("PRB-000001 P2 new", (key, prio, status) == ("PRB-000001", "P2", "new"), (key, prio, status))
    check("vincula 3 incidentes", scalar("SELECT COUNT(*) FROM problem_incidents") == 3)
    check("publica ProblemCreated + ProblemIncidentsLinked (una vez)",
          [p["event_type"] for p in PUBLISHED] == ["ProblemCreated", "ProblemIncidentsLinked"], PUBLISHED)
    consumers.on_incident_created({"Records": [sqs("IncidentCreated", {
        "incidentId": incs[3], "key": "INC-3", "priority": "P4", "ciId": ci})]}, None)
    check("4º incidente se vincula al problema abierto", scalar("SELECT COUNT(*) FROM problems") == 1
          and scalar("SELECT COUNT(*) FROM problem_incidents") == 4)

    pid = str(tenant_conn("tenant_andina").run("SELECT id FROM problems")[0][0])
    s, b = res(problems.getProblem(ev(path={"id": pid}), Ctx()))
    check("getProblem del problema automático", s == 200 and len(b["data"].get("incident_ids", [])) == 4, b)
    s, b = res(problems.listProblems(ev(query={"status": "new"}), Ctx()))
    check("listProblems 200", s == 200, b)

    out = consumers.on_change_implemented({"Records": [sqs("ChangeImplemented", {
        "changeId": str(uuid.uuid4()), "key": "CHG-000007", "problemId": pid, "cis": []})]}, None)
    st, rc = tenant_conn("tenant_andina").run("SELECT status, root_cause FROM problems")[0]
    check("problems-changes-q cierra el problema", out == {"batchItemFailures": []} and st == "closed"
          and "CHG-000007" in rc, (out, st, rc))
    check("aislamiento: pacifico sin problemas", scalar("SELECT COUNT(*) FROM problems", tenant="pacifico") == 0)


# ======================================================================= changes
def t_changes():
    run_migrate()
    from handlers import changes
    ci = str(uuid.uuid4())
    problem = str(uuid.uuid4())
    s, b = res(changes.createChange(ev(body={
        "title": "Actualizar servidor de ventas", "description": "Parche", "type": "normal", "risk": "medium",
        "rollback_plan": "Restaurar snapshot", "planned_start": "2026-11-25T03:00:00Z",
        "planned_end": "2026-11-25T05:00:00Z", "problem_id": problem,
        "cis": [{"ci_id": ci, "new_version": "2.5.0"}]}), Ctx()))
    check("createChange 201", s == 201, b)
    cid = b["data"]["id"]
    check("clave CHG-000001", b["data"].get("key") == "CHG-000001", b)
    s, b = res(changes.updateChange(ev(body={"risk": "high"}, path={"id": cid}), Ctx()))
    check("updateChange 200", s == 200 and b["data"]["risk"] == "high", b)
    s, b = res(changes.changeChangeStatus(ev(body={"status": "submitted"}, path={"id": cid}), Ctx()))
    check("submit 200", s == 200 and b["data"]["status"] == "submitted", b)
    s, b = res(changes.approveChange(ev(role="admin", user=ADMIN, body={"comment": "OK CAB"}, path={"id": cid}), Ctx()))
    check("approve 200", s == 200 and b["data"]["status"] == "approved", b)
    check("ChangeApproved con requesterId", PUBLISHED[-1]["data"].get("requesterId") == AGENT, PUBLISHED[-1])
    s, b = res(changes.changeChangeStatus(ev(body={"status": "scheduled"}, path={"id": cid}), Ctx()))
    s, b = res(changes.changeChangeStatus(ev(body={"status": "implemented"}, path={"id": cid}), Ctx()))
    check("implemented 200", s == 200 and b["data"]["status"] == "implemented", b)
    last = PUBLISHED[-1]
    check("ChangeImplemented con problemId y cis", last["event_type"] == "ChangeImplemented"
          and last["data"]["problemId"] == problem
          and last["data"]["cis"] == [{"ciId": ci, "newVersion": "2.5.0"}], last)
    s, b = res(changes.listChanges(ev(query={"planned_from": "2026-11-24T00:00:00Z",
                                              "planned_to": "2026-11-26T00:00:00Z", "status": "implemented"}), Ctx()))
    check("listChanges calendario", s == 200 and b["meta"]["total"] == 1, b)
    s, b = res(changes.getChange(ev(path={"id": cid}), Ctx()))
    check("getChange con approvals", s == 200 and len(b["data"]["approvals"]) == 1, b)
    check("aislamiento", res(changes.getChange(ev(tenant="pacifico", path={"id": cid}), Ctx()))[0] == 404)


# ======================================================================= requests
def t_requests():
    run_migrate()
    from handlers import requests as rq
    conn = tenant_conn("tenant_andina")
    cat = conn.run("INSERT INTO catalog_categories (name) VALUES ('Accesos') RETURNING id")[0][0]
    item = str(conn.run(
        "INSERT INTO catalog_items (category_id, name, description, form_schema, needs_approval, sla_hours) "
        "VALUES (:c, 'Acceso VPN', 'Acceso remoto', CAST(:f AS jsonb), TRUE, 24) RETURNING id",
        c=cat, f=json.dumps({"fields": [{"name": "motivo", "label": "Motivo", "type": "text", "required": True}]}))[0][0])
    s, b = res(rq.listCatalog(ev(role="customer", user=CUSTOMER), Ctx()))
    check("listCatalog 200", s == 200 and b["data"][0]["category_name"] == "Accesos", b)
    s, b = res(rq.createRequest(ev(role="customer", user=CUSTOMER, body={
        "catalog_item_id": item, "form_data": {"motivo": "Trabajo remoto"}}), Ctx()))
    check("createRequest 201 pending_approval", s == 201 and b["data"]["status"] == "pending_approval", b)
    rid = b["data"]["id"]
    check("RequestSubmitted con catalogItemName", PUBLISHED[-1]["data"].get("catalogItemName") == "Acceso VPN", PUBLISHED[-1])
    s, b = res(rq.updateRequest(ev(role="customer", user=CUSTOMER, body={"form_data": {"motivo": "Viaje"}},
                                   path={"id": rid}), Ctx()))
    check("updateRequest cliente 200", s == 200, b)
    s, b = res(rq.changeRequestStatus(ev(role="admin", user=ADMIN, body={"status": "approved"}, path={"id": rid}), Ctx()))
    check("approve 200", s == 200 and b["data"]["status"] == "approved", b)
    check("RequestApproved con requesterId", PUBLISHED[-1]["data"].get("requesterId") == CUSTOMER, PUBLISHED[-1])
    res(rq.changeRequestStatus(ev(body={"status": "in_fulfillment"}, path={"id": rid}), Ctx()))
    s, b = res(rq.changeRequestStatus(ev(body={"status": "fulfilled"}, path={"id": rid}), Ctx()))
    check("fulfilled con fulfilled_at", s == 200 and b["data"]["fulfilled_at"], b)
    s, b = res(rq.listRequests(ev(role="customer", user=CUSTOMER), Ctx()))
    check("listRequests cliente ve la suya", s == 200 and b["meta"]["total"] == 1, b)
    s, b = res(rq.listRequests(ev(role="customer", user=str(uuid.uuid4())), Ctx()))
    check("otro cliente no la ve", s == 200 and b["meta"]["total"] == 0, b)
    check("aislamiento", res(rq.getRequest(ev(tenant="pacifico", path={"id": rid}), Ctx()))[0] == 404)


# ======================================================================= cmdb
def t_cmdb():
    run_migrate()
    from handlers import cis, consumers
    s, b = res(cis.listCiTypes(ev(), Ctx()))
    check("CM-08 6 tipos (idempotente)", s == 200 and len(b["data"]) == 6 and b["data"][0] == {"id": 1, "name": "Servidor"}, b)
    team = str(uuid.uuid4())
    s, b = res(cis.createCi(ev(body={"type_id": 1, "name": "srv-ventas-01", "environment": "prod", "version": "1.0",
                                      "owner_team_id": team, "attributes": {"ip": "10.0.0.1", "tags": ["a"]}}), Ctx()))
    check("CM-02 201", s == 201 and b["data"]["status"] == "operational" and b["data"]["attributes"]["tags"] == ["a"], b)
    a = b["data"]["id"]
    s, b = res(cis.createCi(ev(body={"type_id": 2, "name": "db-ventas", "environment": "qa"}), Ctx()))
    bid = b["data"]["id"]
    check("CM-02 sin opcionales", s == 201 and b["data"]["attributes"] == {} and b["data"]["version"] is None, b)
    check("CM-02 tipo inexistente 400", res(cis.createCi(ev(body={"type_id": 99, "name": "x1", "environment": "dev"}), Ctx()))[0] == 400)
    s, b = res(cis.listCis(ev(query={"environment": "prod,qa", "search": "ventas", "sort_by": "name", "sort_order": "asc"}), Ctx()))
    check("CM-01 filtros", s == 200 and [c["name"] for c in b["data"]] == ["db-ventas", "srv-ventas-01"], b)
    s, b = res(cis.listCis(ev(query={"owner_team_id": team, "type_id": "1"}), Ctx()))
    check("CM-01 equipo y tipo", s == 200 and b["meta"]["total"] == 1, b)
    s, b = res(cis.updateCi(ev(body={"name": "srv-ventas-02", "attributes": {"ip": "10.0.0.2"}, "version": "1.0"},
                                path={"id": a}), Ctx()))
    check("CM-04 200", s == 200 and b["data"]["name"] == "srv-ventas-02" and b["data"]["updated_at"] >= b["data"]["created_at"], b)
    fields = sorted(r[0] for r in tenant_conn("tenant_andina").run(
        "SELECT field FROM ci_history WHERE ci_id = CAST(:a AS uuid)", a=a))
    check("ci_history: created, name, attributes", fields == ["attributes", "created", "name"], fields)
    tenant_conn("tenant_andina").run("INSERT INTO ci_relations (source_ci_id, target_ci_id, relation) "
                                     "VALUES (CAST(:a AS uuid), CAST(:b AS uuid), 'depends_on')", a=a, b=bid)
    s, b = res(cis.listCiRelations(ev(path={"id": bid}), Ctx()))
    check("CM-07 relación entrante", s == 200 and b["data"][0]["direction"] == "incoming"
          and b["data"][0]["ci"]["name"] == "srv-ventas-02" and b["data"][0]["ci"]["type_name"] == "Servidor", b)
    PUBLISHED.clear()
    s, b = res(cis.changeCiStatus(ev(body={"status": "down"}, path={"id": a}), Ctx()))
    check("CM-05 down + CIStatusChanged", s == 200 and PUBLISHED[-1]["data"]["previousStatus"] == "operational", PUBLISHED)
    check("CM-05 mismo estado 409", res(cis.changeCiStatus(ev(body={"status": "down"}, path={"id": a}), Ctx()))[0] == 409)
    check("CM-06 agente 403", cis.deleteCi(ev(path={"id": a}), Ctx())["statusCode"] == 403)
    check("CM-06 admin 204", cis.deleteCi(ev(role="admin", user=ADMIN, path={"id": a}), Ctx())["statusCode"] == 204)
    check("CM-06 repetido 204 sin evento", cis.deleteCi(ev(role="admin", user=ADMIN, path={"id": a}), Ctx())["statusCode"] == 204
          and sum(p["event_type"] == "CIStatusChanged" for p in PUBLISHED) == 2, PUBLISHED)
    check("CM-04 retirado 409", res(cis.updateCi(ev(body={"name": "otro"}, path={"id": a}), Ctx()))[0] == 409)
    rec = sqs("ChangeImplemented", {"changeId": str(uuid.uuid4()), "cis": [{"ciId": bid, "newVersion": "2.0"},
                                                                          {"ciId": a, "newVersion": "9.9"}]})
    out = consumers.on_change_implemented({"Records": [rec, rec]}, None)
    versions = dict((str(r[0]), r[1]) for r in tenant_conn("tenant_andina").run("SELECT id, version FROM configuration_items"))
    check("cmdb-changes-q: versión aplicada, retirado intacto, duplicado ignorado",
          out == {"batchItemFailures": []} and versions[bid] == "2.0" and versions[a] == "1.0", (out, versions))
    check("aislamiento", res(cis.getCi(ev(tenant="pacifico", path={"id": bid}), Ctx()))[0] == 404)


def reset_db():
    admin = _Orig(user="servidesk_admin", password="localpass123", host="localhost", port=PORT, database="postgres")
    admin.run(f"DROP DATABASE IF EXISTS db_{SERVICE} WITH (FORCE)")
    admin.close()


reset_db()
print(f"== {SERVICE}")
try:
    {"cmdb": t_cmdb, "incidents": t_incidents, "problems": t_problems, "changes": t_changes, "requests": t_requests}[SERVICE]()
except Exception as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAILS.append(f"excepción: {exc}")
print("RESULTADO:", "TODO OK" if not FAILS else f"{len(FAILS)} FALLAS: {FAILS}")
sys.exit(1 if FAILS else 0)
