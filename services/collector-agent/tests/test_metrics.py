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


def test_kube_state_metric_samples_capture_requests_limits_and_workloads() -> None:
    metrics = load_metrics_module()

    raw = """
# HELP kube_pod_container_resource_requests The number of requested request resource by a container.
kube_pod_container_resource_requests{namespace="prod",pod="platform-api-0",container="api",node="node-a",resource="cpu",unit="core"} 0.5
kube_pod_container_resource_requests{namespace="prod",pod="platform-api-0",container="api",node="node-a",resource="memory",unit="byte"} 268435456
kube_pod_container_resource_limits{namespace="prod",pod="platform-api-0",container="api",node="node-a",resource="cpu",unit="core"} 1
kube_pod_status_phase{namespace="prod",pod="platform-api-0",phase="Running"} 1
kube_deployment_spec_replicas{namespace="prod",deployment="platform-api"} 3
kube_deployment_status_replicas_available{namespace="prod",deployment="platform-api"} 2
kube_node_status_allocatable{node="node-a",resource="cpu",unit="core"} 4
"""

    samples = metrics.kube_state_metric_samples(raw)

    assert any(sample["metric_name"] == "request_cpu_cores" and sample["value"] == 0.5 for sample in samples)
    assert any(sample["metric_name"] == "request_memory_bytes" and sample["value"] == 268435456 for sample in samples)
    assert any(sample["metric_name"] == "limit_cpu_cores" and sample["value"] == 1 for sample in samples)
    assert any(sample["metric_name"] == "phase_running" and sample["value"] == 1 for sample in samples)
    assert any(sample["metric_name"] == "replicas_desired" and sample["resource_kind"] == "Deployment" for sample in samples)
    assert any(sample["metric_name"] == "replicas_available" and sample["resource_kind"] == "Deployment" for sample in samples)
    assert any(sample["metric_name"] == "allocatable_cpu_cores" and sample["resource_kind"] == "Node" for sample in samples)


def test_summary_metric_samples_capture_node_and_pod_network() -> None:
    metrics = load_metrics_module()

    summary = {
        "node": {
            "network": {"rxBytes": 1000, "txBytes": 2000},
            "fs": {"capacityBytes": 5000, "availableBytes": 1250},
        },
        "pods": [
            {
                "podRef": {"namespace": "prod", "name": "platform-api-0"},
                "network": {"rxBytes": 300, "txBytes": 450},
            }
        ],
    }

    samples = metrics.summary_metric_samples(summary, "node-a")

    assert any(sample["metric_name"] == "network_rx_bytes" and sample["scope"] == "node" and sample["value"] == 1000 for sample in samples)
    assert any(sample["metric_name"] == "network_tx_bytes" and sample["scope"] == "pod" and sample["value"] == 450 for sample in samples)
    assert any(sample["metric_name"] == "fs_used_bytes" and sample["value"] == 3750 for sample in samples)
