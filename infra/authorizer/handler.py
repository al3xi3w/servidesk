"""Lambda Authorizer (HTTP API, respuesta simple). Responsable: José."""
import os

import jwt


def handle(event, context):
    header = (event.get("headers") or {}).get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return {"isAuthorized": False}
    return {
        "isAuthorized": True,
        "context": {
            "tenant_id": claims["tenant_id"],
            "schema": claims["schema"],
            "role": claims["role"],
            "user_id": claims["sub"],
        },
    }
