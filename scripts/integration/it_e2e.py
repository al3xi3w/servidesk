"""Simulación end-to-end de la arquitectura de eventos de ServiDesk contra PostgreSQL 16 real.

Carga los 6 microservicios en un proceso (cada uno con su propia conexión y su db_<servicio>),
reemplaza SNS por un bus en memoria y entrega cada evento a los consumidores según las
suscripciones SNS -> SQS y FilterPolicy declaradas en los serverless.yml reales.

Historia de la demo (tenant andina):
  1. CMDB: un CI pasa a "down"            -> incidents crea un incidente automático P2
  2. Dos fallas más del mismo CI          -> problems crea un problema automático y lo vincula
  3. Se publica el error conocido         -> incidents comenta el workaround en los incidentes
  4. Cambio aprobado por CAB e implementado -> cmdb aplica la versión nueva, problems cierra el problema
  5. identity notifica en cada paso; pacifico no ve nada de andina.

Uso: python scripts/integration/it_e2e.py   (contenedor de scripts/integration/README.md)
"""
import datetime
import importlib
import importlib.util
import json
import os
import sys
import types
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("IT_PG_PORT", "55432"))
LAYER = REPO / "infra" / "layers" / "common" / "python"
sys.path.insert(0, str(LAYER))
sys.path.insert(0, str(REPO / "scripts"))
os.environ.update({"DB_HOST": "localhost", "DB_USER": "servidesk_admin", "DB_PASSWORD": "localpass123",
                   "JWT_SECRET": "e2e-secret-0123456789-abcdefghijklmnop"})

import pg8000.native  # noqa: E402
import yaml  # noqa: E402

from check_serverless import Loader, refs  # noqa: E402

_Orig = pg8000.native.Connection


class _Conn(_Orig):
    def __init__(self, *a, **kw):
        kw["port"] = PORT
        kw["ssl_context"] = None
        super().__init__(*a, **kw)


pg8000.native.Connection = _Conn

# ------------------------------------------------------------------ bus SNS en memoria
BUS = []
LOG = []


def _publish(event_type, tenant_id, data, source):
    BUS.append({"eventId": str(uuid.uuid4()), "eventType": event_type, "tenantId": tenant_id,
                "occurredAt": datetime.datetime.utcnow().isoformat() + "Z", "source": source, "data": data})


events_mod = types.ModuleType("common.events")
events_mod.publish = _publish
sys.modules["common.events"] = events_mod
import common  # noqa: E402,F401

SERVICES = ["identity", "cmdb", "incidents", "problems", "changes", "requests"]
MODULES = {}


def load_service(name, module_names):
    """Importa handlers.* del servicio con su propio common.db (conexión y DB_NAME propios)."""
    for key in [k for k in sys.modules if k == "handlers" or k.startswith("handlers.") or k == "common.db"]:
        del sys.modules[key]
    sys.path.insert(0, str(REPO / "services" / name))
    try:
        mods = {m: importlib.import_module(f"handlers.{m}") for m in module_names}
    finally:
        sys.path.pop(0)
    MODULES[name] = mods
    return mods


def call(service, fn, *args):
    os.environ["DB_NAME"] = f"db_{service}"
    return fn(*args)


load_service("identity", ["login", "users", "notifications", "consumers", "migrate"])
load_service("cmdb", ["cis", "consumers", "migrate"])
load_service("incidents", ["incidents", "consumers", "problem_events", "migrate"])
load_service("problems", ["problems", "consumers", "migrate"])
load_service("changes", ["changes", "migrate"])
load_service("requests", ["requests", "migrate"])

spec = importlib.util.spec_from_file_location("authz", REPO / "infra" / "authorizer" / "handler.py")
authz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authz)

# ------------------------------------------------------------------ suscripciones desde serverless.yml
SUBSCRIPTIONS = []  # (servicio, función, filtro de eventType)
for svc in SERVICES:
    cfg = yaml.load((REPO / "services" / svc / "serverless.yml").read_text(encoding="utf-8"), Loader=Loader)
    resources = cfg.get("resources", {}).get("Resources", {})
    queue_filter = {}
    for res in resources.values():
        if res.get("Type") == "AWS::SNS::Subscription":
            queue = next(iter(refs(res["Properties"]["Endpoint"])))
            queue_filter[queue] = set(res["Properties"]["FilterPolicy"]["eventType"])
    for fn in cfg["functions"].values():
        for ev in fn.get("events") or []:
            if "sqs" in ev:
                queue = next(iter(refs(ev["sqs"]["arn"])))
                module, func = fn["handler"].split("/", 1)[1].rsplit(".", 1)
                SUBSCRIPTIONS.append((svc, getattr(MODULES[svc][module], func), queue_filter[queue], queue))


