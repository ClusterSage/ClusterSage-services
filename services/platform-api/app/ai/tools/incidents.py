from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.models import AgentExecutionContext
from app.ai.agent.safeguards import safe_reference
from app.core.config import settings
from app.models.entities import AIIncident


class ListClusterIncidentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str | None = None
    namespace: str | None = None
    workload: str | None = None
    incident_type: str | None = None
    hours: int = Field(default=24, ge=1, le=168)
    limit: int = Field(default=10, ge=1, le=50)


class GetIncidentDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=100)


async def list_cluster_incidents(session: AsyncSession, ctx: AgentExecutionContext, args: ListClusterIncidentsInput) -> dict[str, Any]:
    start_at = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    stmt = (
        select(AIIncident)
        .where(
            AIIncident.organization_id == ctx.tenant_id,
            AIIncident.cluster_id == ctx.cluster_id,
            AIIncident.last_seen_at >= start_at,
        )
        .order_by(AIIncident.last_seen_at.desc(), AIIncident.created_at.desc())
        .limit(min(args.limit, settings.ai_agent_max_db_rows))
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = []
    for row in rows:
        if args.severity and row.severity != args.severity:
            continue
        if args.namespace and row.namespace != args.namespace:
            continue
        workload_name = row.workload_name or row.resource_name or row.pod_name
        if args.workload and workload_name != args.workload:
            continue
        if args.incident_type and row.incident_type != args.incident_type:
            continue
        items.append(
            {
                "source_type": "incident",
                "source_id": safe_reference("incident", row.id),
                "title": row.title,
                "severity": row.severity,
                "status": row.status,
                "incident_type": row.incident_type,
                "namespace": row.namespace,
                "workload_name": workload_name,
                "summary": row.ai_summary or row.description,
                "timestamp": row.last_seen_at.isoformat(),
            }
        )
    return {
        "count": len(items),
        "items": items,
        "latest_evidence_at": items[0]["timestamp"] if items else None,
    }


async def get_incident_details(session: AsyncSession, ctx: AgentExecutionContext, args: GetIncidentDetailsInput) -> dict[str, Any]:
    row = await session.get(AIIncident, args.incident_id)
    if row is None or row.organization_id != ctx.tenant_id or row.cluster_id != ctx.cluster_id:
        return {"count": 0, "items": []}
    return {
        "count": 1,
        "items": [
            {
                "source_type": "incident",
                "source_id": safe_reference("incident", row.id),
                "title": row.title,
                "severity": row.severity,
                "status": row.status,
                "incident_type": row.incident_type,
                "namespace": row.namespace,
                "workload_name": row.workload_name or row.resource_name or row.pod_name,
                "summary": row.ai_summary or row.description,
                "evidence": row.evidence,
                "recommended_remediations": [],
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "timestamp": row.last_seen_at.isoformat(),
            }
        ],
        "latest_evidence_at": row.last_seen_at.isoformat(),
    }
