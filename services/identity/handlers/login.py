"""Handlers HTTP de ms-identity."""
from common.http import ok, error, tenant_ctx
from common.db import tenant_conn


def login(event, context):
    # TODO: validar tenant_code + email + password y firmar el JWT
    return error("no implementado", 501)
