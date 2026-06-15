from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import Issue

POD_REASON_SEVERITY = {
    "CrashLoopBackOff": "critical",
    "ImagePullBackOff": "high",
    "ErrImagePull": "high",
    "CreateContainerConfigError": "critical",
    "OOMKilled": "high",
}
NODE_CONDITIONS = {"Ready": "NodeNotReady", "DiskPressure": "DiskPressure", "MemoryPressure": "MemoryPressure"}

async def upsert_issue(session: AsyncSession, organization_id, cluster_id, issue_type: str, title: str, severity: str, namespace: str | None = None, workload: str | None = None, pod_name: str | None = None, description: str | None = None) -> None:
    stmt = select(Issue).where(Issue.organization_id == organization_id, Issue.cluster_id == cluster_id, Issue.issue_type == issue_type, Issue.namespace.is_(namespace) if namespace is None else Issue.namespace == namespace, Issue.pod_name.is_(pod_name) if pod_name is None else Issue.pod_name == pod_name, Issue.status == "open")
    existing = (await session.execute(stmt)).scalars().first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.last_seen_at = now
        existing.severity = severity
        existing.description = description
        return
    session.add(Issue(organization_id=organization_id, cluster_id=cluster_id, namespace=namespace, workload=workload, pod_name=pod_name, severity=severity, issue_type=issue_type, title=title, description=description, first_seen_at=now, last_seen_at=now))

async def detect_from_snapshot(session: AsyncSession, organization_id, cluster_id, snapshot: dict[str, Any]) -> None:
    for pod in snapshot.get("pods", []):
        meta = pod.get("metadata", {})
        status = pod.get("status", {})
        namespace, pod_name = meta.get("namespace"), meta.get("name")
        phase = status.get("phase")
        if phase == "Pending":
            await upsert_issue(session, organization_id, cluster_id, "PendingPod", f"Pod {pod_name} is Pending", "medium", namespace, pod_name=pod_name, description="Pod has remained in Pending phase.")
        for cs in status.get("containerStatuses", []) + status.get("initContainerStatuses", []):
            state = cs.get("state", {}) or {}
            last_state = cs.get("lastState", {}) or {}
            waiting = state.get("waiting") or {}
            terminated = state.get("terminated") or last_state.get("terminated") or {}
            reason = waiting.get("reason") or terminated.get("reason")
            if reason in POD_REASON_SEVERITY:
                await upsert_issue(session, organization_id, cluster_id, reason, f"{reason} in pod {pod_name}", POD_REASON_SEVERITY[reason], namespace, pod_name=pod_name, description=waiting.get("message") or terminated.get("message"))
            if cs.get("restartCount", 0) >= 5:
                await upsert_issue(session, organization_id, cluster_id, "HighRestartCount", f"High restart count in pod {pod_name}", "medium", namespace, pod_name=pod_name, description=f"Container {cs.get('name')} restarted {cs.get('restartCount')} times.")
    for node in snapshot.get("nodes", []):
        meta = node.get("metadata", {})
        for condition in node.get("status", {}).get("conditions", []):
            ctype, cstatus = condition.get("type"), condition.get("status")
            if (ctype == "Ready" and cstatus != "True") or (ctype in {"DiskPressure", "MemoryPressure"} and cstatus == "True"):
                issue_type = NODE_CONDITIONS.get(ctype, ctype)
                await upsert_issue(session, organization_id, cluster_id, issue_type, f"Node {meta.get('name')} reports {issue_type}", "high", description=condition.get("message"))
    for deploy in snapshot.get("deployments", []):
        meta, status = deploy.get("metadata", {}), deploy.get("status", {})
        desired = status.get("replicas", 0) or 0
        unavailable = status.get("unavailableReplicas", 0) or 0
        if desired and unavailable:
            await upsert_issue(session, organization_id, cluster_id, "DeploymentUnavailableReplicas", f"Deployment {meta.get('name')} has unavailable replicas", "high", meta.get("namespace"), workload=meta.get("name"), description=f"{unavailable} of {desired} replicas unavailable.")
    for pvc in snapshot.get("persistentvolumeclaims", []):
        meta = pvc.get("metadata", {})
        if pvc.get("status", {}).get("phase") == "Pending":
            await upsert_issue(session, organization_id, cluster_id, "PVCPending", f"PVC {meta.get('name')} is Pending", "medium", meta.get("namespace"), description="PersistentVolumeClaim is not bound.")

async def detect_from_events(session: AsyncSession, organization_id, cluster_id, events: list[dict[str, Any]]) -> None:
    for event in events:
        reason = event.get("reason") or event.get("metadata", {}).get("reason")
        message = event.get("message") or event.get("note")
        involved = event.get("involvedObject") or event.get("regarding") or {}
        if reason in {"FailedScheduling", "Failed", "BackOff", "Unhealthy"} or "failed scheduling" in str(message).lower():
            await upsert_issue(session, organization_id, cluster_id, "FailedScheduling" if reason == "FailedScheduling" else f"KubernetesEvent{reason or 'Warning'}", f"Kubernetes warning: {reason or 'event'}", "medium", involved.get("namespace"), pod_name=involved.get("name") if involved.get("kind") == "Pod" else None, description=message)
