from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AIClusterQuery, AIIncident, Cluster, ClusterSnapshot, Issue, LogBatch, User
from app.storage.blob import BlobReader

SUPPORTED_QUERY_EXAMPLES = [
    "Show me all CrashLoopBackOff errors in prod from the last 1 hour.",
    "Which pod restarted the most today?",
    "Show errors after the latest deployment.",
    "Find logs containing database connection failure.",
    "Which namespace has the most warning events?",
    "Show critical incidents in the last 24 hours.",
    "Which workloads are affected by image pull failures?",
    "Which pods have OOMKilled events?",
    "Summarize the health of this cluster.",
]

SUPPORTED_INTENTS = {
    "find_crashloop_errors",
    "find_image_pull_errors",
    "find_oomkilled_pods",
    "find_logs_containing_text",
    "most_restarted_pods",
    "errors_after_latest_deployment",
    "namespace_warning_event_count",
    "summarize_cluster_health",
    "list_critical_incidents",
    "list_incidents_by_namespace",
    "list_incidents_by_workload",
}


@dataclass(slots=True)
class ParsedClusterQuery:
    payload: dict[str, Any]
    parser_model: str = "rule-based-parser"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _time_window_from_payload(payload: dict[str, Any]) -> datetime | None:
    time_range = payload.get("time_range")
    if not isinstance(time_range, dict):
        return None
    preset = str(time_range.get("preset") or "").lower()
    if preset == "today":
        now = _now()
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    amount = time_range.get("amount")
    unit = str(time_range.get("unit") or "").lower()
    if not isinstance(amount, int) or amount <= 0:
        return None
    if unit == "minute":
        return _now() - timedelta(minutes=amount)
    if unit == "hour":
        return _now() - timedelta(hours=amount)
    if unit == "day":
        return _now() - timedelta(days=amount)
    return None


def _extract_namespace(question: str) -> str | None:
    match = re.search(r"\bin\s+([a-z0-9][a-z0-9-]{1,62})\b", question)
    if not match:
        return None
    candidate = match.group(1).lower()
    blocked = {"the", "last", "cluster", "namespace", "workload", "pod", "logs"}
    return None if candidate in blocked else candidate


def _extract_search_text(original_question: str) -> str | None:
    quoted = re.search(r'"([^"]+)"', original_question)
    if quoted:
        return quoted.group(1).strip()
    single = re.search(r"'([^']+)'", original_question)
    if single:
        return single.group(1).strip()
    containing = re.search(r"containing\s+(.+)$", original_question, re.IGNORECASE)
    if containing:
        value = re.sub(r"\b(from|in|for|during|within)\b.*$", "", containing.group(1), flags=re.IGNORECASE).strip(" .")
        return value or None
    return None


def _extract_time_range(question: str) -> dict[str, Any] | None:
    lowered = question.lower()
    if "today" in lowered:
        return {"preset": "today"}
    match = re.search(r"last\s+(\d+)\s+(minute|minutes|hour|hours|day|days)\b", lowered)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit.endswith("s"):
        unit = unit[:-1]
    return {"amount": amount, "unit": unit}


def parse_cluster_question(question: str) -> ParsedClusterQuery | None:
    normalized = " ".join(question.strip().split())
    lowered = normalized.lower()
    if not lowered:
        return None

    payload: dict[str, Any] = {
        "namespace": _extract_namespace(lowered),
        "time_range": _extract_time_range(lowered),
        "group_by": None,
    }

    if "crashloop" in lowered:
        payload["intent"] = "find_crashloop_errors"
        payload["group_by"] = "workload" if "workload" in lowered else "pod"
        return ParsedClusterQuery(payload)
    if "image pull" in lowered or "errimagepull" in lowered or "imagepullbackoff" in lowered:
        payload["intent"] = "find_image_pull_errors"
        payload["group_by"] = "workload" if "workload" in lowered else "pod"
        return ParsedClusterQuery(payload)
    if "oomkilled" in lowered or "oom killed" in lowered:
        payload["intent"] = "find_oomkilled_pods"
        payload["group_by"] = "pod"
        return ParsedClusterQuery(payload)
    if "logs containing" in lowered or "find logs" in lowered:
        payload["intent"] = "find_logs_containing_text"
        payload["search_text"] = _extract_search_text(normalized)
        return ParsedClusterQuery(payload)
    if "restarted the most" in lowered or "most restarted" in lowered:
        payload["intent"] = "most_restarted_pods"
        payload["group_by"] = "pod"
        return ParsedClusterQuery(payload)
    if "after the latest deployment" in lowered:
        payload["intent"] = "errors_after_latest_deployment"
        return ParsedClusterQuery(payload)
    if "warning events" in lowered:
        payload["intent"] = "namespace_warning_event_count"
        payload["group_by"] = "namespace"
        return ParsedClusterQuery(payload)
    if "summarize" in lowered and "health" in lowered:
        payload["intent"] = "summarize_cluster_health"
        return ParsedClusterQuery(payload)
    if "critical incidents" in lowered:
        payload["intent"] = "list_critical_incidents"
        return ParsedClusterQuery(payload)
    if "incidents by namespace" in lowered or ("namespace" in lowered and "incidents" in lowered):
        payload["intent"] = "list_incidents_by_namespace"
        payload["group_by"] = "namespace"
        return ParsedClusterQuery(payload)
    if "incidents by workload" in lowered or ("workload" in lowered and "incidents" in lowered):
        payload["intent"] = "list_incidents_by_workload"
        payload["group_by"] = "workload"
        return ParsedClusterQuery(payload)
    return None


