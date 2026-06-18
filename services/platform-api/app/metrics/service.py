from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.entities import ClusterMetricSample
from app.schemas.api import (
    ClusterMetricFilterCatalogResponse,
    ClusterMetricLatestBreakdownItem,
    ClusterMetricLatestResponse,
    ClusterMetricRollupItem,
    ClusterMetricsOverviewResponse,
    ClusterMetricTimeseriesPoint,
    ClusterMetricTimeseriesResponse,
    ClusterMetricTimeseriesSeries,
)


@dataclass(frozen=True)
class _MetricKey:
    label: str
    namespace: str | None
    unit: str


@dataclass(frozen=True)
class _SeriesKey:
    scope: str
    resource_kind: str
    resource_name: str
    namespace: str | None
    node_name: str | None
    container_name: str | None
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


def build_metric_filter_catalog(samples: list[ClusterMetricSample], collected_at: datetime | None) -> ClusterMetricFilterCatalogResponse:
    metric_names = sorted({sample.metric_name for sample in samples})
    scopes = sorted({sample.scope for sample in samples})
    resource_kinds = sorted({sample.resource_kind for sample in samples})
    namespaces = sorted({sample.namespace for sample in samples if sample.namespace})
    nodes = sorted({sample.node_name or sample.resource_name for sample in samples if sample.scope == "node" and (sample.node_name or sample.resource_name)})
    workloads = sorted({sample.resource_name for sample in samples if sample.scope == "workload"})
    pods = sorted({sample.resource_name for sample in samples if sample.scope == "pod"})
    return ClusterMetricFilterCatalogResponse(
        collected_at=collected_at,
        metric_names=metric_names,
        scopes=scopes,
        resource_kinds=resource_kinds,
        namespaces=namespaces,
        nodes=nodes,
        workloads=workloads,
        pods=pods,
    )


def build_latest_metric_response(
    samples: list[ClusterMetricSample],
    *,
    metric_name: str,
    collected_at: datetime | None,
    limit: int = 12,
) -> ClusterMetricLatestResponse:
    matching = [sample for sample in samples if sample.metric_name == metric_name]
    if not matching:
        return ClusterMetricLatestResponse(collected_at=collected_at, metric_name=metric_name)
    unit = matching[0].unit
    ordered = sorted(matching, key=lambda sample: sample.value, reverse=True)
    total_value = sum(sample.value for sample in matching)
    breakdown = [
        ClusterMetricLatestBreakdownItem(
            scope=sample.scope,
            resource_kind=sample.resource_kind,
            resource_name=sample.resource_name,
            namespace=sample.namespace,
            node_name=sample.node_name,
            container_name=sample.container_name,
            value=sample.value,
            unit=sample.unit,
        )
        for sample in ordered[:limit]
    ]
    return ClusterMetricLatestResponse(
        collected_at=collected_at,
        metric_name=metric_name,
        unit=unit,
        total_value=total_value,
        breakdown=breakdown,
    )


def floor_timestamp(value: datetime, step_minutes: int) -> datetime:
    minute = (value.minute // step_minutes) * step_minutes
    return value.replace(minute=minute, second=0, microsecond=0)


def build_metric_timeseries_response(
    samples: list[ClusterMetricSample],
    *,
    metric_name: str,
    window_minutes: int,
    step_minutes: int,
    limit: int = 8,
) -> ClusterMetricTimeseriesResponse:
    matching = [sample for sample in samples if sample.metric_name == metric_name]
    if not matching:
        return ClusterMetricTimeseriesResponse(
            metric_name=metric_name,
            unit=None,
            window_minutes=window_minutes,
            step_minutes=step_minutes,
            series=[],
        )

    grouped: dict[_SeriesKey, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    latest_values: dict[_SeriesKey, float] = defaultdict(float)
    unit = matching[0].unit

    for sample in matching:
        key = _SeriesKey(
            scope=sample.scope,
            resource_kind=sample.resource_kind,
            resource_name=sample.resource_name,
            namespace=sample.namespace,
            node_name=sample.node_name,
            container_name=sample.container_name,
            unit=sample.unit,
        )
        bucket = floor_timestamp(sample.collected_at, step_minutes)
        grouped[key][bucket] += sample.value
        latest_values[key] = sample.value

    sorted_keys = sorted(grouped.keys(), key=lambda key: max(grouped[key].values()), reverse=True)[:limit]
    series = [
        ClusterMetricTimeseriesSeries(
            scope=key.scope,
            resource_kind=key.resource_kind,
            resource_name=key.resource_name,
            namespace=key.namespace,
            node_name=key.node_name,
            container_name=key.container_name,
            unit=key.unit,
            latest_value=latest_values[key],
            points=[
                ClusterMetricTimeseriesPoint(timestamp=timestamp, value=value)
                for timestamp, value in sorted(grouped[key].items(), key=lambda item: item[0])
            ],
        )
        for key in sorted_keys
    ]
    return ClusterMetricTimeseriesResponse(
        metric_name=metric_name,
        unit=unit,
        window_minutes=window_minutes,
        step_minutes=step_minutes,
        series=series,
    )


def metrics_window_start(now: datetime, window_minutes: int) -> datetime:
    return now - timedelta(minutes=window_minutes)
