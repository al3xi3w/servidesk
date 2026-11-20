"""Pruebas unitarias de ms-identity (ID-01..ID-07, notificaciones y migración)."""

import datetime
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch

import jwt

from support import Ctx, FakeConn, make_event, parse  # noqa: E402  (prepara sys.path y mocks)

from handlers import identity_common, login, migrate, notifications, users  # noqa: E402
from handlers.identity_common import hash_password, verify_password  # noqa: E402

USER_ID = uuid.UUID("3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90")
ADMIN_ID = "11111111-1111-4111-8111-111111111111"
CREATED = datetime.datetime(2026, 3, 14, 13, 5, 41, 123456)
FAST_HASH = hash_password("Andina#2026", iterations=1000)


def user_row(user_id=USER_ID, email="lucia.paredes@andina.pe", role="agent", active=True):
    return [user_id, email, "Lucía Paredes Soto", role, active, CREATED]


# ------------------------------------------------------------------ Contraseñas


class TestPasswords(unittest.TestCase):
    def test_hash_y_verificacion(self):
        stored = hash_password("Secreta#123", iterations=1000)
        self.assertTrue(stored.startswith("pbkdf2_sha256$1000$"))
        self.assertTrue(verify_password("Secreta#123", stored))
        self.assertFalse(verify_password("otra-clave", stored))

    def test_salt_distinto_en_cada_hash(self):
        self.assertNotEqual(hash_password("x" * 8, iterations=1000), hash_password("x" * 8, iterations=1000))

    def test_hash_malformado_no_valida(self):
        for stored in ("", "texto", "md5$1$a$b", None, "pbkdf2_sha256$no-num$a$b"):
            self.assertFalse(verify_password("Secreta#123", stored))

    def test_iteraciones_por_defecto(self):
        self.assertEqual(identity_common.PBKDF2_ITERATIONS, 310_000)


# ------------------------------------------------------------------ ID-01 login


class TestLogin(unittest.TestCase):
    def setUp(self):
        self.public = FakeConn().on("FROM public.tenants", [["andina", "tenant_andina", "Andina Retail"]])
        self.tenant = FakeConn().on("FROM users WHERE email", [user_row() + [FAST_HASH]])
        p1 = patch.object(login, "get_conn", return_value=self.public)
        p2 = patch.object(login, "tenant_conn", return_value=self.tenant)
        p3 = patch.object(login, "dummy_password_hash", return_value=FAST_HASH)
        self.tenant_conn = p2.start()
        for p in (p1, p3):
            p.start()
        self.addCleanup(patch.stopall)

    def call(self, body):
        return parse(login.login({"body": body if isinstance(body, str) else json.dumps(body)}, Ctx()))

    def valid(self, **over):
        body = {"tenant_code": "andina", "email": "lucia.paredes@andina.pe", "password": "Andina#2026"}
        body.update(over)
        return body

    def test_login_exitoso_devuelve_token_y_usuario(self):
        status, body = self.call(self.valid())
        self.assertEqual(status, 200)
        data = body["data"]
        self.assertEqual(data["token_type"], "Bearer")
        self.assertEqual(data["expires_in"], 3600)
        self.assertEqual(data["user"]["id"], str(USER_ID))
        self.assertEqual(data["user"]["created_at"], "2026-03-14T13:05:41Z")
        self.assertEqual(data["user"]["tenant"], {"id": "andina", "name": "Andina Retail"})
        self.assertNotIn("password_hash", data["user"])

    def test_claims_del_jwt(self):
        _, body = self.call(self.valid())
        claims = jwt.decode(body["data"]["access_token"], os.environ["JWT_SECRET"], algorithms=["HS256"])
        self.assertEqual(claims["sub"], str(USER_ID))
        self.assertEqual(claims["tenant_id"], "andina")
        self.assertEqual(claims["schema"], "tenant_andina")
        self.assertEqual(claims["role"], "agent")
        self.assertEqual(claims["exp"] - claims["iat"], 3600)
        self.assertLessEqual(abs(claims["iat"] - time.time()), 5)

    def test_normaliza_tenant_y_email(self):
        status, _ = self.call(self.valid(tenant_code=" ANDINA ", email="  Lucia.Paredes@Andina.PE "))
        self.assertEqual(status, 200)
        self.assertEqual(self.public.calls[0][1]["code"], "andina")
        self.assertEqual(self.tenant.calls[0][1]["email"], "lucia.paredes@andina.pe")

    def test_usa_schema_de_public_tenants(self):
        self.call(self.valid())
        self.tenant_conn.assert_called_once_with("tenant_andina")

    def test_password_incorrecta_401(self):
        status, body = self.call(self.valid(password="Incorrecta#1"))
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "INVALID_CREDENTIALS")
        self.assertEqual(body["error"]["request_id"], "req-123")

    def test_tenant_inexistente_401_mismo_mensaje(self):
        self.public.rules = [("FROM public.tenants", [])]
        status, body = self.call(self.valid())
        _, wrong_pw = self.call(self.valid(password="Incorrecta#1"))
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["message"], wrong_pw["error"]["message"])
        self.tenant_conn.assert_not_called()

    def test_usuario_inexistente_401(self):
        self.tenant.rules = []
        status, body = self.call(self.valid())
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "INVALID_CREDENTIALS")

    def test_usuario_inactivo_401(self):
        self.tenant.rules = [("FROM users WHERE email", [user_row(active=False) + [FAST_HASH]])]
        status, _ = self.call(self.valid())
        self.assertEqual(status, 401)

    def test_validaciones(self):
        cases = [
            ({"tenant_code": "A!"}, "tenant_code"),
            ({"tenant_code": 5}, "tenant_code"),
            ({"email": "no-es-email"}, "email"),
            ({"email": "a" * 250 + "@x.pe"}, "email"),
            ({"password": "corta"}, "password"),
            ({"password": "x" * 129}, "password"),
            ({"tenant_id": "andina"}, "tenant_id"),
        ]
        for override, field in cases:
            with self.subTest(field=field):
                status, body = self.call(self.valid(**override))
                self.assertEqual(status, 400)
                self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
                self.assertIn(field, [d["field"] for d in body["error"]["details"]])

    def test_body_faltante_o_invalido(self):
        self.assertEqual(parse(login.login({"body": None}, Ctx()))[0], 400)
        self.assertEqual(self.call("{no json")[0], 400)
        self.assertEqual(self.call("[1, 2]")[0], 400)

    def test_error_interno_500_sin_trazas(self):
        self.public.rules = [("FROM public.tenants", RuntimeError("db caída"))]
        with patch("traceback.print_exc"):
            status, body = self.call(self.valid())
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], {"code": "INTERNAL_ERROR", "message": "Error interno", "request_id": "req-123"})


