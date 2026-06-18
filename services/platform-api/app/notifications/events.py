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


class AlertLimitTriggeredEvent(BaseModel):
    event_type: str = "alert.limit_triggered"
    event_id: str
    organization_id: str
    cluster_id: str
    recipient_email: EmailStr
    cluster_name: str
    alert_limit_id: str
    alert_limit_name: str
    metric_type: str
    metric_label: str
    threshold_value: float
    actual_value: float
    operator: str
    severity: str
    time_window_minutes: int
    dashboard_url: str
    occurred_at: datetime

def servicebus_client():
    from azure.servicebus import ServiceBusClient

    if settings.azure_servicebus_connection_string:
        return ServiceBusClient.from_connection_string(settings.azure_servicebus_connection_string)
    if settings.azure_servicebus_fully_qualified_namespace:
        from azure.identity import DefaultAzureCredential

        return ServiceBusClient(settings.azure_servicebus_fully_qualified_namespace, credential=DefaultAzureCredential())
    return None

def publish_notification_event(event: BaseModel, queue_name: str) -> bool:
    client = servicebus_client()
    if client is None:
        log.info("notification event skipped; Service Bus is not configured")
        return False
    from azure.servicebus import ServiceBusMessage

    body = event.model_dump(mode="json")
    if "occurred_at" in body and isinstance(event.occurred_at, datetime):
        body["occurred_at"] = event.occurred_at.isoformat()
    with client:
        sender = client.get_queue_sender(queue_name=queue_name)
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


def publish_cluster_connected_event(event: ClusterConnectedEvent) -> bool:
    return publish_notification_event(event, settings.cluster_connected_queue_name)


def publish_alert_limit_triggered_event(event: AlertLimitTriggeredEvent) -> bool:
    return publish_notification_event(event, settings.cluster_connected_queue_name)

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


def build_alert_limit_triggered_event(
    *,
    organization_id: Any,
    cluster_id: Any,
    recipient_email: str,
    cluster_name: str,
    alert_limit_id: Any,
    alert_limit_name: str,
    metric_type: str,
    metric_label: str,
    threshold_value: float,
    actual_value: float,
    operator: str,
    severity: str,
    time_window_minutes: int,
    dashboard_url: str,
) -> AlertLimitTriggeredEvent:
    return AlertLimitTriggeredEvent(
        event_id=f"alert-limit-{alert_limit_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        organization_id=str(organization_id),
        cluster_id=str(cluster_id),
        recipient_email=recipient_email,
        cluster_name=cluster_name,
        alert_limit_id=str(alert_limit_id),
        alert_limit_name=alert_limit_name,
        metric_type=metric_type,
        metric_label=metric_label,
        threshold_value=threshold_value,
        actual_value=actual_value,
        operator=operator,
        severity=severity,
        time_window_minutes=time_window_minutes,
        dashboard_url=dashboard_url,
        occurred_at=datetime.now(timezone.utc),
    )
