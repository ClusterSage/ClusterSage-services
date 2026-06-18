import asyncio
import ast
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from kubernetes import client
from kubernetes.client import ApiException

from app.config import settings
from app.kubernetes_client import load_config
from app.models import AgentState
from app.sender import post_with_retry

log = logging.getLogger(__name__)

PROMETHEUS_LINE_RE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?)$"
)
PROMETHEUS_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"')


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


def make_sample(
    *,
    scope: str,
    resource_kind: str,
    resource_name: str,
    metric_name: str,
    unit: str,
    value: float,
    namespace: str | None = None,
    container_name: str | None = None,
    node_name: str | None = None,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "namespace": namespace,
        "resource_kind": resource_kind,
        "resource_name": resource_name,
        "container_name": container_name,
        "node_name": node_name,
        "metric_name": metric_name,
        "unit": unit,
        "value": value,
    }


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
            make_sample(
                scope="pod",
                namespace=namespace,
                resource_kind="Pod",
                resource_name=pod_name,
                node_name=node_name,
                metric_name="cpu_mcores",
                unit="mcores",
                value=cpu_total,
            )
        )
        samples.append(
            make_sample(
                scope="pod",
                namespace=namespace,
                resource_kind="Pod",
                resource_name=pod_name,
                node_name=node_name,
                metric_name="memory_bytes",
                unit="bytes",
                value=memory_total,
            )
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
            make_sample(
                scope="node",
                resource_kind="Node",
                resource_name=name,
                node_name=name,
                metric_name="cpu_mcores",
                unit="mcores",
                value=parse_cpu_to_mcores(str(usage.get("cpu", "0"))),
            )
        )
        samples.append(
            make_sample(
                scope="node",
                resource_kind="Node",
                resource_name=name,
                node_name=name,
                metric_name="memory_bytes",
                unit="bytes",
                value=parse_memory_to_bytes(str(usage.get("memory", "0"))),
            )
        )
    return samples


def parse_prometheus_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    labels: dict[str, str] = {}
    for key, value in PROMETHEUS_LABEL_RE.findall(raw):
        labels[key] = bytes(value, "utf-8").decode("unicode_escape")
    return labels


