
"""Handlers HTTP de ms-requests - ServiDesk."""

import json
import math
import uuid
from datetime import datetime, date, timezone

from common.http import ok, tenant_ctx
from common.db import tenant_conn
from common.events import publish


# =====================================================
# CONSTANTES
# =====================================================

REQUEST_STATUSES = {
    "submitted",
    "pending_approval",
    "approved",
    "rejected",
    "in_fulfillment",
    "fulfilled",
}

REQUEST_SORT_FIELDS = {
    "created_at",
    "status",
    "key",
}

FORM_FIELD_TYPES = {
    "text",
    "textarea",
    "number",
    "date",
    "select",
    "boolean",
}


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def api_error(code, message, status=400):
    """Generar una respuesta de error."""
    return ok({
        "error": {
            "code": code,
            "message": message,
        }
    }, status)


def serialize_value(value):
    """Convertir valores PostgreSQL a JSON."""

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return (
            value.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            serialize_value(item)
            for item in value
        ]

    return value


def serialize_row(columns, row):
    """Convertir una fila SQL a diccionario."""
    return {
        name: serialize_value(value)
        for name, value in zip(columns, row)
    }


def validate_form_schema(form_schema):
    """Validar la definición del formulario del catálogo."""

    if isinstance(form_schema, str):
        try:
            form_schema = json.loads(form_schema)
        except ValueError:
            return None

    if not isinstance(form_schema, dict):
        return None

    fields = form_schema.get("fields")

    if not isinstance(fields, list):
        return None

    names = set()

    for field in fields:
        if not isinstance(field, dict):
            return None

        name = field.get("name")
        field_type = field.get("type")

        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(field_type, str)
            or field_type not in FORM_FIELD_TYPES
            or not isinstance(
                field.get("required", False), bool
            )
        ):
            return None

        names.add(name)

        if field_type == "select":
            options = field.get("options")

            if (
                not isinstance(options, list)
                or not options
            ):
                return None

    return fields


def validate_form_data(form_data, fields):
    """Validar respuestas según el formulario.

    Devuelve None cuando los datos son válidos.
    """

    if not isinstance(form_data, dict):
        return "form_data debe ser un objeto JSON"

    allowed_names = {
        field["name"]
        for field in fields
    }

    unknown = set(form_data) - allowed_names

    if unknown:
        return (
            "Campos no permitidos en form_data: "
            + ", ".join(sorted(unknown))
        )

    for field in fields:
        name = field["name"]
        field_type = field["type"]
        required = field.get("required", False)

        value = form_data.get(name)

        # Validar campos obligatorios
        if value is None or value == "":
            if required:
                return f"El campo {name} es obligatorio"
            continue

        # Texto
        if field_type in ("text", "textarea"):
            if not isinstance(value, str):
                return f"{name} debe ser texto"

        # Número
        elif field_type == "number":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return f"{name} debe ser numérico y finito"

        # Booleano
        elif field_type == "boolean":
            if not isinstance(value, bool):
                return f"{name} debe ser booleano"

        # Fecha
        elif field_type == "date":
            if not isinstance(value, str):
                return f"{name} debe ser una fecha"

            try:
                date.fromisoformat(value)
            except ValueError:
                return (
                    f"{name} debe ser una fecha YYYY-MM-DD"
                )

        # Selección
        elif field_type == "select":
            options = field["options"]

            if (
                type(value) not in (str, int, float, bool)
                or value not in options
            ):
                return (
                    f"{name} contiene una opción inválida"
                )

    return None


# =====================================================
# RQ-01: GET /catalog
# =====================================================

