from datetime import datetime, timezone
from types import SimpleNamespace

from app.metrics.service import build_metrics_overview


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
