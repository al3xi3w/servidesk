
"""Handlers HTTP de ms-changes."""

import json
import uuid
from datetime import datetime, timezone

from common.http import ok, tenant_ctx
from common.db import tenant_conn
from common.events import publish


CHANGE_STATUSES = {
    "draft",
    "submitted",
    "approved",
    "rejected",
    "scheduled",
    "implemented",
    "failed",
}

CHANGE_TYPES = {
    "standard",
    "normal",
    "emergency",
}

CHANGE_RISKS = {
    "low",
    "medium",
    "high",
}

CHANGE_SORT_FIELDS = {
    "created_at",
    "planned_start",
    "risk",
    "status",
    "key",
}


def api_error(code, message, status=400):
    """Respuesta de error según API_CONTRACTS.md."""
    return ok({
        "error": {
            "code": code,
            "message": message,
        }
    }, status)


def serialize_change(change):
    """Convertir UUID y fechas a valores JSON."""
    result = {}

    for key, value in change.items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)

        elif isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)

            result[key] = (
                value.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )

        else:
            result[key] = value

    return result


def parse_date(value):
    """Interpretar una fecha ISO 8601 en UTC."""
    if not isinstance(value, str):
        raise ValueError("Fecha inválida")

    date_value = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if date_value.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria")

    return (
        date_value.astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

def listChanges(event, context):
    """CH-01: GET /changes."""

    # 1. Contexto del usuario autenticado
    ctx = tenant_ctx(event)

    role = ctx["role"]
    user_id = ctx["user_id"]

    # 2. Validar permisos
    if role not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar cambios",
            403,
        )

    query = event.get("queryStringParameters") or {}

    # 3. Validar paginación
    try:
        page = int(query.get("page", "1"))
        limit = int(query.get("limit", "20"))
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "page y limit deben ser enteros",
        )

    if page < 1 or not 1 <= limit <= 100:
        return api_error(
            "VALIDATION_ERROR",
            "page debe ser >= 1 y limit entre 1 y 100",
        )

    # 4. Validar ordenamiento
    sort_by = query.get("sort_by", "created_at")
    sort_order = query.get("sort_order", "desc")

    if sort_by not in CHANGE_SORT_FIELDS:
        return api_error(
            "VALIDATION_ERROR",
            "sort_by inválido",
        )

    if sort_order not in ("asc", "desc"):
        return api_error(
            "VALIDATION_ERROR",
            "sort_order debe ser asc o desc",
        )

    conditions = []
    params = {}

    # 5. Filtros de estado, tipo y riesgo
    enum_filters = {
        "status": CHANGE_STATUSES,
        "type": CHANGE_TYPES,
        "risk": CHANGE_RISKS,
    }

    for field, allowed_values in enum_filters.items():
        value = query.get(field)

        if value is None:
            continue

        if not isinstance(value, str):
            return api_error(
                "VALIDATION_ERROR",
                f"Filtro inválido: {field}",
            )

        values = value.split(",")

        if any(
            item not in allowed_values
            for item in values
        ):
            return api_error(
                "VALIDATION_ERROR",
                f"Filtro inválido: {field}",
            )

        placeholders = []

        for index, item in enumerate(values):
            name = f"{field}_{index}"
            placeholders.append(f":{name}")
            params[name] = item

        conditions.append(
            f"{field} IN ({', '.join(placeholders)})"
        )

    # 6. Filtrar por solicitante
    requester = query.get("requester_id")

    if requester is not None:
        if requester == "me":
            try:
                requester_id = str(
                    uuid.UUID(str(user_id))
                )
            except (ValueError, TypeError, AttributeError):
                return api_error(
                    "VALIDATION_ERROR",
                    "ID del usuario autenticado inválido",
                )
        else:
            try:
                requester_id = str(
                    uuid.UUID(requester)
                )
            except (ValueError, TypeError, AttributeError):
                return api_error(
                    "VALIDATION_ERROR",
                    "requester_id debe ser un UUID válido",
                )

        params["requester_id"] = requester_id
        conditions.append(
            "requester_id = :requester_id"
        )

    # 7. Buscar por clave o título
    search = query.get("search")

    if search is not None:
        if (
            not isinstance(search, str)
            or not 2 <= len(search) <= 100
        ):
            return api_error(
                "VALIDATION_ERROR",
                "search debe tener entre 2 y 100 caracteres",
            )

        params["search"] = f"%{search}%"

        conditions.append(
            "(key ILIKE :search OR title ILIKE :search)"
        )

    # 8. Filtros de calendario
    planned_from = query.get("planned_from")
    planned_to = query.get("planned_to")

    date_from = None
    date_to = None

    try:
        if planned_from is not None:
            date_from = parse_date(planned_from)

        if planned_to is not None:
            date_to = parse_date(planned_to)

    except (ValueError, TypeError, OverflowError):
        return api_error(
            "VALIDATION_ERROR",
            "planned_from y planned_to deben ser fechas ISO 8601",
        )

    if (
        date_from is not None
        and date_to is not None
        and date_from > date_to
    ):
        return api_error(
            "VALIDATION_ERROR",
            "planned_from no puede ser posterior a planned_to",
        )

    # Solapamiento de intervalos:
    # cambio.inicio <= filtro.fin
    # cambio.fin >= filtro.inicio
    if date_from is not None:
        params["planned_from"] = date_from
        conditions.append(
            "planned_end >= :planned_from"
        )

    if date_to is not None:
        params["planned_to"] = date_to
        conditions.append(
            "planned_start <= :planned_to"
        )

    # 9. Construir WHERE
    where_sql = (
        " WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    # 10. Conectar al esquema del tenant
    conn = tenant_conn(ctx["schema"])

    # 11. Contar registros
    count_rows = conn.run(
        "SELECT COUNT(*) FROM changes" + where_sql,
        **params,
    )

    total = count_rows[0][0]

    # 12. Consultar página solicitada
    offset = (page - 1) * limit

    sql = (
        "SELECT * FROM changes"
        + where_sql
        + f" ORDER BY {sort_by} {sort_order.upper()}, id ASC"
        + " LIMIT :limit OFFSET :offset"
    )

    rows = conn.run(
        sql,
        **params,
        limit=limit,
        offset=offset,
    )

    columns = [
        column["name"]
        for column in conn.columns
    ]

    data = [
        serialize_change(dict(zip(columns, row)))
        for row in rows
    ]

    # 13. Respuesta CH-01
    return ok({
        "data": data,
        "meta": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (
                (total + limit - 1) // limit
            ),
        },
    })

