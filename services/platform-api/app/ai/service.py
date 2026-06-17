from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AzureAIFoundryClient
from app.ai.models import AIIncidentAnalysis, AIRecommendedRemediation
from app.ai.persistence import upsert_ai_incident, upsert_log_finding, upsert_remediation_suggestions
from app.ai.preprocessor import FindingGroup, preprocess_log_records
from app.ai.prompts import SYSTEM_PROMPT, build_incident_prompt
from app.core.config import settings
from app.models.entities import Cluster

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AIAnalysisResult:
    groups_processed: int = 0
    incidents_upserted: int = 0
    suggestions_upserted: int = 0


class AIIncidentAnalysisService:
    def __init__(self) -> None:
        self.client = AzureAIFoundryClient()

    async def analyze_log_records(self, session: AsyncSession, cluster: Cluster, records: list[dict]) -> AIAnalysisResult:
        groups = preprocess_log_records(records, settings.ai_max_log_lines_per_analysis)
        result = AIAnalysisResult()
        for group in groups:
            if not group.pod_name:
                continue
            result.groups_processed += 1
            await upsert_log_finding(session, cluster, group)
            analysis = await self._analyze_group(group)
            incident = await upsert_ai_incident(session, cluster, group, analysis)
            normalized_suggestions = self._normalize_suggestions(group, analysis.recommended_remediations)
            await upsert_remediation_suggestions(
                session,
                cluster,
                incident,
                normalized_suggestions or self._fallback_suggestions(group),
                ai_model=settings.azure_ai_foundry_deployment_name or None,
                prompt_version=settings.ai_prompt_version,
            )
            result.incidents_upserted += 1
            result.suggestions_upserted += len(normalized_suggestions or self._fallback_suggestions(group))
        return result

    async def _analyze_group(self, group: FindingGroup) -> AIIncidentAnalysis:
        if not settings.ai_analysis_enabled or not self.client.configured:
            return self._fallback_analysis(group)

        try:
            response = await asyncio.to_thread(
                self.client.analyze,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_incident_prompt(group),
                max_tokens=settings.ai_max_tokens,
                temperature=settings.ai_temperature,
            )
            return AIIncidentAnalysis.model_validate(response)
        except (RuntimeError, ValidationError, KeyError, ValueError) as exc:
            log.warning("ai incident analysis fallback triggered for signature=%s: %s", group.signature, exc)
            return self._fallback_analysis(group)
        except Exception as exc:  # pragma: no cover - defensive fallback path
            log.exception("unexpected ai incident analysis error for signature=%s: %s", group.signature, exc)
            return self._fallback_analysis(group)

    def _fallback_analysis(self, group: FindingGroup) -> AIIncidentAnalysis:
        evidence = [
            {
                "timestamp": item.timestamp,
                "container": item.container_name,
                "message": item.message,
            }
            for item in group.evidence[:10]
        ]
        return AIIncidentAnalysis(
            severity=group.severity,  # type: ignore[arg-type]
            title=group.title,
            incident_type=group.incident_type,
            summary=group.summary,
            confidence_score=0.65 if group.matched_pattern else 0.4,
            scope="pod",
            evidence=evidence,
            recommended_remediations=self._fallback_suggestions(group),
        )

    def _fallback_suggestions(self, group: FindingGroup) -> list[AIRecommendedRemediation]:
        suggestions = [
            AIRecommendedRemediation(
                type="manual_investigation",
                title="Review related pod logs and recent events",
                summary="Inspect surrounding logs, Kubernetes events, and recent workload changes before taking action.",
                risk_level="low",
                requires_approval=True,
                is_executable=False,
            )
        ]
        if group.incident_type in {"application_error", "timeout_failure", "probe_failure"} and group.namespace and group.pod_name:
            suggestions.append(
                AIRecommendedRemediation(
                    type="rollout_restart",
                    title="Consider a rollout restart for the affected workload",
                    summary="A restart may recover a transient runtime state after you confirm which workload owns the pod and verify the issue is not persistent.",
                    risk_level="medium",
                    requires_approval=True,
                    is_executable=False,
                )
            )
        return suggestions

    def _normalize_suggestions(
        self,
        group: FindingGroup,
        suggestions: list[AIRecommendedRemediation],
    ) -> list[AIRecommendedRemediation]:
        if not suggestions:
            return []

        normalized: list[AIRecommendedRemediation] = []
        for suggestion in suggestions:
            if suggestion.type == "rollout_restart":
                normalized.append(
                    suggestion.model_copy(
                        update={
                            "requires_approval": True,
                            "is_executable": False,
                            "action_payload": None,
                            "summary": "Validate the owning workload from the latest cluster snapshot before attempting a rollout restart.",
                        }
                    )
                )
                continue
            normalized.append(suggestion.model_copy(update={"requires_approval": True}))
        return normalized
