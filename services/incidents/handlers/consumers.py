"""Consumidores SQS de ms-incidents."""
import json

from common.db import tenant_conn


def on_ci_status_changed(event, context):
    for record in event["Records"]:
        msg = json.loads(record["body"])  # RawMessageDelivery: el body es el evento
        if msg["data"].get("status") != "down":
            continue
        conn = tenant_conn(f"tenant_{msg['tenantId']}")
        # TODO: crear incidente P2 con channel='auto' para msg["data"]["ciId"]