def createChange(event, context):
    """CH-02: POST /changes."""

    import json

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para crear cambios",
            403,
        )

    # 2. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
        )

    if not isinstance(body, dict):
        return api_error(
            "VALIDATION_ERROR",
            "El body debe ser un objeto JSON",
        )

    # 3. Rechazar campos desconocidos
    allowed_fields = {
        "title",
        "description",
        "type",
        "risk",
        "rollback_plan",
        "planned_start",
        "planned_end",
        "problem_id",
        "cis",
    }

    unknown = set(body) - allowed_fields

    if unknown:
        return api_error(
            "VALIDATION_ERROR",
            "Campos no permitidos: "
            + ", ".join(sorted(unknown)),
        )

    # 4. Validar título
    title = body.get("title")

    if (
        not isinstance(title, str)
        or not 3 <= len(title.strip()) <= 200
    ):
        return api_error(
            "VALIDATION_ERROR",
            "title debe tener entre 3 y 200 caracteres",
        )

    title = title.strip()

    # 5. Validar descripción
    description = body.get("description")

    if description is not None:
        if (
            not isinstance(description, str)
            or len(description) > 5000
        ):
            return api_error(
                "VALIDATION_ERROR",
                "description debe ser texto de máximo 5000 caracteres",
            )

    # 6. Validar tipo y riesgo
    change_type = body.get("type")
    risk = body.get("risk")

    if change_type not in CHANGE_TYPES:
        return api_error(
            "VALIDATION_ERROR",
            "type debe ser standard, normal o emergency",
        )

    if risk not in CHANGE_RISKS:
        return api_error(
            "VALIDATION_ERROR",
            "risk debe ser low, medium o high",
        )

    # 7. Validar plan de reversión
    rollback_plan = body.get("rollback_plan")

    if rollback_plan is not None:
        if (
            not isinstance(rollback_plan, str)
            or len(rollback_plan) > 5000
        ):
            return api_error(
                "VALIDATION_ERROR",
                "rollback_plan debe ser texto de máximo 5000 caracteres",
            )

    # 8. Validar fechas
    planned_start = None
    planned_end = None

    try:
        if body.get("planned_start") is not None:
            planned_start = parse_date(
                body["planned_start"]
            )

        if body.get("planned_end") is not None:
            planned_end = parse_date(
                body["planned_end"]
            )

    except (ValueError, TypeError, OverflowError):
        return api_error(
            "VALIDATION_ERROR",
            "Las fechas deben estar en formato ISO 8601 con zona horaria",
        )

    if (
        planned_start is not None
        and planned_end is not None
        and planned_end <= planned_start
    ):
        return api_error(
            "VALIDATION_ERROR",
            "planned_end debe ser posterior a planned_start",
        )

    # 9. Validar problema relacionado
    problem_id = body.get("problem_id")

    if problem_id is not None:
        try:
            problem_id = str(uuid.UUID(problem_id))
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                "problem_id debe ser un UUID válido",
            )

    # 10. Validar CI afectados
    cis = body.get("cis", [])

    if not isinstance(cis, list):
        return api_error(
            "VALIDATION_ERROR",
            "cis debe ser una lista",
        )

    if len(cis) > 50:
        return api_error(
            "VALIDATION_ERROR",
            "cis no puede contener más de 50 elementos",
        )

    validated_cis = []
    seen_ids = set()

    for item in cis:
        if not isinstance(item, dict):
            return api_error(
                "VALIDATION_ERROR",
                "Cada CI debe ser un objeto JSON",
            )

        unknown_ci_fields = set(item) - {
            "ci_id",
            "new_version",
        }

        if unknown_ci_fields:
            return api_error(
                "VALIDATION_ERROR",
                "Campos no permitidos en cis",
            )

        try:
            ci_id = str(uuid.UUID(item.get("ci_id")))
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                "Cada ci_id debe ser un UUID válido",
            )

        if ci_id in seen_ids:
            return api_error(
                "VALIDATION_ERROR",
                "No se permiten CI duplicados",
            )

        seen_ids.add(ci_id)

        new_version = item.get("new_version")

        if new_version is not None:
            if (
                not isinstance(new_version, str)
                or len(new_version) > 50
            ):
                return api_error(
                    "VALIDATION_ERROR",
                    "new_version debe tener máximo 50 caracteres",
                )

        validated_cis.append({
            "ci_id": ci_id,
            "new_version": new_version,
        })

    # 11. Validar ID del solicitante autenticado
    try:
        requester_id = str(
            uuid.UUID(str(ctx["user_id"]))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "INTERNAL_ERROR",
            "Contexto de usuario inválido",
            500,
        )

    # 12. Conectar al tenant
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 13. Bloquear generación de claves por tenant
        conn.run(
            """
            SELECT pg_advisory_xact_lock(
                hashtext(current_schema() || ':change_key')
            )
            """
        )

        # 14. Obtener siguiente correlativo
        rows = conn.run(
            """
            SELECT COALESCE(
                MAX(SUBSTRING(key FROM 5)::integer),
                0
            )
            FROM changes
            WHERE key ~ '^CHG-[0-9]{6}$'
            """
        )

        next_number = rows[0][0] + 1

        if next_number > 999999:
            raise RuntimeError(
                "Se agotó el rango de claves de cambios"
            )

        change_key = f"CHG-{next_number:06d}"

        # 15. Crear cambio en estado draft
        rows = conn.run(
            """
            INSERT INTO changes (
                key,
                title,
                description,
                type,
                risk,
                status,
                rollback_plan,
                planned_start,
                planned_end,
                requester_id,
                problem_id
            )
            VALUES (
                :key,
                :title,
                :description,
                :type,
                :risk,
                'draft',
                :rollback_plan,
                :planned_start,
                :planned_end,
                :requester_id,
                :problem_id
            )
            RETURNING *
            """,
            key=change_key,
            title=title,
            description=description,
            type=change_type,
            risk=risk,
            rollback_plan=rollback_plan,
            planned_start=planned_start,
            planned_end=planned_end,
            requester_id=requester_id,
            problem_id=problem_id,
        )

        columns = [
            column["name"]
            for column in conn.columns
        ]

        change = dict(zip(columns, rows[0]))
        change_id = str(change["id"])

        # 16. Vincular los CI afectados
        for ci in validated_cis:
            conn.run(
                """
                INSERT INTO change_cis (
                    change_id,
                    ci_id,
                    new_version
                )
                VALUES (
                    :change_id,
                    :ci_id,
                    :new_version
                )
                """,
                change_id=change_id,
                ci_id=ci["ci_id"],
                new_version=ci["new_version"],
            )

        # 17. Confirmar transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 18. Respuesta ChangeDetail
    detail = serialize_change(change)
    detail["cis"] = validated_cis
    detail["approvals"] = []

    return ok({
        "data": detail
    }, 201)