def _incident_text(incident: AIIncident) -> str:
    return " ".join(
        str(part or "")
        for part in [
            incident.incident_type,
            incident.title,
            incident.description,
            incident.ai_summary,
            incident.resource_kind,
            incident.resource_name,
            incident.workload_kind,
            incident.workload_name,
            incident.pod_name,
            incident.container_name,
        ]
    ).lower()


def _incident_item(incident: AIIncident) -> dict[str, Any]:
    return {
        "id": str(incident.id),
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "incident_type": incident.incident_type,
        "namespace": incident.namespace,
        "pod_name": incident.pod_name,
        "container_name": incident.container_name,
        "workload_kind": incident.workload_kind,
        "workload_name": incident.workload_name,
        "resource_kind": incident.resource_kind,
        "resource_name": incident.resource_name,
        "occurrence_count": incident.occurrence_count,
        "first_seen_at": incident.first_seen_at.isoformat() if incident.first_seen_at else None,
        "last_seen_at": incident.last_seen_at.isoformat() if incident.last_seen_at else None,
        "summary": incident.ai_summary or incident.description,
    }


def _issue_matches_time(issue: Issue, start_at: datetime | None) -> bool:
    return start_at is None or issue.last_seen_at >= start_at


def _incident_matches_filters(incident: AIIncident, payload: dict[str, Any], keywords: tuple[str, ...] | None = None) -> bool:
    namespace = payload.get("namespace")
    if namespace and incident.namespace != namespace:
        return False
    start_at = _time_window_from_payload(payload)
    if start_at and incident.last_seen_at < start_at:
        return False
    if not keywords:
        return True
    haystack = _incident_text(incident)
    return any(keyword in haystack for keyword in keywords)


