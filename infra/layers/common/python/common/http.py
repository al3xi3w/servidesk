import json


def tenant_ctx(event):
    """Lee tenant_id, schema, role y user_id que dejó el Lambda Authorizer."""
    return event["requestContext"]["authorizer"]["lambda"]


def ok(body, status=200):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def error(message, status=400):
    return ok({"error": message}, status)