def getChange(event, context):
    """CH-03: GET /changes/{id}."""

    # 1. Obtener contexto del usuario
    ctx = tenant_ctx(event)

    # 2. Verificar permisos
    if ctx["role"] not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar cambios",
            403,
        )

    # 3. Validar UUID del cambio
    path_params = event.get("pathParameters") or {}

    try:
        change_id = str(
            uuid.UUID(path_params.get("id"))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID del cambio debe ser un UUID válido",
            400,
        )

    # 4. Conectar al esquema del tenant
    conn = tenant_conn(ctx["schema"])

    # 5. Consultar solicitud de cambio
    rows = conn.run(
        """
        SELECT *
        FROM changes
        WHERE id = :change_id
        """,
        change_id=change_id,
    )

    if not rows:
        return api_error(
            "NOT_FOUND",
            "Solicitud de cambio no encontrada",
            404,
        )

    # 6. Convertir el cambio a diccionario
    columns = [
        column["name"]
        for column in conn.columns
    ]

    change = dict(zip(columns, rows[0]))

    # 7. Consultar los CI relacionados
    ci_rows = conn.run(
        """
        SELECT
            ci_id,
            new_version
        FROM change_cis
        WHERE change_id = :change_id
        ORDER BY ci_id ASC
        """,
        change_id=change_id,
    )

    ci_columns = [
        column["name"]
        for column in conn.columns
    ]

    cis = [
        serialize_change(dict(zip(ci_columns, row)))
        for row in ci_rows
    ]

    # 8. Consultar las aprobaciones CAB
    approval_rows = conn.run(
        """
        SELECT
            id,
            change_id,
            approver_id,
            decision,
            comment,
            decided_at
        FROM change_approvals
        WHERE change_id = :change_id
        ORDER BY decided_at ASC, id ASC
        """,
        change_id=change_id,
    )

    approval_columns = [
        column["name"]
        for column in conn.columns
    ]

    approvals = [
        serialize_change(dict(zip(approval_columns, row)))
        for row in approval_rows
    ]

    # 9. Construir ChangeDetail
    detail = serialize_change(change)

    detail["cis"] = cis
    detail["approvals"] = approvals

    # 10. Responder según CH-03
    return ok({
        "data": detail
    })