def parse_prometheus_text(raw: str) -> list[tuple[str, dict[str, str], float]]:
    series: list[tuple[str, dict[str, str], float]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PROMETHEUS_LINE_RE.match(line)
        if not match:
            continue
        metric_name, labels_raw, value_raw = match.groups()
        try:
            value = float(value_raw)
        except ValueError:
            continue
        series.append((metric_name, parse_prometheus_labels(labels_raw), value))
    return series


def kube_state_metric_samples(raw: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for metric_name, labels, value in parse_prometheus_text(raw):
        namespace = labels.get("namespace")
        pod = labels.get("pod")
        container = labels.get("container")
        node = labels.get("node")
        deployment = labels.get("deployment")
        statefulset = labels.get("statefulset")
        daemonset = labels.get("daemonset")
        phase = labels.get("phase")
        resource = labels.get("resource")
        unit = labels.get("unit")

        if metric_name == "kube_pod_container_resource_requests" and pod and resource and unit:
            if resource == "cpu" and unit == "core":
                samples.append(
                    make_sample(
                        scope="pod",
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod,
                        container_name=container,
                        node_name=node,
                        metric_name="request_cpu_cores",
                        unit="cores",
                        value=value,
                    )
                )
            elif resource == "memory" and unit == "byte":
                samples.append(
                    make_sample(
                        scope="pod",
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod,
                        container_name=container,
                        node_name=node,
                        metric_name="request_memory_bytes",
                        unit="bytes",
                        value=value,
                    )
                )
        elif metric_name == "kube_pod_container_resource_limits" and pod and resource and unit:
            if resource == "cpu" and unit == "core":
                samples.append(
                    make_sample(
                        scope="pod",
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod,
                        container_name=container,
                        node_name=node,
                        metric_name="limit_cpu_cores",
                        unit="cores",
                        value=value,
                    )
                )
            elif resource == "memory" and unit == "byte":
                samples.append(
                    make_sample(
                        scope="pod",
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod,
                        container_name=container,
                        node_name=node,
                        metric_name="limit_memory_bytes",
                        unit="bytes",
                        value=value,
                    )
                )
        elif metric_name == "kube_pod_container_resource_requests_cpu_cores" and pod:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod,
                    container_name=container,
                    node_name=node,
                    metric_name="request_cpu_cores",
                    unit="cores",
                    value=value,
                )
            )
        elif metric_name == "kube_pod_container_resource_limits_cpu_cores" and pod:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod,
                    container_name=container,
                    node_name=node,
                    metric_name="limit_cpu_cores",
                    unit="cores",
                    value=value,
                )
            )
        elif metric_name == "kube_pod_container_resource_requests_memory_bytes" and pod:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod,
                    container_name=container,
                    node_name=node,
                    metric_name="request_memory_bytes",
                    unit="bytes",
                    value=value,
                )
            )
        elif metric_name == "kube_pod_container_resource_limits_memory_bytes" and pod:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod,
                    container_name=container,
                    node_name=node,
                    metric_name="limit_memory_bytes",
                    unit="bytes",
                    value=value,
                )
            )
        elif metric_name == "kube_pod_status_phase" and pod and phase and value >= 1:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod,
                    node_name=node,
                    metric_name=f"phase_{phase.lower()}",
                    unit="count",
                    value=1,
                )
            )
        elif metric_name == "kube_deployment_spec_replicas" and deployment:
            samples.append(
                make_sample(
                    scope="workload",
                    namespace=namespace,
                    resource_kind="Deployment",
                    resource_name=deployment,
                    metric_name="replicas_desired",
                    unit="count",
                    value=value,
                )
            )
        elif metric_name == "kube_deployment_status_replicas_available" and deployment:
            samples.append(
                make_sample(
                    scope="workload",
                    namespace=namespace,
                    resource_kind="Deployment",
                    resource_name=deployment,
                    metric_name="replicas_available",
                    unit="count",
                    value=value,
                )
            )
        elif metric_name == "kube_statefulset_replicas" and statefulset:
            samples.append(
                make_sample(
                    scope="workload",
                    namespace=namespace,
                    resource_kind="StatefulSet",
                    resource_name=statefulset,
                    metric_name="replicas_desired",
                    unit="count",
                    value=value,
                )
            )
        elif metric_name == "kube_statefulset_status_replicas_ready" and statefulset:
            samples.append(
                make_sample(
                    scope="workload",
                    namespace=namespace,
                    resource_kind="StatefulSet",
                    resource_name=statefulset,
                    metric_name="replicas_ready",
                    unit="count",
                    value=value,
                )
            )
        elif metric_name == "kube_daemonset_status_desired_number_scheduled" and daemonset:
            samples.append(
                make_sample(
                    scope="workload",
                    namespace=namespace,
                    resource_kind="DaemonSet",
                    resource_name=daemonset,
                    metric_name="pods_desired",
                    unit="count",
                    value=value,
                )
            )
        elif metric_name == "kube_daemonset_status_number_ready" and daemonset:
            samples.append(
                make_sample(
                    scope="workload",
                    namespace=namespace,
                    resource_kind="DaemonSet",
                    resource_name=daemonset,
                    metric_name="pods_ready",
                    unit="count",
                    value=value,
                )
            )
        elif metric_name == "kube_node_status_allocatable" and node and resource and unit:
            if resource == "cpu" and unit == "core":
                samples.append(
                    make_sample(
                        scope="node",
                        resource_kind="Node",
                        resource_name=node,
                        node_name=node,
                        metric_name="allocatable_cpu_cores",
                        unit="cores",
                        value=value,
                    )
                )
            elif resource == "memory" and unit == "byte":
                samples.append(
                    make_sample(
                        scope="node",
                        resource_kind="Node",
                        resource_name=node,
                        node_name=node,
                        metric_name="allocatable_memory_bytes",
                        unit="bytes",
                        value=value,
                    )
                )
        elif metric_name == "kube_node_status_capacity" and node and resource and unit:
            if resource == "cpu" and unit == "core":
                samples.append(
                    make_sample(
                        scope="node",
                        resource_kind="Node",
                        resource_name=node,
                        node_name=node,
                        metric_name="capacity_cpu_cores",
                        unit="cores",
                        value=value,
                    )
                )
            elif resource == "memory" and unit == "byte":
                samples.append(
                    make_sample(
                        scope="node",
                        resource_kind="Node",
                        resource_name=node,
                        node_name=node,
                        metric_name="capacity_memory_bytes",
                        unit="bytes",
                        value=value,
                    )
                )
    return samples


