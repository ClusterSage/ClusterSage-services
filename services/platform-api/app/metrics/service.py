from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.models.entities import ClusterMetricSample
from app.schemas.api import ClusterMetricRollupItem, ClusterMetricsOverviewResponse


@dataclass(frozen=True)
class _MetricKey:
    label: str
    namespace: str | None
    unit: str


def build_metrics_overview(samples: list[ClusterMetricSample], collected_at: datetime | None) -> ClusterMetricsOverviewResponse:
    pod_cpu_total = 0.0
    pod_memory_total = 0.0
    node_cpu_total = 0.0
    node_memory_total = 0.0

    pod_cpu: dict[_MetricKey, float] = defaultdict(float)
    pod_memory: dict[_MetricKey, float] = defaultdict(float)
    node_cpu: dict[_MetricKey, float] = defaultdict(float)
    node_memory: dict[_MetricKey, float] = defaultdict(float)

    for sample in samples:
        key = _MetricKey(
            label=sample.resource_name,
            namespace=sample.namespace,
            unit=sample.unit,
        )
        if sample.scope == "pod" and sample.metric_name == "cpu_mcores":
            pod_cpu_total += sample.value
            pod_cpu[key] += sample.value
        elif sample.scope == "pod" and sample.metric_name == "memory_bytes":
            pod_memory_total += sample.value
            pod_memory[key] += sample.value
        elif sample.scope == "node" and sample.metric_name == "cpu_mcores":
            node_cpu_total += sample.value
            node_cpu[key] += sample.value
        elif sample.scope == "node" and sample.metric_name == "memory_bytes":
            node_memory_total += sample.value
            node_memory[key] += sample.value

    def to_items(values: dict[_MetricKey, float]) -> list[ClusterMetricRollupItem]:
        return [
            ClusterMetricRollupItem(label=key.label, namespace=key.namespace, value=value, unit=key.unit)
            for key, value in sorted(values.items(), key=lambda entry: entry[1], reverse=True)[:8]
        ]

    return ClusterMetricsOverviewResponse(
        collected_at=collected_at,
        pod_cpu_mcores_total=pod_cpu_total,
        pod_memory_bytes_total=pod_memory_total,
        node_cpu_mcores_total=node_cpu_total,
        node_memory_bytes_total=node_memory_total,
        top_pods_by_cpu=to_items(pod_cpu),
        top_pods_by_memory=to_items(pod_memory),
        top_nodes_by_cpu=to_items(node_cpu),
        top_nodes_by_memory=to_items(node_memory),
    )
