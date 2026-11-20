"""Lambda Authorizer compartido (HTTP API, respuesta simple).

Valida firma HS256, expiración y claims obligatorios del JWT que emite ms-identity
(docs/API_CONTRACTS.md §3.2 y §3.3) y entrega a cada handler el contexto
tenant_id, schema, role y user_id. El schema nunca sale del cliente.
"""
import os
import re

import jwt

ROLES = ("admin", "agent", "customer")
TENANT_RE = re.compile(r"^[a-z0-9_]{2,30}$")
DENY = {"isAuthorized": False}


def handle(event, context):
    headers = event.get("headers") or {}
    header = headers.get("authorization") or headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return DENY
    token = header[7:].strip()

    try:
        claims = jwt.decode(
            token,
            os.environ["JWT_SECRET"],
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "tenant_id", "schema", "role"]},
        )
    except jwt.PyJWTError:
        return DENY

    tenant_id = claims["tenant_id"]
    if (
        not isinstance(tenant_id, str)
        or not TENANT_RE.match(tenant_id)
        or claims["schema"] != f"tenant_{tenant_id}"
        or claims["role"] not in ROLES
    ):
        return DENY

    return {
        "isAuthorized": True,
        "context": {
            "tenant_id": tenant_id,
            "schema": claims["schema"],
            "role": claims["role"],
            "user_id": str(claims["sub"]),
        },
    }
