from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.models import AgentExecutionContext
from app.ai.agent.safeguards import safe_reference
from app.core.config import settings
from app.models.entities import ClusterSnapshot
from app.storage.blob import BlobReader


class WorkloadStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(min_length=1, max_length=100)
    workload_name: str = Field(min_length=1, max_length=255)
    workload_kind: str | None = Field(default=None, max_length=80)


class EmptyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _latest_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return snapshot.get("snapshot", {}) if isinstance(snapshot, dict) else {}


async def _load_snapshot_row(session: AsyncSession, ctx: AgentExecutionContext) -> ClusterSnapshot | None:
    return (
        await session.execute(
            select(ClusterSnapshot)
            .where(
                ClusterSnapshot.organization_id == ctx.tenant_id,
                ClusterSnapshot.cluster_id == ctx.cluster_id,
            )
            .order_by(ClusterSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def _load_snapshot(session: AsyncSession, ctx: AgentExecutionContext) -> tuple[ClusterSnapshot | None, dict[str, Any]]:
    row = await _load_snapshot_row(session, ctx)
    if row is None:
        return None, {}
    try:
        data = BlobReader().read_json_gz(row.blob_path)
    except Exception:
        return row, {}
    return row, _latest_snapshot(data)


async def get_latest_cluster_snapshot_summary(session: AsyncSession, ctx: AgentExecutionContext, _: BaseModel | None = None) -> dict[str, Any]:
    row, snapshot = await _load_snapshot(session, ctx)
    pods = snapshot.get("pods", []) or []
    deployments = snapshot.get("deployments", []) or []
    unhealthy = []
    total_restarts = 0
    for pod in pods[:500]:
        metadata = pod.get("metadata") or {}
        status = pod.get("status") or {}
        restart_count = sum(int(item.get("restartCount") or 0) for item in status.get("containerStatuses", []) or [])
        total_restarts += restart_count
        if status.get("phase") not in {"Running", "Succeeded"} or restart_count > 0:
            unhealthy.append(
                {
                    "namespace": metadata.get("namespace"),
                    "pod_name": metadata.get("name"),
                    "phase": status.get("phase"),
                    "restart_count": restart_count,
                }
            )
    return {
        "count": 1 if row else 0,
        "items": [
            {
                "source_type": "snapshot",
                "source_id": safe_reference("snapshot", row.id if row else "latest"),
                "title": "Latest cluster snapshot summary",
                "nodes": len(snapshot.get("nodes", []) or []),
                "pods": len(pods),
                "deployments": len(deployments),
                "namespaces": len(snapshot.get("namespaces", []) or []),
                "total_restarts": total_restarts,
                "unhealthy_workloads": unhealthy[:10],
                "timestamp": row.created_at.isoformat() if row else None,
            }
        ]
        if row
        else [],
        "latest_evidence_at": row.created_at.isoformat() if row else None,
    }


async def get_workload_status(session: AsyncSession, ctx: AgentExecutionContext, args: WorkloadStatusInput) -> dict[str, Any]:
    row, snapshot = await _load_snapshot(session, ctx)
    pods = snapshot.get("pods", []) or []
    deployments = snapshot.get("deployments", []) or []
    matched_deployment = next(
        (
            item
            for item in deployments
            if (item.get("metadata") or {}).get("namespace") == args.namespace
            and (item.get("metadata") or {}).get("name") == args.workload_name
        ),
        None,
    )
    related_pods = []
    for pod in pods[:500]:
        metadata = pod.get("metadata") or {}
        if metadata.get("namespace") != args.namespace:
            continue
        owner_refs = metadata.get("ownerReferences") or []
        owner_names = {owner.get("name") for owner in owner_refs}
        if args.workload_name in owner_names or metadata.get("name", "").startswith(args.workload_name):
            related_pods.append(
                {
                    "pod_name": metadata.get("name"),
                    "phase": (pod.get("status") or {}).get("phase"),
                    "restart_count": sum(int(item.get("restartCount") or 0) for item in (pod.get("status") or {}).get("containerStatuses", []) or []),
                }
            )
    return {
        "count": 1 if row else 0,
        "items": [
            {
                "source_type": "workload",
                "source_id": safe_reference("workload", args.namespace, args.workload_name),
                "title": f"{args.namespace}/{args.workload_name} workload status",
                "namespace": args.namespace,
                "workload_name": args.workload_name,
                "workload_kind": args.workload_kind or "Deployment",
                "deployment_status": (matched_deployment or {}).get("status") or {},
                "related_pods": related_pods[: min(len(related_pods), settings.ai_agent_max_db_rows)],
                "timestamp": row.created_at.isoformat() if row else None,
            }
        ]
        if row
        else [],
        "latest_evidence_at": row.created_at.isoformat() if row else None,
    }
