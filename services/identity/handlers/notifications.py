"""ms-identity · Bandeja de notificaciones (la llena el consumidor identity-notify-q).

Rutas propuestas en frontend/src/api/notificationService.ts:
    GET  /notifications?limit=20   -> {"data": Notification[], "meta": {"unread": n}}
    POST /notifications/read {ids?} -> 204 (sin ids marca todas)
"""

from common.db import tenant_conn
from common.http import ok, tenant_ctx
from handlers.identity_common import (
    handle_errors,
    is_uuid,
    no_content,
    parse_body,
    query_params,
    row_to_dict,
    unknown_fields,
    validation_error,
)

NOTIFICATION_FIELDS = (
    "id",
    "user_id",
    "event_type",
    "title",
    "body",
    "read",
    "created_at",
    "resource_type",
    "resource_id",
)


@handle_errors
def listNotifications(event, context):
    ctx = tenant_ctx(event)
    query = query_params(event)

    limit = 20
    if query.get("limit") not in (None, ""):
        try:
            limit = int(query["limit"])
            if not 1 <= limit <= 100:
                raise ValueError
        except ValueError:
            return validation_error([{"field": "limit", "issue": "Debe ser un entero entre 1 y 100"}], context)

    conn = tenant_conn(ctx["schema"])
    rows = conn.run(
        f"SELECT {', '.join(NOTIFICATION_FIELDS)} FROM notifications "
        "WHERE user_id = CAST(:user_id AS uuid) "
        "ORDER BY created_at DESC, id LIMIT :limit",
        user_id=ctx["user_id"],
        limit=limit,
    )
    unread = conn.run(
        "SELECT COUNT(*) FROM notifications WHERE user_id = CAST(:user_id AS uuid) AND NOT read",
        user_id=ctx["user_id"],
    )[0][0]

    return ok({
        "data": [row_to_dict(NOTIFICATION_FIELDS, row) for row in rows],
        "meta": {"unread": unread},
    })


@handle_errors
def markNotificationsRead(event, context):
    ctx = tenant_ctx(event)
    body, err = parse_body(event, context, required=False)
    if err:
        return err

    errors = unknown_fields(body, {"ids"})
    ids = body.get("ids")
    if ids is not None and (
        not isinstance(ids, list) or len(ids) > 100 or not all(is_uuid(i) for i in ids)
    ):
        errors.append({"field": "ids", "issue": "Debe ser una lista de hasta 100 UUID"})
    if errors:
        return validation_error(errors, context)

    conn = tenant_conn(ctx["schema"])
    sql = "UPDATE notifications SET read = TRUE WHERE user_id = CAST(:user_id AS uuid) AND NOT read"
    params = {"user_id": ctx["user_id"]}
    if ids is not None:
        sql += " AND id = ANY(CAST(:ids AS uuid[]))"
        params["ids"] = ids
    conn.run(sql, **params)
    return no_content()
