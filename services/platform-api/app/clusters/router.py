from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.audit.service import write_audit
from app.auth.dependencies import get_current_user
from app.db.session import get_session
from app.models.entities import Cluster, ClusterSnapshot, Issue, LogBatch, User
from app.schemas.api import ClusterResponse, IssueResponse, LogBatchResponse, ResourceLogEntry, ResourceSummary, SnapshotResponse
from app.storage.blob import BlobReader

router = APIRouter(prefix="/api/clusters", tags=["clusters"])

RESOURCE_KEYS = {
    "pod": "pods",
    "pods": "pods",
    "deployment": "deployments",
    "deployments": "deployments",
    "service": "services",
    "services": "services",
    "replicaset": "replicasets",
    "replicasets": "replicasets",
    "statefulset": "statefulsets",
    "statefulsets": "statefulsets",
    "daemonset": "daemonsets",
    "daemonsets": "daemonsets",
    "job": "jobs",
    "jobs": "jobs",
    "cronjob": "cronjobs",
    "cronjobs": "cronjobs",
    "namespace": "namespaces",
    "namespaces": "namespaces",
}

KIND_LABELS = {
    "pods": "Pod",
    "deployments": "Deployment",
    "services": "Service",
    "replicasets": "ReplicaSet",
    "statefulsets": "StatefulSet",
    "daemonsets": "DaemonSet",
    "jobs": "Job",
    "cronjobs": "CronJob",
    "namespaces": "Namespace",
}

@router.get("", response_model=list[ClusterResponse])
async def clusters(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(Cluster).where(Cluster.organization_id == user.organization_id).order_by(Cluster.created_at.desc()))).scalars().all()

async def get_cluster(cluster_id: UUID, user: User, session: AsyncSession) -> Cluster:
    cluster = await session.get(Cluster, cluster_id)
    if not cluster or cluster.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster

