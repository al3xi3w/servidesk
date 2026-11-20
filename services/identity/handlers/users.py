"""ms-identity · ID-03..ID-07: usuarios y equipos."""

from common.db import tenant_conn
from common.events import publish
from common.http import ok, tenant_ctx
from handlers.identity_common import (
    ROLES,
    USER_COLUMNS,
    api_error,
    forbidden,
    handle_errors,
    has_role,
    hash_password,
    is_unique_violation,
    is_uuid,
    like_pattern,
    not_found,
    page_meta,
    parse_body,
    parse_pagination,
    path_param,
    query_params,
    row_to_dict,
    split_csv,
    unknown_fields,
    user_from_row,
    validate_email,
    validate_password,
    validate_search,
    validate_text,
    validation_error,
)

USER_SORT_FIELDS = ("created_at", "full_name", "email")
TEAM_FIELDS = ("id", "name", "description")


# ------------------------------------------------------------------ ID-03 GET /users


@handle_errors
def listUsers(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)

    query = query_params(event)
    paging, errors = parse_pagination(query, USER_SORT_FIELDS, "created_at")
    search = validate_search(query, errors)

    where = []
    params = {}

    if query.get("role") not in (None, ""):
        roles = split_csv(query["role"])
        if not roles or any(role not in ROLES for role in roles):
            errors.append({"field": "role", "issue": f"Valores permitidos: {', '.join(ROLES)}"})
        else:
            where.append("role = ANY(CAST(:roles AS text[]))")
            params["roles"] = roles

    if query.get("active") not in (None, ""):
        if query["active"] not in ("true", "false"):
            errors.append({"field": "active", "issue": "Debe ser true o false"})
        else:
            where.append("active = :active")
            params["active"] = query["active"] == "true"

    if query.get("ids") not in (None, ""):
        ids = split_csv(query["ids"])
        if len(ids) > 100 or not all(is_uuid(i) for i in ids):
            errors.append({"field": "ids", "issue": "Hasta 100 UUID separados por comas"})
        else:
            where.append("id = ANY(CAST(:ids AS uuid[]))")
            params["ids"] = ids

    if search:
        where.append("(email ILIKE :search ESCAPE '\\' OR full_name ILIKE :search ESCAPE '\\')")
        params["search"] = like_pattern(search)

    if errors:
        return validation_error(errors, context)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    conn = tenant_conn(ctx["schema"])

    total = conn.run(f"SELECT COUNT(*) FROM users {where_sql}", **params)[0][0]
    rows = conn.run(
        f"SELECT {USER_COLUMNS} FROM users {where_sql} "
        f"ORDER BY {paging['sort_by']} {paging['sort_order']}, id "
        "LIMIT :limit OFFSET :offset",
        limit=paging["limit"],
        offset=(paging["page"] - 1) * paging["limit"],
        **params,
    )

    return ok({
        "data": [user_from_row(row) for row in rows],
        "meta": page_meta(paging["page"], paging["limit"], total),
    })


# ------------------------------------------------------------------ ID-04 GET /users/{id}


@handle_errors
def getUser(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)

    user_id = path_param(event, "id")
    if not is_uuid(user_id):
        return validation_error([{"field": "id", "issue": "Debe ser un UUID"}], context)

    conn = tenant_conn(ctx["schema"])
    rows = conn.run(
        f"SELECT {USER_COLUMNS} FROM users WHERE id = CAST(:id AS uuid)",
        id=user_id,
    )
    if not rows:
        return not_found("Usuario", context)
    return ok({"data": user_from_row(rows[0])})


# ------------------------------------------------------------------ ID-05 POST /users


