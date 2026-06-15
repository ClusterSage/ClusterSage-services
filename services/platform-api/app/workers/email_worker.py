import json
import logging
import time
from typing import Any

from azure.servicebus import ServiceBusReceivedMessage

from app.core.config import settings
from app.notifications.events import servicebus_client
from app.notifications.templates import cluster_connected_body, cluster_connected_subject

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def message_body(message: ServiceBusReceivedMessage) -> dict[str, Any]:
    raw = b"".join(part for part in message.body)
    return json.loads(raw.decode("utf-8"))

def email_client():
    from azure.communication.email import EmailClient

    if settings.azure_communication_email_connection_string:
        return EmailClient.from_connection_string(settings.azure_communication_email_connection_string)
    if settings.azure_communication_email_endpoint:
        from azure.identity import DefaultAzureCredential

        return EmailClient(settings.azure_communication_email_endpoint, DefaultAzureCredential())
    return None

def send_cluster_connected_email(event: dict[str, Any]) -> None:
    client = email_client()
    if client is None:
        raise RuntimeError("Azure Communication Services Email is not configured")
    if not settings.email_sender_address:
        raise RuntimeError("EMAIL_SENDER_ADDRESS is required")
    message = {
        "senderAddress": settings.email_sender_address,
        "recipients": {"to": [{"address": event["recipient_email"]}]},
        "content": {
            "subject": cluster_connected_subject(),
            "plainText": cluster_connected_body(event["cluster_name"]),
        },
    }
    poller = client.begin_send(message)
    poller.result()

def run() -> None:
    client = servicebus_client()
    if client is None:
        raise RuntimeError("Service Bus is not configured")
    with client:
        receiver = client.get_queue_receiver(queue_name=settings.cluster_connected_queue_name, max_wait_time=settings.email_worker_poll_seconds)
        with receiver:
            log.info("email worker listening on queue %s", settings.cluster_connected_queue_name)
            while True:
                messages = receiver.receive_messages(max_message_count=10, max_wait_time=settings.email_worker_poll_seconds)
                if not messages:
                    time.sleep(1)
                    continue
                for message in messages:
                    try:
                        event = message_body(message)
                        if event.get("event_type") != "cluster.connected":
                            receiver.complete_message(message)
                            continue
                        send_cluster_connected_email(event)
                        receiver.complete_message(message)
                        log.info("cluster connected email sent for cluster_id=%s", event.get("cluster_id"))
                    except Exception as exc:
                        log.exception("email worker failed to process message: %s", exc)
                        receiver.abandon_message(message)

if __name__ == "__main__":
    run()