def listCatalog(event, context):
    """Listar el catálogo de servicios de un tenant."""

    ctx = tenant_ctx(event)

    # Verificar permisos
    if ctx["role"] not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar el catálogo",
            403,
        )

    query = event.get("queryStringParameters") or {}

    conditions = ["ci.active = TRUE"]
    params = {}

    # Filtro por categoría
    category_id = query.get("category_id")

    if category_id is not None:
        try:
            category_id = int(category_id)
        except (ValueError, TypeError):
            return api_error(
                "VALIDATION_ERROR",
                "category_id debe ser un número entero",
            )

        if category_id < 1:
            return api_error(
                "VALIDATION_ERROR",
                "category_id debe ser mayor que cero",
            )

        conditions.append(
            "ci.category_id = :category_id"
        )

        params["category_id"] = category_id

    # Búsqueda por nombre
    search = query.get("search")

    if search is not None:
        if (
            not isinstance(search, str)
            or not 2 <= len(search.strip()) <= 100
        ):
            return api_error(
                "VALIDATION_ERROR",
                "search debe tener entre 2 y 100 caracteres",
            )

        params["search"] = f"%{search.strip()}%"

        conditions.append(
            "ci.name ILIKE :search"
        )

    where_sql = " AND ".join(conditions)

    sql = f"""
        SELECT
            ci.id,
            ci.category_id,
            cc.name AS category_name,
            ci.name,
            ci.description,
            ci.form_schema,
            ci.needs_approval,
            ci.sla_hours,
            ci.active,
            ci.created_at
        FROM catalog_items AS ci
        INNER JOIN catalog_categories AS cc
            ON cc.id = ci.category_id
        WHERE {where_sql}
        ORDER BY ci.name ASC, ci.id ASC
    """

    conn = tenant_conn(ctx["schema"])

    rows = conn.run(
        sql,
        **params,
    )

    columns = [
        column["name"]
        for column in conn.columns
    ]

    data = [
        serialize_row(columns, row)
        for row in rows
    ]

    return ok({
        "data": data
    })


# =====================================================
# RQ-02: GET /requests
# =====================================================

