import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.clusters.router import KIND_LABELS
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import AIIncident, AlertEvent, AlertLimit, Cluster, ClusterSnapshot, Issue
from app.notifications.events import build_alert_limit_triggered_event, publish_alert_limit_triggered_event
from app.storage.blob import BlobReader

log = logging.getLogger(__name__)

SUPPORTED_METRIC_TYPES = {
    "resource_health",
    "pod_restarts",
    "open_incidents",
    "critical_incidents",
    "major_incidents",
    "minor_incidents",
    "warning_events",
}

UNHEALTHY_STATUS_TOKENS = ("pending", "failed", "0/", "unavailable", "notready", "error")
ALERT_EVALUATION_LOCK_ID = 41723019


@dataclass
class AlertEvaluationResult:
    evaluated_limits: int = 0
    triggered_limits: int = 0
    skipped_cooldown: int = 0
    skipped_unsupported: int = 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compare_threshold(operator: str, actual: float, threshold: float) -> bool:
    if operator == "gt":
        return actual > threshold
    if operator == "gte":
        return actual >= threshold
    if operator == "lt":
        return actual < threshold
    if operator == "lte":
        return actual <= threshold
    if operator == "eq":
        return actual == threshold
    raise ValueError(f"Unsupported operator {operator}")


def operator_label(operator: str) -> str:
    return {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "=",
    }.get(operator, operator)


def metric_label(metric_type: str) -> str:
    return {
        "resource_health": "Resources needing attention",
        "pod_restarts": "Pod restart count",
        "open_incidents": "Open incidents",
        "critical_incidents": "Critical incidents",
        "major_incidents": "Major incidents",
        "minor_incidents": "Minor incidents",
        "warning_events": "Warning events",
    }.get(metric_type, metric_type)


def resource_metadata(resource: dict[str, Any]) -> dict[str, Any]:
    return resource.get("metadata") or {}


def resource_kind_label(snapshot_key: str) -> str:
    return KIND_LABELS.get(snapshot_key, snapshot_key.rstrip("s").title())


def resource_identifier(snapshot_key: str, resource: dict[str, Any]) -> str:
    metadata = resource_metadata(resource)
    namespace = metadata.get("namespace") or "_cluster"
    name = metadata.get("name") or "unknown"
    return f"{resource_kind_label(snapshot_key)}/{namespace}/{name}"


def resource_status(snapshot_key: str, resource: dict[str, Any]) -> str | None:
    status = resource.get("status") or {}
    spec = resource.get("spec") or {}
    if snapshot_key == "pods":
        return status.get("phase")
    if snapshot_key in {"deployments", "replicasets", "statefulsets"}:
        ready = status.get("readyReplicas") or status.get("availableReplicas") or 0
        desired = spec.get("replicas") or status.get("replicas") or 0
        return f"{ready}/{desired} ready"
    if snapshot_key == "daemonsets":
        ready = status.get("numberReady") or 0
        desired = status.get("desiredNumberScheduled") or 0
        return f"{ready}/{desired} ready"
    if snapshot_key == "services":
        return spec.get("type")
    if snapshot_key == "jobs":
        if status.get("failed"):
            return "Failed"
        if status.get("succeeded"):
            return "Succeeded"
        return "Running" if status.get("active") else None
    if snapshot_key == "cronjobs":
        return "Suspended" if spec.get("suspend") else "Active"
    if snapshot_key == "namespaces":
        return status.get("phase")
    return None


def restart_count(resource: dict[str, Any]) -> int:
    statuses = (resource.get("status") or {}).get("containerStatuses") or []
    return sum(int(item.get("restartCount") or 0) for item in statuses)


def workload_scope_match(resource: dict[str, Any], workload_name: str | None) -> bool:
    if not workload_name:
        return False
    metadata = resource_metadata(resource)
    if metadata.get("name") == workload_name:
        return True
    owner_refs = metadata.get("ownerReferences") or []
    return any(owner.get("name") == workload_name for owner in owner_refs if isinstance(owner, dict))


def resource_matches_scope(snapshot_key: str, resource: dict[str, Any], limit: AlertLimit) -> bool:
    metadata = resource_metadata(resource)
    if limit.scope_type == "cluster":
        return True
    if limit.scope_type == "namespace":
        return metadata.get("namespace") == limit.namespace
    if limit.scope_type == "workload":
        return workload_scope_match(resource, limit.workload_name)
    if limit.scope_type == "resource":
        return resource_identifier(snapshot_key, resource).lower() == (limit.resource_id or "").lower()
    return False


