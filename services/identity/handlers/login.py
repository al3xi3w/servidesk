"""ms-identity · ID-01 POST /auth/login y ID-02 GET /auth/me."""

import os
import time

import jwt

from common.db import get_conn, tenant_conn
from common.http import ok, tenant_ctx
from handlers.identity_common import (
    TENANT_CODE_RE,
    TOKEN_TTL_SECONDS,
    USER_COLUMNS,
    api_error,
    dummy_password_hash,
    handle_errors,
    not_found,
    parse_body,
    unknown_fields,
    user_from_row,
    validate_email,
    validate_password,
    validation_error,
    verify_password,
)


def _invalid_credentials(context):
    # Mismo mensaje para tenant, usuario, usuario inactivo o contraseña incorrecta.
    return api_error(
        "INVALID_CREDENTIALS",
        "Código de organización, email o contraseña incorrectos",
        401,
        context=context,
    )


def _find_tenant(conn, code):
    rows = conn.run(
        "SELECT code, schema_name, name FROM public.tenants WHERE code = :code AND active",
        code=code,
    )
    return rows[0] if rows else None


def issue_token(user, tenant_code, schema, now=None):
    now = int(now if now is not None else time.time())
    claims = {
        "sub": user["id"],
        "tenant_id": tenant_code,
        "schema": schema,
        "role": user["role"],
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")


@handle_errors
def login(event, context):
    """ID-01: valida tenant_code + email + password y firma un JWT HS256 de 1 hora."""
    body, err = parse_body(event, context)
    if err:
        return err

    errors = unknown_fields(body, {"tenant_code", "email", "password"})

    tenant_code = body.get("tenant_code")
    if isinstance(tenant_code, str):
        tenant_code = tenant_code.strip().lower()
    if not isinstance(tenant_code, str) or not TENANT_CODE_RE.match(tenant_code):
        errors.append({"field": "tenant_code", "issue": "Código de organización inválido"})

    email = validate_email(body, errors)
    password = validate_password(body, errors)

    if errors:
        return validation_error(errors, context)

    tenant = _find_tenant(get_conn(), tenant_code)
    if tenant is None:
        verify_password(password, dummy_password_hash())
        return _invalid_credentials(context)

    code, schema, tenant_name = tenant
    conn = tenant_conn(schema)
    rows = conn.run(
        f"SELECT {USER_COLUMNS}, password_hash FROM users WHERE email = :email",
        email=email,
    )
    if not rows:
        verify_password(password, dummy_password_hash())
        return _invalid_credentials(context)

    row = rows[0]
    user = user_from_row(row[:-1])
    password_ok = verify_password(password, row[-1])
    if not password_ok or not user["active"]:
        return _invalid_credentials(context)

    user["tenant"] = {"id": code, "name": tenant_name}
    return ok({
        "data": {
            "access_token": issue_token(user, code, schema),
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL_SECONDS,
            "user": user,
        }
    })


@handle_errors
def me(event, context):
    """ID-02: usuario autenticado (restaura la sesión al recargar la página)."""
    ctx = tenant_ctx(event)
    conn = tenant_conn(ctx["schema"])
    rows = conn.run(
        f"SELECT {USER_COLUMNS} FROM users WHERE id = CAST(:id AS uuid)",
        id=ctx["user_id"],
    )
    if not rows:
        return not_found("Usuario", context)

    user = user_from_row(rows[0])
    tenant = conn.run(
        "SELECT name FROM public.tenants WHERE code = :code",
        code=ctx["tenant_id"],
    )
    user["tenant"] = {
        "id": ctx["tenant_id"],
        "name": tenant[0][0] if tenant else ctx["tenant_id"],
    }
    return ok({"data": user})
