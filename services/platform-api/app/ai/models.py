from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["minor", "major", "critical"]
Scope = Literal["pod", "workload", "namespace", "cluster"]
SuggestionType = Literal[
    "explanation",
    "kubectl_command",
    "rollout_restart",
    "config_change",
    "scaling_guidance",
    "manual_investigation",
]
RiskLevel = Literal["low", "medium", "high"]


class EvidenceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str | None = None
    container: str | None = None
    message: str = Field(min_length=1)


class RemediationSuggestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload_kind: str | None = None
    workload_name: str | None = None
    namespace: str | None = None


class AIRecommendedRemediation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SuggestionType
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    risk_level: RiskLevel = "medium"
    requires_approval: bool = True
    is_executable: bool = False
    action_payload: RemediationSuggestionPayload | None = None


class AIIncidentAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    title: str = Field(min_length=1)
    incident_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    confidence_score: float = Field(ge=0, le=1)
    scope: Scope = "pod"
    evidence: list[EvidenceLine] = Field(default_factory=list)
    recommended_remediations: list[AIRecommendedRemediation] = Field(default_factory=list)
