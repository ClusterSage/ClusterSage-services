from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIIncidentAnalysis, AIRecommendedRemediation
from app.ai.preprocessor import FindingGroup
from app.models.entities import AILogFinding, AIIncident, Cluster, RemediationSuggestion


async def upsert_log_finding(session: AsyncSession, cluster: Cluster, group: FindingGroup) -> AILogFinding:
    stmt = select(AILogFinding).where(
        AILogFinding.organization_id == cluster.organization_id,
        AILogFinding.cluster_id == cluster.id,
        AILogFinding.log_signature == group.signature,
        AILogFinding.namespace == group.namespace,
        AILogFinding.pod_name == group.pod_name,
        AILogFinding.container_name == group.container_name,
    )
    finding = (await session.execute(stmt)).scalars().first()
    now = datetime.now(timezone.utc)
    sample = {
        "evidence": [
            {
                "timestamp": item.timestamp,
                "namespace": item.namespace,
                "pod_name": item.pod_name,
                "container_name": item.container_name,
                "message": item.message,
            }
            for item in group.evidence[:10]
        ]
    }
    if finding:
        finding.last_seen_at = now
        finding.occurrence_count += group.occurrence_count
        finding.preliminary_severity = group.severity
        finding.matched_pattern = group.matched_pattern
        finding.raw_evidence_sample = sample
        return finding

    finding = AILogFinding(
        organization_id=cluster.organization_id,
        cluster_id=cluster.id,
        resource_kind="Pod" if group.pod_name else None,
        resource_name=group.pod_name,
        namespace=group.namespace,
        pod_name=group.pod_name,
        container_name=group.container_name,
        workload_kind="Pod" if group.pod_name else None,
        workload_name=group.pod_name,
        log_signature=group.signature,
        matched_pattern=group.matched_pattern,
        raw_evidence_sample=sample,
        first_seen_at=now,
        last_seen_at=now,
        occurrence_count=group.occurrence_count,
        preliminary_severity=group.severity,
    )
    session.add(finding)
    await session.flush()
    return finding


async def upsert_ai_incident(session: AsyncSession, cluster: Cluster, group: FindingGroup, analysis: AIIncidentAnalysis) -> AIIncident:
    stmt = select(AIIncident).where(
        AIIncident.organization_id == cluster.organization_id,
        AIIncident.cluster_id == cluster.id,
        AIIncident.scope == analysis.scope,
        AIIncident.incident_type == analysis.incident_type,
        AIIncident.namespace == group.namespace,
        AIIncident.pod_name == group.pod_name,
        AIIncident.container_name == group.container_name,
        AIIncident.status == "open",
    )
    incident = (await session.execute(stmt)).scalars().first()
    now = datetime.now(timezone.utc)
    evidence = {
        "lines": [item.model_dump(mode="json") for item in analysis.evidence],
        "matched_pattern": group.matched_pattern,
        "signature": group.signature,
    }
    if incident:
        incident.title = analysis.title
        incident.severity = analysis.severity
        incident.description = analysis.summary
        incident.ai_summary = analysis.summary
        incident.evidence = evidence
        incident.confidence_score = analysis.confidence_score
        incident.last_seen_at = now
        incident.occurrence_count += group.occurrence_count
        return incident

    incident = AIIncident(
        organization_id=cluster.organization_id,
        cluster_id=cluster.id,
        resource_kind="Pod" if group.pod_name else None,
        resource_name=group.pod_name,
        scope=analysis.scope,
        title=analysis.title,
        incident_type=analysis.incident_type,
        severity=analysis.severity,
        status="open",
        namespace=group.namespace,
        pod_name=group.pod_name,
        container_name=group.container_name,
        workload_kind="Pod" if group.pod_name else None,
        workload_name=group.pod_name,
        description=analysis.summary,
        ai_summary=analysis.summary,
        evidence=evidence,
        confidence_score=analysis.confidence_score,
        first_seen_at=now,
        last_seen_at=now,
        occurrence_count=group.occurrence_count,
    )
    session.add(incident)
    await session.flush()
    return incident


async def upsert_remediation_suggestions(
    session: AsyncSession,
    cluster: Cluster,
    incident: AIIncident,
    suggestions: Iterable[AIRecommendedRemediation],
    *,
    ai_model: str | None,
    prompt_version: str,
) -> None:
    for suggestion in suggestions:
        stmt = select(RemediationSuggestion).where(
            RemediationSuggestion.organization_id == cluster.organization_id,
            RemediationSuggestion.cluster_id == cluster.id,
            RemediationSuggestion.incident_id == incident.id,
            RemediationSuggestion.suggestion_type == suggestion.type,
            RemediationSuggestion.title == suggestion.title,
        )
        existing = (await session.execute(stmt)).scalars().first()
        payload = suggestion.action_payload.model_dump(mode="json") if suggestion.action_payload else None
        if existing:
            existing.summary = suggestion.summary
            existing.risk_level = suggestion.risk_level
            existing.requires_approval = suggestion.requires_approval
            existing.is_executable = suggestion.is_executable
            existing.executable_action_type = "rollout_restart" if suggestion.type == "rollout_restart" and suggestion.is_executable else None
            existing.action_payload = payload
            existing.ai_model = ai_model
            existing.prompt_version = prompt_version
            continue
        session.add(
            RemediationSuggestion(
                organization_id=cluster.organization_id,
                cluster_id=cluster.id,
                incident_id=incident.id,
                resource_kind=incident.resource_kind,
                resource_name=incident.resource_name,
                suggestion_type=suggestion.type,
                title=suggestion.title,
                summary=suggestion.summary,
                risk_level=suggestion.risk_level,
                requires_approval=suggestion.requires_approval,
                is_executable=suggestion.is_executable,
                executable_action_type="rollout_restart" if suggestion.type == "rollout_restart" and suggestion.is_executable else None,
                action_payload=payload,
                ai_model=ai_model,
                prompt_version=prompt_version,
                confidence_score=incident.confidence_score,
            )
        )
