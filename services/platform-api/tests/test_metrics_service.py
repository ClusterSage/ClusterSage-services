from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.metrics.service import (
    build_latest_metric_response,
    build_metric_filter_catalog,
    build_metric_timeseries_response,
    build_metrics_overview,
)


def sample(**overrides):
    base = {
        "scope": "pod",
        "namespace": "prod",
        "resource_kind": "Pod",
        "resource_name": "api-0",
        "container_name": None,
        "node_name": "node-a",
        "metric_name": "cpu_mcores",
        "unit": "mcores",
        "value": 150.0,
        "collected_at": datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_metrics_overview_aggregates_latest_samples() -> None:
    collected_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    overview = build_metrics_overview(
        [
            sample(resource_name="api-0", metric_name="cpu_mcores", value=120.0),
            sample(resource_name="api-0", metric_name="memory_bytes", unit="bytes", value=1024.0),
            sample(resource_name="worker-0", metric_name="cpu_mcores", value=80.0),
            sample(resource_name="node-a", scope="node", namespace=None, resource_kind="Node", node_name="node-a", metric_name="cpu_mcores", value=650.0),
        ],
        collected_at,
    )

    assert overview.collected_at == collected_at
    assert overview.pod_cpu_mcores_total == 200.0
    assert overview.pod_memory_bytes_total == 1024.0
    assert overview.node_cpu_mcores_total == 650.0
    assert overview.top_pods_by_cpu[0].label == "api-0"
    assert overview.top_pods_by_cpu[0].value == 120.0


def test_build_metric_filter_catalog_lists_dimensions() -> None:
    collected_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    catalog = build_metric_filter_catalog(
        [
            sample(metric_name="cpu_mcores"),
            sample(metric_name="request_cpu_cores"),
            sample(scope="workload", resource_kind="Deployment", resource_name="platform-api", metric_name="replicas_available", unit="count"),
            sample(scope="node", namespace=None, resource_kind="Node", resource_name="node-a", node_name="node-a", metric_name="network_rx_bytes", unit="bytes"),
        ],
        collected_at,
    )

    assert catalog.collected_at == collected_at
    assert "cpu_mcores" in catalog.metric_names
    assert "request_cpu_cores" in catalog.metric_names
    assert "workload" in catalog.scopes
    assert "Deployment" in catalog.resource_kinds
    assert "prod" in catalog.namespaces
    assert "node-a" in catalog.nodes
    assert "platform-api" in catalog.workloads
    assert "api-0" in catalog.pods


def test_build_latest_metric_response_sums_and_sorts_matching_metric() -> None:
    collected_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    response = build_latest_metric_response(
        [
            sample(resource_name="api-0", metric_name="request_cpu_cores", unit="cores", value=0.5),
            sample(resource_name="worker-0", metric_name="request_cpu_cores", unit="cores", value=0.25),
            sample(resource_name="api-0", metric_name="cpu_mcores", value=100.0),
        ],
        metric_name="request_cpu_cores",
        collected_at=collected_at,
    )

    assert response.collected_at == collected_at
    assert response.metric_name == "request_cpu_cores"
    assert response.unit == "cores"
    assert response.total_value == 0.75
    assert response.breakdown[0].resource_name == "api-0"
    assert response.breakdown[0].value == 0.5


def test_build_metric_timeseries_response_groups_by_resource_and_bucket() -> None:
    start = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    response = build_metric_timeseries_response(
        [
            sample(resource_name="api-0", metric_name="network_rx_bytes", unit="bytes", value=10, collected_at=start),
            sample(resource_name="api-0", metric_name="network_rx_bytes", unit="bytes", value=15, collected_at=start + timedelta(minutes=2)),
            sample(resource_name="api-0", metric_name="network_rx_bytes", unit="bytes", value=9, collected_at=start + timedelta(minutes=7)),
            sample(resource_name="worker-0", metric_name="network_rx_bytes", unit="bytes", value=5, collected_at=start + timedelta(minutes=1)),
        ],
        metric_name="network_rx_bytes",
        window_minutes=180,
        step_minutes=5,
        limit=8,
    )

    assert response.metric_name == "network_rx_bytes"
    assert response.unit == "bytes"
    assert len(response.series) == 2
    api_series = next(item for item in response.series if item.resource_name == "api-0")
    assert len(api_series.points) == 2
    assert api_series.points[0].value == 25
    assert api_series.points[1].value == 9
