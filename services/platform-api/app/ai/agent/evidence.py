from __future__ import annotations

from datetime import datetime
from typing import Any

from app.ai.agent.models import DataFreshness, EvidenceReference


def compact_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"tool": tool_name}
    if "count" in result:
        summary["count"] = result["count"]
    if "returned_matches" in result:
        summary["returned_matches"] = result["returned_matches"]
    if "truncated" in result:
        summary["truncated"] = result["truncated"]
    if "latest_evidence_at" in result:
        summary["latest_evidence_at"] = result["latest_evidence_at"]
    return summary


def merge_data_freshness(results: list[dict[str, Any]]) -> DataFreshness:
    latest: datetime | None = None
    truncated = False
    for result in results:
        if result.get("truncated"):
            truncated = True
        value = result.get("latest_evidence_at")
        if not isinstance(value, str):
            continue
        try:
            candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or candidate > latest:
            latest = candidate
    return DataFreshness(
        latest_evidence_at=latest.isoformat() if latest else None,
        truncated=truncated,
    )


def normalize_evidence_reference(item: dict[str, Any]) -> EvidenceReference | None:
    try:
        return EvidenceReference.model_validate(item)
    except Exception:
        return None