# ------------------------------------------------------------------ ID-02 me


class TestMe(unittest.TestCase):
    def test_devuelve_usuario_con_tenant(self):
        conn = FakeConn().on("FROM users WHERE id", [user_row()]).on("FROM public.tenants", [["Andina Retail"]])
        with patch.object(login, "tenant_conn", return_value=conn):
            status, body = parse(login.me(make_event(role="agent", user_id=str(USER_ID)), Ctx()))
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["email"], "lucia.paredes@andina.pe")
        self.assertEqual(body["data"]["tenant"], {"id": "andina", "name": "Andina Retail"})
        self.assertEqual(conn.calls[0][1]["id"], str(USER_ID))

    def test_usuario_eliminado_404(self):
        with patch.object(login, "tenant_conn", return_value=FakeConn()):
            status, body = parse(login.me(make_event(), Ctx()))
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")


# ------------------------------------------------------------------ ID-03 listUsers


class TestListUsers(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn().on("SELECT COUNT(*)", [[45]]).on("FROM users", [user_row(), user_row(uuid.uuid4())])
        p = patch.object(users, "tenant_conn", return_value=self.conn)
        self.tenant_conn = p.start()
        self.addCleanup(patch.stopall)

    def call(self, as_role="admin", **query):
        return parse(users.listUsers(make_event(role=as_role, query=query or None), Ctx()))

    def test_listado_paginado(self):
        status, body = self.call(page="2", limit="20")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]), 2)
        self.assertEqual(body["meta"], {"page": 2, "limit": 20, "total": 45, "total_pages": 3})
        select = self.conn.find("LIMIT")[0]
        self.assertIn("ORDER BY created_at desc, id", select[0])
        self.assertEqual(select[1]["offset"], 20)

    def test_agente_puede_leer(self):
        self.assertEqual(self.call(as_role="agent")[0], 200)

    def test_cliente_403(self):
        status, body = self.call(as_role="customer")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "FORBIDDEN")
        self.tenant_conn.assert_not_called()

    def test_usa_schema_del_token(self):
        self.call()
        self.tenant_conn.assert_called_once_with("tenant_andina")

    def test_filtros(self):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        status, _ = self.call(as_role="agent", search="pare_des", active="true", ids=",".join(ids),
                              sort_by="full_name", sort_order="asc")
        self.assertEqual(status, 200)
        sql, params = self.conn.find("SELECT COUNT(*)")[0]
        self.assertNotIn("roles", params)
        self.assertIn("active = :active", sql)
        self.assertIn("id = ANY(CAST(:ids AS uuid[]))", sql)
        self.assertIn("ILIKE :search ESCAPE", sql)
        self.assertEqual(params["search"], "%pare\\_des%")
        self.assertEqual(params["ids"], ids)
        self.assertTrue(params["active"])
        self.assertIn("ORDER BY full_name asc", self.conn.find("LIMIT")[0][0])

    def test_filtro_roles_multiples(self):
        self.call(role="agent,admin")
        self.assertEqual(self.conn.find("SELECT COUNT(*)")[0][1]["roles"], ["agent", "admin"])

    def test_validaciones(self):
        cases = [
            ({"limit": "101"}, "limit"),
            ({"limit": "0"}, "limit"),
            ({"page": "x"}, "page"),
            ({"sort_by": "password_hash"}, "sort_by"),
            ({"sort_order": "up"}, "sort_order"),
            ({"role": "root"}, "role"),
            ({"active": "si"}, "active"),
            ({"ids": "no-uuid"}, "ids"),
            ({"ids": ",".join(str(uuid.uuid4()) for _ in range(101))}, "ids"),
            ({"search": "a"}, "search"),
        ]
        for query, field in cases:
            with self.subTest(field=field):
                status, body = self.call(**query)
                self.assertEqual(status, 400)
                self.assertEqual(body["error"]["details"][0]["field"], field)

    def test_pagina_fuera_de_rango_devuelve_total(self):
        self.conn.rules = [("SELECT COUNT(*)", [[3]]), ("FROM users", [])]
        status, body = self.call(page="9")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["meta"]["total"], 3)

    def test_sin_resultados(self):
        self.conn.rules = [("SELECT COUNT(*)", [[0]]), ("FROM users", [])]
        _, body = self.call()
        self.assertEqual(body["meta"]["total_pages"], 0)