def updateChange(event, context):
    """CH-04: PATCH /changes/{id}."""

    import json

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para actualizar cambios",
            403,
        )

    # 2. Validar UUID del cambio
    path_params = event.get("pathParameters") or {}

    try:
        change_id = str(uuid.UUID(path_params.get("id")))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID del cambio debe ser un UUID válido",
            400,
        )

    # 3. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
        )

    if not isinstance(body, dict) or not body:
        return api_error(
            "VALIDATION_ERROR",
            "Debes enviar al menos un campo",
            400,
        )

    # 4. Validar campos permitidos
    allowed_fields = {
        "title",
        "description",
        "type",
        "risk",
        "rollback_plan",
        "planned_start",
        "planned_end",
        "problem_id",
        "cis",
    }

    unknown = set(body) - allowed_fields

    if unknown:
        return api_error(
            "VALIDATION_ERROR",
            "Campos no permitidos: "
            + ", ".join(sorted(unknown)),
            400,
        )

    # 5. Validar título
    if "title" in body:
        title = body["title"]

        if (
            not isinstance(title, str)
            or not 3 <= len(title.strip()) <= 200
        ):
            return api_error(
                "VALIDATION_ERROR",
                "title debe tener entre 3 y 200 caracteres",
                400,
            )

        body["title"] = title.strip()

    # 6. Validar descripción y plan de reversión
    for field in ("description", "rollback_plan"):
        if field not in body:
            continue

        value = body[field]

        if value is not None:
            if (
                not isinstance(value, str)
                or len(value) > 5000
            ):
                return api_error(
                    "VALIDATION_ERROR",
                    f"{field} debe ser texto de máximo 5000 caracteres",
                    400,
                )

    # 7. Validar tipo
    if "type" in body:
        value = body["type"]

        if (
            not isinstance(value, str)
            or value not in CHANGE_TYPES
        ):
            return api_error(
                "VALIDATION_ERROR",
                "type debe ser standard, normal o emergency",
                400,
            )

    # 8. Validar riesgo
    if "risk" in body:
        value = body["risk"]

        if (
            not isinstance(value, str)
            or value not in CHANGE_RISKS
        ):
            return api_error(
                "VALIDATION_ERROR",
                "risk debe ser low, medium o high",
                400,
            )

    # 9. Validar fechas
    for field in ("planned_start", "planned_end"):
        if field not in body or body[field] is None:
            continue

        try:
            body[field] = parse_date(body[field])
        except (ValueError, TypeError, OverflowError):
            return api_error(
                "VALIDATION_ERROR",
                f"{field} debe ser una fecha ISO 8601 válida",
                400,
            )

    # 10. Validar problema relacionado
    if (
        "problem_id" in body
        and body["problem_id"] is not None
    ):
        try:
            body["problem_id"] = str(
                uuid.UUID(body["problem_id"])
            )
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                "problem_id debe ser un UUID válido",
                400,
            )

    # 11. Validar CI afectados
    validated_cis = None

    if "cis" in body:
        cis = body["cis"]

        if not isinstance(cis, list):
            return api_error(
                "VALIDATION_ERROR",
                "cis debe ser una lista",
                400,
            )

        if len(cis) > 50:
            return api_error(
                "VALIDATION_ERROR",
                "cis no puede tener más de 50 elementos",
                400,
            )

        validated_cis = []
        seen_ids = set()

        for item in cis:
            if not isinstance(item, dict):
                return api_error(
                    "VALIDATION_ERROR",
                    "Cada CI debe ser un objeto JSON",
                    400,
                )

            unknown_ci_fields = set(item) - {
                "ci_id",
                "new_version",
            }

            if unknown_ci_fields:
                return api_error(
                    "VALIDATION_ERROR",
                    "Campos no permitidos en cis",
                    400,
                )

            try:
                ci_id = str(
                    uuid.UUID(item.get("ci_id"))
                )
            except (ValueError, TypeError, AttributeError):
                return api_error(
                    "VALIDATION_ERROR",
                    "Cada ci_id debe ser un UUID válido",
                    400,
                )

            if ci_id in seen_ids:
                return api_error(
                    "VALIDATION_ERROR",
                    "No se permiten CI duplicados",
                    400,
                )

            seen_ids.add(ci_id)

            new_version = item.get("new_version")

            if new_version is not None:
                if (
                    not isinstance(new_version, str)
                    or len(new_version) > 50
                ):
                    return api_error(
                        "VALIDATION_ERROR",
                        "new_version debe tener máximo 50 caracteres",
                        400,
                    )

            validated_cis.append({
                "ci_id": ci_id,
                "new_version": new_version,
            })

    # 12. Conectar al schema autenticado
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 13. Bloquear el cambio
        rows = conn.run(
            """
            SELECT
                status,
                planned_start,
                planned_end
            FROM changes
            WHERE id = :change_id
            FOR UPDATE
            """,
            change_id=change_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Solicitud de cambio no encontrada",
                404,
            )

        current_status = rows[0][0]
        current_start = rows[0][1]
        current_end = rows[0][2]

        # 14. Solo se pueden modificar drafts
        if current_status != "draft":
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "CONFLICT",
                "Solo se pueden editar cambios en estado draft",
                409,
            )

        # 15. Validar fechas combinando valores
        # actuales con los enviados en el PATCH
        final_start = body.get(
            "planned_start",
            current_start,
        )

        final_end = body.get(
            "planned_end",
            current_end,
        )

        if (
            final_start is not None
            and final_end is not None
            and final_end <= final_start
        ):
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "VALIDATION_ERROR",
                "planned_end debe ser posterior a planned_start",
                400,
            )

        # 16. Separar campos normales de los CI
        updates = {
            field: value
            for field, value in body.items()
            if field != "cis"
        }

        # 17. Actualizar campos del cambio
        if updates:
            assignments = [
                f"{field} = :{field}"
                for field in updates
            ]

            sql = (
                "UPDATE changes SET "
                + ", ".join(assignments)
                + " WHERE id = :change_id"
            )

            conn.run(
                sql,
                change_id=change_id,
                **updates,
            )

        # 18. Reemplazar CI si fueron enviados
        if validated_cis is not None:
            conn.run(
                """
                DELETE FROM change_cis
                WHERE change_id = :change_id
                """,
                change_id=change_id,
            )

            for ci in validated_cis:
                conn.run(
                    """
                    INSERT INTO change_cis (
                        change_id,
                        ci_id,
                        new_version
                    )
                    VALUES (
                        :change_id,
                        :ci_id,
                        :new_version
                    )
                    """,
                    change_id=change_id,
                    ci_id=ci["ci_id"],
                    new_version=ci["new_version"],
                )

        # 19. Confirmar todos los cambios
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 20. Devolver ChangeDetail actualizado
    return getChange(event, context)

