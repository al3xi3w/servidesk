"""Handlers HTTP de ms-requests."""
from common.http import ok, error, tenant_ctx
from common.db import tenant_conn


def listRequests(event, context):
    ctx = tenant_ctx(event)
    conn = tenant_conn(ctx["schema"])
    rows = conn.run("SELECT * FROM service_requests ORDER BY created_at DESC LIMIT 50")
    cols = [c["name"] for c in conn.columns]
    return ok([dict(zip(cols, r)) for r in rows])
