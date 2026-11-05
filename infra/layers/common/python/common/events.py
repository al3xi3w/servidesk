"""Publica eventos de dominio en el tópico SNS compartido."""
import datetime
import json
import os
import uuid

import boto3

_sns = boto3.client("sns")


def publish(event_type: str, tenant_id: str, data: dict, source: str):
    message = {
        "eventId": str(uuid.uuid4()),
        "eventType": event_type,
        "tenantId": tenant_id,
        "occurredAt": datetime.datetime.utcnow().isoformat() + "Z",
        "source": source,
        "data": data,
    }
    _sns.publish(
        TopicArn=os.environ["EVENTS_TOPIC_ARN"],
        Message=json.dumps(message, default=str),
        MessageAttributes={
            "eventType": {"DataType": "String", "StringValue": event_type},
            "tenantId": {"DataType": "String", "StringValue": tenant_id},
        },
    )