def changeChangeStatus(event, context):
    """CH-05: PUT /changes/{id}/status."""

    import json

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para cambiar el estado",
            403,
        )

    # 2. Validar UUID
    try:
        change_id = str(uuid.UUID(
            (event.get("pathParameters") or {}).get("id")
        ))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID del cambio debe ser un UUID válido",
            400,
        )

    # 3. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
        )

    if not isinstance(body, dict):
        return api_error(
            "VALIDATION_ERROR",
            "El body debe ser un objeto JSON",
            400,
        )

    # 4. Solo se permite status
    if set(body) != {"status"}:
        return api_error(
            "VALIDATION_ERROR",
            "Debes enviar únicamente el campo status",
            400,
        )

    # approved y rejected solo mediante CH-06 y CH-07
    allowed_targets = {
        "draft",
        "submitted",
        "scheduled",
        "implemented",
        "failed",
    }

    requested_status = body["status"]

    if (
        not isinstance(requested_status, str)
        or requested_status not in allowed_targets
    ):
        return api_error(
            "VALIDATION_ERROR",
            "Estado no permitido para este endpoint",
            400,
        )

    # 5. Transiciones permitidas mediante CH-05
    transitions = {
        "draft": {"submitted"},
        "rejected": {"draft"},
        "approved": {"scheduled"},
        "scheduled": {"implemented", "failed"},
    }

    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 6. Consultar y bloquear el cambio
        rows = conn.run(
            """
            SELECT
                status,
                type,
                rollback_plan,
                planned_start,
                planned_end,
                key,
                risk
            FROM changes
            WHERE id = :change_id
            FOR UPDATE
            """,
            change_id=change_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Solicitud de cambio no encontrada",
                404,
            )

        (
            current_status,
            change_type,
            rollback_plan,
            planned_start,
            planned_end,
            change_key,
            risk,
        ) = rows[0]

        # 7. Validar transición
        if requested_status not in transitions.get(
            current_status, set()
        ):
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "INVALID_STATUS_TRANSITION",
                "Transición de estado no permitida",
                409,
            )

        final_status = requested_status

        # 8. Reglas al enviar un cambio
        if (
            current_status == "draft"
            and requested_status == "submitted"
        ):
            # Las fechas son obligatorias
            if (
                planned_start is None
                or planned_end is None
                or planned_end <= planned_start
            ):
                conn.run("ROLLBACK")
                transaction_started = False

                return api_error(
                    "VALIDATION_ERROR",
                    "El cambio necesita fechas de inicio y fin válidas",
                    400,
                )

            # Cambios no estándar requieren plan de reversión
            if change_type != "standard":
                if (
                    not isinstance(rollback_plan, str)
                    or not rollback_plan.strip()
                ):
                    conn.run("ROLLBACK")
                    transaction_started = False

                    return api_error(
                        "VALIDATION_ERROR",
                        "El cambio requiere rollback_plan",
                        400,
                    )

            # D14: los standard se aprueban automáticamente
            if change_type == "standard":
                final_status = "approved"

        # 9. Actualizar estado
        conn.run(
            """
            UPDATE changes
            SET status = :new_status
            WHERE id = :change_id
            """,
            new_status=final_status,
            change_id=change_id,
        )

        # 10. Confirmar transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 11. Publicar eventos después del COMMIT
    event_type = None

    if requested_status == "submitted":
        event_type = "ChangeSubmitted"

    elif final_status == "implemented":
        event_type = "ChangeImplemented"

    # 12. ChangeDetail actualizado (también alimenta el evento)
    detail_response = getChange(event, context)

    if event_type is not None:
        try:
            detail = json.loads(detail_response.get("body") or "{}").get("data") or {}
        except (TypeError, ValueError, AttributeError):
            detail = {}

        publish(
            event_type=event_type,
            tenant_id=ctx["tenant_id"],
            data={
                "changeId": change_id,
                "key": change_key,
                "type": change_type,
                "risk": risk,
                "status": final_status,
                "plannedStart": detail.get("planned_start"),
                "requesterId": detail.get("requester_id"),
                # ms-problems cierra este problema; ms-cmdb aplica new_version a cada CI
                "problemId": detail.get("problem_id"),
                "cis": [
                    {"ciId": ci.get("ci_id"), "newVersion": ci.get("new_version")}
                    for ci in detail.get("cis") or []
                ],
                "actorId": ctx["user_id"],
            },
            source="ms-changes",
        )

    return detail_response

