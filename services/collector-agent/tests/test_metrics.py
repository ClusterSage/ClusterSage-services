import importlib
import os


def load_metrics_module():
    os.environ.setdefault("CLUSTERWATCH_BACKEND_URL", "https://example.com")
    os.environ.setdefault("CLUSTERWATCH_EMAIL", "owner@example.com")
    os.environ.setdefault("CLUSTERWATCH_ACCESS_KEY", "cw_test_key")
    os.environ.setdefault("CLUSTERWATCH_CLUSTER_NAME", "prod-cluster")
    metrics = importlib.import_module("app.metrics")
    importlib.reload(metrics)
    return metrics


def test_parse_cpu_to_mcores_handles_multiple_quantity_formats() -> None:
    metrics = load_metrics_module()

    assert metrics.parse_cpu_to_mcores("250m") == 250
    assert metrics.parse_cpu_to_mcores("1") == 1000
    assert metrics.parse_cpu_to_mcores("250000000n") == 250


def test_pod_metric_samples_aggregate_container_usage() -> None:
    metrics = load_metrics_module()

    samples = metrics.pod_metric_samples(
        {
            "items": [
                {
                    "metadata": {
                        "namespace": "prod",
                        "name": "platform-api-0",
                    },
                    "containers": [
                        {"usage": {"cpu": "100m", "memory": "64Mi"}},
                        {"usage": {"cpu": "50m", "memory": "32Mi"}},
                    ],
                }
            ]
        }
    )

    cpu_sample = next(sample for sample in samples if sample["metric_name"] == "cpu_mcores")
    memory_sample = next(sample for sample in samples if sample["metric_name"] == "memory_bytes")
    assert cpu_sample["value"] == 150
    assert memory_sample["value"] == (64 + 32) * 1024 * 1024
