"""Pruebas del Lambda Authorizer compartido (infra/authorizer/handler.py)."""

import importlib.util
import os
import time
import unittest

import jwt

from support import REPO_ROOT  # noqa: E402

_spec = importlib.util.spec_from_file_location("authorizer_handler", REPO_ROOT / "infra" / "authorizer" / "handler.py")
authorizer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(authorizer)

SECRET = os.environ["JWT_SECRET"]


def token(**over):
    now = int(time.time())
    claims = {"sub": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90", "tenant_id": "andina", "schema": "tenant_andina",
              "role": "agent", "iat": now, "exp": now + 3600}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def call(header):
    return authorizer.handle({"headers": {"authorization": header} if header is not None else {}}, None)


class TestAuthorizer(unittest.TestCase):
    def test_token_valido(self):
        result = call(f"Bearer {token()}")
        self.assertEqual(result, {"isAuthorized": True, "context": {
            "tenant_id": "andina", "schema": "tenant_andina", "role": "agent",
            "user_id": "3f9a1c52-8d0e-4b7a-9f21-6c4e2a7b1d90"}})

    def test_rechazos(self):
        now = int(time.time())
        cases = {
            "sin header": None,
            "sin bearer": token(),
            "basura": "Bearer abc.def.ghi",
            "vencido": f"Bearer {token(iat=now - 7200, exp=now - 3600)}",
            "otra firma": "Bearer " + jwt.encode({"sub": "x", "tenant_id": "andina", "schema": "tenant_andina",
                                                  "role": "admin", "exp": now + 60}, "otro-secreto-" * 3,
                                                 algorithm="HS256"),
            "schema de otro tenant": f"Bearer {token(schema='tenant_pacifico')}",
            "rol desconocido": f"Bearer {token(role='root')}",
            "tenant inválido": f"Bearer {token(tenant_id='Andina!', schema='tenant_Andina!')}",
            "sin exp": f"Bearer {token(exp=None)}",
            "sin schema": f"Bearer {token(schema=None)}",
            "alg none": "Bearer " + jwt.encode({"sub": "x", "tenant_id": "andina", "schema": "tenant_andina",
                                                "role": "admin", "exp": now + 60}, None, algorithm="none"),
        }
        for name, header in cases.items():
            with self.subTest(name):
                self.assertEqual(call(header), {"isAuthorized": False})

    def test_bearer_sin_importar_mayusculas(self):
        self.assertTrue(call(f"bearer {token()}")["isAuthorized"])


if __name__ == "__main__":
    unittest.main()
