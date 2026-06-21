from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.models import AgentExecutionContext
from app.ai.agent.safeguards import safe_reference, sanitize_text
from app.core.config import settings
from app.models.entities import LogBatch
from app.storage.blob import BlobReader


class SearchClusterLogsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    namespace: str | None = None
    pod: str | None = None
    container: str | None = None
    hours: int = Field(default=6, ge=1, le=24)
    max_results: int = Field(default=10, ge=1, le=20)


def _record_field(record: dict[str, Any], *names: str) -> str | None:
    kubernetes = record.get("kubernetes") if isinstance(record.get("kubernetes"), dict) else {}
    for name in names:
        value = record.get(name) or kubernetes.get(name)
        if value is not None:
            return str(value)
    return None


async def search_cluster_logs(session: AsyncSession, ctx: AgentExecutionContext, args: SearchClusterLogsInput) -> dict[str, Any]:
    start_at = datetime.now(timezone.utc) - timedelta(hours=min(args.hours, settings.ai_agent_log_max_time_range_hours))
    batches = (
        await session.execute(
            select(LogBatch)
            .where(
                LogBatch.organization_id == ctx.tenant_id,
                LogBatch.cluster_id == ctx.cluster_id,
                LogBatch.created_at >= start_at,
            )
            .order_by(LogBatch.created_at.desc())
            .limit(settings.ai_agent_max_blob_batches)
        )
    ).scalars().all()
    try:
        reader = BlobReader()
    except Exception:
        return {"count": 0, "matches": [], "returned_matches": 0, "total_matches_scanned": 0, "truncated": False}
    matches: list[dict[str, Any]] = []
    scanned = 0
    seen_messages: set[tuple[str | None, str | None, str]] = set()
    truncated = False
    for batch in batches:
        try:
            data = reader.read_json_gz(batch.blob_path)
        except Exception:
            continue
        for record in data.get("logs", []) if isinstance(data, dict) else []:
            if not isinstance(record, dict):
                continue
            message = str(record.get("log") or record.get("message") or record.get("msg") or "")
            if args.query.lower() not in message.lower():
                continue
            namespace = _record_field(record, "namespace", "namespace_name")
            pod_name = _record_field(record, "pod", "pod_name")
            container_name = _record_field(record, "container", "container_name")
            if args.namespace and namespace != args.namespace:
                continue
            if args.pod and pod_name != args.pod:
                continue
            if args.container and container_name != args.container:
                continue
            scanned += 1
            key = (namespace, pod_name, message)
            if key in seen_messages:
                continue
            seen_messages.add(key)
            matches.append(
                {
                    "source_type": "log",
                    "source_id": safe_reference("log", namespace, pod_name, container_name, scanned),
                    "title": f"{namespace or 'cluster'}/{pod_name or 'unknown'}",
                    "timestamp": _record_field(record, "time", "timestamp", "@timestamp"),
                    "namespace": namespace,
                    "pod": pod_name,
                    "container": container_name,
                    "message_excerpt": sanitize_text(message.rstrip(), max_chars=300),
                }
            )
            if len(matches) >= min(args.max_results, settings.ai_agent_max_log_matches):
                truncated = scanned > len(matches)
                break
        if len(matches) >= min(args.max_results, settings.ai_agent_max_log_matches):
            break
    return {
        "count": len(matches),
        "matches": matches,
        "returned_matches": len(matches),
        "total_matches_scanned": scanned,
        "truncated": truncated,
        "latest_evidence_at": matches[0]["timestamp"] if matches else None,
        "items": matches,
    }
