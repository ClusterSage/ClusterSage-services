from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_session
from app.models.entities import RemediationAction, RemediationApproval, RemediationSuggestion, User
from app.schemas.api import (
    RemediationActionResponse,
    RemediationApprovalResultResponse,
    RemediationDecisionRequest,
)

router = APIRouter(tags=["remediation"])

ACTIVE_ACTION_STATUSES = {"queued", "picked_up", "running"}
TERMINAL_OR_BUSY_ACTION_STATUSES = ACTIVE_ACTION_STATUSES | {"succeeded"}
APPROVAL_ROLES = {"owner", "admin"}


async def get_suggestion_for_user(session: AsyncSession, suggestion_id: UUID, user: User) -> RemediationSuggestion:
    suggestion = (
        await session.execute(
            select(RemediationSuggestion).where(
                RemediationSuggestion.id == suggestion_id,
                RemediationSuggestion.organization_id == user.organization_id,
            )
        )
    ).scalars().first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Remediation suggestion not found")
    return suggestion


async def latest_action_for_suggestion(session: AsyncSession, suggestion_id: UUID) -> RemediationAction | None:
    return (
        await session.execute(
            select(RemediationAction)
            .where(RemediationAction.suggestion_id == suggestion_id)
            .order_by(RemediationAction.requested_at.desc(), RemediationAction.id.desc())
            .limit(1)
        )
    ).scalars().first()


def ensure_approval_permissions(user: User) -> None:
    if user.role not in APPROVAL_ROLES:
        raise HTTPException(status_code=403, detail="You do not have permission to approve remediation actions")


def validate_rollout_restart_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=409, detail="Remediation suggestion does not contain an executable action payload")
    workload_kind = str(payload.get("workload_kind") or "")
    workload_name = str(payload.get("workload_name") or "")
    namespace = str(payload.get("namespace") or "")
    if workload_kind != "Deployment":
        raise HTTPException(status_code=409, detail="Only Deployment rollout restarts are supported in this phase")
    if not workload_name or not namespace:
        raise HTTPException(status_code=409, detail="Remediation suggestion is missing a valid deployment target")
    return {
        "workload_kind": workload_kind,
        "workload_name": workload_name,
        "namespace": namespace,
    }


@router.post("/api/remediation-suggestions/{suggestionId}/approve", response_model=RemediationApprovalResultResponse)
async def approve_remediation_suggestion(
    suggestionId: UUID,
    payload: RemediationDecisionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not settings.remediation_approval_enabled:
        raise HTTPException(status_code=409, detail="Remediation approvals are currently disabled")
    if not settings.agent_remediation_enabled:
        raise HTTPException(status_code=409, detail="Agent remediation is disabled in this environment")

    ensure_approval_permissions(user)
    suggestion = await get_suggestion_for_user(session, suggestionId, user)

    if payload.confirmation_text != "APPROVE":
        raise HTTPException(status_code=400, detail='Type "APPROVE" to confirm this remediation request')
    if not suggestion.requires_approval:
        raise HTTPException(status_code=409, detail="This suggestion does not require an approval workflow")
    if not suggestion.is_executable or suggestion.executable_action_type != "rollout_restart":
        raise HTTPException(status_code=409, detail="This suggestion is not currently executable")

    action_payload = validate_rollout_restart_payload(suggestion.action_payload)
    existing_action = await latest_action_for_suggestion(session, suggestion.id)
    if existing_action and existing_action.status in TERMINAL_OR_BUSY_ACTION_STATUSES:
        message = (
            "A remediation action is already in progress for this suggestion"
            if existing_action.status in ACTIVE_ACTION_STATUSES
            else "This remediation suggestion has already produced an action"
        )
        raise HTTPException(status_code=409, detail=message)

    now = datetime.now(timezone.utc)
    approval = RemediationApproval(
        organization_id=user.organization_id,
        cluster_id=suggestion.cluster_id,
        suggestion_id=suggestion.id,
        approved_by_user_id=user.id,
        approval_status="approved",
        approval_reason=payload.approval_reason,
        approved_at=now,
    )
    session.add(approval)
    await session.flush()

    action = RemediationAction(
        organization_id=user.organization_id,
        cluster_id=suggestion.cluster_id,
        suggestion_id=suggestion.id,
        approval_id=approval.id,
        action_type="rollout_restart",
        action_payload=action_payload,
        status="queued",
        requested_by_user_id=user.id,
        requested_at=now,
    )
    session.add(action)
    await write_audit(
        session,
        "remediation.approved",
        "user",
        user.organization_id,
        user.id,
        suggestion.cluster_id,
        {
            "suggestion_id": str(suggestion.id),
            "action_id": str(action.id),
            "action_type": action.action_type,
            "namespace": action_payload["namespace"],
            "workload_kind": action_payload["workload_kind"],
            "workload_name": action_payload["workload_name"],
            "approval_reason": payload.approval_reason,
        },
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    return RemediationApprovalResultResponse(
        suggestion_id=suggestion.id,
        approval_id=approval.id,
        approval_status=approval.approval_status,
        action_id=action.id,
        action_status=action.status,
        message="Remediation action queued for agent pickup",
    )


@router.post("/api/remediation-suggestions/{suggestionId}/reject", response_model=RemediationApprovalResultResponse)
async def reject_remediation_suggestion(
    suggestionId: UUID,
    payload: RemediationDecisionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not settings.remediation_approval_enabled:
        raise HTTPException(status_code=409, detail="Remediation approvals are currently disabled")

    ensure_approval_permissions(user)
    suggestion = await get_suggestion_for_user(session, suggestionId, user)
    existing_action = await latest_action_for_suggestion(session, suggestion.id)
    if existing_action and existing_action.status in TERMINAL_OR_BUSY_ACTION_STATUSES:
        raise HTTPException(status_code=409, detail="This suggestion already has an action and can no longer be rejected")

    approval = RemediationApproval(
        organization_id=user.organization_id,
        cluster_id=suggestion.cluster_id,
        suggestion_id=suggestion.id,
        approved_by_user_id=user.id,
        approval_status="rejected",
        approval_reason=payload.approval_reason,
        rejected_at=datetime.now(timezone.utc),
    )
    session.add(approval)
    await write_audit(
        session,
        "remediation.rejected",
        "user",
        user.organization_id,
        user.id,
        suggestion.cluster_id,
        {
            "suggestion_id": str(suggestion.id),
            "approval_reason": payload.approval_reason,
        },
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    return RemediationApprovalResultResponse(
        suggestion_id=suggestion.id,
        approval_id=approval.id,
        approval_status=approval.approval_status,
        action_id=None,
        action_status=None,
        message="Remediation suggestion rejected",
    )


@router.get("/api/remediation-actions/{actionId}", response_model=RemediationActionResponse)
async def get_remediation_action(
    actionId: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    action = (
        await session.execute(
            select(RemediationAction).where(
                RemediationAction.id == actionId,
                RemediationAction.organization_id == user.organization_id,
            )
        )
    ).scalars().first()
    if not action:
        raise HTTPException(status_code=404, detail="Remediation action not found")
    return action
