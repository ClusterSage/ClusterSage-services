def cluster_connected_subject() -> str:
    return "ClusterSage: Cluster connected successfully"

def cluster_connected_body(cluster_name: str) -> str:
    return (
        f"Hello, your Kubernetes cluster {cluster_name} was successfully connected to ClusterSage. "
        "You can now view resources, logs, incidents, and AI suggestions from your dashboard."
    )
