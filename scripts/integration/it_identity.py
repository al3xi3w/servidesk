"""Prueba de integración de ms-identity contra PostgreSQL 16 real (contenedor Docker).

Usa el common.db REAL del layer (pg8000), solo cambia puerto y SSL. SNS se simula.
Uso: python scripts/integration/it_identity.py
Requiere el contenedor de scripts/integration/README.md (PostgreSQL 16 en el puerto IT_PG_PORT, 55432 por defecto).
"""
import json
import os
import sys
import types
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("IT_PG_PORT", "55432"))
sys.path[:0] = [str(REPO / "services" / "identity"), str(REPO / "infra" / "layers" / "common" / "python")]

os.environ.update({
    "DB_HOST": "localhost", "DB_USER": "servidesk_admin", "DB_PASSWORD": "localpass123",
    "DB_NAME": "db_identity", "JWT_SECRET": "integration-secret-0123456789-abcdef",
})

import pg8000.native  # noqa: E402

_Orig = pg8000.native.Connection


class _Conn(_Orig):
    def __init__(self, *a, **kw):
        kw["port"] = PORT
        kw["ssl_context"] = None
        super().__init__(*a, **kw)


pg8000.native.Connection = _Conn

# Base limpia en cada ejecución
_admin = _Orig(user="servidesk_admin", password="localpass123", host="localhost", port=PORT, database="postgres")
_admin.run("DROP DATABASE IF EXISTS db_identity WITH (FORCE)")
_admin.close()

published = []
events = types.ModuleType("common.events")
events.publish = lambda **kw: published.append(kw)
sys.modules["common.events"] = events

import importlib.util  # noqa: E402

from handlers import consumers, login, migrate, notifications, users  # noqa: E402

spec = importlib.util.spec_from_file_location("authz", REPO / "infra" / "authorizer" / "handler.py")
authz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authz)


class Ctx:
    aws_request_id = "it-req"


FAILS = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  -> {extra}" if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


def res(r):
    return r["statusCode"], (json.loads(r["body"]) if r.get("body") else None)


def do_login(tenant, email, password):
    return res(login.login({"body": json.dumps({"tenant_code": tenant, "email": email, "password": password})}, Ctx()))


def ev(token, body=None, query=None, path=None):
    a = authz.handle({"headers": {"authorization": f"Bearer {token}"}}, None)
    assert a["isAuthorized"], a
    return {"requestContext": {"authorizer": {"lambda": a["context"]}},
            "body": None if body is None else json.dumps(body), "queryStringParameters": query,
            "pathParameters": path}


print("== migrate (x2, idempotente)")
r1 = migrate.handle({}, None)
r2 = migrate.handle({}, None)
check("migrate 1 crea 3 demo por tenant", all(v["demo_users_created"] == 3 for v in r1["schemas"].values()), r1)
check("migrate 2 no crea nada", all(v["demo_users_created"] == 0 for v in r2["schemas"].values()), r2)

print("== login")
s, b = do_login("andina", "lucia.paredes@andina.pe", "Andina#2026")
check("login agente andina 200", s == 200, b)
agent_tok = b["data"]["access_token"]
check("user.tenant", b["data"]["user"]["tenant"] == {"id": "andina", "name": "Andina Retail"})
check("created_at formato Z", b["data"]["user"]["created_at"].endswith("Z") and "." not in b["data"]["user"]["created_at"])
s, b = do_login("andina", "carla.mendoza@andina.pe", "Andina#2026"); admin_tok = b["data"]["access_token"]
admin_id = b["data"]["user"]["id"]
s, b = do_login("andina", "jorge.huaman@andina.pe", "Andina#2026"); cust_tok = b["data"]["access_token"]
cust_id = b["data"]["user"]["id"]
s, b = do_login("pacifico", "ricardo.vega@pacifico.pe", "Pacifico#2026"); pac_tok = b["data"]["access_token"]
check("login admin pacifico 200", s == 200, b)
check("password incorrecta 401", do_login("andina", "lucia.paredes@andina.pe", "Mala#12345")[0] == 401)
check("tenant inexistente 401", do_login("zzz", "lucia.paredes@andina.pe", "Andina#2026")[0] == 401)
check("usuario de otro tenant 401", do_login("pacifico", "lucia.paredes@andina.pe", "Andina#2026")[0] == 401)