@handle_errors
def createUser(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin"):
        return forbidden(context)

    body, err = parse_body(event, context)
    if err:
        return err

    errors = unknown_fields(body, {"email", "full_name", "role", "password", "active"})
    email = validate_email(body, errors)
    full_name = validate_text(body, "full_name", 3, 150, errors)
    role = body.get("role")
    if role not in ROLES:
        errors.append({"field": "role", "issue": f"Valores permitidos: {', '.join(ROLES)}"})
    password = validate_password(body, errors)
    active = body.get("active", True)
    if not isinstance(active, bool):
        errors.append({"field": "active", "issue": "Debe ser booleano"})

    if errors:
        return validation_error(errors, context)

    conn = tenant_conn(ctx["schema"])
    if conn.run("SELECT 1 FROM users WHERE email = :email", email=email):
        return _email_exists(context)

    try:
        rows = conn.run(
            "INSERT INTO users (email, full_name, role, password_hash, active) "
            "VALUES (:email, :full_name, :role, :password_hash, :active) "
            f"RETURNING {USER_COLUMNS}",
            email=email,
            full_name=full_name,
            role=role,
            password_hash=hash_password(password),
            active=active,
        )
    except Exception as exc:  # carrera entre el SELECT y el INSERT
        if is_unique_violation(exc):
            return _email_exists(context)
        raise

    user = user_from_row(rows[0])
    publish(
        event_type="UserCreated",
        tenant_id=ctx["tenant_id"],
        data={
            "userId": user["id"],
            "email": user["email"],
            "role": user["role"],
            "actorId": ctx["user_id"],
        },
        source="ms-identity",
    )
    return ok({"data": user}, 201)


def _email_exists(context):
    return api_error(
        "EMAIL_ALREADY_EXISTS",
        "Ya existe un usuario con ese email en la organización",
        409,
        context=context,
    )


# ------------------------------------------------------------------ ID-06 PATCH /users/{id}


@handle_errors
def updateUser(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin"):
        return forbidden(context)

    user_id = path_param(event, "id")
    if not is_uuid(user_id):
        return validation_error([{"field": "id", "issue": "Debe ser un UUID"}], context)

    body, err = parse_body(event, context)
    if err:
        return err

    errors = unknown_fields(body, {"full_name", "role", "active", "password"})
    sets = []
    params = {"id": user_id}

    if "full_name" in body:
        full_name = validate_text(body, "full_name", 3, 150, errors)
        if full_name is not None:
            sets.append("full_name = :full_name")
            params["full_name"] = full_name

    if "role" in body:
        if body["role"] not in ROLES:
            errors.append({"field": "role", "issue": f"Valores permitidos: {', '.join(ROLES)}"})
        else:
            sets.append("role = :role")
            params["role"] = body["role"]

    if "active" in body:
        if not isinstance(body["active"], bool):
            errors.append({"field": "active", "issue": "Debe ser booleano"})
        else:
            sets.append("active = :active")
            params["active"] = body["active"]

    if "password" in body:
        password = validate_password(body, errors)
        if password is not None:
            sets.append("password_hash = :password_hash")
            params["password_hash"] = hash_password(password)

    if not body:
        errors.append({"field": "body", "issue": "Envía al menos un campo para actualizar"})

    if errors:
        return validation_error(errors, context)

    # Un admin no puede quitarse a sí mismo el rol admin ni desactivarse.
    if user_id.lower() == str(ctx["user_id"]).lower() and (
        params.get("role", "admin") != "admin" or params.get("active", True) is False
    ):
        return api_error(
            "CONFLICT",
            "No puedes quitarte el rol de administrador ni desactivar tu propia cuenta",
            409,
            context=context,
        )

    conn = tenant_conn(ctx["schema"])
    rows = conn.run(
        f"UPDATE users SET {', '.join(sets)} WHERE id = CAST(:id AS uuid) RETURNING {USER_COLUMNS}",
        **params,
    )
    if not rows:
        return not_found("Usuario", context)
    return ok({"data": user_from_row(rows[0])})


# ------------------------------------------------------------------ ID-07 GET /teams


@handle_errors
def listTeams(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)

    query = query_params(event)
    paging, errors = parse_pagination(query, ("name",), "name", default_order="asc")
    search = validate_search(query, errors)
    if errors:
        return validation_error(errors, context)

    where_sql = ""
    params = {}
    if search:
        where_sql = "WHERE name ILIKE :search ESCAPE '\\'"
        params["search"] = like_pattern(search)

    conn = tenant_conn(ctx["schema"])
    total = conn.run(f"SELECT COUNT(*) FROM teams {where_sql}", **params)[0][0]
    rows = conn.run(
        f"SELECT id, name, description FROM teams {where_sql} "
        f"ORDER BY name {paging['sort_order']}, id LIMIT :limit OFFSET :offset",
        limit=paging["limit"],
        offset=(paging["page"] - 1) * paging["limit"],
        **params,
    )
    return ok({
        "data": [row_to_dict(TEAM_FIELDS, row) for row in rows],
        "meta": page_meta(paging["page"], paging["limit"], total),
    })