def summary_metric_samples(summary: dict[str, Any], node_name: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    node = summary.get("node") or {}
    network = node.get("network") or {}
    fs = node.get("fs") or {}

    if network.get("rxBytes") is not None:
        samples.append(
            make_sample(
                scope="node",
                resource_kind="Node",
                resource_name=node_name,
                node_name=node_name,
                metric_name="network_rx_bytes",
                unit="bytes",
                value=float(network["rxBytes"]),
            )
        )
    if network.get("txBytes") is not None:
        samples.append(
            make_sample(
                scope="node",
                resource_kind="Node",
                resource_name=node_name,
                node_name=node_name,
                metric_name="network_tx_bytes",
                unit="bytes",
                value=float(network["txBytes"]),
            )
        )
    if fs.get("capacityBytes") is not None:
        samples.append(
            make_sample(
                scope="node",
                resource_kind="Node",
                resource_name=node_name,
                node_name=node_name,
                metric_name="fs_capacity_bytes",
                unit="bytes",
                value=float(fs["capacityBytes"]),
            )
        )
    if fs.get("availableBytes") is not None:
        available = float(fs["availableBytes"])
        samples.append(
            make_sample(
                scope="node",
                resource_kind="Node",
                resource_name=node_name,
                node_name=node_name,
                metric_name="fs_available_bytes",
                unit="bytes",
                value=available,
            )
        )
        if fs.get("capacityBytes") is not None:
            capacity = float(fs["capacityBytes"])
            samples.append(
                make_sample(
                    scope="node",
                    resource_kind="Node",
                    resource_name=node_name,
                    node_name=node_name,
                    metric_name="fs_used_bytes",
                    unit="bytes",
                    value=max(capacity - available, 0),
                )
            )

    for pod in summary.get("pods", []) or []:
        pod_ref = pod.get("podRef") or {}
        namespace = pod_ref.get("namespace")
        pod_name = pod_ref.get("name")
        if not namespace or not pod_name:
            continue
        pod_network = pod.get("network") or {}
        if pod_network.get("rxBytes") is not None:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod_name,
                    node_name=node_name,
                    metric_name="network_rx_bytes",
                    unit="bytes",
                    value=float(pod_network["rxBytes"]),
                )
            )
        if pod_network.get("txBytes") is not None:
            samples.append(
                make_sample(
                    scope="pod",
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod_name,
                    node_name=node_name,
                    metric_name="network_tx_bytes",
                    unit="bytes",
                    value=float(pod_network["txBytes"]),
                )
            )
    return samples


def parse_summary_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                return None
        return parsed if isinstance(parsed, dict) else None
    return None


def collect_resource_usage_samples() -> list[dict[str, Any]]:
    if not settings.clusterwatch_metrics_resource_usage_enabled:
        return []
    custom_api = client.CustomObjectsApi()
    pod_metrics = custom_api.list_cluster_custom_object(group="metrics.k8s.io", version="v1beta1", plural="pods")
    node_metrics = custom_api.list_cluster_custom_object(group="metrics.k8s.io", version="v1beta1", plural="nodes")
    return pod_metric_samples(pod_metrics) + node_metric_samples(node_metrics)


def collect_kubelet_summary_samples() -> list[dict[str, Any]]:
    if not settings.clusterwatch_metrics_kubelet_summary_enabled:
        return []
    core_api = client.CoreV1Api()
    samples: list[dict[str, Any]] = []
    for node in core_api.list_node().items:
        node_name = node.metadata.name if node.metadata else None
        if not node_name:
            continue
        raw = core_api.connect_get_node_proxy_with_path(node_name, "stats/summary")
        summary = parse_summary_payload(raw)
        if summary is not None:
            samples.extend(summary_metric_samples(summary, node_name))
    return samples


def collect_kubernetes_api_samples() -> list[dict[str, Any]]:
    load_config()
    samples: list[dict[str, Any]] = []
    try:
        samples.extend(collect_resource_usage_samples())
    except ApiException as exc:
        if exc.status in {403, 404}:
            log.info("resource usage metrics skipped: Kubernetes Metrics API is unavailable (%s)", exc.status)
        else:
            raise
    if settings.clusterwatch_metrics_kubelet_summary_enabled:
        try:
            samples.extend(collect_kubelet_summary_samples())
        except ApiException as exc:
            if exc.status in {403, 404}:
                log.info("kubelet summary metrics skipped: node proxy access is unavailable (%s)", exc.status)
            else:
                raise
    return samples


async def collect_kube_state_samples() -> list[dict[str, Any]]:
    if not settings.clusterwatch_metrics_kube_state_enabled:
        return []
    async with httpx.AsyncClient(timeout=settings.clusterwatch_metrics_kube_state_timeout_seconds) as http:
        response = await http.get(settings.kube_state_metrics_url)
        response.raise_for_status()
    return kube_state_metric_samples(response.text)


async def collect_metrics_samples() -> list[dict[str, Any]]:
    samples = await asyncio.to_thread(collect_kubernetes_api_samples)
    try:
        samples.extend(await collect_kube_state_samples())
    except httpx.HTTPError as exc:
        log.info("kube-state-metrics scrape skipped: %s", exc)
    return samples


async def metrics_loop(state: AgentState) -> None:
    if not settings.clusterwatch_metrics_enabled:
        log.info("metrics collection disabled by configuration")
        return
    while True:
        try:
            samples = await collect_metrics_samples()
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
                log.info("metrics collection skipped: Kubernetes metrics surfaces are unavailable (%s)", exc.status)
            else:
                log.error("metrics collection failed: %s", exc)
        except Exception as exc:
            log.error("metrics collection failed: %s", exc)
        await asyncio.sleep(settings.clusterwatch_metrics_interval_seconds)