# ------------------------------------------------------------------ ID-04 getUser


class TestGetUser(unittest.TestCase):
    def call(self, role="agent", user_id=str(USER_ID), conn=None):
        conn = conn or FakeConn().on("FROM users WHERE id", [user_row()])
        with patch.object(users, "tenant_conn", return_value=conn):
            return parse(users.getUser(make_event(role=role, path={"id": user_id}), Ctx()))

    def test_ok(self):
        status, body = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["id"], str(USER_ID))

    def test_uuid_invalido_400(self):
        self.assertEqual(self.call(user_id="abc")[0], 400)

    def test_inexistente_o_de_otro_tenant_404(self):
        self.assertEqual(self.call(conn=FakeConn())[0], 404)

    def test_cliente_403(self):
        self.assertEqual(self.call(role="customer")[0], 403)


# ------------------------------------------------------------------ ID-05 createUser


class TestCreateUser(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn().on("SELECT 1 FROM users", []).on(
            "INSERT INTO users", [user_row(email="jorge.huaman@andina.pe", role="customer")]
        )
        patch.object(users, "tenant_conn", return_value=self.conn).start()
        patch.object(users, "hash_password", side_effect=lambda p: f"hashed:{p}").start()
        self.publish = patch.object(users, "publish").start()
        self.addCleanup(patch.stopall)

    def call(self, as_role="admin", **over):
        body = {"email": "Jorge.Huaman@andina.pe", "full_name": "Jorge Huamán Ríos", "role": "customer",
                "password": "Temporal#2026"}
        body.update(over)
        return parse(users.createUser(make_event(role=as_role, body=body), Ctx()))

    def test_crea_usuario_201(self):
        status, body = self.call()
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["email"], "jorge.huaman@andina.pe")
        params = self.conn.find("INSERT INTO users")[0][1]
        self.assertEqual(params["email"], "jorge.huaman@andina.pe")
        self.assertEqual(params["password_hash"], "hashed:Temporal#2026")
        self.assertTrue(params["active"])

    def test_publica_user_created(self):
        self.call()
        kwargs = self.publish.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "UserCreated")
        self.assertEqual(kwargs["tenant_id"], "andina")
        self.assertEqual(kwargs["source"], "ms-identity")
        self.assertEqual(kwargs["data"]["actorId"], ADMIN_ID)

    def test_solo_admin(self):
        for role in ("agent", "customer"):
            self.assertEqual(self.call(as_role=role)[0], 403)
        self.publish.assert_not_called()

    def test_email_duplicado_409(self):
        self.conn.rules.insert(0, ("SELECT 1 FROM users", [[1]]))
        status, body = self.call()
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "EMAIL_ALREADY_EXISTS")
        self.assertFalse(self.conn.find("INSERT INTO users"))

    def test_carrera_unique_violation_409(self):
        self.conn.rules = [("SELECT 1 FROM users", []),
                           ("INSERT INTO users", Exception({"C": "23505", "M": "duplicate key"}))]
        self.assertEqual(self.call()[0], 409)

    def test_validaciones(self):
        cases = [
            ({"email": "x"}, "email"),
            ({"full_name": "ab"}, "full_name"),
            ({"role": "root"}, "role"),
            ({"password": "1234"}, "password"),
            ({"active": "si"}, "active"),
            ({"tenant_id": "pacifico"}, "tenant_id"),
        ]
        for over, field in cases:
            with self.subTest(field=field):
                status, body = self.call(**over)
                self.assertEqual(status, 400)
                self.assertIn(field, [d["field"] for d in body["error"]["details"]])


