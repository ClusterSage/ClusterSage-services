from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.auth.dependencies import get_current_user
from app.db.session import get_session
from app.models.entities import AlertEvent, AlertLimit, Cluster, User
from app.schemas.api import (
    AlertEventResponse,
    AlertLimitCreateRequest,
    AlertLimitResponse,
    AlertLimitUpdateRequest,
)

router = APIRouter(prefix="/api/clusters", tags=["alerts"])

SUPPORTED_METRIC_TYPES = {
    "resource_health",
    "pod_restarts",
    "open_incidents",
    "critical_incidents",
    "major_incidents",
    "minor_incidents",
    "warning_events",
}

CLUSTER_ONLY_METRICS = {
    "open_incidents",
    "critical_incidents",
    "major_incidents",
    "minor_incidents",
    "warning_events",
}


async def get_cluster(cluster_id: UUID, user: User, session: AsyncSession) -> Cluster:
    cluster = await session.get(Cluster, cluster_id)
    if not cluster or cluster.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


async def get_alert_limit(cluster_id: UUID, limit_id: UUID, user: User, session: AsyncSession) -> AlertLimit:
    row = (
        await session.execute(
            select(AlertLimit).where(
                AlertLimit.id == limit_id,
                AlertLimit.cluster_id == cluster_id,
                AlertLimit.organization_id == user.organization_id,
            )
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Alert limit not found")
    return row


def validate_metric_scope(metric_type: str, scope_type: str, namespace: str | None, workload_name: str | None, resource_id: str | None) -> None:
    if metric_type not in SUPPORTED_METRIC_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported metric type: {metric_type}")
    if metric_type in CLUSTER_ONLY_METRICS and scope_type != "cluster":
        raise HTTPException(status_code=400, detail=f"Metric type {metric_type} only supports cluster scope")
    if scope_type == "namespace" and not namespace:
        raise HTTPException(status_code=400, detail="namespace is required for namespace scope")
    if scope_type == "workload" and not workload_name:
        raise HTTPException(status_code=400, detail="workload_name is required for workload scope")
    if scope_type == "resource" and not resource_id:
        raise HTTPException(status_code=400, detail="resource_id is required for resource scope")


def normalize_notification_email(value: str | None, fallback: str) -> str:
    return (value or fallback).strip().lower()


@router.get("/{clusterId}/limits", response_model=list[AlertLimitResponse])
async def list_alert_limits(
    clusterId: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    return (
        await session.execute(
            select(AlertLimit)
            .where(
                AlertLimit.cluster_id == clusterId,
                AlertLimit.organization_id == user.organization_id,
            )
            .order_by(AlertLimit.created_at.desc())
        )
    ).scalars().all()


@router.post("/{clusterId}/limits", response_model=AlertLimitResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_limit(
    clusterId: UUID,
    body: AlertLimitCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    validate_metric_scope(body.metric_type, body.scope_type, body.namespace, body.workload_name, body.resource_id)
    limit = AlertLimit(
        organization_id=user.organization_id,
        cluster_id=clusterId,
        created_by_user_id=user.id,
        name=body.name,
        metric_type=body.metric_type,
        scope_type=body.scope_type,
        namespace=body.namespace,
        workload_name=body.workload_name,
        resource_id=body.resource_id,
        operator=body.operator,
        threshold_value=body.threshold_value,
        time_window_minutes=body.time_window_minutes,
        severity=body.severity,
        email_enabled=body.email_enabled,
        notification_email=normalize_notification_email(body.notification_email, user.email),
        enabled=body.enabled,
        cooldown_minutes=body.cooldown_minutes,
    )
    session.add(limit)
    await write_audit(
        session,
        "alert_limit.created",
        "user",
        user.organization_id,
        user.id,
        clusterId,
        details={
            "alert_limit_name": body.name,
            "metric_type": body.metric_type,
            "scope_type": body.scope_type,
            "severity": body.severity,
        },
    )
    await session.commit()
    await session.refresh(limit)
    return limit


@router.patch("/{clusterId}/limits/{limitId}", response_model=AlertLimitResponse)
async def update_alert_limit(
    clusterId: UUID,
    limitId: UUID,
    body: AlertLimitUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    limit = await get_alert_limit(clusterId, limitId, user, session)

    updates = body.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(limit, field_name, value)

    if "notification_email" in updates:
        limit.notification_email = normalize_notification_email(updates.get("notification_email"), user.email)

    validate_metric_scope(limit.metric_type, limit.scope_type, limit.namespace, limit.workload_name, limit.resource_id)
    await write_audit(
        session,
        "alert_limit.updated",
        "user",
        user.organization_id,
        user.id,
        clusterId,
        details={
            "alert_limit_id": str(limit.id),
            "updated_fields": sorted(updates.keys()),
            "metric_type": limit.metric_type,
        },
    )
    await session.commit()
    await session.refresh(limit)
    return limit


@router.post("/{clusterId}/limits/{limitId}/enable", response_model=AlertLimitResponse)
async def enable_alert_limit(
    clusterId: UUID,
    limitId: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    limit = await get_alert_limit(clusterId, limitId, user, session)
    limit.enabled = True
    await write_audit(
        session,
        "alert_limit.enabled",
        "user",
        user.organization_id,
        user.id,
        clusterId,
        details={"alert_limit_id": str(limit.id), "metric_type": limit.metric_type},
    )
    await session.commit()
    await session.refresh(limit)
    return limit


@router.post("/{clusterId}/limits/{limitId}/disable", response_model=AlertLimitResponse)
async def disable_alert_limit(
    clusterId: UUID,
    limitId: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    limit = await get_alert_limit(clusterId, limitId, user, session)
    limit.enabled = False
    await write_audit(
        session,
        "alert_limit.disabled",
        "user",
        user.organization_id,
        user.id,
        clusterId,
        details={"alert_limit_id": str(limit.id), "metric_type": limit.metric_type},
    )
    await session.commit()
    await session.refresh(limit)
    return limit


@router.delete("/{clusterId}/limits/{limitId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_limit(
    clusterId: UUID,
    limitId: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    limit = await get_alert_limit(clusterId, limitId, user, session)
    await write_audit(
        session,
        "alert_limit.deleted",
        "user",
        user.organization_id,
        user.id,
        clusterId,
        details={"alert_limit_id": str(limit.id), "metric_type": limit.metric_type, "name": limit.name},
    )
    await session.delete(limit)
    await session.commit()
    return None


@router.get("/{clusterId}/alert-events", response_model=list[AlertEventResponse])
async def list_alert_events(
    clusterId: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_cluster(clusterId, user, session)
    return (
        await session.execute(
            select(AlertEvent)
            .where(
                AlertEvent.cluster_id == clusterId,
                AlertEvent.organization_id == user.organization_id,
            )
            .order_by(AlertEvent.triggered_at.desc(), AlertEvent.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
