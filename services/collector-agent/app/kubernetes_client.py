import asyncio
import logging
from typing import Any
from kubernetes import client, config
from kubernetes.client import ApiException
from app.config import settings
from app.models import AgentState
from app.sender import post_with_retry

log = logging.getLogger(__name__)

def load_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

def sanitize(obj: Any) -> Any:
    data = client.ApiClient().sanitize_for_serialization(obj)
    if isinstance(data, dict):
        data.pop("managedFields", None)
        if data.get("kind") == "Secret":
            return {"metadata": data.get("metadata", {}), "type": "redacted"}
    return data

def collect_snapshot() -> dict[str, Any]:
    load_config()
    core = client.CoreV1Api(); apps = client.AppsV1Api(); batch = client.BatchV1Api(); networking = client.NetworkingV1Api()
    snapshot: dict[str, Any] = {}
    snapshot["pods"] = [sanitize(i) for i in core.list_pod_for_all_namespaces(watch=False).items]
    snapshot["nodes"] = [sanitize(i) for i in core.list_node(watch=False).items]
    snapshot["services"] = [sanitize(i) for i in core.list_service_for_all_namespaces(watch=False).items]
    snapshot["persistentvolumeclaims"] = [sanitize(i) for i in core.list_persistent_volume_claim_for_all_namespaces(watch=False).items]
    snapshot["namespaces"] = [sanitize(i) for i in core.list_namespace(watch=False).items]
    snapshot["deployments"] = [sanitize(i) for i in apps.list_deployment_for_all_namespaces(watch=False).items]
    snapshot["daemonsets"] = [sanitize(i) for i in apps.list_daemon_set_for_all_namespaces(watch=False).items]
    snapshot["statefulsets"] = [sanitize(i) for i in apps.list_stateful_set_for_all_namespaces(watch=False).items]
    snapshot["replicasets"] = [sanitize(i) for i in apps.list_replica_set_for_all_namespaces(watch=False).items]
    snapshot["jobs"] = [sanitize(i) for i in batch.list_job_for_all_namespaces(watch=False).items]
    snapshot["cronjobs"] = [sanitize(i) for i in batch.list_cron_job_for_all_namespaces(watch=False).items]
    try:
        snapshot["ingresses"] = [sanitize(i) for i in networking.list_ingress_for_all_namespaces(watch=False).items]
    except ApiException as exc:
        log.warning("ingress collection skipped: %s", exc)
        snapshot["ingresses"] = []
    return snapshot

def collect_events() -> list[dict[str, Any]]:
    load_config()
    core = client.CoreV1Api()
    return [sanitize(i) for i in core.list_event_for_all_namespaces(watch=False).items]

async def snapshot_loop(state: AgentState) -> None:
    while True:
        try:
            snapshot = await asyncio.to_thread(collect_snapshot)
            await post_with_retry(state, "/api/ingest/snapshot", {"snapshot_type": "full", "snapshot": snapshot})
            events = await asyncio.to_thread(collect_events)
            await post_with_retry(state, "/api/ingest/events", {"events": events})
        except Exception as exc:
            log.error("snapshot/events collection failed: %s", exc)
        await asyncio.sleep(settings.clusterwatch_snapshot_interval_seconds)