print("== me / users / teams")
s, b = res(login.me(ev(agent_tok), Ctx()))
check("me 200", s == 200 and b["data"]["email"] == "lucia.paredes@andina.pe", b)
s, b = res(users.listUsers(ev(agent_tok, query={"search": "paredes", "role": "agent,admin", "active": "true"}), Ctx()))
check("listUsers filtros", s == 200 and b["meta"]["total"] == 1, b)
s, b = res(users.listUsers(ev(admin_tok, query={"sort_by": "full_name", "sort_order": "asc", "limit": "2"}), Ctx()))
check("listUsers paginado", s == 200 and b["meta"] == {"page": 1, "limit": 2, "total": 3, "total_pages": 2}, b)
s, b = res(users.listUsers(ev(admin_tok, query={"ids": f"{admin_id},{cust_id}"}), Ctx()))
check("listUsers ids", s == 200 and {u["id"] for u in b["data"]} == {admin_id, cust_id}, b)
s, b = res(users.listUsers(ev(admin_tok, query={"search": "100%_"}), Ctx()))
check("search con % y _ escapados", s == 200 and b["meta"]["total"] == 0, b)
s, b = res(users.listUsers(ev(pac_tok), Ctx()))
check("aislamiento: pacifico solo ve los suyos",
      s == 200 and all(u["email"].endswith("@pacifico.pe") for u in b["data"]), b)
s, _ = res(users.getUser(ev(pac_tok, path={"id": admin_id}), Ctx()))
check("getUser de otro tenant 404", s == 404)
s, b = res(users.listTeams(ev(agent_tok, query={"search": "soporte"}), Ctx()))
check("listTeams", s == 200 and b["data"][0]["name"] == "Soporte N2", b)

print("== create / update")
email = f"nuevo.{uuid.uuid4().hex[:6]}@andina.pe"
s, b = res(users.createUser(ev(admin_tok, body={"email": email.upper(), "full_name": "Nuevo Usuario",
                                                  "role": "customer", "password": "Temporal#2026"}), Ctx()))
check("createUser 201", s == 201 and b["data"]["email"] == email, b)
new_id = b["data"]["id"]
check("publica UserCreated", published and published[-1]["event_type"] == "UserCreated")
s, b = res(users.createUser(ev(admin_tok, body={"email": email, "full_name": "Otro", "role": "agent",
                                                  "password": "Temporal#2026"}), Ctx()))
check("email duplicado 409", s == 409 and b["error"]["code"] == "EMAIL_ALREADY_EXISTS", b)
check("login usuario nuevo", do_login("andina", email, "Temporal#2026")[0] == 200)
s, b = res(users.updateUser(ev(admin_tok, body={"role": "agent", "password": "OtraClave#1"}, path={"id": new_id}), Ctx()))
check("updateUser 200", s == 200 and b["data"]["role"] == "agent", b)
check("login con nueva clave", do_login("andina", email, "OtraClave#1")[0] == 200)
s, _ = res(users.updateUser(ev(admin_tok, body={"active": False}, path={"id": new_id}), Ctx()))
check("login usuario desactivado 401", do_login("andina", email, "OtraClave#1")[0] == 401)
s, _ = res(users.updateUser(ev(admin_tok, body={"role": "agent"}, path={"id": admin_id}), Ctx()))
check("admin no se degrada 409", s == 409)

print("== consumidor identity-notify-q + bandeja")
eid = str(uuid.uuid4())
msg = {"eventId": eid, "eventType": "RequestSubmitted", "tenantId": "andina", "source": "ms-requests",
       "data": {"requestId": str(uuid.uuid4()), "key": "REQ-000001", "catalogItemName": "Acceso VPN",
                "requesterId": cust_id, "status": "pending_approval", "actorId": cust_id}}
rec = {"messageId": "m1", "body": json.dumps(msg)}
out = consumers.on_notify_event({"Records": [rec, rec]}, None)
check("consumidor sin fallas", out == {"batchItemFailures": []}, out)
s, b = res(notifications.listNotifications(ev(admin_tok), Ctx()))
check("admin recibe 1 notificación (duplicado ignorado)", s == 200 and b["meta"]["unread"] == 1 and len(b["data"]) == 1, b)
check("notificación con resource_type", b["data"][0]["resource_type"] == "request" and b["data"][0]["title"].startswith("El pedido"), b)
s, b = res(notifications.listNotifications(ev(cust_tok), Ctx()))
check("solicitante (actor) no recibe", b["meta"]["unread"] == 0, b)
r = notifications.markNotificationsRead(ev(admin_tok, body={}), Ctx())
s, b = res(notifications.listNotifications(ev(admin_tok), Ctx()))
check("marcar leídas", r["statusCode"] == 204 and b["meta"]["unread"] == 0 and b["data"][0]["read"] is True, b)
msg2 = dict(msg, eventId=str(uuid.uuid4()), eventType="ChangeApproved",
            data={"changeId": str(uuid.uuid4()), "key": "CHG-1", "requesterId": str(uuid.uuid4()), "actorId": admin_id})
out = consumers.on_notify_event({"Records": [{"messageId": "m2", "body": json.dumps(msg2)}]}, None)
check("destinatario inexistente no rompe (FK)", out == {"batchItemFailures": []}, out)

print()
print("RESULTADO:", "TODO OK" if not FAILS else f"{len(FAILS)} FALLAS: {FAILS}")
sys.exit(1 if FAILS else 0)
