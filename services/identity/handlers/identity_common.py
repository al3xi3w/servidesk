"""Utilidades compartidas por los handlers de ms-identity.

Respuestas, validación y paginación según docs/API_CONTRACTS.md (§4 y §5) y
hash de contraseñas PBKDF2-SHA256 (decisión D7: solo hashlib, sin binarios en el layer).
"""

import base64
import datetime
import functools
import hashlib
import hmac
import json
import re
import secrets
import traceback
import uuid

from common.http import ok

ROLES = ("admin", "agent", "customer")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TENANT_CODE_RE = re.compile(r"^[a-z0-9_]{2,30}$")

USER_FIELDS = ("id", "email", "full_name", "role", "active", "created_at")
USER_COLUMNS = ", ".join(USER_FIELDS)

PBKDF2_ITERATIONS = 310_000
TOKEN_TTL_SECONDS = 3600


# ------------------------------------------------------------------ Serialización


def json_value(value):
    """Convierte valores de PostgreSQL a JSON según el contrato (UUID texto, fechas ISO UTC con Z)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=0).isoformat() + "Z"
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def row_to_dict(fields, row):
    return {field: json_value(value) for field, value in zip(fields, row)}


def user_from_row(row):
    return row_to_dict(USER_FIELDS, row)


# ------------------------------------------------------------------ Respuestas


def request_id_of(context):
    return getattr(context, "aws_request_id", None)


def api_error(code, message, status=400, details=None, context=None):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    request_id = request_id_of(context)
    if request_id:
        body["request_id"] = request_id
    return ok({"error": body}, status)


def validation_error(details, context=None):
    return api_error(
        "VALIDATION_ERROR",
        "La solicitud tiene campos inválidos",
        400,
        details,
        context,
    )


def forbidden(context=None):
    return api_error("FORBIDDEN", "No tienes permiso para esta operación", 403, context=context)


def not_found(resource, context=None):
    return api_error("NOT_FOUND", f"{resource} no encontrado", 404, context=context)


def no_content():
    return {"statusCode": 204, "headers": {"Content-Type": "application/json"}}


def handle_errors(fn):
    """Convierte cualquier excepción no controlada en 500 INTERNAL_ERROR con request_id."""

    @functools.wraps(fn)
    def wrapper(event, context):
        try:
            return fn(event, context)
        except Exception:  # noqa: BLE001 - la Lambda nunca debe filtrar trazas al cliente
            traceback.print_exc()
            return api_error("INTERNAL_ERROR", "Error interno", 500, context=context)

    return wrapper


# ------------------------------------------------------------------ Entrada


def parse_body(event, context=None, required=True):
    """Devuelve (dict, None) o (None, respuesta de error)."""
    raw = event.get("body")
    if raw in (None, ""):
        if required:
            return None, validation_error([{"field": "body", "issue": "El cuerpo es obligatorio"}], context)
        return {}, None
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None, validation_error([{"field": "body", "issue": "Cuerpo inválido"}], context)
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return None, validation_error([{"field": "body", "issue": "JSON inválido"}], context)
    if not isinstance(body, dict):
        return None, validation_error([{"field": "body", "issue": "Debe ser un objeto JSON"}], context)
    return body, None


def unknown_fields(body, allowed):
    """Decisión D12: un campo no definido produce 400."""
    return [{"field": key, "issue": "Campo no permitido"} for key in body if key not in allowed]


def query_params(event):
    return event.get("queryStringParameters") or {}


def path_param(event, name):
    return (event.get("pathParameters") or {}).get(name)


def is_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def split_csv(value):
    return [part.strip() for part in str(value).split(",") if part.strip()]


def like_pattern(text):
    """Patrón ILIKE con % y _ escapados (se usa con ESCAPE '\\')."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def has_role(ctx, *roles):
    return ctx.get("role") in roles


def parse_pagination(query, sortable, default_sort, default_order="desc"):
    """Valida page, limit, sort_by y sort_order (§5). Devuelve (dict, errores)."""
    errors = []
    result = {"page": 1, "limit": 20, "sort_by": default_sort, "sort_order": default_order}

    if query.get("page") not in (None, ""):
        try:
            result["page"] = int(query["page"])
            if result["page"] < 1:
                raise ValueError
        except ValueError:
            errors.append({"field": "page", "issue": "Debe ser un entero mayor o igual a 1"})

    if query.get("limit") not in (None, ""):
        try:
            result["limit"] = int(query["limit"])
            if not 1 <= result["limit"] <= 100:
                raise ValueError
        except ValueError:
            errors.append({"field": "limit", "issue": "Debe ser un entero entre 1 y 100"})

    if query.get("sort_by") not in (None, ""):
        if query["sort_by"] not in sortable:
            errors.append({"field": "sort_by", "issue": f"Valores permitidos: {', '.join(sortable)}"})
        else:
            result["sort_by"] = query["sort_by"]

    if query.get("sort_order") not in (None, ""):
        if query["sort_order"] not in ("asc", "desc"):
            errors.append({"field": "sort_order", "issue": "Valores permitidos: asc, desc"})
        else:
            result["sort_order"] = query["sort_order"]

    return result, errors


def page_meta(page, limit, total):
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": (total + limit - 1) // limit if total else 0,
    }


def validate_search(query, errors):
    search = query.get("search")
    if search in (None, ""):
        return None
    search = search.strip()
    if not 2 <= len(search) <= 100:
        errors.append({"field": "search", "issue": "Debe tener entre 2 y 100 caracteres"})
        return None
    return search


# ------------------------------------------------------------------ Contraseñas


def hash_password(password, iterations=PBKDF2_ITERATIONS, salt=None):
    """Formato: pbkdf2_sha256$<iteraciones>$<salt b64>$<hash b64>."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password, stored):
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(digest, expected)


@functools.lru_cache(maxsize=1)
def dummy_password_hash():
    """Hash de relleno: se verifica contra él cuando el tenant o el usuario no existen,
    para que el tiempo de respuesta no revele cuál de los datos falló."""
    return hash_password("servidesk-dummy-password", salt=b"servidesk-dummy!")


def is_unique_violation(exc):
    """pg8000 incluye el SQLSTATE en los argumentos de la excepción (23505 = unique_violation)."""
    return "23505" in str(exc)


def validate_text(body, field, min_len, max_len, errors, required=True):
    if field not in body:
        if required:
            errors.append({"field": field, "issue": "Es obligatorio"})
        return None
    value = body[field]
    if not isinstance(value, str) or not min_len <= len(value.strip()) <= max_len:
        errors.append({"field": field, "issue": f"Debe tener entre {min_len} y {max_len} caracteres"})
        return None
    return value.strip()


def validate_email(body, errors, field="email"):
    value = body.get(field)
    if not isinstance(value, str):
        errors.append({"field": field, "issue": "Es obligatorio"})
        return None
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_RE.match(value):
        errors.append({"field": field, "issue": "Formato de email inválido"})
        return None
    return value


def validate_password(body, errors, field="password", required=True):
    if field not in body:
        if required:
            errors.append({"field": field, "issue": "Es obligatorio"})
        return None
    value = body[field]
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        errors.append({"field": field, "issue": "Debe tener entre 8 y 128 caracteres"})
        return None
    return value