def listRequests(event, context):
    """Listar solicitudes con filtros y paginación."""

    ctx = tenant_ctx(event)

    role = ctx["role"]
    user_id = ctx["user_id"]

    # Verificar permisos
    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar solicitudes",
            403,
        )

    query = event.get("queryStringParameters") or {}

    # Paginación
    try:
        page = int(query.get("page", "1"))
        limit = int(query.get("limit", "20"))
    except (ValueError, TypeError, OverflowError):
        return api_error(
            "VALIDATION_ERROR",
            "page y limit deben ser números enteros",
        )

    if page < 1:
        return api_error(
            "VALIDATION_ERROR",
            "page debe ser mayor o igual a 1",
        )

    if not 1 <= limit <= 100:
        return api_error(
            "VALIDATION_ERROR",
            "limit debe estar entre 1 y 100",
        )

    # Ordenamiento
    sort_by = query.get("sort_by", "created_at")
    sort_order = query.get("sort_order", "desc")

    if sort_by not in REQUEST_SORT_FIELDS:
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

    # Filtro por estado
    status = query.get("status")

    if status is not None:
        if not isinstance(status, str):
            return api_error(
                "VALIDATION_ERROR",
                "status inválido",
            )

        statuses = status.split(",")

        if any(
            item not in REQUEST_STATUSES
            for item in statuses
        ):
            return api_error(
                "VALIDATION_ERROR",
                "status contiene valores no permitidos",
            )

        placeholders = []

        for index, value in enumerate(statuses):
            name = f"status_{index}"

            params[name] = value
            placeholders.append(f":{name}")

        conditions.append(
            "sr.status IN ("
            + ", ".join(placeholders)
            + ")"
        )

    # Filtro por servicio
    catalog_item_id = query.get("catalog_item_id")

    if catalog_item_id is not None:
        try:
            catalog_item_id = str(
                uuid.UUID(catalog_item_id)
            )
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                "catalog_item_id debe ser un UUID válido",
            )

        conditions.append(
            "sr.catalog_item_id = :catalog_item_id"
        )

        params["catalog_item_id"] = catalog_item_id

    # Validar usuario del token
    try:
        authenticated_user_id = str(
            uuid.UUID(str(user_id))
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "INTERNAL_ERROR",
            "Contexto de usuario inválido",
            500,
        )

    # Filtro por solicitante
    requester_filter = query.get("requester_id")

    if requester_filter is not None:
        if requester_filter == "me":
            requester_id = authenticated_user_id
        else:
            try:
                requester_id = str(
                    uuid.UUID(requester_filter)
                )
            except (ValueError, TypeError, AttributeError):
                return api_error(
                    "VALIDATION_ERROR",
                    "requester_id debe ser un UUID válido o me",
                )

        if (
            role == "customer"
            and requester_id != authenticated_user_id
        ):
            return api_error(
                "FORBIDDEN",
                "Solo puedes consultar tus propias solicitudes",
                403,
            )

        conditions.append(
            "sr.requester_id = :requester_id"
        )

        params["requester_id"] = requester_id

    elif role == "customer":
        # Los clientes solo ven sus propias solicitudes
        conditions.append(
            "sr.requester_id = :requester_id"
        )

        params["requester_id"] = authenticated_user_id

    # Filtro por responsable
    assignee_filter = query.get("assignee_id")

    if assignee_filter is not None:
        if assignee_filter == "none":
            conditions.append(
                "sr.assignee_id IS NULL"
            )

        else:
            if assignee_filter == "me":
                assignee_id = authenticated_user_id
            else:
                try:
                    assignee_id = str(
                        uuid.UUID(assignee_filter)
                    )
                except (ValueError, TypeError, AttributeError):
                    return api_error(
                        "VALIDATION_ERROR",
                        "assignee_id debe ser un UUID, me o none",
                    )

            conditions.append(
                "sr.assignee_id = :assignee_id"
            )

            params["assignee_id"] = assignee_id

    # Búsqueda por clave
    search = query.get("search")

    if search is not None:
        if (
            not isinstance(search, str)
            or not 2 <= len(search.strip()) <= 100
        ):
            return api_error(
                "VALIDATION_ERROR",
                "search debe tener entre 2 y 100 caracteres",
            )

        conditions.append(
            "sr.key ILIKE :search"
        )

        params["search"] = f"%{search.strip()}%"

    # Construir WHERE
    where_sql = (
        " WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )

    conn = tenant_conn(ctx["schema"])

    # Contar solicitudes
    count_sql = (
        "SELECT COUNT(*) "
        "FROM service_requests AS sr"
        + where_sql
    )

    count_rows = conn.run(
        count_sql,
        **params,
    )

    total = count_rows[0][0]

    # Calcular paginación
    offset = (page - 1) * limit

    # Consultar solicitudes
    list_sql = f"""
        SELECT
            sr.id,
            sr.key,
            sr.catalog_item_id,
            ci.name AS catalog_item_name,
            sr.form_data,
            sr.status,
            sr.requester_id,
            sr.assignee_id,
            sr.created_at,
            sr.fulfilled_at
        FROM service_requests AS sr
        INNER JOIN catalog_items AS ci
            ON ci.id = sr.catalog_item_id
        {where_sql}
        ORDER BY
            sr.{sort_by} {sort_order.upper()},
            sr.id ASC
        LIMIT :limit OFFSET :offset
    """

    rows = conn.run(
        list_sql,
        **params,
        limit=limit,
        offset=offset,
    )

    columns = [
        column["name"]
        for column in conn.columns
    ]

    data = [
        serialize_row(columns, row)
        for row in rows
    ]

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

# =====================================================
# RQ-03: POST /requests
# =====================================================

def createRequest(event, context):
    """Crear una solicitud de servicio."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para crear solicitudes",
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

    # 3. Validar campos permitidos
    if set(body) != {"catalog_item_id", "form_data"}:
        return api_error(
            "VALIDATION_ERROR",
            "Debes enviar catalog_item_id y form_data",
        )

    # 4. Validar UUID del servicio
    try:
        catalog_item_id = str(
            uuid.UUID(body["catalog_item_id"])
        )
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "catalog_item_id debe ser un UUID válido",
        )

    # 5. Validar estructura y tamaño del formulario
    form_data = body["form_data"]

    if not isinstance(form_data, dict):
        return api_error(
            "VALIDATION_ERROR",
            "form_data debe ser un objeto JSON",
        )

    # CORRECCIÓN:
    # Capturar valores que no pueden serializarse
    # como JSON válido.
    try:
        form_json = json.dumps(
            form_data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "form_data contiene valores inválidos",
            400,
        )

    if len(form_json.encode("utf-8")) > 8192:
        return api_error(
            "VALIDATION_ERROR",
            "form_data no puede superar 8 KB",
        )

    # 6. Validar identidad del solicitante
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

    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 7. Buscar el servicio activo
        rows = conn.run(
            """
            SELECT
                name,
                form_schema,
                needs_approval
            FROM catalog_items
            WHERE id = :catalog_item_id
              AND active = TRUE
            """,
            catalog_item_id=catalog_item_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Servicio del catálogo no encontrado",
                404,
            )

        (
            catalog_item_name,
            form_schema,
            needs_approval,
        ) = rows[0]

        # 8. Validar la definición del formulario
        fields = validate_form_schema(form_schema)

        if fields is None:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "INTERNAL_ERROR",
                "El formulario del catálogo no está configurado correctamente",
                500,
            )

        # 9. Validar las respuestas del usuario
        validation_error = validate_form_data(
            form_data,
            fields,
        )

        if validation_error:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "VALIDATION_ERROR",
                validation_error,
                400,
            )

        # 10. Bloquear generación de claves por tenant
        conn.run(
            """
            SELECT pg_advisory_xact_lock(
                hashtext(
                    current_schema() || ':request_key'
                )
            )
            """
        )

        number_rows = conn.run(
            """
            SELECT COALESCE(
                MAX(SUBSTRING(key FROM 5)::integer),
                0
            )
            FROM service_requests
            WHERE key ~ '^REQ-[0-9]{6}$'
            """
        )

        next_number = number_rows[0][0] + 1

        if next_number > 999999:
            raise RuntimeError(
                "Se agotaron las claves de solicitudes"
            )

        request_key = f"REQ-{next_number:06d}"

        # 11. Determinar estado inicial
        initial_status = (
            "pending_approval"
            if needs_approval
            else "submitted"
        )

        # 12. Guardar la solicitud
        rows = conn.run(
            """
            INSERT INTO service_requests (
                key,
                catalog_item_id,
                form_data,
                status,
                requester_id
            )
            VALUES (
                :key,
                :catalog_item_id,
                CAST(:form_data AS jsonb),
                :status,
                :requester_id
            )
            RETURNING
                id,
                key,
                catalog_item_id,
                form_data,
                status,
                requester_id,
                assignee_id,
                created_at,
                fulfilled_at
            """,
            key=request_key,
            catalog_item_id=catalog_item_id,
            form_data=form_json,
            status=initial_status,
            requester_id=requester_id,
        )

        columns = [
            column["name"]
            for column in conn.columns
        ]

        request_detail = serialize_row(
            columns,
            rows[0],
        )

        request_detail["catalog_item_name"] = (
            catalog_item_name
        )
        request_detail["approvals"] = []

        # 13. Confirmar transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 14. Publicar evento SNS
    publish(
        event_type="RequestSubmitted",
        tenant_id=ctx["tenant_id"],
        data={
            "requestId": str(request_detail["id"]),
            "key": request_key,
            "catalogItemId": catalog_item_id,
            "catalogItemName": catalog_item_name,
            "requesterId": requester_id,
            "status": initial_status,
        },
        source="ms-requests",
    )

    # 15. Devolver respuesta
    return ok({
        "data": request_detail
    }, 201)

# =====================================================
# RQ-04: GET /requests/{id}
# =====================================================

def getRequest(event, context):
    """Consultar una solicitud con sus aprobaciones."""

    # 1. Autenticación y permisos
    ctx = tenant_ctx(event)
    role = ctx["role"]

    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar solicitudes",
            403,
        )

    # 2. Obtener y validar el ID de la ruta
    path_params = event.get("pathParameters") or {}
    raw_id = path_params.get("id")

    try:
        request_id = str(uuid.UUID(raw_id))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID de la solicitud debe ser un UUID válido",
            400,
        )

    # 3. Conectar al tenant
    conn = tenant_conn(ctx["schema"])

    # 4. Consultar la solicitud
    rows = conn.run(
        """
        SELECT
            sr.id,
            sr.key,
            sr.catalog_item_id,
            ci.name AS catalog_item_name,
            sr.form_data,
            sr.status,
            sr.requester_id,
            sr.assignee_id,
            sr.created_at,
            sr.fulfilled_at
        FROM service_requests AS sr
        INNER JOIN catalog_items AS ci
            ON ci.id = sr.catalog_item_id
        WHERE sr.id = :request_id
        """,
        request_id=request_id,
    )

    if not rows:
        return api_error(
            "NOT_FOUND",
            "Solicitud no encontrada",
            404,
        )

    columns = [
        column["name"]
        for column in conn.columns
    ]

    request_detail = serialize_row(
        columns,
        rows[0],
    )

    # 5. Un customer solo puede consultar
    # sus propias solicitudes.
    if role == "customer":
        try:
            user_id = str(
                uuid.UUID(str(ctx["user_id"]))
            )
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "INTERNAL_ERROR",
                "Contexto de usuario inválido",
                500,
            )

        if request_detail["requester_id"] != user_id:
            return api_error(
                "FORBIDDEN",
                "Solo puedes consultar tus propias solicitudes",
                403,
            )

    # 6. Consultar historial de aprobaciones
    approval_rows = conn.run(
        """
        SELECT
            id,
            request_id,
            approver_id,
            decision,
            decided_at
        FROM request_approvals
        WHERE request_id = :request_id
        ORDER BY decided_at ASC, id ASC
        """,
        request_id=request_id,
    )

    approval_columns = [
        column["name"]
        for column in conn.columns
    ]

    request_detail["approvals"] = [
        serialize_row(approval_columns, row)
        for row in approval_rows
    ]

    # 7. Devolver detalle completo
    return ok({
        "data": request_detail
    })

# =====================================================
# RQ-05: PATCH /requests/{id}
# =====================================================

def updateRequest(event, context):
    """Actualizar responsable o formulario de una solicitud."""

    ctx = tenant_ctx(event)
    role = ctx["role"]

    # 1. Verificar rol
    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para actualizar solicitudes",
            403,
        )

    # 2. Validar identificador de la solicitud
    try:
        request_id = str(uuid.UUID(
            (event.get("pathParameters") or {}).get("id")
        ))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID de la solicitud debe ser un UUID válido",
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
            "Debes enviar un objeto JSON con campos",
            400,
        )

    # 4. Campos permitidos según el rol
    allowed_fields = (
        {"assignee_id"}
        if role in ("admin", "agent")
        else {"form_data"}
    )

    if not set(body).issubset(allowed_fields):
        return api_error(
            "VALIDATION_ERROR",
            "El body contiene campos no permitidos para tu rol",
            400,
        )

    # 5. Validar el usuario autenticado
    if role == "customer":
        try:
            user_id = str(uuid.UUID(str(ctx["user_id"])))
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "INTERNAL_ERROR",
                "Contexto de usuario inválido",
                500,
            )

    # 6. Validar assignee_id
    if role in ("admin", "agent"):
        assignee_id = body["assignee_id"]

        if assignee_id is not None:
            try:
                assignee_id = str(uuid.UUID(assignee_id))
            except (ValueError, TypeError, AttributeError):
                return api_error(
                    "VALIDATION_ERROR",
                    "assignee_id debe ser un UUID válido o null",
                    400,
                )

    # 7. Validar estructura y tamaño de form_data
    if role == "customer":
        form_data = body["form_data"]

        if not isinstance(form_data, dict):
            return api_error(
                "VALIDATION_ERROR",
                "form_data debe ser un objeto JSON",
                400,
            )

        try:
            form_json = json.dumps(
                form_data,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (ValueError, TypeError):
            return api_error(
                "VALIDATION_ERROR",
                "form_data contiene valores inválidos",
                400,
            )

        if len(form_json.encode("utf-8")) > 8192:
            return api_error(
                "VALIDATION_ERROR",
                "form_data no puede superar 8 KB",
                400,
            )

    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        # 8. Bloquear la solicitud para evitar
        # actualizaciones concurrentes
        conn.run("BEGIN")
        transaction_started = True

        rows = conn.run(
            """
            SELECT
                sr.requester_id,
                sr.status,
                ci.form_schema
            FROM service_requests AS sr
            INNER JOIN catalog_items AS ci
                ON ci.id = sr.catalog_item_id
            WHERE sr.id = :request_id
            FOR UPDATE OF sr
            """,
            request_id=request_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Solicitud no encontrada",
                404,
            )

        requester_id, status, form_schema = rows[0]

        # 9. Reglas especiales para customer
        if role == "customer":
            if str(requester_id) != user_id:
                conn.run("ROLLBACK")
                transaction_started = False

                return api_error(
                    "FORBIDDEN",
                    "Solo puedes modificar tus propias solicitudes",
                    403,
                )

            if status not in (
                "submitted",
                "pending_approval",
            ):
                conn.run("ROLLBACK")
                transaction_started = False

                return api_error(
                    "CONFLICT",
                    "La solicitud ya no puede editarse",
                    409,
                )

            # 10. Validar form_data contra form_schema
            fields = validate_form_schema(form_schema)

            if fields is None:
                conn.run("ROLLBACK")
                transaction_started = False

                return api_error(
                    "INTERNAL_ERROR",
                    "El formulario del catálogo es inválido",
                    500,
                )

            validation_error = validate_form_data(
                form_data,
                fields,
            )

            if validation_error:
                conn.run("ROLLBACK")
                transaction_started = False

                return api_error(
                    "VALIDATION_ERROR",
                    validation_error,
                    400,
                )

            # 11. Actualizar formulario
            conn.run(
                """
                UPDATE service_requests
                SET form_data = CAST(:form_data AS jsonb)
                WHERE id = :request_id
                """,
                form_data=form_json,
                request_id=request_id,
            )

        else:
            # 12. Admin y agent actualizan responsable
            conn.run(
                """
                UPDATE service_requests
                SET assignee_id = :assignee_id
                WHERE id = :request_id
                """,
                assignee_id=assignee_id,
                request_id=request_id,
            )

        # 13. Consultar detalle actualizado
        rows = conn.run(
            """
            SELECT
                sr.id,
                sr.key,
                sr.catalog_item_id,
                ci.name AS catalog_item_name,
                sr.form_data,
                sr.status,
                sr.requester_id,
                sr.assignee_id,
                sr.created_at,
                sr.fulfilled_at
            FROM service_requests AS sr
            INNER JOIN catalog_items AS ci
                ON ci.id = sr.catalog_item_id
            WHERE sr.id = :request_id
            """,
            request_id=request_id,
        )

        columns = [
            column["name"]
            for column in conn.columns
        ]

        request_detail = serialize_row(
            columns,
            rows[0],
        )

        # 14. Consultar aprobaciones
        approval_rows = conn.run(
            """
            SELECT
                id,
                request_id,
                approver_id,
                decision,
                decided_at
            FROM request_approvals
            WHERE request_id = :request_id
            ORDER BY decided_at ASC, id ASC
            """,
            request_id=request_id,
        )

        approval_columns = [
            column["name"]
            for column in conn.columns
        ]

        request_detail["approvals"] = [
            serialize_row(approval_columns, row)
            for row in approval_rows
        ]

        # 15. Confirmar transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    return ok({
        "data": request_detail
    })

# =====================================================
# RQ-06: PUT /requests/{id}/status
# =====================================================

REQUEST_TRANSITIONS = {
    "pending_approval": {"approved", "rejected"},
    "submitted": {"in_fulfillment"},
    "approved": {"in_fulfillment"},
    "in_fulfillment": {"fulfilled"},
}

REQUEST_STATUS_EVENTS = {
    "approved": "RequestApproved",
    "rejected": "RequestRejected",
    "fulfilled": "RequestFulfilled",
}

def changeRequestStatus(event, context):
    """Cambiar el estado de una solicitud de servicio."""

    # 1. Validar permisos
    ctx = tenant_ctx(event)
    role = ctx["role"]

    if role not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para cambiar estados",
            403,
        )

    # 2. Validar UUID de la solicitud
    try:
        request_id = str(uuid.UUID(
            (event.get("pathParameters") or {}).get("id")
        ))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID de la solicitud debe ser un UUID válido",
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

    if not isinstance(body, dict) or set(body) != {"status"}:
        return api_error(
            "VALIDATION_ERROR",
            "Debes enviar únicamente el campo status",
            400,
        )

    new_status = body["status"]

    if not isinstance(new_status, str) or new_status not in {
        "approved",
        "rejected",
        "in_fulfillment",
        "fulfilled",
    }:
        return api_error(
            "VALIDATION_ERROR",
            "Estado de solicitud inválido",
            400,
        )

    # 4. Validar identidad del usuario
    try:
        user_id = str(uuid.UUID(str(ctx["user_id"])))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "INTERNAL_ERROR",
            "Contexto de usuario inválido",
            500,
        )

    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        # 5. Iniciar transacción y bloquear la fila
        conn.run("BEGIN")
        transaction_started = True

        rows = conn.run(
            """
            SELECT status
            FROM service_requests
            WHERE id = :request_id
            FOR UPDATE
            """,
            request_id=request_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "NOT_FOUND",
                "Solicitud no encontrada",
                404,
            )

        current_status = rows[0][0]

        # 6. Verificar transición permitida
        allowed = REQUEST_TRANSITIONS.get(
            current_status, set()
        )

        if new_status not in allowed:
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "CONFLICT",
                "Transición de estado no permitida",
                409,
            )

        # 7. Solo admin puede aprobar o rechazar
        if new_status in ("approved", "rejected") and role != "admin":
            conn.run("ROLLBACK")
            transaction_started = False

            return api_error(
                "FORBIDDEN",
                "Solo un administrador puede aprobar o rechazar",
                403,
            )

        # 8. Actualizar estado
        # fulfilled_at se fija únicamente al completar
        conn.run(
            """
            UPDATE service_requests
            SET
                status = :status,
                fulfilled_at = CASE
                    WHEN CAST(:status AS varchar) = 'fulfilled'
                    THEN CURRENT_TIMESTAMP
                    ELSE fulfilled_at
                END
            WHERE id = :request_id
            """,
            status=new_status,
            request_id=request_id,
        )

        # 9. Registrar aprobación o rechazo
        if new_status in ("approved", "rejected"):
            conn.run(
                """
                INSERT INTO request_approvals (
                    request_id,
                    approver_id,
                    decision
                )
                VALUES (
                    :request_id,
                    :approver_id,
                    :decision
                )
                """,
                request_id=request_id,
                approver_id=user_id,
                decision=new_status,
            )

        # 10. Consultar detalle actualizado
        rows = conn.run(
            """
            SELECT
                sr.id,
                sr.key,
                sr.catalog_item_id,
                ci.name AS catalog_item_name,
                sr.form_data,
                sr.status,
                sr.requester_id,
                sr.assignee_id,
                sr.created_at,
                sr.fulfilled_at
            FROM service_requests AS sr
            INNER JOIN catalog_items AS ci
                ON ci.id = sr.catalog_item_id
            WHERE sr.id = :request_id
            """,
            request_id=request_id,
        )

        columns = [
            column["name"]
            for column in conn.columns
        ]

        request_detail = serialize_row(columns, rows[0])

        # 11. Consultar historial de aprobaciones
        approval_rows = conn.run(
            """
            SELECT
                id,
                request_id,
                approver_id,
                decision,
                decided_at
            FROM request_approvals
            WHERE request_id = :request_id
            ORDER BY decided_at ASC, id ASC
            """,
            request_id=request_id,
        )

        approval_columns = [
            column["name"]
            for column in conn.columns
        ]

        request_detail["approvals"] = [
            serialize_row(approval_columns, row)
            for row in approval_rows
        ]

        # 12. Confirmar cambios
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 13. Publicar evento cuando corresponda
    event_type = REQUEST_STATUS_EVENTS.get(new_status)

    if event_type:
        publish(
            event_type=event_type,
            tenant_id=ctx["tenant_id"],
            data={
                "requestId": request_id,
                "key": request_detail["key"],
                "status": new_status,
                "previousStatus": current_status,
                "requesterId": request_detail.get("requester_id"),
                "catalogItemName": request_detail.get("catalog_item_name"),
                "actorId": user_id,
            },
            source="ms-requests",
        )

    # 14. Responder con detalle completo
    return ok({
        "data": request_detail
    })

