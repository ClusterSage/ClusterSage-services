from __future__ import annotations

import json

from app.ai.preprocessor import FindingGroup


SYSTEM_PROMPT = """You are ClusterSage AI, a Kubernetes incident analysis assistant.
Return JSON only. Do not return markdown.
Only use the supplied evidence. Do not invent missing facts.
Classify severity as one of: minor, major, critical.
Only suggest rollout_restart when the evidence points to a transient application state and when the target is a Deployment.
Never suggest arbitrary shell commands or arbitrary kubernetes patches."""


def build_incident_prompt(group: FindingGroup) -> str:
    evidence = [
        {
            "timestamp": item.timestamp,
            "container": item.container_name,
            "message": item.message,
        }
        for item in group.evidence[:10]
    ]
    payload = {
        "incident_type": group.incident_type,
        "preliminary_severity": group.severity,
        "matched_pattern": group.matched_pattern,
        "namespace": group.namespace,
        "pod_name": group.pod_name,
        "container_name": group.container_name,
        "occurrence_count": group.occurrence_count,
        "evidence": evidence,
    }
    return (
        "Analyze the following Kubernetes pod log evidence and return structured JSON that matches the required schema.\n"
        f"{json.dumps(payload, separators=(',', ':'))}"
    )
