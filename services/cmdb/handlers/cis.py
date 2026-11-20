"""ms-cmdb · CM-01..CM-08: elementos de configuración (CI), relaciones y tipos.

Contrato: docs/API_CONTRACTS.md §8.2. Cada cambio de campo o de estado queda en ci_history.
PUT /cis/{id}/status y DELETE /cis/{id} publican CIStatusChanged: si el CI pasa a "down",
ms-incidents (incidents-ci-q) abre un incidente P2 automático.
"""

import json

from common.db import tenant_conn
from common.events import publish
from common.http import ok, tenant_ctx
from handlers.cmdb_common import (
    api_error,
    forbidden,
    handle_errors,
    has_role,
    is_uuid,
    like_pattern,
    no_content,
    not_found,
    page_meta,
    parse_body,
    parse_pagination,
    path_param,
    query_params,
    row_to_dict,
    split_csv,
    unknown_fields,
    validate_search,
    validate_text,
    validation_error,
)

CI_STATUSES = ("operational", "degraded", "down", "retired")
ENVIRONMENTS = ("prod", "qa", "dev")
CI_SORT_FIELDS = ("created_at", "updated_at", "name", "status")
EDITABLE_FIELDS = ("type_id", "name", "environment", "version", "owner_team_id", "attributes")
MAX_ATTRIBUTES_BYTES = 8 * 1024

CI_FIELDS = (
    "id", "type_id", "type_name", "name", "status", "environment", "version",
    "owner_team_id", "attributes", "created_at", "updated_at",
)
CI_SELECT = (
    "SELECT c.id, c.type_id, t.name AS type_name, c.name, c.status, c.environment, c.version, "
    "c.owner_team_id, c.attributes, c.created_at, c.updated_at "
    "FROM configuration_items c JOIN ci_types t ON t.id = c.type_id"
)


# ------------------------------------------------------------------ utilidades


def _ci_from_row(row):
    ci = row_to_dict(CI_FIELDS, row)
    if isinstance(ci["attributes"], str):  # por si el driver devuelve jsonb como texto
        ci["attributes"] = json.loads(ci["attributes"])
    if ci["attributes"] is None:
        ci["attributes"] = {}
    return ci


def _fetch_ci(conn, ci_id):
    rows = conn.run(f"{CI_SELECT} WHERE c.id = CAST(:id AS uuid)", id=ci_id)
    return _ci_from_row(rows[0]) if rows else None