def approveChange(event, context):
    """CH-06: POST /changes/{id}/approve."""

    import json

    ctx = tenant_ctx(event)

    # 1. Solo administradores pueden aprobar
    if ctx["role"] != "admin":
        return api_error(
            "FORBIDDEN",
            "Solo un administrador puede aprobar cambios",
            403,
        )

    # 2. Validar UUID del cambio
    path_params = event.get("pathParameters") or {}

    try:
        change_id = str(
            uuid.UUID(path_params.get("id"))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID del cambio debe ser un UUID válido",
            400,
        )

    # 3. Validar UUID del administrador autenticado
    try:
        approver_id = str(
            uuid.UUID(str(ctx["user_id"]))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "INTERNAL_ERROR",
            "Contexto de usuario inválido",
            500,
        )

    # 4. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
        )

    if not isinstance(body, dict):
        return api_error(
            "VALIDATION_ERROR",
            "El body debe ser un objeto JSON",
            400,
        )

    # 5. Solo se permite el campo comment
    unknown = set(body) - {"comment"}

    if unknown:
        return api_error(
            "VALIDATION_ERROR",
            "Campos no permitidos: "
            + ", ".join(sorted(unknown)),
            400,
        )

    # 6. Comentario opcional, máximo 2000 caracteres
    comment = body.get("comment")

    if comment is not None:
        if (
            not isinstance(comment, str)
            or len(comment) > 2000
        ):
            return api_error(
                "VALIDATION_ERROR",
                "comment debe ser texto de máximo 2000 caracteres",
                400,
            )

    # 7. Conectar al schema del tenant
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 8. Consultar y bloquear el cambio
        rows = conn.run(
            """
            SELECT
                status,
                requester_id,
                key,
                type,
                risk
            FROM changes
            WHERE id = :change_id
            FOR UPDATE
            """,
            change_id=change_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Solicitud de cambio no encontrada",
                404,
            )

        (
            current_status,
            requester_id,
            change_key,
            change_type,
            risk,
        ) = rows[0]

        # 9. Solo se aprueban cambios submitted
        if current_status != "submitted":
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "CONFLICT",
                "Solo se pueden aprobar cambios en estado submitted",
                409,
            )

        # 10. El solicitante no puede aprobar
        # su propio cambio
        if str(requester_id) == approver_id:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "FORBIDDEN",
                "No puedes aprobar tu propia solicitud de cambio",
                403,
            )

        # 11. Registrar decisión CAB
        conn.run(
            """
            INSERT INTO change_approvals (
                change_id,
                approver_id,
                decision,
                comment,
                decided_at
            )
            VALUES (
                :change_id,
                :approver_id,
                'approved',
                :comment,
                CURRENT_TIMESTAMP
            )
            """,
            change_id=change_id,
            approver_id=approver_id,
            comment=comment,
        )

        # 12. Cambiar estado a approved
        conn.run(
            """
            UPDATE changes
            SET status = 'approved'
            WHERE id = :change_id
            """,
            change_id=change_id,
        )

        # 13. Confirmar transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 14. Publicar evento después del COMMIT
    publish(
        event_type="ChangeApproved",
        tenant_id=ctx["tenant_id"],
        data={
            "changeId": change_id,
            "key": change_key,
            "type": change_type,
            "risk": risk,
            "status": "approved",
            "requesterId": str(requester_id),
            "approverId": approver_id,
            "comment": comment,
            "actorId": approver_id,
        },
        source="ms-changes",
    )

    # 15. Devolver ChangeDetail actualizado
    return getChange(event, context)

