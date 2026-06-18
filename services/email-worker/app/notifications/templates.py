def cluster_connected_subject() -> str:
    return "ClusterSage: Cluster connected successfully"


def cluster_connected_body(cluster_name: str) -> str:
    return (
        f"Hello, your Kubernetes cluster {cluster_name} was successfully connected to ClusterSage. "
        "You can now view resources, logs, incidents, and AI suggestions from your dashboard."
    )


def alert_limit_triggered_subject(cluster_name: str, alert_limit_name: str) -> str:
    return f"ClusterSage alert: {cluster_name} / {alert_limit_name}"


def alert_limit_triggered_body(
    *,
    cluster_name: str,
    alert_limit_name: str,
    metric_label: str,
    operator: str,
    threshold_value: float,
    actual_value: float,
    severity: str,
    time_window_minutes: int,
    dashboard_url: str,
) -> str:
    return (
        f"ClusterSage detected an alert threshold breach for cluster {cluster_name}.\n\n"
        f"Alert: {alert_limit_name}\n"
        f"Metric: {metric_label}\n"
        f"Condition: value {operator} {threshold_value}\n"
        f"Observed value: {actual_value}\n"
        f"Severity: {severity}\n"
        f"Time window: {time_window_minutes} minutes\n\n"
        f"Review the cluster limits page here:\n{dashboard_url}\n"
    )