def issue_matches_scope(issue: Issue, limit: AlertLimit) -> bool:
    if limit.scope_type == "cluster":
        return True
    if limit.scope_type == "namespace":
        return issue.namespace == limit.namespace
    if limit.scope_type == "workload":
        return issue.workload == limit.workload_name or issue.pod_name == limit.workload_name
    if limit.scope_type == "resource":
        return (limit.resource_id or "").endswith(f"/{issue.namespace or '_cluster'}/{issue.pod_name or issue.workload or ''}")
    return False


def incident_matches_scope(incident: AIIncident, limit: AlertLimit) -> bool:
    if limit.scope_type == "cluster":
        return True
    if limit.scope_type == "namespace":
        return incident.namespace == limit.namespace
    if limit.scope_type == "workload":
        return incident.workload_name == limit.workload_name or incident.resource_name == limit.workload_name or incident.pod_name == limit.workload_name
    if limit.scope_type == "resource":
        return (limit.resource_id or "").endswith(f"/{incident.namespace or '_cluster'}/{incident.resource_name or incident.pod_name or ''}")
    return False


def is_unhealthy_resource(snapshot_key: str, resource: dict[str, Any]) -> bool:
    status_text = (resource_status(snapshot_key, resource) or "").lower()
    if any(token in status_text for token in UNHEALTHY_STATUS_TOKENS):
        return True
    if snapshot_key == "pods":
        for container in (resource.get("status") or {}).get("containerStatuses") or []:
            state = container.get("state") or {}
            waiting = state.get("waiting") or {}
            terminated = state.get("terminated") or {}
            if waiting.get("reason") or terminated.get("reason"):
                return True
    return False


