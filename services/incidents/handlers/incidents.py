"""Handlers HTTP de ms-incidents."""
from common.http import ok, error, tenant_ctx
from common.db import tenant_conn


def listIncidents(event, context):
    ctx = tenant_ctx(event)
    conn = tenant_conn(ctx["schema"])
    rows = conn.run("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 50")
    cols = [c["name"] for c in conn.columns]
    return ok([dict(zip(cols, r)) for r in rows])


def createIncident(event, context):
    # TODO: insertar en el schema del tenant y publicar IncidentCreated
    return error("no implementado", 501)