def deliver():
    """Entrega los eventos del bus como lo harían SNS (FilterPolicy) y SQS (lote de 1)."""
    while BUS:
        env = BUS.pop(0)
        targets = [s for s in SUBSCRIPTIONS if env["eventType"] in s[2]]
        LOG.append(f"{env['source']:12} {env['eventType']:24} -> {', '.join(f'{t[0]}:{t[3]}' for t in targets) or '(sin cola)'}")
        for svc, fn, _, queue in targets:
            record = {"messageId": str(uuid.uuid4()), "body": json.dumps(env)}
            out = call(svc, fn, {"Records": [record]}, None)
            if out.get("batchItemFailures"):
                raise AssertionError(f"{queue} falló con {env['eventType']}")


# ------------------------------------------------------------------ utilidades
FAILS = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond:
        FAILS.append(name)


class Ctx:
    aws_request_id = "e2e"


def res(r):
    return r["statusCode"], (json.loads(r["body"]) if r.get("body") else None)


def login(tenant, email, password):
    s, b = res(call("identity", MODULES["identity"]["login"].login,
                    {"body": json.dumps({"tenant_code": tenant, "email": email, "password": password})}, Ctx()))
    assert s == 200, b
    return b["data"]["access_token"], b["data"]["user"]["id"]


def ev(token, body=None, query=None, path=None):
    a = authz.handle({"headers": {"authorization": f"Bearer {token}"}}, None)
    assert a["isAuthorized"]
    return {"requestContext": {"authorizer": {"lambda": a["context"]}}, "body": None if body is None else json.dumps(body),
            "queryStringParameters": query, "pathParameters": path}


def sql(service, query, tenant="andina", **params):
    """Consulta directa a db_<service> (con la conexión propia de ese servicio)."""
    os.environ["DB_NAME"] = f"db_{service}"
    c = MODULES[service]["migrate"].get_conn()
    c.run(f"SET search_path TO tenant_{tenant}")
    return c.run(query, **params)


# ------------------------------------------------------------------ escenario
admin = _Orig(user="servidesk_admin", password="localpass123", host="localhost", port=PORT, database="postgres")
for svc in SERVICES:
    admin.run(f"DROP DATABASE IF EXISTS db_{svc} WITH (FORCE)")
admin.close()

print("== 0. Migraciones de los 6 servicios")
for svc in SERVICES:
    call(svc, MODULES[svc]["migrate"].handle, {}, None)
check("6 migraciones", True)

agent_tok, agent_id = login("andina", "lucia.paredes@andina.pe", "Andina#2026")
admin_tok, admin_id = login("andina", "carla.mendoza@andina.pe", "Andina#2026")
cust_tok, cust_id = login("andina", "jorge.huaman@andina.pe", "Andina#2026")
pac_tok, _ = login("pacifico", "ana.quispe@pacifico.pe", "Pacifico#2026")

print("== 1. El CI cae -> incidente automático")
cis_mod = MODULES["cmdb"]["cis"]
s, b = res(call("cmdb", cis_mod.createCi, ev(agent_tok, body={
    "type_id": 3, "name": "pos-tienda-07", "environment": "prod", "version": "2.4.1",
    "attributes": {"tienda": "Miraflores"}}), Ctx()))
check("CM-02 crea el CI", s == 201, b)
ci_id = b["data"]["id"]
s, b = res(call("cmdb", cis_mod.changeCiStatus, ev(agent_tok, body={"status": "down"}, path={"id": ci_id}), Ctx()))
check("CM-05 CI -> down", s == 200 and b["data"]["status"] == "down", b)
deliver()
auto = sql("incidents", "SELECT key, priority, channel FROM incidents WHERE ci_id = CAST(:c AS uuid)", c=ci_id)
check("incidente automático P2 canal auto", len(auto) == 1 and auto[0][1:] == ["P2", "auto"], auto)

print("== 2. Dos fallas más del mismo CI -> problema automático")
inc_mod = MODULES["incidents"]["incidents"]
for title in ("La caja de Miraflores no imprime boletas", "POS de Miraflores se reinicia solo"):
    s, b = res(call("incidents", inc_mod.createIncident, ev(cust_tok, body={
        "title": title, "description": "Desde esta mañana", "impact": "medium", "urgency": "high",
        "ci_id": ci_id}), Ctx()))
    check(f"IN-02 '{title[:28]}…'", s == 201, b)