class AlertEvaluationService:
    def __init__(self) -> None:
        self._blob_reader: BlobReader | None = None

    def _reader(self) -> BlobReader | None:
        if self._blob_reader is None:
            with contextlib.suppress(RuntimeError):
                self._blob_reader = BlobReader()
        return self._blob_reader

    async def _latest_snapshot_payload(self, session: AsyncSession, cluster_id: Any) -> dict[str, Any]:
        snapshot = (
            await session.execute(
                select(ClusterSnapshot)
                .where(ClusterSnapshot.cluster_id == cluster_id)
                .order_by(ClusterSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if not snapshot:
            return {}
        reader = self._reader()
        if reader is None:
            return {}
        try:
            data = reader.read_json_gz(snapshot.blob_path)
        except Exception:
            log.exception("failed to load snapshot blob for alert evaluation: %s", snapshot.blob_path)
            return {}
        return data.get("snapshot", {}) if isinstance(data, dict) else {}

    async def _metric_value(self, session: AsyncSession, cluster: Cluster, limit: AlertLimit) -> float | None:
        since = utcnow() - timedelta(minutes=limit.time_window_minutes)
        if limit.metric_type == "resource_health":
            snapshot = await self._latest_snapshot_payload(session, cluster.id)
            total = 0
            for snapshot_key in KIND_LABELS:
                for resource in snapshot.get(snapshot_key, []) or []:
                    if resource_matches_scope(snapshot_key, resource, limit) and is_unhealthy_resource(snapshot_key, resource):
                        total += 1
            return float(total)

        if limit.metric_type == "pod_restarts":
            snapshot = await self._latest_snapshot_payload(session, cluster.id)
            max_restart = 0
            for resource in snapshot.get("pods", []) or []:
                if resource_matches_scope("pods", resource, limit):
                    max_restart = max(max_restart, restart_count(resource))
            return float(max_restart)

        if limit.metric_type in {"open_incidents", "critical_incidents", "major_incidents", "minor_incidents"}:
            rows = (
                await session.execute(
                    select(AIIncident).where(
                        AIIncident.cluster_id == cluster.id,
                        AIIncident.organization_id == limit.organization_id,
                        AIIncident.status == "open",
                        AIIncident.last_seen_at >= since,
                    )
                )
            ).scalars().all()
            matches = [
                incident
                for incident in rows
                if incident_matches_scope(incident, limit)
                and (
                    limit.metric_type == "open_incidents"
                    or incident.severity == limit.metric_type.replace("_incidents", "")
                )
            ]
            return float(len(matches))

        if limit.metric_type == "warning_events":
            rows = (
                await session.execute(
                    select(Issue).where(
                        Issue.cluster_id == cluster.id,
                        Issue.organization_id == limit.organization_id,
                        Issue.last_seen_at >= since,
                    )
                )
            ).scalars().all()
            matches = [
                issue
                for issue in rows
                if issue_matches_scope(issue, limit)
                and (issue.issue_type.startswith("KubernetesEvent") or issue.issue_type == "FailedScheduling")
            ]
            return float(len(matches))

        return None

    async def evaluate_limit(self, session: AsyncSession, cluster: Cluster, limit: AlertLimit) -> bool:
        metric_value = await self._metric_value(session, cluster, limit)
        if metric_value is None:
            return False
        if not compare_threshold(limit.operator, metric_value, limit.threshold_value):
            return False

        now = utcnow()
        event = AlertEvent(
            organization_id=limit.organization_id,
            cluster_id=cluster.id,
            alert_limit_id=limit.id,
            metric_value=metric_value,
            threshold_value=limit.threshold_value,
            triggered_at=now,
            notification_sent=False,
        )
        limit.last_triggered_at = now

        if limit.email_enabled and limit.notification_email:
            try:
                queued = await asyncio.to_thread(
                    publish_alert_limit_triggered_event,
                    build_alert_limit_triggered_event(
                        organization_id=limit.organization_id,
                        cluster_id=cluster.id,
                        recipient_email=limit.notification_email,
                        cluster_name=cluster.name,
                        alert_limit_id=limit.id,
                        alert_limit_name=limit.name,
                        metric_type=limit.metric_type,
                        metric_label=metric_label(limit.metric_type),
                        threshold_value=limit.threshold_value,
                        actual_value=metric_value,
                        operator=operator_label(limit.operator),
                        severity=limit.severity,
                        time_window_minutes=limit.time_window_minutes,
                        dashboard_url=f"{settings.public_app_url.rstrip('/')}/dashboard/clusters/{cluster.id}/limits",
                    ),
                )
                event.notification_sent = queued
                if not queued:
                    event.notification_error = "notification queue not configured"
            except Exception as exc:
                log.exception("failed to queue alert notification for limit %s: %s", limit.id, exc)
                event.notification_error = "publish_failed"

        session.add(event)
        await write_audit(
            session,
            "alert_limit.triggered",
            "system",
            limit.organization_id,
            cluster_id=cluster.id,
            details={
                "alert_limit_id": str(limit.id),
                "alert_limit_name": limit.name,
                "metric_type": limit.metric_type,
                "metric_value": metric_value,
                "threshold_value": limit.threshold_value,
            },
        )
        await session.commit()
        return True

    async def evaluate_pending_limits(self, session: AsyncSession) -> AlertEvaluationResult:
        result = AlertEvaluationResult()
        limits = (
            await session.execute(
                select(AlertLimit, Cluster)
                .join(Cluster, Cluster.id == AlertLimit.cluster_id)
                .where(AlertLimit.enabled.is_(True))
                .order_by(AlertLimit.created_at.asc())
            )
        ).all()
        now = utcnow()
        for limit, cluster in limits:
            result.evaluated_limits += 1
            if limit.metric_type not in SUPPORTED_METRIC_TYPES:
                result.skipped_unsupported += 1
                continue
            if limit.last_triggered_at and limit.last_triggered_at >= now - timedelta(minutes=limit.cooldown_minutes):
                result.skipped_cooldown += 1
                continue
            triggered = await self.evaluate_limit(session, cluster, limit)
            if triggered:
                result.triggered_limits += 1
        return result


async def evaluate_alerts_once() -> AlertEvaluationResult:
    async with SessionLocal() as session:
        lock_acquired = False
        if session.bind and session.bind.dialect.name == "postgresql":
            lock_acquired = bool(
                (
                    await session.execute(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": ALERT_EVALUATION_LOCK_ID},
                    )
                ).scalar()
            )
            if not lock_acquired:
                return AlertEvaluationResult()
        service = AlertEvaluationService()
        try:
            return await service.evaluate_pending_limits(session)
        finally:
            if lock_acquired:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": ALERT_EVALUATION_LOCK_ID},
                )
