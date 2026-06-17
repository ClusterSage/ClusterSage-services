from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.ai.redaction import redact_text


@dataclass(slots=True)
class LogEvidence:
    timestamp: str | None
    namespace: str | None
    pod_name: str | None
    container_name: str | None
    message: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FindingGroup:
    signature: str
    matched_pattern: str | None
    severity: str
    incident_type: str
    title: str
    namespace: str | None
    pod_name: str | None
    container_name: str | None
    evidence: list[LogEvidence] = field(default_factory=list)

    @property
    def occurrence_count(self) -> int:
        return len(self.evidence)

    @property
    def summary(self) -> str:
        if self.matched_pattern:
            return f"Detected {self.matched_pattern} symptoms in pod logs."
        return "Detected repeated error patterns in pod logs."


PATTERN_RULES: list[tuple[re.Pattern[str], str, str, str, str]] = [
    (re.compile(r"CrashLoopBackOff", re.I), "crash_loop_backoff", "critical", "CrashLoopBackOff detected", "crash loop"),
    (re.compile(r"OOMKilled|out of memory|oom kill", re.I), "oom_killed", "critical", "Pod repeatedly OOMKilled", "oom kill"),
    (re.compile(r"ImagePullBackOff|ErrImagePull", re.I), "image_pull_failure", "major", "Image pull failures detected", "image pull failure"),
    (re.compile(r"connection refused|could not connect|database connection", re.I), "database_connection_failure", "major", "Database connection failures detected", "database connection failure"),
    (re.compile(r"permission denied|forbidden|not authorized|unauthorized", re.I), "permission_failure", "major", "Permission failures detected", "permission failure"),
    (re.compile(r"readiness probe failed|liveness probe failed", re.I), "probe_failure", "major", "Probe failures detected", "probe failure"),
    (re.compile(r"dns|name or service not known|no such host", re.I), "dns_failure", "major", "DNS/network failures detected", "dns or host resolution failure"),
    (re.compile(r"timeout|timed out", re.I), "timeout_failure", "minor", "Timeouts detected", "timeout"),
    (re.compile(r"\berror\b|\bexception\b|\btraceback\b", re.I), "application_error", "major", "Application errors detected", "application error"),
    (re.compile(r"\bwarn(ing)?\b", re.I), "warning", "minor", "Warnings detected", "warning"),
]

NORMALIZATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-f]{8,}\b", re.I), "<hex>"),
    (re.compile(r"\b\d+\b"), "<num>"),
    (re.compile(r"\s+"), " "),
]

SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1}


def _record_field(record: dict[str, Any], *names: str) -> str | None:
    kubernetes = record.get("kubernetes") if isinstance(record.get("kubernetes"), dict) else {}
    for name in names:
        value = record.get(name) or kubernetes.get(name)
        if value is not None:
            return str(value)
    return None


def normalize_message(message: str) -> str:
    normalized = redact_text(message)
    for pattern, replacement in NORMALIZATION_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    return normalized.strip().lower()


def classify_message(message: str) -> tuple[str, str, str, str | None]:
    for pattern, incident_type, severity, title, matched_pattern in PATTERN_RULES:
        if pattern.search(message):
            return incident_type, severity, title, matched_pattern
    return "log_anomaly", "minor", "Suspicious log pattern detected", None


def build_signature(message: str, namespace: str | None, pod_name: str | None, container_name: str | None, incident_type: str) -> str:
    normalized = normalize_message(message)
    key = "|".join([incident_type, namespace or "", pod_name or "", container_name or "", normalized])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def preprocess_log_records(records: list[dict[str, Any]], max_lines: int) -> list[FindingGroup]:
    grouped: dict[str, FindingGroup] = {}
    for record in records[:max_lines]:
        if not isinstance(record, dict):
            continue
        message = str(record.get("log") or record.get("message") or record.get("msg") or "").strip()
        if not message:
            continue
        redacted_message = redact_text(message)
        namespace = _record_field(record, "namespace", "namespace_name")
        pod_name = _record_field(record, "pod", "pod_name")
        container_name = _record_field(record, "container", "container_name")
        timestamp = _record_field(record, "time", "timestamp", "@timestamp")
        incident_type, severity, title, matched_pattern = classify_message(redacted_message)
        signature = build_signature(redacted_message, namespace, pod_name, container_name, incident_type)
        group = grouped.get(signature)
        evidence = LogEvidence(
            timestamp=timestamp,
            namespace=namespace,
            pod_name=pod_name,
            container_name=container_name,
            message=redacted_message,
            raw=record,
        )
        if group is None:
            grouped[signature] = FindingGroup(
                signature=signature,
                matched_pattern=matched_pattern,
                severity=severity,
                incident_type=incident_type,
                title=title,
                namespace=namespace,
                pod_name=pod_name,
                container_name=container_name,
                evidence=[evidence],
            )
        else:
            group.evidence.append(evidence)
            if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(group.severity, 0):
                group.severity = severity
                group.title = title
                group.matched_pattern = matched_pattern
    filtered_groups = [
        group
        for group in grouped.values()
        if group.matched_pattern or group.occurrence_count >= 3
    ]
    return sorted(
        filtered_groups,
        key=lambda item: (SEVERITY_RANK.get(item.severity, 0), item.occurrence_count),
        reverse=True,
    )