# ------------------------------------------------------------------ ID-06 updateUser


class TestUpdateUser(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn().on("UPDATE users", [user_row(role="admin")])
        patch.object(users, "tenant_conn", return_value=self.conn).start()
        patch.object(users, "hash_password", side_effect=lambda p: f"hashed:{p}").start()
        self.addCleanup(patch.stopall)

    def call(self, body, role="admin", target=str(USER_ID)):
        return parse(users.updateUser(make_event(role=role, body=body, path={"id": target}), Ctx()))

    def test_actualiza_campos(self):
        status, _ = self.call({"role": "admin", "active": False, "full_name": "  Nuevo Nombre ",
                               "password": "Nueva#Clave1"})
        self.assertEqual(status, 200)
        sql, params = self.conn.find("UPDATE users")[0]
        self.assertIn("full_name = :full_name", sql)
        self.assertIn("password_hash = :password_hash", sql)
        self.assertEqual(params["full_name"], "Nuevo Nombre")
        self.assertEqual(params["password_hash"], "hashed:Nueva#Clave1")
        self.assertIs(params["active"], False)

    def test_email_no_editable(self):
        status, body = self.call({"email": "otro@andina.pe"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["details"][0]["field"], "email")

    def test_body_vacio_400(self):
        self.assertEqual(self.call({})[0], 400)

    def test_admin_no_puede_degradarse_ni_desactivarse(self):
        for body in ({"role": "agent"}, {"active": False}):
            with self.subTest(body=body):
                status, resp = self.call(body, target=ADMIN_ID)
                self.assertEqual(status, 409)
                self.assertEqual(resp["error"]["code"], "CONFLICT")
        self.assertFalse(self.conn.find("UPDATE users"))

    def test_admin_puede_editar_su_nombre(self):
        self.assertEqual(self.call({"full_name": "Carla M."}, target=ADMIN_ID)[0], 200)

    def test_inexistente_404(self):
        self.conn.rules = []
        self.assertEqual(self.call({"active": True})[0], 404)

    def test_solo_admin(self):
        self.assertEqual(self.call({"active": True}, role="agent")[0], 403)

    def test_uuid_invalido(self):
        self.assertEqual(self.call({"active": True}, target="nope")[0], 400)


# ------------------------------------------------------------------ ID-07 listTeams


class TestListTeams(unittest.TestCase):
    def call(self, role="agent", **query):
        self.conn = FakeConn().on("SELECT COUNT(*)", [[6]]).on(
            "FROM teams", [[uuid.uuid4(), "Mesa de Ayuda N1", "Primer contacto"]]
        )
        with patch.object(users, "tenant_conn", return_value=self.conn):
            return parse(users.listTeams(make_event(role=role, query=query or None), Ctx()))

    def test_ok_orden_por_nombre_asc(self):
        status, body = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(set(body["data"][0]), {"id", "name", "description"})
        self.assertEqual(body["meta"]["total"], 6)
        self.assertIn("ORDER BY name asc", self.conn.find("LIMIT")[0][0])

    def test_busqueda(self):
        self.call(search="mesa")
        self.assertEqual(self.conn.find("COUNT")[0][1]["search"], "%mesa%")

    def test_cliente_403(self):
        self.assertEqual(self.call(role="customer")[0], 403)

    def test_sort_invalido(self):
        self.assertEqual(self.call(sort_by="created_at")[0], 400)


# ------------------------------------------------------------------ Notificaciones


class TestNotifications(unittest.TestCase):
    def test_lista_con_no_leidas(self):
        notif_id = uuid.uuid4()
        conn = FakeConn().on("SELECT COUNT(*)", [[3]]).on(
            "FROM notifications",
            [[notif_id, USER_ID, "ChangeApproved", "Título", "Cuerpo", False, CREATED, "change", uuid.uuid4()]],
        )
        with patch.object(notifications, "tenant_conn", return_value=conn):
            status, body = parse(notifications.listNotifications(
                make_event(role="customer", user_id=str(USER_ID), query={"limit": "5"}), Ctx()))
        self.assertEqual(status, 200)
        self.assertEqual(body["meta"], {"unread": 3})
        self.assertEqual(body["data"][0]["id"], str(notif_id))
        self.assertFalse(body["data"][0]["read"])
        self.assertEqual(conn.calls[0][1], {"user_id": str(USER_ID), "limit": 5})

    def test_limit_invalido(self):
        status, _ = parse(notifications.listNotifications(make_event(query={"limit": "500"}), Ctx()))
        self.assertEqual(status, 400)

    def test_marcar_todas(self):
        conn = FakeConn()
        with patch.object(notifications, "tenant_conn", return_value=conn):
            response = notifications.markNotificationsRead(make_event(body=None), Ctx())
        self.assertEqual(response["statusCode"], 204)
        self.assertNotIn("ids", conn.calls[0][1])
        self.assertIn("user_id = CAST(:user_id AS uuid)", conn.calls[0][0])

    def test_marcar_algunas(self):
        ids = [str(uuid.uuid4())]
        conn = FakeConn()
        with patch.object(notifications, "tenant_conn", return_value=conn):
            response = notifications.markNotificationsRead(make_event(body={"ids": ids}), Ctx())
        self.assertEqual(response["statusCode"], 204)
        self.assertEqual(conn.calls[0][1]["ids"], ids)

    def test_ids_invalidos(self):
        for body in ({"ids": "x"}, {"ids": ["no-uuid"]}, {"otro": 1}):
            with self.subTest(body=body):
                status, _ = parse(notifications.markNotificationsRead(make_event(body=body), Ctx()))
                self.assertEqual(status, 400)


# ------------------------------------------------------------------ Migración


class TestMigrate(unittest.TestCase):
    def test_crea_public_tenants_y_cuentas_demo(self):
        conn = FakeConn().on("SELECT email FROM users", [])
        with patch.object(migrate, "get_conn", return_value=conn), \
                patch.object(migrate, "ensure_database") as ensure, \
                patch.object(migrate, "hash_password", return_value="h"):
            result = migrate.handle({}, None)

        ensure.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["schemas"]), {"tenant_andina", "tenant_pacifico", "tenant_unitec"})
        self.assertEqual(result["schemas"]["tenant_andina"]["demo_users_created"], 3)

        sql = conn.sql()
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS public.tenants" in s for s in sql))
        self.assertEqual(len(conn.find("INSERT INTO public.tenants")), 3)
        self.assertEqual(len(conn.find("INSERT INTO users")), 9)
        self.assertEqual(len(conn.find("INSERT INTO teams")), 18)
        self.assertIn("SET LOCAL search_path TO tenant_pacifico", sql)
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS notifications" in s for s in sql))
        self.assertEqual(sql.count("COMMIT"), 4)

    def test_idempotente_no_recrea_usuarios(self):
        conn = FakeConn().on("SELECT email FROM users", lambda _: [
            ["carla.mendoza@andina.pe"], ["lucia.paredes@andina.pe"], ["jorge.huaman@andina.pe"],
            ["ricardo.vega@pacifico.pe"], ["ana.quispe@pacifico.pe"], ["marta.salazar@pacifico.pe"],
            ["diego.torres@unitec.edu.pe"], ["sofia.ramos@unitec.edu.pe"], ["pablo.chavez@unitec.edu.pe"],
        ])
        with patch.object(migrate, "get_conn", return_value=conn), patch.object(migrate, "ensure_database"):
            result = migrate.handle({}, None)
        self.assertFalse(conn.find("INSERT INTO users"))
        self.assertEqual(result["schemas"]["tenant_unitec"]["demo_users_created"], 0)

    def test_rollback_si_falla(self):
        conn = FakeConn().on("CREATE SCHEMA", RuntimeError("boom"))
        with patch.object(migrate, "get_conn", return_value=conn), patch.object(migrate, "ensure_database"):
            with self.assertRaises(RuntimeError):
                migrate.handle({}, None)
        self.assertEqual(conn.sql()[-1], "ROLLBACK")

    def test_uuid_deterministas(self):
        from handlers import tenant_data
        a = tenant_data.user_id("andina", "Carla.Mendoza@andina.pe")
        self.assertEqual(a, tenant_data.user_id("andina", "carla.mendoza@andina.pe"))
        self.assertNotEqual(a, tenant_data.user_id("pacifico", "carla.mendoza@andina.pe"))


if __name__ == "__main__":
    unittest.main()
