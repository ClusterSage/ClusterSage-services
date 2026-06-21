from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Confidence = Literal["low", "medium", "high"]
SourceType = Literal["incident", "issue", "snapshot", "log", "document", "knowledge_base", "deployment", "workload"]


@dataclass(slots=True)
class AgentExecutionContext:
    tenant_id: UUID
    user_id: UUID
    cluster_id: UUID
    conversation_id: UUID
    correlation_id: str


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    timestamp: str | None = None


class DataFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_evidence_at: str | None = None
    truncated: bool = False


class AgentFinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    confidence: Confidence = "low"
    data_freshness: DataFreshness = Field(default_factory=DataFreshness)


class ToolExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: Literal["ok", "denied", "timeout", "error"]
    started_at: datetime
    finished_at: datetime
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str

