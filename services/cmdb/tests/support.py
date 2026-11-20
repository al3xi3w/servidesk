"""Preparación común de las pruebas de ms-cmdb.

- Usa el common.http real del layer (infra/layers/common/python).
- Simula common.db y common.events (sin PostgreSQL ni AWS).
- FakeConn responde según fragmentos del SQL y registra cada llamada.
"""

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
LAYER = REPO_ROOT / "infra" / "layers" / "common" / "python"

for path in (str(SERVICE_ROOT), str(LAYER)):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("JWT_SECRET", "test-secret-de-al-menos-32-caracteres!!")

if "common.db" not in sys.modules:
    import common  # noqa: F401  (paquete real del layer)

    db = types.ModuleType("common.db")
    db.tenant_conn = MagicMock(name="tenant_conn")
    db.get_conn = MagicMock(name="get_conn")
    db.ensure_database = MagicMock(name="ensure_database")
    sys.modules["common.db"] = db

if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock(name="publish")
    sys.modules["common.events"] = events


class FakeConn:
    """Conexión pg8000 simulada: la primera regla cuyo fragmento aparece en el SQL gana."""

    def __init__(self, *rules):
        self.rules = list(rules)
        self.calls = []

    def on(self, fragment, result):
        self.rules.append((fragment, result))
        return self

    def run(self, sql, **params):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        for fragment, result in self.rules:
            if fragment in normalized:
                if isinstance(result, Exception):
                    raise result
                return result(params) if callable(result) else result
        return []

    def sql(self):
        return [call[0] for call in self.calls]

    def find(self, fragment):
        return [call for call in self.calls if fragment in call[0]]


def make_event(role="admin", user_id="11111111-1111-4111-8111-111111111111", tenant="andina",
               body=None, query=None, path=None, authorizer=True):
    event = {
        "queryStringParameters": query,
        "pathParameters": path,
        "body": None if body is None else (body if isinstance(body, str) else json.dumps(body)),
    }
    if authorizer:
        event["requestContext"] = {
            "authorizer": {
                "lambda": {
                    "tenant_id": tenant,
                    "schema": f"tenant_{tenant}",
                    "role": role,
                    "user_id": user_id,
                }
            }
        }
    return event


class Ctx:
    aws_request_id = "req-123"


def parse(response):
    body = response.get("body")
    return response["statusCode"], (json.loads(body) if body else None)
