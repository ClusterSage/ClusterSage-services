import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from kubernetes import client
from kubernetes.client import ApiException

from app.config import settings
from app.models import AgentState
from app.sender import post_with_retry
from app.kubernetes_client import load_config

log = logging.getLogger(__name__)


def parse_cpu_to_mcores(raw: str) -> float:
    if raw.endswith("n"):
        return float(raw[:-1]) / 1_000_000
    if raw.endswith("u"):
        return float(raw[:-1]) / 1000
    if raw.endswith("m"):
        return float(raw[:-1])
    return float(raw) * 1000


def parse_memory_to_bytes(raw: str) -> float:
    suffixes = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "Pi": 1024**5,
        "Ei": 1024**6,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
        "P": 1000**5,
        "E": 1000**6,
    }
    for suffix, multiplier in suffixes.items():
        if raw.endswith(suffix):
            return float(raw[: -len(suffix)]) * multiplier
    return float(raw)


def pod_metric_samples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in payload.get("items", []) or []:
        metadata = item.get("metadata") or {}
        namespace = metadata.get("namespace")
        pod_name = metadata.get("name")
        if not namespace or not pod_name:
            continue
        node_name = (item.get("metadata") or {}).get("labels", {}).get("kubernetes.io/hostname")
        cpu_total = 0.0
        memory_total = 0.0
        for container in item.get("containers", []) or []:
            usage = container.get("usage") or {}
            cpu_total += parse_cpu_to_mcores(str(usage.get("cpu", "0")))
            memory_total += parse_memory_to_bytes(str(usage.get("memory", "0")))
        samples.append(
            {
                "scope": "pod",
                "namespace": namespace,
                "resource_kind": "Pod",
                "resource_name": pod_name,
                "node_name": node_name,
                "metric_name": "cpu_mcores",
                "unit": "mcores",
                "value": cpu_total,
            }
        )
        samples.append(
            {
                "scope": "pod",
                "namespace": namespace,
                "resource_kind": "Pod",
                "resource_name": pod_name,
                "node_name": node_name,
                "metric_name": "memory_bytes",
                "unit": "bytes",
                "value": memory_total,
            }
        )
    return samples


def node_metric_samples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in payload.get("items", []) or []:
        metadata = item.get("metadata") or {}
        name = metadata.get("name")
        if not name:
            continue
        usage = item.get("usage") or {}
        samples.append(
            {
                "scope": "node",
                "namespace": None,
                "resource_kind": "Node",
                "resource_name": name,
                "node_name": name,
                "metric_name": "cpu_mcores",
                "unit": "mcores",
                "value": parse_cpu_to_mcores(str(usage.get("cpu", "0"))),
            }
        )
        samples.append(
            {
                "scope": "node",
                "namespace": None,
                "resource_kind": "Node",
                "resource_name": name,
                "node_name": name,
                "metric_name": "memory_bytes",
                "unit": "bytes",
                "value": parse_memory_to_bytes(str(usage.get("memory", "0"))),
            }
        )
    return samples


def collect_metrics_samples() -> list[dict[str, Any]]:
    load_config()
    custom_api = client.CustomObjectsApi()
    pod_metrics = custom_api.list_cluster_custom_object(group="metrics.k8s.io", version="v1beta1", plural="pods")
    node_metrics = custom_api.list_cluster_custom_object(group="metrics.k8s.io", version="v1beta1", plural="nodes")
    return pod_metric_samples(pod_metrics) + node_metric_samples(node_metrics)


async def metrics_loop(state: AgentState) -> None:
    if not settings.clusterwatch_metrics_enabled:
        log.info("metrics collection disabled by configuration")
        return
    while True:
        try:
            samples = await asyncio.to_thread(collect_metrics_samples)
            await post_with_retry(
                state,
                "/api/ingest/metrics",
                {
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "samples": samples,
                },
            )
        except ApiException as exc:
            if exc.status in {403, 404}:
                log.info("metrics collection skipped: Kubernetes Metrics API is unavailable (%s)", exc.status)
            else:
                log.error("metrics collection failed: %s", exc)
        except Exception as exc:
            log.error("metrics collection failed: %s", exc)
        await asyncio.sleep(settings.clusterwatch_metrics_interval_seconds)
