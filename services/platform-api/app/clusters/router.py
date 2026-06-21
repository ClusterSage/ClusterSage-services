from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.ai.agent.orchestrator import ClusterAgentOrchestrator
from app.ai.client import AzureAIFoundryRateLimitError
from app.ai.cluster_query import ClusterQueryService
from app.audit.service import write_audit
from app.auth.dependencies import get_current_user
from app.db.session import get_session
from app.core.config import settings
from app.metrics import (
    build_latest_metric_response,
    build_metric_filter_catalog,
    build_metric_timeseries_response,
    build_metrics_overview,
    metrics_window_start,
)
from app.models.entities import AIConversation, AIIncident, AIMessage, Cluster, ClusterMetricSample, ClusterSnapshot, Issue, LogBatch, RemediationAction, RemediationApproval, RemediationSuggestion, User
from app.schemas.api import AIChatRequest, AIChatResponse, AIClusterQueryRequest, AIClusterQueryResponse, AIConversationDetailResponse, AIConversationMessageResponse, AIConversationResponse, AIIncidentResponse, ClusterMetricFilterCatalogResponse, ClusterMetricLatestResponse, ClusterMetricsOverviewResponse, ClusterMetricTimeseriesResponse, ClusterResponse, IssueResponse, LogBatchResponse, ResourceAISuggestionResponse, ResourceLogEntry, ResourceSummary, SnapshotResponse
from app.storage.blob import BlobReader