class ClusterQueryService:
    async def run(
        self,
        *,
        session: AsyncSession,
        cluster: Cluster,
        user: User,
        question: str,
    ) -> AIClusterQuery:
        parsed = parse_cluster_question(question)
        if parsed is None:
            query = AIClusterQuery(
                organization_id=user.organization_id,
                cluster_id=cluster.id,
                user_id=user.id,
                question=question,
                parsed_query={"intent": "unsupported"},
                answer_summary="That question is not supported yet. Try one of the built-in cluster queries shown in the examples.",
                result={"supported_examples": SUPPORTED_QUERY_EXAMPLES},
                ai_model="rule-based-parser",
            )
            session.add(query)
            await session.commit()
            await session.refresh(query)
            return query

        result = await self._execute(session=session, cluster=cluster, user=user, payload=parsed.payload)
        summary = self._summary_for_result(parsed.payload, result)
        query = AIClusterQuery(
            organization_id=user.organization_id,
            cluster_id=cluster.id,
            user_id=user.id,
            question=question,
            parsed_query=parsed.payload,
            answer_summary=summary,
            result=result,
            ai_model=parsed.parser_model,
        )
        session.add(query)
        await session.commit()
        await session.refresh(query)
        return query

    async def _execute(
        self,
        *,
        session: AsyncSession,
        cluster: Cluster,
        user: User,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        intent = str(payload.get("intent") or "")
        if intent not in SUPPORTED_INTENTS:
            return {"supported_examples": SUPPORTED_QUERY_EXAMPLES}

        incidents = await self._load_incidents(session=session, cluster=cluster, user=user)
        issues = await self._load_issues(session=session, cluster=cluster, user=user)
        snapshot = await self._load_snapshot(session=session, cluster=cluster)
        if intent == "find_crashloop_errors":
            return self._list_matching_incidents(payload, incidents, ("crashloop",))
        if intent == "find_image_pull_errors":
            return self._list_matching_incidents(payload, incidents, ("imagepull", "image pull", "errimagepull"))
        if intent == "find_oomkilled_pods":
            return self._list_matching_incidents(payload, incidents, ("oomkilled", "oom killed"))
        if intent == "find_logs_containing_text":
            return await self._find_logs_containing_text(session=session, cluster=cluster, user=user, payload=payload)
        if intent == "most_restarted_pods":
            return self._most_restarted_pods(payload, snapshot)
        if intent == "errors_after_latest_deployment":
            return self._errors_after_latest_deployment(incidents, snapshot)
        if intent == "namespace_warning_event_count":
            return self._namespace_warning_event_count(payload, issues)
        if intent == "summarize_cluster_health":
            return self._summarize_cluster_health(incidents, issues, snapshot)
        if intent == "list_critical_incidents":
            critical_payload = {**payload}
            return self._list_matching_incidents(critical_payload, [incident for incident in incidents if incident.severity == "critical"], None)
        if intent == "list_incidents_by_namespace":
            return self._aggregate_incidents_by_namespace(payload, incidents)
        if intent == "list_incidents_by_workload":
            return self._aggregate_incidents_by_workload(payload, incidents)
        return {"supported_examples": SUPPORTED_QUERY_EXAMPLES}

    async def _load_incidents(self, *, session: AsyncSession, cluster: Cluster, user: User) -> list[AIIncident]:
        return (
            await session.execute(
                select(AIIncident)
                .where(
                    AIIncident.organization_id == user.organization_id,
                    AIIncident.cluster_id == cluster.id,
                )
                .order_by(AIIncident.last_seen_at.desc(), AIIncident.created_at.desc())
                .limit(500)
            )
        ).scalars().all()

    async def _load_issues(self, *, session: AsyncSession, cluster: Cluster, user: User) -> list[Issue]:
        return (
            await session.execute(
                select(Issue)
                .where(
                    Issue.organization_id == user.organization_id,
                    Issue.cluster_id == cluster.id,
                )
                .order_by(Issue.last_seen_at.desc())
                .limit(500)
            )
        ).scalars().all()

    async def _load_snapshot(self, *, session: AsyncSession, cluster: Cluster) -> dict[str, Any]:
        snapshot = (
            await session.execute(
                select(ClusterSnapshot)
                .where(ClusterSnapshot.cluster_id == cluster.id)
                .order_by(ClusterSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if not snapshot:
            return {}
        try:
            data = BlobReader().read_json_gz(snapshot.blob_path)
        except Exception:
            return {}
        return data.get("snapshot", {}) if isinstance(data, dict) else {}

    def _list_matching_incidents(
        self,
        payload: dict[str, Any],
        incidents: list[AIIncident],
        keywords: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        matches = [incident for incident in incidents if _incident_matches_filters(incident, payload, keywords)]
        return {"count": len(matches), "items": [_incident_item(incident) for incident in matches[:50]]}

    def _most_restarted_pods(self, payload: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        namespace = payload.get("namespace")
        items: list[dict[str, Any]] = []
        for pod in snapshot.get("pods", []) or []:
            metadata = pod.get("metadata") or {}
            status = pod.get("status") or {}
            pod_namespace = metadata.get("namespace")
            if namespace and pod_namespace != namespace:
                continue
            restart_total = sum(int(item.get("restartCount") or 0) for item in status.get("containerStatuses", []) or [])
            owner_refs = metadata.get("ownerReferences") or []
            workload = owner_refs[0].get("name") if owner_refs else None
            items.append(
                {
                    "namespace": pod_namespace,
                    "pod_name": metadata.get("name"),
                    "restart_count": restart_total,
                    "status": status.get("phase"),
                    "workload_name": workload,
                }
            )
        items.sort(key=lambda item: item.get("restart_count") or 0, reverse=True)
        return {"count": len(items), "items": items[:20]}

    def _errors_after_latest_deployment(self, incidents: list[AIIncident], snapshot: dict[str, Any]) -> dict[str, Any]:
        deployments = snapshot.get("deployments", []) or []
        latest: dict[str, Any] | None = None
        latest_time: datetime | None = None
        for deployment in deployments:
            metadata = deployment.get("metadata") or {}
            candidate_times = [_to_datetime(metadata.get("creationTimestamp"))]
            candidate_times.extend(_to_datetime(item.get("time")) for item in metadata.get("managedFields") or [])
            candidate_times = [item for item in candidate_times if item is not None]
            if not candidate_times:
                continue
            deployment_time = max(candidate_times)
            if latest_time is None or deployment_time > latest_time:
                latest_time = deployment_time
                latest = {
                    "name": metadata.get("name"),
                    "namespace": metadata.get("namespace"),
                    "at": deployment_time.isoformat(),
                }
        if latest_time is None:
            return {"latest_deployment": None, "count": 0, "items": []}
        matches = [incident for incident in incidents if incident.last_seen_at >= latest_time]
        return {
            "latest_deployment": latest,
            "count": len(matches),
            "items": [_incident_item(incident) for incident in matches[:50]],
        }

    def _namespace_warning_event_count(self, payload: dict[str, Any], issues: list[Issue]) -> dict[str, Any]:
        start_at = _time_window_from_payload(payload)
        counts: Counter[str] = Counter()
        for issue in issues:
            if not _issue_matches_time(issue, start_at):
                continue
            issue_type = (issue.issue_type or "").lower()
            if not (issue_type.startswith("kubernetesevent") or issue.issue_type == "FailedScheduling"):
                continue
            counts[issue.namespace or "cluster"] += 1
        items = [
            {"namespace": namespace, "warning_event_count": count}
            for namespace, count in counts.most_common(20)
        ]
        return {"count": len(items), "items": items}

    def _summarize_cluster_health(self, incidents: list[AIIncident], issues: list[Issue], snapshot: dict[str, Any]) -> dict[str, Any]:
        severity_counts = Counter(incident.severity for incident in incidents)
        open_incidents = [incident for incident in incidents if incident.status == "open"]
        pods = snapshot.get("pods", []) or []
        deployments = snapshot.get("deployments", []) or []
        top_restarted = self._most_restarted_pods({}, snapshot).get("items", [])[:5]
        unhealthy_deployments = []
        for deployment in deployments:
            metadata = deployment.get("metadata") or {}
            status = deployment.get("status") or {}
            unavailable = int(status.get("unavailableReplicas") or 0)
            if unavailable > 0:
                unhealthy_deployments.append(
                    {
                        "namespace": metadata.get("namespace"),
                        "name": metadata.get("name"),
                        "unavailable_replicas": unavailable,
                    }
                )
        return {
            "incident_counts": {
                "critical": severity_counts.get("critical", 0),
                "major": severity_counts.get("major", 0),
                "minor": severity_counts.get("minor", 0),
                "open": len(open_incidents),
            },
            "resource_counts": {
                "pods": len(pods),
                "deployments": len(deployments),
                "issues": len(issues),
            },
            "top_restarted_pods": top_restarted,
            "unhealthy_deployments": unhealthy_deployments[:10],
        }

    def _aggregate_incidents_by_namespace(self, payload: dict[str, Any], incidents: list[AIIncident]) -> dict[str, Any]:
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"incident_count": 0, "critical_count": 0, "open_count": 0})
        for incident in incidents:
            if not _incident_matches_filters(incident, payload):
                continue
            namespace = incident.namespace or "cluster"
            buckets[namespace]["incident_count"] += 1
            if incident.severity == "critical":
                buckets[namespace]["critical_count"] += 1
            if incident.status == "open":
                buckets[namespace]["open_count"] += 1
        items = [
            {"namespace": namespace, **counts}
            for namespace, counts in sorted(buckets.items(), key=lambda item: item[1]["incident_count"], reverse=True)
        ]
        return {"count": len(items), "items": items[:30]}

    def _aggregate_incidents_by_workload(self, payload: dict[str, Any], incidents: list[AIIncident]) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"incident_count": 0, "critical_count": 0, "open_count": 0, "namespace": None})
        for incident in incidents:
            if not _incident_matches_filters(incident, payload):
                continue
            workload_name = incident.workload_name or incident.resource_name or incident.pod_name or "unknown"
            buckets[workload_name]["incident_count"] += 1
            buckets[workload_name]["namespace"] = incident.namespace
            if incident.severity == "critical":
                buckets[workload_name]["critical_count"] += 1
            if incident.status == "open":
                buckets[workload_name]["open_count"] += 1
        items = [
            {"workload_name": workload_name, **counts}
            for workload_name, counts in sorted(buckets.items(), key=lambda item: item[1]["incident_count"], reverse=True)
        ]
        return {"count": len(items), "items": items[:30]}

    async def _find_logs_containing_text(
        self,
        *,
        session: AsyncSession,
        cluster: Cluster,
        user: User,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        search_text = str(payload.get("search_text") or "").strip()
        if not search_text:
            return {
                "count": 0,
                "items": [],
                "message": "Please include the text to search for, for example: Find logs containing \"database connection failure\".",
            }
        batches = (
            await session.execute(
                select(LogBatch)
                .where(
                    LogBatch.organization_id == user.organization_id,
                    LogBatch.cluster_id == cluster.id,
                )
                .order_by(LogBatch.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        namespace = payload.get("namespace")
        start_at = _time_window_from_payload(payload)
        items: list[dict[str, Any]] = []
        try:
            reader = BlobReader()
        except Exception:
            return {"count": 0, "items": [], "message": "Log storage is not available right now."}
        for batch in batches:
            try:
                data = reader.read_json_gz(batch.blob_path)
            except Exception:
                continue
            for record in data.get("logs", []) if isinstance(data, dict) else []:
                if not isinstance(record, dict):
                    continue
                message = str(record.get("log") or record.get("message") or record.get("msg") or "")
                if search_text.lower() not in message.lower():
                    continue
                kubernetes = record.get("kubernetes") if isinstance(record.get("kubernetes"), dict) else {}
                record_namespace = str(record.get("namespace") or record.get("namespace_name") or kubernetes.get("namespace_name") or kubernetes.get("namespace") or "")
                record_timestamp = _to_datetime(str(record.get("time") or record.get("timestamp") or record.get("@timestamp") or ""))
                if namespace and record_namespace != namespace:
                    continue
                if start_at and record_timestamp and record_timestamp < start_at:
                    continue
                items.append(
                    {
                        "timestamp": record_timestamp.isoformat() if record_timestamp else None,
                        "namespace": record_namespace or None,
                        "pod_name": str(record.get("pod") or record.get("pod_name") or kubernetes.get("pod_name") or ""),
                        "container_name": str(record.get("container") or record.get("container_name") or kubernetes.get("container_name") or ""),
                        "message": message.rstrip(),
                    }
                )
                if len(items) >= 100:
                    return {"count": len(items), "items": items, "search_text": search_text}
        return {"count": len(items), "items": items, "search_text": search_text}

    def _summary_for_result(self, payload: dict[str, Any], result: dict[str, Any]) -> str:
        intent = str(payload.get("intent") or "")
        count = int(result.get("count") or 0) if isinstance(result.get("count"), int) else 0
        if intent == "most_restarted_pods":
            first = (result.get("items") or [{}])[0] if isinstance(result.get("items"), list) and result.get("items") else {}
            if first:
                return f"The most restarted pod is {first.get('pod_name') or 'unknown'} with {first.get('restart_count') or 0} restarts."
            return "No pod restart data is available yet."
        if intent == "namespace_warning_event_count":
            first = (result.get("items") or [{}])[0] if isinstance(result.get("items"), list) and result.get("items") else {}
            if first:
                return f"The namespace with the most warning events is {first.get('namespace')} with {first.get('warning_event_count')} warnings."
            return "No warning events were found for the requested range."
        if intent == "summarize_cluster_health":
            incident_counts = result.get("incident_counts") or {}
            return (
                f"Cluster health summary: {incident_counts.get('critical', 0)} critical, "
                f"{incident_counts.get('major', 0)} major, and {incident_counts.get('minor', 0)} minor incidents."
            )
        if intent == "errors_after_latest_deployment":
            latest = result.get("latest_deployment") or {}
            if latest:
                return f"Found {count} incidents after the latest deployment of {latest.get('namespace')}/{latest.get('name')}."
            return "I could not find deployment timing data in the latest cluster snapshot."
        if intent == "find_logs_containing_text" and result.get("message"):
            return str(result["message"])
        if intent == "list_incidents_by_namespace":
            return f"I grouped incidents by namespace and found {count} namespace buckets."
        if intent == "list_incidents_by_workload":
            return f"I grouped incidents by workload and found {count} workload buckets."
        if intent == "list_critical_incidents":
            return f"I found {count} critical incidents in this cluster."
        label_map = {
            "find_crashloop_errors": "CrashLoopBackOff-related incidents",
            "find_image_pull_errors": "image pull incidents",
            "find_oomkilled_pods": "OOMKilled-related incidents",
        }
        label = label_map.get(intent, "matching results")
        return f"I found {count} {label}."
