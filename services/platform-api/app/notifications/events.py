import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, EmailStr

from app.core.config import settings

log = logging.getLogger(__name__)

class ClusterConnectedEvent(BaseModel):
    event_type: str = "cluster.connected"
    event_id: str
    organization_id: str
    user_id: str
    recipient_email: EmailStr
    cluster_id: str
    cluster_name: str
    occurred_at: datetime

def servicebus_client():
    from azure.servicebus import ServiceBusClient

    if settings.azure_servicebus_connection_string:
        return ServiceBusClient.from_connection_string(settings.azure_servicebus_connection_string)
    if settings.azure_servicebus_fully_qualified_namespace:
        from azure.identity import DefaultAzureCredential

        return ServiceBusClient(settings.azure_servicebus_fully_qualified_namespace, credential=DefaultAzureCredential())
    return None

def publish_cluster_connected_event(event: ClusterConnectedEvent) -> bool:
    client = servicebus_client()
    if client is None:
        log.info("cluster connected email event skipped; Service Bus is not configured")
        return False
    from azure.servicebus import ServiceBusMessage

    body = event.model_dump(mode="json")
    body["occurred_at"] = event.occurred_at.isoformat()
    with client:
        sender = client.get_queue_sender(queue_name=settings.cluster_connected_queue_name)
        with sender:
            sender.send_messages(
                ServiceBusMessage(
                    json.dumps(body, separators=(",", ":")),
                    message_id=event.event_id,
                    content_type="application/json",
                    application_properties={"event_type": event.event_type},
                )
            )
    return True

def build_cluster_connected_event(*, organization_id: Any, user_id: Any, recipient_email: str, cluster_id: Any, cluster_name: str) -> ClusterConnectedEvent:
    return ClusterConnectedEvent(
        event_id=f"cluster-connected-{cluster_id}-{user_id}",
        organization_id=str(organization_id),
        user_id=str(user_id),
        recipient_email=recipient_email,
        cluster_id=str(cluster_id),
        cluster_name=cluster_name,
        occurred_at=datetime.now(timezone.utc),
    )