router = APIRouter(prefix="/api/clusters", tags=["clusters"])
cluster_query_service = ClusterQueryService()
cluster_agent_orchestrator = ClusterAgentOrchestrator()

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
async def delete_cluster(clusterId: UUID, request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    cluster = await get_cluster(clusterId, user, session)
    await write_audit(
        session,
        "cluster.deleted",
        "user",
        user.organization_id,
        user.id,
        cluster.id,
        {"cluster_name": cluster.name, "provider": cluster.provider},
        ip_address=request.client.host if request.client else None,
    )
    await session.delete(cluster)
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


async def latest_metrics_timestamp(cluster_id: UUID, organization_id: UUID, session: AsyncSession) -> datetime | None:
    return (
        await session.execute(
            select(ClusterMetricSample.collected_at)
            .where(
                ClusterMetricSample.cluster_id == cluster_id,
                ClusterMetricSample.organization_id == organization_id,
            )
            .order_by(ClusterMetricSample.collected_at.desc())
            .limit(1)
        )
    ).scalars().first()


def apply_metric_filters(
    query,
    *,
    cluster_id: UUID,
    organization_id: UUID,
    metric_name: str | None = None,
    scope: str | None = None,
    namespace: str | None = None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    node_name: str | None = None,
    container_name: str | None = None,
):
    query = query.where(
        ClusterMetricSample.cluster_id == cluster_id,
        ClusterMetricSample.organization_id == organization_id,
    )
    if metric_name:
        query = query.where(ClusterMetricSample.metric_name == metric_name)
    if scope:
        query = query.where(ClusterMetricSample.scope == scope)
    if namespace:
        query = query.where(ClusterMetricSample.namespace == namespace)
    if resource_kind:
        query = query.where(ClusterMetricSample.resource_kind == resource_kind)
    if resource_name:
        query = query.where(ClusterMetricSample.resource_name == resource_name)
    if node_name:
        query = query.where(ClusterMetricSample.node_name == node_name)
    if container_name:
        query = query.where(ClusterMetricSample.container_name == container_name)
    return query

@router.get("/{clusterId}/metrics/overview", response_model=ClusterMetricsOverviewResponse)
async def cluster_metrics_overview(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    latest_collected_at = await latest_metrics_timestamp(clusterId, user.organization_id, session)
    if latest_collected_at is None:
        return ClusterMetricsOverviewResponse()
    samples = (
        await session.execute(
            apply_metric_filters(
                select(ClusterMetricSample),
                cluster_id=clusterId,
                organization_id=user.organization_id,
            ).where(ClusterMetricSample.collected_at == latest_collected_at)
        )
    ).scalars().all()
    return build_metrics_overview(samples, latest_collected_at)


@router.get("/{clusterId}/metrics/catalog", response_model=ClusterMetricFilterCatalogResponse)
async def cluster_metrics_catalog(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_cluster(clusterId, user, session)
    latest_collected_at = await latest_metrics_timestamp(clusterId, user.organization_id, session)
    if latest_collected_at is None:
        return ClusterMetricFilterCatalogResponse()
    samples = (
        await session.execute(
            apply_metric_filters(
                select(ClusterMetricSample),
                cluster_id=clusterId,
                organization_id=user.organization_id,
            ).where(ClusterMetricSample.collected_at == latest_collected_at)
        )
    ).scalars().all()
    return build_metric_filter_catalog(samples, latest_collected_at)


@router.get("/{clusterId}/metrics/latest", response_model=ClusterMetricLatestResponse)
async def cluster_metric_latest(
    clusterId: UUID,
    metric_name: str,
    scope: str | None = None,
    namespace: str | None = None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    node_name: str | None = None,
    container_name: str | None = None,
    limit: int = 12,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    latest_collected_at = await latest_metrics_timestamp(clusterId, user.organization_id, session)
    if latest_collected_at is None:
        return ClusterMetricLatestResponse(metric_name=metric_name)
    samples = (
        await session.execute(
            apply_metric_filters(
                select(ClusterMetricSample),
                cluster_id=clusterId,
                organization_id=user.organization_id,
                metric_name=metric_name,
                scope=scope,
                namespace=namespace,
                resource_kind=resource_kind,
                resource_name=resource_name,
                node_name=node_name,
                container_name=container_name,
            ).where(ClusterMetricSample.collected_at == latest_collected_at)
        )
    ).scalars().all()
    return build_latest_metric_response(samples, metric_name=metric_name, collected_at=latest_collected_at, limit=max(1, min(limit, 50)))


@router.get("/{clusterId}/metrics/timeseries", response_model=ClusterMetricTimeseriesResponse)
async def cluster_metric_timeseries(
    clusterId: UUID,
    metric_name: str,
    scope: str | None = None,
    namespace: str | None = None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    node_name: str | None = None,
    container_name: str | None = None,
    window_minutes: int = 180,
    step_minutes: int = 5,
    limit: int = 8,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    window_minutes = max(5, min(window_minutes, 24 * 60))
    step_minutes = max(1, min(step_minutes, 60))
    limit = max(1, min(limit, 20))
    window_start = metrics_window_start(datetime.now(timezone.utc), window_minutes)
    samples = (
        await session.execute(
            apply_metric_filters(
                select(ClusterMetricSample),
                cluster_id=clusterId,
                organization_id=user.organization_id,
                metric_name=metric_name,
                scope=scope,
                namespace=namespace,
                resource_kind=resource_kind,
                resource_name=resource_name,
                node_name=node_name,
                container_name=container_name,
            )
            .where(ClusterMetricSample.collected_at >= window_start)
            .order_by(ClusterMetricSample.collected_at.asc())
        )
    ).scalars().all()
    return build_metric_timeseries_response(
        samples,
        metric_name=metric_name,
        window_minutes=window_minutes,
        step_minutes=step_minutes,
        limit=limit,
    )

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

def incident_matches_resource(
    incident: AIIncident,
    key: str,
    expected_namespace: str | None,
    name: str,
    target_pods: set[tuple[str | None, str]],
) -> bool:
    if key == "namespaces":
        return incident.namespace == name
    if key == "pods":
        return incident.namespace == expected_namespace and incident.pod_name == name
    if incident.namespace is not None and incident.pod_name is not None and (incident.namespace, incident.pod_name) in target_pods:
        return True
    if incident.namespace == expected_namespace and incident.workload_name == name:
        return True
    if incident.namespace == expected_namespace and incident.resource_name == name:
        return True
    return False

async def incidents_for_resource(
    cluster_id: UUID,
    user: User,
    session: AsyncSession,
    kind: str,
    namespace: str,
    name: str,
) -> list[AIIncident]:
    await resource_detail(cluster_id, kind, namespace, name, user, session)
    key = normalize_resource_key(kind)
    expected_namespace = None if namespace == "_cluster" else namespace
    snapshot = await latest_snapshot_payload(cluster_id, session)
    target_pods = related_pod_refs(snapshot, key, expected_namespace, name)

    incidents = (
        await session.execute(
            select(AIIncident)
            .where(
                AIIncident.cluster_id == cluster_id,
                AIIncident.organization_id == user.organization_id,
            )
            .order_by(AIIncident.last_seen_at.desc(), AIIncident.created_at.desc())
        )
    ).scalars().all()

    return [
        incident
        for incident in incidents
        if incident_matches_resource(incident, key, expected_namespace, name, target_pods)
    ]


async def cluster_incident_rows(cluster_id: UUID, user: User, session: AsyncSession) -> list[AIIncident]:
    await get_cluster(cluster_id, user, session)
    return (
        await session.execute(
            select(AIIncident)
            .where(
                AIIncident.cluster_id == cluster_id,
                AIIncident.organization_id == user.organization_id,
            )
            .order_by(AIIncident.last_seen_at.desc(), AIIncident.created_at.desc())
            .limit(500)
        )
    ).scalars().all()

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

@router.get("/{clusterId}/resources/{kind}/{namespace}/{name}/incidents", response_model=list[AIIncidentResponse])
async def resource_incidents(clusterId: UUID, kind: str, namespace: str, name: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await incidents_for_resource(clusterId, user, session, kind, namespace, name)


@router.get("/{clusterId}/incidents", response_model=list[AIIncidentResponse])
async def cluster_incidents(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await cluster_incident_rows(clusterId, user, session)


def conversation_response_from(row: AIConversation) -> AIConversationResponse:
    return AIConversationResponse.model_validate(row)


def message_response_from(row: AIMessage) -> AIConversationMessageResponse:
    return AIConversationMessageResponse.model_validate(row)


@router.post("/{clusterId}/ai/chat", response_model=AIChatResponse)
async def cluster_ai_chat(clusterId: UUID, body: AIChatRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not settings.ai_agent_enabled:
        raise HTTPException(status_code=403, detail="AI agent is disabled in this environment")
    cluster = await get_cluster(clusterId, user, session)
    try:
        conversation, assistant_message = await cluster_agent_orchestrator.chat(
            session=session,
            cluster=cluster,
            user=user,
            message=body.message,
            conversation_id=str(body.conversation_id) if body.conversation_id else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AzureAIFoundryRateLimitError as exc:
        raise HTTPException(status_code=429, detail="AI provider is rate limited. Please retry in a moment.") from exc
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "AI provider unavailable":
            raise HTTPException(status_code=503, detail="AI provider unavailable") from exc
        raise HTTPException(status_code=403, detail=detail) from exc
    return AIChatResponse(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        answer=assistant_message.content,
        evidence=assistant_message.evidence_references or [],
        confidence=assistant_message.confidence or "low",
        data_freshness=assistant_message.data_freshness or {},
        tools_used=[item.get("tool_name") for item in (assistant_message.tool_execution_metadata or []) if isinstance(item, dict) and item.get("tool_name")],
        created_at=assistant_message.created_at,
    )


@router.get("/{clusterId}/ai/conversations", response_model=list[AIConversationResponse])
async def cluster_ai_conversations(clusterId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not settings.ai_agent_enabled:
        raise HTTPException(status_code=403, detail="AI agent is disabled in this environment")
    cluster = await get_cluster(clusterId, user, session)
    rows = await cluster_agent_orchestrator.list_conversations(session=session, cluster=cluster, user=user)
    return [conversation_response_from(row) for row in rows]


@router.get("/{clusterId}/ai/conversations/{conversationId}", response_model=AIConversationDetailResponse)
async def cluster_ai_conversation_detail(clusterId: UUID, conversationId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not settings.ai_agent_enabled:
        raise HTTPException(status_code=403, detail="AI agent is disabled in this environment")
    cluster = await get_cluster(clusterId, user, session)
    try:
        conversation, messages = await cluster_agent_orchestrator.get_conversation(
            session=session,
            cluster=cluster,
            user=user,
            conversation_id=str(conversationId),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AIConversationDetailResponse(
        conversation=conversation_response_from(conversation),
        messages=[message_response_from(message) for message in messages],
    )


@router.post("/{clusterId}/ai/query", response_model=AIClusterQueryResponse)
async def cluster_ai_query(clusterId: UUID, body: AIClusterQueryRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not settings.ai_cluster_query_enabled:
        raise HTTPException(status_code=403, detail="Cluster AI queries are disabled in this environment")
    cluster = await get_cluster(clusterId, user, session)
    query = await cluster_query_service.run(session=session, cluster=cluster, user=user, question=body.question)
    await write_audit(
        session,
        "cluster.ai_query.requested",
        "user",
        user.organization_id,
        user.id,
        cluster.id,
        details={"query_id": str(query.id), "intent": (query.parsed_query or {}).get("intent")},
    )
    await session.commit()
    return query

@router.get("/{clusterId}/resources/{kind}/{namespace}/{name}/ai-suggestions", response_model=list[ResourceAISuggestionResponse])
async def resource_ai_suggestions(clusterId: UUID, kind: str, namespace: str, name: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    incidents = await incidents_for_resource(clusterId, user, session, kind, namespace, name)
    if not incidents:
        return []

    incident_ids = [incident.id for incident in incidents]
    incident_map = {incident.id: incident for incident in incidents}
    rows = (
        await session.execute(
            select(RemediationSuggestion)
            .where(
                RemediationSuggestion.cluster_id == clusterId,
                RemediationSuggestion.organization_id == user.organization_id,
                RemediationSuggestion.incident_id.in_(incident_ids),
            )
            .order_by(RemediationSuggestion.updated_at.desc(), RemediationSuggestion.created_at.desc())
        )
    ).scalars().all()
    suggestion_ids = [suggestion.id for suggestion in rows]
    if not suggestion_ids:
        return []
    approval_rows = (
        await session.execute(
            select(RemediationApproval)
            .where(
                RemediationApproval.cluster_id == clusterId,
                RemediationApproval.organization_id == user.organization_id,
                RemediationApproval.suggestion_id.in_(suggestion_ids),
            )
        )
    ).scalars().all()
    action_rows = (
        await session.execute(
            select(RemediationAction)
            .where(
                RemediationAction.cluster_id == clusterId,
                RemediationAction.organization_id == user.organization_id,
                RemediationAction.suggestion_id.in_(suggestion_ids),
            )
        )
    ).scalars().all()
    latest_approvals: dict[UUID, RemediationApproval] = {}
    for approval in approval_rows:
        current = latest_approvals.get(approval.suggestion_id)
        if current is None or approval.created_at >= current.created_at:
            latest_approvals[approval.suggestion_id] = approval
    latest_actions: dict[UUID, RemediationAction] = {}
    for action in action_rows:
        current = latest_actions.get(action.suggestion_id)
        if current is None or action.requested_at >= current.requested_at:
            latest_actions[action.suggestion_id] = action

    response: list[ResourceAISuggestionResponse] = []
    for suggestion in rows:
        incident = incident_map.get(suggestion.incident_id)
        if not incident:
            continue
        latest_approval = latest_approvals.get(suggestion.id)
        latest_action = latest_actions.get(suggestion.id)
        approval_available = False
        approval_block_reason: str | None = None
        if suggestion.suggestion_type == "rollout_restart":
            if latest_action and latest_action.status in {"queued", "picked_up", "running", "succeeded"}:
                approval_block_reason = f"Action already {latest_action.status.replace('_', ' ')}"
            elif not settings.remediation_approval_enabled:
                approval_block_reason = "Remediation approvals are disabled"
            elif not settings.agent_remediation_enabled:
                approval_block_reason = "Agent remediation is disabled in this environment"
            elif not suggestion.requires_approval:
                approval_block_reason = "This suggestion is not configured for approvals"
            elif not suggestion.is_executable or suggestion.executable_action_type != "rollout_restart":
                approval_block_reason = "This suggestion is advisory only and cannot be executed yet"
            else:
                payload = suggestion.action_payload if isinstance(suggestion.action_payload, dict) else {}
                if payload.get("workload_kind") != "Deployment" or not payload.get("workload_name") or not payload.get("namespace"):
                    approval_block_reason = "The deployment target for this restart is incomplete"
                else:
                    approval_available = True
        response.append(
            ResourceAISuggestionResponse(
                id=suggestion.id,
                cluster_id=suggestion.cluster_id,
                incident_id=suggestion.incident_id,
                incident_title=incident.title,
                incident_severity=incident.severity,
                incident_status=incident.status,
                resource_kind=suggestion.resource_kind,
                resource_name=suggestion.resource_name,
                suggestion_type=suggestion.suggestion_type,
                title=suggestion.title,
                summary=suggestion.summary,
                risk_level=suggestion.risk_level,
                requires_approval=suggestion.requires_approval,
                is_executable=suggestion.is_executable,
                executable_action_type=suggestion.executable_action_type,
                action_payload=suggestion.action_payload,
                ai_model=suggestion.ai_model,
                prompt_version=suggestion.prompt_version,
                confidence_score=suggestion.confidence_score,
                latest_approval_status=latest_approval.approval_status if latest_approval else None,
                latest_action_id=latest_action.id if latest_action else None,
                latest_action_status=latest_action.status if latest_action else None,
                approval_available=approval_available,
                approval_block_reason=approval_block_reason,
                created_at=suggestion.created_at,
                updated_at=suggestion.updated_at,
            )
        )
    return response
