"""Handlers HTTP de ms-incidents."""

import json
import uuid
from datetime import datetime, timezone

from common.http import ok, tenant_ctx
from common.db import tenant_conn
from common.events import publish


# Matriz D6: prioridad según impacto y urgencia
PRIORITY_MATRIX = {
    "high": {
        "high": "P1",
        "medium": "P2",
        "low": "P3",
    },
    "medium": {
        "high": "P2",
        "medium": "P3",
        "low": "P4",
    },
    "low": {
        "high": "P3",
        "medium": "P4",
        "low": "P4",
    },
}

LEVELS = {"high", "medium", "low"}

ALLOWED_FIELDS = {
    "title",
    "description",
    "impact",
    "urgency",
    "ci_id",
    "team_id",
    "assignee_id",
}


def api_error(code, message, status=400, details=None, context=None):
    """Devuelve errores siguiendo API_CONTRACTS.md."""
    result = {
        "code": code,
        "message": message,
    }

    if details:
        result["details"] = details

    request_id = getattr(context, "aws_request_id", None)
    if request_id:
        result["request_id"] = request_id

    return ok({"error": result}, status)


def serialize_incident(incident):
    """Convierte UUID y fechas al formato JSON del contrato."""
    result = {}

    for key, value in incident.items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)

        elif isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)

            result[key] = (
                value.astimezone(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )

        else:
            result[key] = value

    return result



def listIncidents(event, context):
    ctx = tenant_ctx(event)
    role = ctx["role"]
    user_id = ctx["user_id"]

    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar incidentes",
            403,
            context=context,
        )

    query = event.get("queryStringParameters") or {}

    # 1. Paginación
    try:
        page = int(query.get("page", "1"))
        limit = int(query.get("limit", "20"))
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "page y limit deben ser enteros",
            400,
            context=context,
        )

    if page < 1 or not 1 <= limit <= 100:
        return api_error(
            "VALIDATION_ERROR",
            "page debe ser >= 1 y limit entre 1 y 100",
            400,
            context=context,
        )

    # 2. Ordenamiento
    allowed_sort = {
        "created_at", "priority", "sla_due_at",
        "status", "key",
    }

    sort_by = query.get("sort_by", "created_at")
    sort_order = query.get("sort_order", "desc")

    if sort_by not in allowed_sort:
        return api_error(
            "VALIDATION_ERROR",
            "sort_by inválido",
            400,
            context=context,
        )

    if sort_order not in ("asc", "desc"):
        return api_error(
            "VALIDATION_ERROR",
            "sort_order inválido",
            400,
            context=context,
        )

    conditions = []
    params = {}

    # 3. Seguridad para customers
    if role == "customer":
        conditions.append("reporter_id = :reporter_id")
        params["reporter_id"] = user_id

    # 4. Filtros de valores enumerados
    enum_filters = {
        "status": {
            "new", "in_progress", "on_hold",
            "resolved", "closed",
        },
        "priority": {"P1", "P2", "P3", "P4"},
        "impact": {"high", "medium", "low"},
        "urgency": {"high", "medium", "low"},
        "channel": {"portal", "email", "auto"},
    }

    for field, allowed_values in enum_filters.items():
        value = query.get(field)

        if value is None:
            continue

        values = value.split(",")

        if any(v not in allowed_values for v in values):
            return api_error(
                "VALIDATION_ERROR",
                f"Filtro inválido: {field}",
                400,
                context=context,
            )

        placeholders = []

        for index, value in enumerate(values):
            param_name = f"{field}_{index}"
            placeholders.append(f":{param_name}")
            params[param_name] = value

        conditions.append(
            f"{field} IN ({', '.join(placeholders)})"
        )

    # 5. Filtros UUID
    for field in ("team_id", "ci_id", "problem_id"):
        value = query.get(field)

        if value is None:
            continue

        try:
            params[field] = str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                f"UUID inválido: {field}",
                400,
                context=context,
            )

        conditions.append(f"{field} = :{field}")

    # 6. Colas de agentes
    assignee = query.get("assignee_id")

    if assignee == "none":
        conditions.append("assignee_id IS NULL")

    elif assignee == "me":
        conditions.append("assignee_id = :assignee_id")
        params["assignee_id"] = user_id

    elif assignee is not None:
        try:
            params["assignee_id"] = str(uuid.UUID(assignee))
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                "assignee_id inválido",
                400,
                context=context,
            )

        conditions.append("assignee_id = :assignee_id")

    # 7. Filtro de SLA incumplido
    sla_breached = query.get("sla_breached")

    if sla_breached is not None:
        if sla_breached not in ("true", "false"):
            return api_error(
                "VALIDATION_ERROR",
                "sla_breached debe ser true o false",
                400,
                context=context,
            )

        conditions.append(
            "sla_breached = :sla_breached"
        )
        params["sla_breached"] = (
            sla_breached == "true"
        )

    # 8. Búsqueda por clave o título
    search = query.get("search")

    if search is not None:
        if not 2 <= len(search) <= 100:
            return api_error(
                "VALIDATION_ERROR",
                "search debe tener entre 2 y 100 caracteres",
                400,
                context=context,
            )

        conditions.append(
            "(key ILIKE :search OR title ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    # 9. Construcción de las consultas
    where_sql = (
        " WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    conn = tenant_conn(ctx["schema"])

    # Contar todos los registros que cumplen los filtros
    count_rows = conn.run(
        "SELECT COUNT(*) FROM incidents" + where_sql,
        **params,
    )

    total = count_rows[0][0]

    # Obtener únicamente la página solicitada
    offset = (page - 1) * limit

    sql = (
        "SELECT * FROM incidents"
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

    cols = [c["name"] for c in conn.columns]

    data = [
        serialize_incident(dict(zip(cols, row)))
        for row in rows
    ]

    # 10. Formato IN-01
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



def createIncident(event, context):
    # 1. Obtener el contexto del usuario autenticado
    ctx = tenant_ctx(event)

    role = ctx["role"]
    tenant_id = ctx["tenant_id"]

    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para crear incidentes",
            403,
            context=context,
        )

    # 2. Leer el JSON recibido
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
            context=context,
        )

    if not isinstance(body, dict):
        return api_error(
            "VALIDATION_ERROR",
            "El body debe ser un objeto JSON",
            400,
            context=context,
        )

    # 3. Validar campos según IN-02
    details = []

    for field in body:
        if field not in ALLOWED_FIELDS:
            details.append({
                "field": field,
                "issue": "Campo no permitido",
            })

    title = body.get("title")

    if (
        not isinstance(title, str)
        or not 3 <= len(title.strip()) <= 200
    ):
        details.append({
            "field": "title",
            "issue": "Debe tener entre 3 y 200 caracteres",
        })

    description = body.get("description")

    if description is not None:
        if (
            not isinstance(description, str)
            or len(description) > 5000
        ):
            details.append({
                "field": "description",
                "issue": "Debe ser texto de máximo 5000 caracteres",
            })

    impact = body.get("impact")
    urgency = body.get("urgency")

    if not isinstance(impact, str) or impact not in LEVELS:
        details.append({
            "field": "impact",
            "issue": "Debe ser high, medium o low",
        })

    if not isinstance(urgency, str) or urgency not in LEVELS:
        details.append({
            "field": "urgency",
            "issue": "Debe ser high, medium o low",
        })

    # 4. Validar UUID opcionales
    optional_ids = {}

    for field in ("ci_id", "team_id", "assignee_id"):
        value = body.get(field)

        if value is None:
            optional_ids[field] = None
            continue

        try:
            if not isinstance(value, str):
                raise ValueError("UUID inválido")

            optional_ids[field] = str(uuid.UUID(value))

        except (ValueError, AttributeError):
            details.append({
                "field": field,
                "issue": "Debe ser un UUID válido",
            })

    # 5. Restricciones para customer
    if role == "customer":
        for field in ("team_id", "assignee_id"):
            if field in body:
                details.append({
                    "field": field,
                    "issue": "No permitido para customer",
                })

    if details:
        return api_error(
            "VALIDATION_ERROR",
            "La solicitud tiene campos inválidos",
            400,
            details=details,
            context=context,
        )

    # 6. Obtener reporter_id del authorizer
    try:
        reporter_id = str(uuid.UUID(ctx["user_id"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        return api_error(
            "INTERNAL_ERROR",
            "Contexto de usuario inválido",
            500,
            context=context,
        )

    # 7. Calcular prioridad con matriz D6
    priority = PRIORITY_MATRIX[impact][urgency]

    # 8. Conectarse al schema del tenant
    conn = tenant_conn(ctx["schema"])

    # 9. Buscar la política SLA correspondiente
    policies = conn.run(
        """
        SELECT id, resolution_minutes
        FROM sla_policies
        WHERE priority = :priority
        ORDER BY id
        LIMIT 1
        """,
        priority=priority,
    )

    if not policies:
        return api_error(
            "INTERNAL_ERROR",
            "No existe una política SLA para la prioridad",
            500,
            context=context,
        )

    sla_policy_id = policies[0][0]
    resolution_minutes = policies[0][1]

    # 10. Crear incidente dentro de una transacción
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # Evitar que dos creaciones simultáneas generen
        # la misma clave dentro del tenant.
        conn.run(
            """
            SELECT pg_advisory_xact_lock(
                hashtext(current_schema() || ':incident_key')
            )
            """
        )

        # Obtener el último número de incidente
        rows = conn.run(
            """
            SELECT COALESCE(
                MAX(SUBSTRING(key FROM 5)::integer),
                0
            )
            FROM incidents
            WHERE key ~ '^INC-[0-9]{6}$'
            """
        )

        next_number = rows[0][0] + 1

        if next_number > 999999:
            raise RuntimeError(
                "Se agotó el rango de claves de incidentes"
            )

        incident_key = f"INC-{next_number:06d}"

        # 11. Insertar incidente y calcular SLA
        rows = conn.run(
            """
            INSERT INTO incidents (
                key,
                title,
                description,
                status,
                impact,
                urgency,
                priority,
                sla_policy_id,
                sla_due_at,
                sla_breached,
                reporter_id,
                assignee_id,
                team_id,
                ci_id,
                channel,
                created_at
            )
            VALUES (
                :key,
                :title,
                :description,
                'new',
                :impact,
                :urgency,
                :priority,
                :sla_policy_id,
                (
                    CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                    + :resolution_minutes * INTERVAL '1 minute'
                ),
                FALSE,
                :reporter_id,
                :assignee_id,
                :team_id,
                :ci_id,
                'portal',
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            )
            RETURNING *
            """,
            key=incident_key,
            title=title.strip(),
            description=description,
            impact=impact,
            urgency=urgency,
            priority=priority,
            sla_policy_id=sla_policy_id,
            resolution_minutes=resolution_minutes,
            reporter_id=reporter_id,
            assignee_id=optional_ids["assignee_id"],
            team_id=optional_ids["team_id"],
            ci_id=optional_ids["ci_id"],
        )

        cols = [c["name"] for c in conn.columns]
        incident = dict(zip(cols, rows[0]))

        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 12. Publicar IncidentCreated usando el helper común
    publish(
        event_type="IncidentCreated",
        tenant_id=tenant_id,
        data={
            "incidentId": str(incident["id"]),
            "key": incident["key"],
            "title": incident["title"],
            "priority": incident["priority"],
            "ciId": (
                str(incident["ci_id"])
                if incident["ci_id"] else None
            ),
            "teamId": (
                str(incident["team_id"])
                if incident["team_id"] else None
            ),
            "assigneeId": (
                str(incident["assignee_id"])
                if incident["assignee_id"] else None
            ),
            "reporterId": str(incident["reporter_id"]),
            "channel": incident["channel"],
            "actorId": reporter_id,
        },
        source="ms-incidents",
    )

    # 13. Responder con el contrato oficial
    return ok({
        "data": serialize_incident(incident)
    }, 201)


def getIncident(event, context):
    """IN-03: GET /incidents/{id}."""

    # 1. Obtener tenant y usuario autenticado
    ctx = tenant_ctx(event)

    role = ctx["role"]
    user_id = ctx["user_id"]

    # 2. Comprobar permisos
    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para consultar incidentes",
            403,
            context=context,
        )

    # 3. Obtener ID de la ruta
    path_params = event.get("pathParameters") or {}
    incident_id = path_params.get("id")

    # 4. Validar que sea UUID
    try:
        incident_id = str(uuid.UUID(incident_id))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "El ID del incidente debe ser un UUID válido",
            400,
            context=context,
        )

    # 5. Conectar al schema del tenant
    conn = tenant_conn(ctx["schema"])

    # 6. Construir consulta según el rol
    params = {"incident_id": incident_id}

    sql = """
        SELECT *
        FROM incidents
        WHERE id = :incident_id
    """

    # Customer solo puede consultar incidentes propios
    if role == "customer":
        sql += " AND reporter_id = :reporter_id"
        params["reporter_id"] = user_id

    # 7. Consultar incidente
    rows = conn.run(sql, **params)

    # 8. Incidente inexistente o sin acceso
    if not rows:
        return api_error(
            "NOT_FOUND",
            "Incidente no encontrado",
            404,
            context=context,
        )

    # 9. Convertir resultado PostgreSQL a diccionario
    cols = [column["name"] for column in conn.columns]

    incident = dict(zip(cols, rows[0]))

    # 10. Responder con el contrato IN-03
    return ok({
        "data": serialize_incident(incident)
    })

def updateIncident(event, context):
    """IN-04: PATCH /incidents/{id}."""

    ctx = tenant_ctx(event)
    role = ctx["role"]

    # 1. Solo administradores y agentes
    if role not in ("admin", "agent"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para actualizar incidentes",
            403,
            context=context,
        )

    # 2. Validar ID de la ruta
    try:
        incident_id = str(uuid.UUID(
            (event.get("pathParameters") or {}).get("id")
        ))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "ID de incidente inválido",
            400,
            context=context,
        )

    # 3. Leer y validar JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
            context=context,
        )

    if not isinstance(body, dict) or not body:
        return api_error(
            "VALIDATION_ERROR",
            "Debes enviar al menos un campo",
            400,
            context=context,
        )

    allowed_fields = {
        "title", "description", "impact", "urgency",
        "ci_id", "team_id", "assignee_id", "problem_id",
    }

    unknown = set(body) - allowed_fields

    if unknown:
        return api_error(
            "VALIDATION_ERROR",
            "Campos no permitidos: " + ", ".join(sorted(unknown)),
            400,
            context=context,
        )

    # 4. Validar título
    if "title" in body:
        value = body["title"]
        if not isinstance(value, str) or not 3 <= len(value) <= 200:
            return api_error(
                "VALIDATION_ERROR",
                "title debe tener entre 3 y 200 caracteres",
                400,
                context=context,
            )

    # 5. Validar descripción
    if "description" in body:
        value = body["description"]
        if not isinstance(value, str) or len(value) > 5000:
            return api_error(
                "VALIDATION_ERROR",
                "description debe ser texto de máximo 5000 caracteres",
                400,
                context=context,
            )

    # 6. Validar impacto y urgencia
    for field in ("impact", "urgency"):
        if field in body and body[field] not in (
            "high", "medium", "low"
        ):
            return api_error(
                "VALIDATION_ERROR",
                f"Valor inválido para {field}",
                400,
                context=context,
            )

    # 7. Validar UUID opcionales
    for field in (
        "ci_id", "team_id", "assignee_id", "problem_id"
    ):
        if field not in body or body[field] is None:
            continue

        try:
            body[field] = str(uuid.UUID(body[field]))
        except (ValueError, TypeError, AttributeError):
            return api_error(
                "VALIDATION_ERROR",
                f"UUID inválido: {field}",
                400,
                context=context,
            )

    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        # 8. Iniciar transacción
        conn.run("BEGIN")
        transaction_started = True

        # 9. Consultar y bloquear el incidente
        rows = conn.run(
            """
            SELECT *
            FROM incidents
            WHERE id = :incident_id
            FOR UPDATE
            """,
            incident_id=incident_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False
            return api_error(
                "NOT_FOUND",
                "Incidente no encontrado",
                404,
                context=context,
            )

        cols = [c["name"] for c in conn.columns]
        current = dict(zip(cols, rows[0]))

        # 10. No editar incidentes cerrados
        if current["status"] == "closed":
            conn.run("ROLLBACK")
            transaction_started = False
            return api_error(
                "CONFLICT",
                "No se puede editar un incidente cerrado",
                409,
                context=context,
            )

        updates = dict(body)

        # 11. Recalcular prioridad y SLA cuando
        # cambie impacto o urgencia
        priority_changed = (
            ("impact" in body and body["impact"] != current["impact"])
            or
            ("urgency" in body and body["urgency"] != current["urgency"])
        )

        if priority_changed:
            impact = updates.get("impact", current["impact"])
            urgency = updates.get("urgency", current["urgency"])

            matrix = {
                "high": {
                    "high": "P1",
                    "medium": "P2",
                    "low": "P3",
                },
                "medium": {
                    "high": "P2",
                    "medium": "P3",
                    "low": "P4",
                },
                "low": {
                    "high": "P3",
                    "medium": "P4",
                    "low": "P4",
                },
            }

            if (
                impact not in matrix
                or urgency not in matrix[impact]
            ):
                conn.run("ROLLBACK")
                transaction_started = False
                return api_error(
                    "VALIDATION_ERROR",
                    "Impacto o urgencia inválidos",
                    400,
                    context=context,
                )

            priority = matrix[impact][urgency]

            policies = conn.run(
                """
                SELECT id, resolution_minutes
                FROM sla_policies
                WHERE priority = :priority
                ORDER BY id
                LIMIT 1
                """,
                priority=priority,
            )

            if not policies:
                conn.run("ROLLBACK")
                transaction_started = False
                return api_error(
                    "SLA_NOT_CONFIGURED",
                    f"No existe política SLA para {priority}",
                    500,
                    context=context,
                )

            updates["priority"] = priority
            updates["sla_policy_id"] = policies[0][0]
            updates["resolution_minutes"] = policies[0][1]

        # 12. Construir actualización parametrizada
        # Los nombres de columnas vienen de una lista permitida,
        # no directamente del usuario.
        assignments = []

        for field in updates:
            if field == "resolution_minutes":
                continue

            assignments.append(f"{field} = :{field}")

        if priority_changed:
            assignments.append(
                "sla_due_at = ("
                "CURRENT_TIMESTAMP AT TIME ZONE 'UTC' "
                "+ :resolution_minutes * INTERVAL '1 minute'"
                ")"
            )

        sql = (
            "UPDATE incidents SET "
            + ", ".join(assignments)
            + " WHERE id = :incident_id RETURNING *"
        )

        rows = conn.run(
            sql,
            incident_id=incident_id,
            **updates,
        )

        cols = [c["name"] for c in conn.columns]
        updated = dict(zip(cols, rows[0]))

        # 13. Confirmar cambios
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 14. Publicar evento después del COMMIT
    publish(
        event_type="IncidentUpdated",
        tenant_id=ctx["tenant_id"],
        data={
            "incidentId": str(updated["id"]),
            "key": updated["key"],
            "status": updated["status"],
            "priority": updated["priority"],
            "assigneeId": (
                str(updated["assignee_id"])
                if updated.get("assignee_id")
                else None
            ),
            "teamId": (
                str(updated["team_id"])
                if updated.get("team_id")
                else None
            ),
            "actorId": ctx["user_id"],
            "changedFields": list(body.keys()),
        },
        source="ms-incidents",
    )

    # 15. Responder con el incidente actualizado
    return ok({
        "data": serialize_incident(updated)
    })


def changeIncidentStatus(event, context):
    """IN-05: PUT /incidents/{id}/status."""

    ctx = tenant_ctx(event)
    role = ctx["role"]
    user_id = ctx["user_id"]

    # 1. Validar rol
    if role not in ("admin", "agent", "customer"):
        return api_error(
            "FORBIDDEN",
            "No tienes permiso para cambiar estados",
            403,
            context=context,
        )

    # 2. Validar ID
    try:
        incident_id = str(uuid.UUID(
            (event.get("pathParameters") or {}).get("id")
        ))
    except (ValueError, TypeError, AttributeError):
        return api_error(
            "VALIDATION_ERROR",
            "ID de incidente inválido",
            400,
            context=context,
        )

    # 3. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return api_error(
            "VALIDATION_ERROR",
            "JSON inválido",
            400,
            context=context,
        )

    if not isinstance(body, dict):
        return api_error(
            "VALIDATION_ERROR",
            "El body debe ser un objeto JSON",
            400,
            context=context,
        )

    if set(body) - {"status", "comment"}:
        return api_error(
            "VALIDATION_ERROR",
            "El body contiene campos no permitidos",
            400,
            context=context,
        )

    new_status = body.get("status")
    comment = body.get("comment")

    valid_statuses = {
        "new", "in_progress", "on_hold",
        "resolved", "closed",
    }

    if (
        not isinstance(new_status, str)
        or new_status not in valid_statuses
    ):
        return api_error(
            "VALIDATION_ERROR",
            "Estado inválido",
            400,
            context=context,
        )

    if comment is not None:
        if (
            not isinstance(comment, str)
            or not 1 <= len(comment.strip()) <= 5000
        ):
            return api_error(
                "VALIDATION_ERROR",
                "comment debe tener entre 1 y 5000 caracteres",
                400,
                context=context,
            )

    # 4. Definir las transiciones del contrato
    transitions = {
        "new": {"in_progress", "on_hold", "resolved"},
        "in_progress": {"on_hold", "resolved"},
        "on_hold": {"in_progress", "resolved"},
        "resolved": {"closed", "in_progress"},
        "closed": set(),
    }

    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 5. Consultar y bloquear el incidente
        params = {"incident_id": incident_id}

        sql = """
            SELECT *
            FROM incidents
            WHERE id = :incident_id
        """

        # No revelar incidentes ajenos a customers
        if role == "customer":
            sql += " AND reporter_id = :reporter_id"
            params["reporter_id"] = user_id

        sql += " FOR UPDATE"

        rows = conn.run(sql, **params)

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False
            return api_error(
                "NOT_FOUND",
                "Incidente no encontrado",
                404,
                context=context,
            )

        cols = [c["name"] for c in conn.columns]
        incident = dict(zip(cols, rows[0]))

        old_status = incident["status"]

        # 6. Permisos específicos de customer
        if role == "customer":
            allowed_customer = (
                old_status == "resolved"
                and new_status in {"closed", "in_progress"}
            )

            if not allowed_customer:
                conn.run("ROLLBACK")
                transaction_started = False
                return api_error(
                    "FORBIDDEN",
                    "No tienes permiso para esta transición",
                    403,
                    context=context,
                )

        # 7. Validar transición
        if new_status not in transitions.get(old_status, set()):
            conn.run("ROLLBACK")
            transaction_started = False
            return api_error(
                "INVALID_STATUS_TRANSITION",
                "Transición de estado no permitida",
                409,
                context=context,
            )

        # 8. Comentario obligatorio al resolver
        if new_status == "resolved" and comment is None:
            conn.run("ROLLBACK")
            transaction_started = False
            return api_error(
                "VALIDATION_ERROR",
                "comment es obligatorio al resolver",
                400,
                context=context,
            )

        # 9. Actualizar estado y fecha de resolución
        if new_status == "resolved":
            resolved_sql = (
                "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'"
            )
        elif old_status == "resolved" and new_status == "in_progress":
            resolved_sql = "NULL"
        else:
            resolved_sql = "resolved_at"

        rows = conn.run(
            f"""
            UPDATE incidents
            SET status = :new_status,
                resolved_at = {resolved_sql}
            WHERE id = :incident_id
            RETURNING *
            """,
            new_status=new_status,
            incident_id=incident_id,
        )

        cols = [c["name"] for c in conn.columns]
        updated = dict(zip(cols, rows[0]))

        # 10. Registrar historial de transición
        # Requiere migración de incident_events.
        conn.run(
            """
            INSERT INTO incident_events (
                incident_id,
                actor_id,
                old_status,
                new_status
            )
            VALUES (
                :incident_id,
                :actor_id,
                :old_status,
                :new_status
            )
            """,
            incident_id=incident_id,
            actor_id=user_id,
            old_status=old_status,
            new_status=new_status,
        )

        # 11. Guardar comentario público, si existe
        if comment is not None:
            conn.run(
                """
                INSERT INTO incident_comments (
                    incident_id,
                    author_id,
                    body,
                    internal
                )
                VALUES (
                    :incident_id,
                    :author_id,
                    :body,
                    FALSE
                )
                """,
                incident_id=incident_id,
                author_id=user_id,
                body=comment.strip(),
            )

        # 12. Confirmar transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 13. Publicar eventos después del COMMIT
    event_data = {
        "incidentId": str(updated["id"]),
        "key": updated["key"],
        "status": new_status,
        "previousStatus": old_status,
        "priority": updated["priority"],
        "reporterId": (
            str(updated["reporter_id"])
            if updated.get("reporter_id") else None
        ),
        "assigneeId": (
            str(updated["assignee_id"])
            if updated.get("assignee_id") else None
        ),
        "actorId": user_id,
    }

    publish(
        event_type="IncidentUpdated",
        tenant_id=ctx["tenant_id"],
        data=event_data,
        source="ms-incidents",
    )

    if new_status == "resolved":
        publish(
            event_type="IncidentResolved",
            tenant_id=ctx["tenant_id"],
            data=event_data,
            source="ms-incidents",
        )

    # 14. Respuesta IN-05
    return ok({
        "data": serialize_incident(updated)
    })