deliver()
probs = sql("problems", "SELECT id, key, status, priority FROM problems WHERE ci_id = CAST(:c AS uuid)", c=ci_id)
check("problema automático creado", len(probs) == 1 and probs[0][2] == "new", probs)
problem_id = str(probs[0][0])
linked = sql("incidents", "SELECT COUNT(*) FROM incidents WHERE problem_id = CAST(:p AS uuid)", p=problem_id)[0][0]
check("los 3 incidentes quedan vinculados en ms-incidents", linked == 3, linked)

print("== 3. Error conocido -> workaround en los incidentes")
prob_mod = MODULES["problems"]["problems"]
s, b = res(call("problems", prob_mod.changeProblemStatus, ev(agent_tok, body={"status": "investigating"},
                                                             path={"id": problem_id}), Ctx()))
check("PR-05 problema -> investigating", s == 200, b)
s, b = res(call("problems", prob_mod.publishKnownError, ev(agent_tok, body={
    "symptom": "El POS se cuelga al imprimir.", "workaround": "Reiniciar el servicio de impresión del POS."},
    path={"id": problem_id}), Ctx()))
check("PR-06 error conocido publicado", s == 201, b)
deliver()
comments = sql("incidents", "SELECT COUNT(*) FROM incident_comments WHERE body LIKE 'Solución temporal%'")[0][0]
check("workaround comentado en los 3 incidentes", comments == 3, comments)

print("== 4. Cambio aprobado e implementado -> CI actualizado y problema cerrado")
ch_mod = MODULES["changes"]["changes"]
s, b = res(call("changes", ch_mod.createChange, ev(agent_tok, body={
    "title": "Actualizar firmware del POS", "type": "normal", "risk": "medium",
    "rollback_plan": "Reinstalar firmware 2.4.1", "planned_start": "2026-11-25T03:00:00Z",
    "planned_end": "2026-11-25T04:00:00Z", "problem_id": problem_id,
    "cis": [{"ci_id": ci_id, "new_version": "3.0.0"}]}), Ctx()))
check("CH-02 cambio creado", s == 201, b)
change_id = b["data"]["id"]
steps = [(agent_tok, ch_mod.changeChangeStatus, {"status": "submitted"}),
         (admin_tok, ch_mod.approveChange, {"comment": "Aprobado en CAB"}),
         (agent_tok, ch_mod.changeChangeStatus, {"status": "scheduled"}),
         (agent_tok, ch_mod.changeChangeStatus, {"status": "implemented"})]
for token, fn, body in steps:
    s, b = res(call("changes", fn, ev(token, body=body, path={"id": change_id}), Ctx()))
    check(f"CH {list(body.values())[0][:15]} -> {b['data']['status'] if s == 200 else s}", s == 200, b)
    deliver()
version = sql("cmdb", "SELECT version FROM configuration_items WHERE id = CAST(:c AS uuid)", c=ci_id)[0][0]
check("cmdb-changes-q aplicó la versión 3.0.0", version == "3.0.0", version)
hist = sql("cmdb", "SELECT source, change_id FROM ci_history WHERE field = 'version'")
check("ci_history registra el cambio", hist and hist[0][0] == "ms-changes" and str(hist[0][1]) == change_id, hist)
st = sql("problems", "SELECT status FROM problems WHERE id = CAST(:p AS uuid)", p=problem_id)[0][0]
check("problems-changes-q cerró el problema", st == "closed", st)

print("== 5. Notificaciones e aislamiento")
notif = MODULES["identity"]["notifications"]
_, b = res(call("identity", notif.listNotifications, ev(admin_tok, query={"limit": "50"}), Ctx()))
titles = [n["title"] for n in b["data"]]
check("admin: falla nueva, actualización por aprobar, workaround", any("Nueva falla" in t for t in titles)
      and any("espera tu aprobación" in t for t in titles) and any("solución temporal" in t for t in titles), titles)
_, b = res(call("identity", notif.listNotifications, ev(agent_tok), Ctx()))
check("agente: su cambio fue aprobado", any("fue aprobada" in n["title"] for n in b["data"]), b["data"])
s, b = res(call("cmdb", cis_mod.listCis, ev(pac_tok), Ctx()))
check("pacifico no ve el CI de andina", s == 200 and b["meta"]["total"] == 0, b)

print("\nEventos que viajaron por el bus (SNS -> SQS):")
for line in LOG:
    print("  " + line)
print("\nRESULTADO:", "TODO OK" if not FAILS else f"{len(FAILS)} FALLAS: {FAILS}")
sys.exit(1 if FAILS else 0)
