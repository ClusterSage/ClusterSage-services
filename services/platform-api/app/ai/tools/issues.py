from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.models import AgentExecutionContext
from app.ai.agent.safeguards import safe_reference
from app.core.config import settings
from app.models.entities import Issue


class ClusterIssueSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: int = Field(default=24, ge=1, le=168)
    namespace: str | None = None
    issue_type: str | None = None


async def get_cluster_issue_summary(session: AsyncSession, ctx: AgentExecutionContext, args: ClusterIssueSummaryInput) -> dict[str, Any]:
    start_at = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    rows = (
        await session.execute(
            select(Issue)
            .where(
                Issue.organization_id == ctx.tenant_id,
                Issue.cluster_id == ctx.cluster_id,
                Issue.last_seen_at >= start_at,
            )
            .order_by(Issue.last_seen_at.desc())
            .limit(settings.ai_agent_max_db_rows)
        )
    ).scalars().all()
    counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for row in rows:
        if args.namespace and row.namespace != args.namespace:
            continue
        if args.issue_type and row.issue_type != args.issue_type:
            continue
        counts[row.issue_type] += 1
        if len(examples) < 8:
            examples.append(
                {
                    "source_type": "issue",
                    "source_id": safe_reference("issue", row.id),
                    "title": row.title,
                    "issue_type": row.issue_type,
                    "severity": row.severity,
                    "namespace": row.namespace,
                    "summary": row.description,
                    "timestamp": row.last_seen_at.isoformat(),
                }
            )
    return {
        "count": sum(counts.values()),
        "aggregates": [{"issue_type": name, "count": count} for name, count in counts.most_common()],
        "items": examples,
        "latest_evidence_at": examples[0]["timestamp"] if examples else None,
    }