def _history_text(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _add_history(conn, ci_id, field, old, new, actor_id, source="api", change_id=None):
    conn.run(
        "INSERT INTO ci_history (ci_id, field, old_value, new_value, actor_id, source, change_id) "
        "VALUES (CAST(:ci_id AS uuid), :field, CAST(:old AS text), CAST(:new AS text), "
        "CAST(:actor_id AS uuid), :source, CAST(:change_id AS uuid))",
        ci_id=ci_id,
        field=field,
        old=_history_text(old),
        new=_history_text(new),
        actor_id=actor_id,
        source=source,
        change_id=change_id,
    )


def _validate_fields(body, errors, required):
    """Valida los campos editables presentes en el body. Devuelve {columna: valor}."""
    values = {}

    if "type_id" in body:
        type_id = body["type_id"]
        if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id < 1:
            errors.append({"field": "type_id", "issue": "Debe ser un entero positivo"})
        else:
            values["type_id"] = type_id
    elif required:
        errors.append({"field": "type_id", "issue": "Es obligatorio"})

    if "name" in body or required:
        name = validate_text(body, "name", 2, 150, errors)
        if name is not None:
            values["name"] = name

    if "environment" in body or required:
        if body.get("environment") not in ENVIRONMENTS:
            errors.append({"field": "environment", "issue": f"Valores permitidos: {', '.join(ENVIRONMENTS)}"})
        else:
            values["environment"] = body["environment"]

    if "version" in body:
        version = body["version"]
        if version is not None and (not isinstance(version, str) or len(version.strip()) > 50):
            errors.append({"field": "version", "issue": "Texto de máximo 50 caracteres o null"})
        else:
            values["version"] = (version or "").strip() or None

    if "owner_team_id" in body:
        team = body["owner_team_id"]
        if team is not None and not is_uuid(team):
            errors.append({"field": "owner_team_id", "issue": "Debe ser un UUID o null"})
        else:
            values["owner_team_id"] = team.lower() if team else None

    if "attributes" in body:
        attributes = body["attributes"]
        if not isinstance(attributes, dict):
            errors.append({"field": "attributes", "issue": "Debe ser un objeto JSON"})
        elif len(json.dumps(attributes, ensure_ascii=False).encode("utf-8")) > MAX_ATTRIBUTES_BYTES:
            errors.append({"field": "attributes", "issue": "No puede superar 8 KB"})
        else:
            values["attributes"] = attributes

    return values


def _type_exists(conn, type_id):
    return bool(conn.run("SELECT 1 FROM ci_types WHERE id = :id", id=type_id))


def _ci_id_or_error(event, context):
    ci_id = path_param(event, "id")
    if not is_uuid(ci_id):
        return None, validation_error([{"field": "id", "issue": "Debe ser un UUID"}], context)
    return ci_id.lower(), None


def _rollback(conn):
    try:
        conn.run("ROLLBACK")
    except Exception:  # noqa: BLE001
        pass


def _publish_status_changed(ctx, ci, previous_status):
    publish(
        event_type="CIStatusChanged",
        tenant_id=ctx["tenant_id"],
        data={
            "ciId": ci["id"],
            "name": ci["name"],
            "previousStatus": previous_status,
            "status": ci["status"],
            "actorId": ctx["user_id"],
        },
        source="ms-cmdb",
    )


# ------------------------------------------------------------------ CM-01 GET /cis


@handle_errors
def listCis(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)

    query = query_params(event)
    paging, errors = parse_pagination(query, CI_SORT_FIELDS, "created_at")
    search = validate_search(query, errors)

    where = []
    params = {}
    for field, allowed in (("status", CI_STATUSES), ("environment", ENVIRONMENTS)):
        if query.get(field) not in (None, ""):
            values = split_csv(query[field])
            if not values or any(v not in allowed for v in values):
                errors.append({"field": field, "issue": f"Valores permitidos: {', '.join(allowed)}"})
            else:
                where.append(f"c.{field} = ANY(CAST(:{field} AS text[]))")
                params[field] = values

    if query.get("type_id") not in (None, ""):
        try:
            params["type_id"] = int(query["type_id"])
            where.append("c.type_id = :type_id")
        except ValueError:
            errors.append({"field": "type_id", "issue": "Debe ser un entero"})

    if query.get("owner_team_id") not in (None, ""):
        if not is_uuid(query["owner_team_id"]):
            errors.append({"field": "owner_team_id", "issue": "Debe ser un UUID"})
        else:
            where.append("c.owner_team_id = CAST(:owner_team_id AS uuid)")
            params["owner_team_id"] = query["owner_team_id"]

    if search:
        where.append("c.name ILIKE :search ESCAPE '\\'")
        params["search"] = like_pattern(search)

    if errors:
        return validation_error(errors, context)

    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    conn = tenant_conn(ctx["schema"])
    total = conn.run(f"SELECT COUNT(*) FROM configuration_items c{where_sql}", **params)[0][0]
    rows = conn.run(
        f"{CI_SELECT}{where_sql} ORDER BY c.{paging['sort_by']} {paging['sort_order']}, c.id "
        "LIMIT :limit OFFSET :offset",
        limit=paging["limit"],
        offset=(paging["page"] - 1) * paging["limit"],
        **params,
    )
    return ok({
        "data": [_ci_from_row(row) for row in rows],
        "meta": page_meta(paging["page"], paging["limit"], total),
    })


# ------------------------------------------------------------------ CM-02 POST /cis


@handle_errors
def createCi(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)

    body, err = parse_body(event, context)
    if err:
        return err
    errors = unknown_fields(body, EDITABLE_FIELDS)
    values = _validate_fields(body, errors, required=True)
    if errors:
        return validation_error(errors, context)

    conn = tenant_conn(ctx["schema"])
    if not _type_exists(conn, values["type_id"]):
        return validation_error([{"field": "type_id", "issue": "Tipo de CI inexistente"}], context)

    conn.run("BEGIN")
    try:
        rows = conn.run(
            "INSERT INTO configuration_items (type_id, name, status, environment, version, owner_team_id, attributes) "
            "VALUES (:type_id, :name, 'operational', :environment, CAST(:version AS varchar), "
            "CAST(:owner_team_id AS uuid), CAST(:attributes AS jsonb)) RETURNING id",
            type_id=values["type_id"],
            name=values["name"],
            environment=values["environment"],
            version=values.get("version"),
            owner_team_id=values.get("owner_team_id"),
            attributes=json.dumps(values.get("attributes") or {}, ensure_ascii=False),
        )
        ci_id = str(rows[0][0])
        _add_history(conn, ci_id, "created", None, values["name"], ctx["user_id"])
        conn.run("COMMIT")
    except Exception:
        _rollback(conn)
        raise

    return ok({"data": _fetch_ci(conn, ci_id)}, 201)


# ------------------------------------------------------------------ CM-03 GET /cis/{id}


@handle_errors
def getCi(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)
    ci_id, err = _ci_id_or_error(event, context)
    if err:
        return err

    ci = _fetch_ci(tenant_conn(ctx["schema"]), ci_id)
    if ci is None:
        return not_found("CI", context)
    return ok({"data": ci})


# ------------------------------------------------------------------ CM-04 PATCH /cis/{id}


@handle_errors
def updateCi(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)
    ci_id, err = _ci_id_or_error(event, context)
    if err:
        return err

    body, err = parse_body(event, context)
    if err:
        return err
    errors = unknown_fields(body, EDITABLE_FIELDS)
    if not body:
        errors.append({"field": "body", "issue": "Envía al menos un campo para actualizar"})
    values = _validate_fields(body, errors, required=False)
    if errors:
        return validation_error(errors, context)

    conn = tenant_conn(ctx["schema"])
    conn.run("BEGIN")
    try:
        current = conn.run(
            "SELECT type_id, name, environment, version, owner_team_id, attributes, status "
            "FROM configuration_items WHERE id = CAST(:id AS uuid) FOR UPDATE",
            id=ci_id,
        )
        if not current:
            _rollback(conn)
            return not_found("CI", context)

        before = dict(zip(EDITABLE_FIELDS + ("status",), current[0]))
        before["owner_team_id"] = str(before["owner_team_id"]) if before["owner_team_id"] else None
        if isinstance(before["attributes"], str):
            before["attributes"] = json.loads(before["attributes"])

        if before["status"] == "retired":
            _rollback(conn)
            return api_error("CONFLICT", "Un CI retirado no se puede editar", 409, context=context)

        if "type_id" in values and values["type_id"] != before["type_id"] and not _type_exists(conn, values["type_id"]):
            _rollback(conn)
            return validation_error([{"field": "type_id", "issue": "Tipo de CI inexistente"}], context)

        changed = {f: v for f, v in values.items() if v != before[f]}
        if changed:
            casts = {"version": "CAST(:version AS varchar)", "owner_team_id": "CAST(:owner_team_id AS uuid)",
                     "attributes": "CAST(:attributes AS jsonb)"}
            sets = [f"{f} = {casts.get(f, ':' + f)}" for f in changed]
            params = dict(changed)
            if "attributes" in params:
                params["attributes"] = json.dumps(params["attributes"], ensure_ascii=False)
            conn.run(
                f"UPDATE configuration_items SET {', '.join(sets)}, updated_at = (now() AT TIME ZONE 'utc') "
                "WHERE id = CAST(:id AS uuid)",
                id=ci_id,
                **params,
            )
            for field, new in changed.items():
                _add_history(conn, ci_id, field, before[field], new, ctx["user_id"])
        conn.run("COMMIT")
    except Exception:
        _rollback(conn)
        raise

    return ok({"data": _fetch_ci(conn, ci_id)})


# ------------------------------------------------------------------ CM-05 PUT /cis/{id}/status


def _set_status(conn, ctx, ci_id, new_status):
    """Cambia el estado dentro de una transacción. Devuelve (ci, estado_anterior) o (None, motivo)."""
    rows = conn.run(
        "SELECT status FROM configuration_items WHERE id = CAST(:id AS uuid) FOR UPDATE",
        id=ci_id,
    )
    if not rows:
        return None, "not_found"
    previous = rows[0][0]
    if previous == new_status:
        return None, previous
    conn.run(
        "UPDATE configuration_items SET status = :status, updated_at = (now() AT TIME ZONE 'utc') "
        "WHERE id = CAST(:id AS uuid)",
        status=new_status,
        id=ci_id,
    )
    _add_history(conn, ci_id, "status", previous, new_status, ctx["user_id"])
    return _fetch_ci(conn, ci_id), previous


@handle_errors
def changeCiStatus(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)
    ci_id, err = _ci_id_or_error(event, context)
    if err:
        return err

    body, err = parse_body(event, context)
    if err:
        return err
    errors = unknown_fields(body, {"status"})
    if body.get("status") not in CI_STATUSES:
        errors.append({"field": "status", "issue": f"Valores permitidos: {', '.join(CI_STATUSES)}"})
    if errors:
        return validation_error(errors, context)
    new_status = body["status"]

    conn = tenant_conn(ctx["schema"])
    conn.run("BEGIN")
    try:
        current = conn.run(
            "SELECT status FROM configuration_items WHERE id = CAST(:id AS uuid) FOR UPDATE", id=ci_id)
        if not current:
            _rollback(conn)
            return not_found("CI", context)
        previous = current[0][0]
        if previous == "retired" or previous == new_status:
            _rollback(conn)
            return api_error(
                "INVALID_STATUS_TRANSITION",
                "Transición de estado no permitida",
                409,
                details=[{"field": "status", "issue": f"De '{previous}' no se puede pasar a '{new_status}'"}],
                context=context,
            )
        ci, previous = _set_status(conn, ctx, ci_id, new_status)
        conn.run("COMMIT")
    except Exception:
        _rollback(conn)
        raise

    _publish_status_changed(ctx, ci, previous)
    return ok({"data": ci})


# ------------------------------------------------------------------ CM-06 DELETE /cis/{id}


@handle_errors
def deleteCi(event, context):
    """Baja lógica: status = retired. Idempotente (204 también si ya estaba retirado)."""
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin"):
        return forbidden(context)
    ci_id, err = _ci_id_or_error(event, context)
    if err:
        return err

    conn = tenant_conn(ctx["schema"])
    conn.run("BEGIN")
    try:
        ci, previous = _set_status(conn, ctx, ci_id, "retired")
        conn.run("COMMIT")
    except Exception:
        _rollback(conn)
        raise

    if ci is None and previous == "not_found":
        return not_found("CI", context)
    if ci is not None:
        _publish_status_changed(ctx, ci, previous)
    return no_content()


# ------------------------------------------------------------------ CM-07 GET /cis/{id}/relations


@handle_errors
def listCiRelations(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)
    ci_id, err = _ci_id_or_error(event, context)
    if err:
        return err

    conn = tenant_conn(ctx["schema"])
    if not conn.run("SELECT 1 FROM configuration_items WHERE id = CAST(:id AS uuid)", id=ci_id):
        return not_found("CI", context)

    rows = conn.run(
        "SELECT r.id, r.relation, "
        "CASE WHEN r.source_ci_id = CAST(:id AS uuid) THEN 'outgoing' ELSE 'incoming' END AS direction, "
        "o.id, o.name, o.status, t.name "
        "FROM ci_relations r "
        "JOIN configuration_items o ON o.id = CASE WHEN r.source_ci_id = CAST(:id AS uuid) "
        "THEN r.target_ci_id ELSE r.source_ci_id END "
        "JOIN ci_types t ON t.id = o.type_id "
        "WHERE r.source_ci_id = CAST(:id AS uuid) OR r.target_ci_id = CAST(:id AS uuid) "
        "ORDER BY direction DESC, r.relation, o.name",
        id=ci_id,
    )
    data = []
    for rel_id, relation, direction, other_id, name, status, type_name in rows:
        data.append({
            "id": str(rel_id),
            "relation": relation,
            "direction": direction,
            "ci": {"id": str(other_id), "name": name, "status": status, "type_name": type_name},
        })
    return ok({"data": data})


# ------------------------------------------------------------------ CM-08 GET /ci-types


@handle_errors
def listCiTypes(event, context):
    ctx = tenant_ctx(event)
    if not has_role(ctx, "admin", "agent"):
        return forbidden(context)
    rows = tenant_conn(ctx["schema"]).run("SELECT id, name FROM ci_types ORDER BY id")
    return ok({"data": [{"id": r[0], "name": r[1]} for r in rows]})
