from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.models import AgentExecutionContext
from app.ai.agent.safeguards import safe_reference
from app.ai.tools.snapshots import _load_snapshot


class RecentDeploymentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str | None = None
    workload: str | None = None
    hours: int = Field(default=72, ge=1, le=168)
    limit: int = Field(default=10, ge=1, le=20)


async def get_recent_deployments(session: AsyncSession, ctx: AgentExecutionContext, args: RecentDeploymentsInput) -> dict[str, Any]:
    row, snapshot = await _load_snapshot(session, ctx)
    deployments = snapshot.get("deployments", []) or []
    start_at = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    items: list[dict[str, Any]] = []
    for deployment in deployments:
        metadata = deployment.get("metadata") or {}
        namespace = metadata.get("namespace")
        name = metadata.get("name")
        if args.namespace and namespace != args.namespace:
            continue
        if args.workload and name != args.workload:
            continue
        created = metadata.get("creationTimestamp")
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                created_dt = None
            if created_dt and created_dt < start_at:
                continue
        items.append(
            {
                "source_type": "deployment",
                "source_id": safe_reference("deployment", namespace, name),
                "title": f"{namespace}/{name}",
                "namespace": namespace,
                "workload_name": name,
                "status": deployment.get("status") or {},
                "timestamp": created,
            }
        )
    items.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    items = items[: args.limit]
    return {
        "count": len(items),
        "items": items,
        "latest_evidence_at": items[0]["timestamp"] if items else (row.created_at.isoformat() if row else None),
    }