@router.get("/{clusterId}", response_model=ClusterResponse)
async def cluster_detail(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await get_cluster(clusterId, user, session)

@router.delete("/{clusterId}", status_code=204)
async def deactivate_cluster(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    cluster = await get_cluster(clusterId, user, session)
    cluster.status = "deactivated"
    await write_audit(session, "cluster.deactivated", "user", user.organization_id, user.id, cluster.id, {"cluster_name": cluster.name})
    await session.commit()
    return None

@router.get("/{clusterId}/logs", response_model=list[LogBatchResponse])
async def cluster_logs(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    return (await session.execute(select(LogBatch).where(LogBatch.cluster_id == clusterId).order_by(LogBatch.created_at.desc()).limit(100))).scalars().all()

@router.get("/{clusterId}/issues", response_model=list[IssueResponse])
async def cluster_issues(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    return (await session.execute(select(Issue).where(Issue.cluster_id == clusterId).order_by(Issue.last_seen_at.desc()).limit(200))).scalars().all()

@router.get("/{clusterId}/snapshots/latest", response_model=SnapshotResponse | None)
async def latest_snapshot(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    return (await session.execute(select(ClusterSnapshot).where(ClusterSnapshot.cluster_id == clusterId).order_by(ClusterSnapshot.created_at.desc()).limit(1))).scalars().first()

def normalize_resource_key(kind: str) -> str:
    key = RESOURCE_KEYS.get(kind.lower())
    if not key:
        raise HTTPException(status_code=400, detail="Unsupported resource kind")
    return key

async def latest_snapshot_payload(cluster_id: UUID, session: AsyncSession) -> dict[str, Any]:
    snapshot = (await session.execute(
        select(ClusterSnapshot).where(ClusterSnapshot.cluster_id == cluster_id).order_by(ClusterSnapshot.created_at.desc()).limit(1)
    )).scalars().first()
    if not snapshot:
        return {}
    try:
        data = BlobReader().read_json_gz(snapshot.blob_path)
    except RuntimeError:
        return {}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Snapshot data is temporarily unavailable") from exc
    return data.get("snapshot", {}) if isinstance(data, dict) else {}

def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

def age_from(created_at: datetime | None) -> str | None:
    if not created_at:
        return None
    delta = datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)
    days = delta.days
    if days:
        return f"{days}d"
    hours = delta.seconds // 3600
    if hours:
        return f"{hours}h"
    minutes = delta.seconds // 60
    return f"{minutes}m"

def resource_status(key: str, resource: dict[str, Any]) -> str | None:
    status = resource.get("status") or {}
    spec = resource.get("spec") or {}
    if key == "pods":
        return status.get("phase")
    if key in {"deployments", "replicasets", "statefulsets"}:
        ready = status.get("readyReplicas") or status.get("availableReplicas") or 0
        desired = spec.get("replicas") or status.get("replicas") or 0
        return f"{ready}/{desired} ready"
    if key == "daemonsets":
        ready = status.get("numberReady") or 0
        desired = status.get("desiredNumberScheduled") or 0
        return f"{ready}/{desired} ready"
    if key == "services":
        return spec.get("type")
    if key == "jobs":
        if status.get("failed"):
            return "Failed"
        if status.get("succeeded"):
            return "Succeeded"
        return "Running" if status.get("active") else None
    if key == "cronjobs":
        return "Suspended" if spec.get("suspend") else "Active"
    if key == "namespaces":
        return status.get("phase")
    return None

def restart_count(resource: dict[str, Any]) -> int | None:
    statuses = (resource.get("status") or {}).get("containerStatuses") or []
    if not statuses:
        return None
    return sum(int(item.get("restartCount") or 0) for item in statuses)

def summarize_resource(key: str, resource: dict[str, Any]) -> ResourceSummary | None:
    metadata = resource.get("metadata") or {}
    name = metadata.get("name")
    if not name:
        return None
    created_at = parse_datetime(metadata.get("creationTimestamp"))
    return ResourceSummary(
        name=name,
        namespace=metadata.get("namespace"),
        kind=KIND_LABELS[key],
        status=resource_status(key, resource),
        age=age_from(created_at),
        node_name=(resource.get("spec") or {}).get("nodeName"),
        restart_count=restart_count(resource),
        labels=metadata.get("labels") or {},
        last_updated_at=parse_datetime(metadata.get("managedFields", [{}])[-1].get("time")) if metadata.get("managedFields") else None,
        created_at=created_at,
        metadata=resource,
    )

@router.get("/{clusterId}/resources", response_model=list[ResourceSummary])
async def cluster_resources(clusterId: UUID, kind: str | None = None, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    snapshot = await latest_snapshot_payload(clusterId, session)
    keys = [normalize_resource_key(kind)] if kind else list(KIND_LABELS)
    resources: list[ResourceSummary] = []
    for key in keys:
        for item in snapshot.get(key, []) or []:
            summary = summarize_resource(key, item)
            if summary:
                resources.append(summary)
    return sorted(resources, key=lambda item: (item.kind, item.namespace or "", item.name))

@router.get("/{clusterId}/resources/{kind}/{namespace}/{name}", response_model=ResourceSummary)
async def resource_detail(clusterId: UUID, kind: str, namespace: str, name: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    key = normalize_resource_key(kind)
    expected_namespace = None if namespace == "_cluster" else namespace
    snapshot = await latest_snapshot_payload(clusterId, session)
    for item in snapshot.get(key, []) or []:
        summary = summarize_resource(key, item)
        if summary and summary.name == name and summary.namespace == expected_namespace:
            return summary
    raise HTTPException(status_code=404, detail="Resource not found")

def record_field(record: dict[str, Any], *names: str) -> str | None:
    kubernetes = record.get("kubernetes") if isinstance(record.get("kubernetes"), dict) else {}
    for name in names:
        value = record.get(name) or kubernetes.get(name)
        if value is not None:
            return str(value)
    return None

def log_entry_from(record: dict[str, Any]) -> ResourceLogEntry:
    message = record.get("log") or record.get("message") or record.get("msg") or ""
    return ResourceLogEntry(
        timestamp=record_field(record, "time", "timestamp", "@timestamp"),
        namespace=record_field(record, "namespace", "namespace_name"),
        pod=record_field(record, "pod", "pod_name"),
        container=record_field(record, "container", "container_name"),
        message=str(message).rstrip(),
        raw=record,
    )

def resource_metadata(resource: dict[str, Any]) -> dict[str, Any]:
    return resource.get("metadata") or {}

def resource_namespace(resource: dict[str, Any]) -> str | None:
    return resource_metadata(resource).get("namespace")

def resource_name(resource: dict[str, Any]) -> str | None:
    return resource_metadata(resource).get("name")

def is_owned_by(resource: dict[str, Any], kind: str, name: str) -> bool:
    for owner in resource_metadata(resource).get("ownerReferences") or []:
        if owner.get("kind") == kind and owner.get("name") == name:
            return True
    return False

def selector_matches(resource: dict[str, Any], selector: dict[str, Any]) -> bool:
    if not selector:
        return False
    labels = resource_metadata(resource).get("labels") or {}
    return all(labels.get(key) == value for key, value in selector.items())

def match_labels(resource: dict[str, Any]) -> dict[str, Any]:
    selector = (resource.get("spec") or {}).get("selector") or {}
    return selector.get("matchLabels") or selector

def related_pod_refs(snapshot: dict[str, Any], key: str, namespace: str | None, name: str) -> set[tuple[str | None, str]]:
    pods = snapshot.get("pods", []) or []
    if key == "pods":
        return {(namespace, name)}
    if key == "namespaces":
        return {
            (resource_namespace(pod), resource_name(pod))
            for pod in pods
            if resource_namespace(pod) == name and resource_name(pod)
        }

    resources = snapshot.get(key, []) or []
    target = next(
        (
            item for item in resources
            if resource_name(item) == name and resource_namespace(item) == namespace
        ),
        None,
    )
    if not target:
        return set()

    refs: set[tuple[str | None, str]] = set()
    selector = match_labels(target)

    if key == "deployments":
        replica_sets = {
            resource_name(rs)
            for rs in snapshot.get("replicasets", []) or []
            if resource_namespace(rs) == namespace and resource_name(rs) and is_owned_by(rs, "Deployment", name)
        }
        for pod in pods:
            pod_name = resource_name(pod)
            if resource_namespace(pod) != namespace or not pod_name:
                continue
            if any(is_owned_by(pod, "ReplicaSet", replica_set) for replica_set in replica_sets) or selector_matches(pod, selector):
                refs.add((namespace, pod_name))
        return refs

    if key == "replicasets":
        for pod in pods:
            pod_name = resource_name(pod)
            if resource_namespace(pod) == namespace and pod_name and (is_owned_by(pod, "ReplicaSet", name) or selector_matches(pod, selector)):
                refs.add((namespace, pod_name))
        return refs

    if key in {"daemonsets", "statefulsets", "jobs"}:
        owner_kind = KIND_LABELS[key]
        for pod in pods:
            pod_name = resource_name(pod)
            if resource_namespace(pod) == namespace and pod_name and (is_owned_by(pod, owner_kind, name) or selector_matches(pod, selector)):
                refs.add((namespace, pod_name))
        return refs

    if key == "cronjobs":
        jobs = {
            resource_name(job)
            for job in snapshot.get("jobs", []) or []
            if resource_namespace(job) == namespace and resource_name(job) and is_owned_by(job, "CronJob", name)
        }
        for pod in pods:
            pod_name = resource_name(pod)
            if resource_namespace(pod) == namespace and pod_name and any(is_owned_by(pod, "Job", job) for job in jobs):
                refs.add((namespace, pod_name))
        return refs

    if key == "services":
        selector = (target.get("spec") or {}).get("selector") or {}
        for pod in pods:
            pod_name = resource_name(pod)
            if resource_namespace(pod) == namespace and pod_name and selector_matches(pod, selector):
                refs.add((namespace, pod_name))
        return refs

    return refs

@router.get("/{clusterId}/resources/{kind}/{namespace}/{name}/logs", response_model=list[ResourceLogEntry])
async def resource_logs(clusterId: UUID, kind: str, namespace: str, name: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await resource_detail(clusterId, kind, namespace, name, user, session)
    key = normalize_resource_key(kind)
    expected_namespace = None if namespace == "_cluster" else namespace
    snapshot = await latest_snapshot_payload(clusterId, session)
    target_pods = related_pod_refs(snapshot, key, expected_namespace, name)
    if not target_pods:
        return []
    batches = (await session.execute(
        select(LogBatch)
        .where(LogBatch.cluster_id == clusterId, LogBatch.organization_id == user.organization_id)
        .order_by(LogBatch.created_at.desc())
        .limit(100)
    )).scalars().all()
    entries: list[ResourceLogEntry] = []
    try:
        reader = BlobReader()
    except RuntimeError:
        return []
    for batch in batches:
        try:
            data = reader.read_json_gz(batch.blob_path)
        except Exception:
            continue
        for record in data.get("logs", []) if isinstance(data, dict) else []:
            if not isinstance(record, dict):
                continue
            record_pod = record_field(record, "pod", "pod_name")
            record_namespace = record_field(record, "namespace", "namespace_name")
            if (record_namespace, record_pod) in target_pods:
                entries.append(log_entry_from(record))
                if len(entries) >= 1000:
                    return entries
    return entries