def rejectChange(event, context):
    """CH-07: POST /changes/{id}/reject."""

    import json

    ctx = tenant_ctx(event)

    # 1. Solo administradores pueden rechazar
    if ctx["role"] != "admin":
        return api_error(
            "FORBIDDEN",
            "Solo un administrador puede rechazar cambios",
            403,
        )

    # 2. Validar UUID del cambio
    path_params = event.get("pathParameters") or {}

    try:
        change_id = str(
            uuid.UUID(path_params.get("id"))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID del cambio debe ser un UUID válido",
            400,
        )

    # 3. Validar UUID del administrador autenticado
    try:
        approver_id = str(
            uuid.UUID(str(ctx["user_id"]))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "INTERNAL_ERROR",
            "Contexto de usuario inválido",
            500,
        )

    # 4. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
        )

    if not isinstance(body, dict):
        return api_error(
            "VALIDATION_ERROR",
            "El body debe ser un objeto JSON",
            400,
        )

    # 5. Solo se acepta comment
    if set(body) != {"comment"}:
        return api_error(
            "VALIDATION_ERROR",
            "Debes enviar únicamente el campo comment",
            400,
        )

    # 6. Comentario obligatorio de 3 a 2000 caracteres
    comment = body["comment"]

    if not isinstance(comment, str):
        return api_error(
            "VALIDATION_ERROR",
            "comment debe ser texto",
            400,
        )

    comment = comment.strip()

    if not 3 <= len(comment) <= 2000:
        return api_error(
            "VALIDATION_ERROR",
            "comment debe tener entre 3 y 2000 caracteres",
            400,
        )

    # 7. Conectar al schema autenticado
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 8. Buscar y bloquear el cambio
        rows = conn.run(
            """
            SELECT
                status,
                requester_id,
                key,
                type,
                risk
            FROM changes
            WHERE id = :change_id
            FOR UPDATE
            """,
            change_id=change_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Solicitud de cambio no encontrada",
                404,
            )

        (
            current_status,
            requester_id,
            change_key,
            change_type,
            risk,
        ) = rows[0]

        # 9. Solo se rechazan cambios submitted
        if current_status != "submitted":
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "CONFLICT",
                "Solo se pueden rechazar cambios en estado submitted",
                409,
            )

        # 10. No permitir que el solicitante
        # rechace su propio cambio
        if str(requester_id) == approver_id:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "FORBIDDEN",
                "No puedes rechazar tu propia solicitud de cambio",
                403,
            )

        # 11. Registrar decisión CAB
        conn.run(
            """
            INSERT INTO change_approvals (
                change_id,
                approver_id,
                decision,
                comment,
                decided_at
            )
            VALUES (
                :change_id,
                :approver_id,
                'rejected',
                :comment,
                CURRENT_TIMESTAMP
            )
            """,
            change_id=change_id,
            approver_id=approver_id,
            comment=comment,
        )

        # 12. Cambiar estado a rejected
        conn.run(
            """
            UPDATE changes
            SET status = 'rejected'
            WHERE id = :change_id
            """,
            change_id=change_id,
        )

        # 13. Confirmar la transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 14. Publicar evento SNS después del COMMIT
    publish(
        event_type="ChangeRejected",
        tenant_id=ctx["tenant_id"],
        data={
            "changeId": change_id,
            "key": change_key,
            "type": change_type,
            "risk": risk,
            "status": "rejected",
            "requesterId": str(requester_id),
            "approverId": approver_id,
            "comment": comment,
            "actorId": approver_id,
        },
        source="ms-changes",
    )

    # 15. Devolver ChangeDetail actualizado
    return getChange(event, context)



