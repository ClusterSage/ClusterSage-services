from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.context import load_recent_conversation_turns
from app.ai.agent.evidence import merge_data_freshness, normalize_evidence_reference
from app.ai.agent.models import AgentExecutionContext, AgentFinalAnswer
from app.ai.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.agent.safeguards import wrap_untrusted_evidence
from app.ai.client import AzureAIFoundryClient
from app.ai.tools.registry import TOOL_MAP, execute_tool, tool_schemas
from app.audit.service import write_audit
from app.core.config import settings
from app.models.entities import AIConversation, AIMessage, Cluster, User

log = logging.getLogger(__name__)


class ClusterAgentOrchestrator:
    def __init__(self) -> None:
        self.client = AzureAIFoundryClient()

    async def chat(
        self,
        *,
        session: AsyncSession,
        cluster: Cluster,
        user: User,
        message: str,
        conversation_id: str | None = None,
    ) -> tuple[AIConversation, AIMessage]:
        if not settings.ai_agent_enabled:
            raise RuntimeError("AI agent disabled")
        if not self.client.configured:
            raise RuntimeError("AI provider unavailable")

        conversation = await self._get_or_create_conversation(session, cluster, user, message, conversation_id)
        user_message = AIMessage(
            conversation_id=conversation.id,
            organization_id=user.organization_id,
            cluster_id=cluster.id,
            user_id=user.id,
            role="user",
            content=message,
        )
        session.add(user_message)
        await session.flush()

        ctx = AgentExecutionContext(
            tenant_id=user.organization_id,
            user_id=user.id,
            cluster_id=cluster.id,
            conversation_id=conversation.id,
            correlation_id=str(uuid.uuid4()),
        )
        await write_audit(
            session,
            "ai.chat.requested",
            "user",
            organization_id=user.organization_id,
            user_id=user.id,
            cluster_id=cluster.id,
            details={"conversation_id": str(conversation.id), "correlation_id": ctx.correlation_id},
        )

        answer, tool_records, usage = await self._run_agent_loop(session, ctx, conversation, message)
        assistant_message = AIMessage(
            conversation_id=conversation.id,
            organization_id=user.organization_id,
            cluster_id=cluster.id,
            user_id=None,
            role="assistant",
            content=answer.answer,
            evidence_references=[item.model_dump(mode="json") for item in answer.evidence],
            tool_execution_metadata=[record.model_dump(mode="json") for record in tool_records],
            ai_model=settings.azure_ai_foundry_deployment_name or None,
            prompt_version=settings.ai_agent_prompt_version,
            confidence=answer.confidence,
            data_freshness=answer.data_freshness.model_dump(mode="json"),
            token_usage=usage,
        )
        conversation.updated_at = datetime.now(timezone.utc)
        session.add(assistant_message)
        await write_audit(
            session,
            "ai.chat.completed",
            "user",
            organization_id=user.organization_id,
            user_id=user.id,
            cluster_id=cluster.id,
            details={
                "conversation_id": str(conversation.id),
                "tool_count": len(tool_records),
                "confidence": answer.confidence,
                "truncated": answer.data_freshness.truncated,
            },
        )
        await session.commit()
        await session.refresh(conversation)
        await session.refresh(assistant_message)
        return conversation, assistant_message

    async def list_conversations(self, *, session: AsyncSession, cluster: Cluster, user: User) -> list[AIConversation]:
        return (
            await session.execute(
                select(AIConversation)
                .where(
                    AIConversation.organization_id == user.organization_id,
                    AIConversation.cluster_id == cluster.id,
                    AIConversation.user_id == user.id,
                    AIConversation.archived_at.is_(None),
                )
                .order_by(AIConversation.updated_at.desc(), AIConversation.created_at.desc())
                .limit(50)
            )
        ).scalars().all()

    async def get_conversation(self, *, session: AsyncSession, cluster: Cluster, user: User, conversation_id: str) -> tuple[AIConversation, list[AIMessage]]:
        conversation = await session.get(AIConversation, conversation_id)
        if conversation is None or conversation.organization_id != user.organization_id or conversation.cluster_id != cluster.id or conversation.user_id != user.id:
            raise LookupError("Conversation not found")
        messages = (
            await session.execute(
                select(AIMessage)
                .where(AIMessage.conversation_id == conversation.id)
                .order_by(AIMessage.created_at.asc())
            )
        ).scalars().all()
        return conversation, messages

    async def _get_or_create_conversation(
        self,
        session: AsyncSession,
        cluster: Cluster,
        user: User,
        message: str,
        conversation_id: str | None,
    ) -> AIConversation:
        if conversation_id:
            conversation = await session.get(AIConversation, conversation_id)
            if conversation is None or conversation.organization_id != user.organization_id or conversation.cluster_id != cluster.id or conversation.user_id != user.id:
                raise LookupError("Conversation not found")
            return conversation
        title = message.strip()[:80] or "New investigation"
        conversation = AIConversation(
            organization_id=user.organization_id,
            cluster_id=cluster.id,
            user_id=user.id,
            title=title,
            summary=None,
        )
        session.add(conversation)
        await session.flush()
        return conversation

    async def _run_agent_loop(
        self,
        session: AsyncSession,
        ctx: AgentExecutionContext,
        conversation: AIConversation,
        question: str,
    ) -> tuple[AgentFinalAnswer, list[Any], dict[str, Any] | None]:
        history = await load_recent_conversation_turns(session, conversation)
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": build_user_prompt(question)})

        tool_records = []
        tool_results: list[dict[str, Any]] = []
        usage: dict[str, Any] | None = None
        tool_calls_used = 0
        bootstrap_results, bootstrap_records = await self._bootstrap_tool_results(session, ctx, question)
        if bootstrap_results:
            tool_results.extend(bootstrap_results)
            tool_records.extend(bootstrap_records)
            tool_calls_used += len(bootstrap_records)
            messages.append({"role": "system", "content": self._build_bootstrap_context(bootstrap_results)})

        for _ in range(settings.ai_agent_max_iterations):
            response = await asyncio.to_thread(
                self.client.complete_chat,
                messages=messages,
                max_tokens=settings.ai_max_tokens,
                temperature=settings.ai_temperature,
                tools=tool_schemas(),
                tool_choice="auto",
                response_format={"type": "json_object"},
                timeout=settings.ai_agent_request_timeout_seconds,
            )
            usage = response.get("usage") if isinstance(response, dict) else None
            choice = response["choices"][0]
            message = choice["message"]
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
                for tool_call in tool_calls:
                    if tool_calls_used >= settings.ai_agent_max_tool_calls:
                        break
                    function = tool_call.get("function") or {}
                    name = function.get("name")
                    if name not in TOOL_MAP:
                        continue
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    result, record = await execute_tool(session, ctx, tool_name=name, arguments=arguments)
                    tool_calls_used += 1
                    tool_records.append(record)
                    tool_results.append(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "content": wrap_untrusted_evidence(result),
                        }
                    )
                    await write_audit(
                        session,
                        "ai.tool.executed",
                        "user",
                        organization_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        cluster_id=ctx.cluster_id,
                        details={
                            "conversation_id": str(ctx.conversation_id),
                            "tool_name": name,
                            "status": record.status,
                        },
                    )
                if tool_calls_used >= settings.ai_agent_max_tool_calls:
                    break
                continue
            final = self._parse_final_answer(question, message.get("content"), tool_results)
            return final, tool_records, usage

        final = self._fallback_answer(question, tool_results)
        return final, tool_records, usage

    async def _bootstrap_tool_results(
        self,
        session: AsyncSession,
        ctx: AgentExecutionContext,
        question: str,
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        results: list[dict[str, Any]] = []
        records: list[Any] = []
        for tool_name, arguments in self._bootstrap_tool_requests(question):
            result, record = await execute_tool(session, ctx, tool_name=tool_name, arguments=arguments)
            results.append(result)
            records.append(record)
        return results, records

    def _bootstrap_tool_requests(self, question: str) -> list[tuple[str, dict[str, Any]]]:
        normalized = question.lower()
        requests: list[tuple[str, dict[str, Any]]] = [("get_latest_cluster_snapshot_summary", {})]
        issue_window = self._issue_time_window_args(normalized)
        if any(token in normalized for token in ["error", "issue", "incident", "problem", "failing", "failure", "restart", "health", "unhealthy"]):
            requests.append(("get_cluster_issue_summary", issue_window))
            requests.append(("list_cluster_incidents", {**issue_window, "limit": 10}))
        if any(token in normalized for token in ["deployment", "deploy", "release", "rollout"]):
            requests.append(("get_recent_deployments", {"hours": 72, "limit": 10}))
        unique: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        for tool_name, arguments in requests:
            key = (tool_name, json.dumps(arguments, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            unique.append((tool_name, arguments))
        return unique[: settings.ai_agent_max_tool_calls]

    def _build_bootstrap_context(self, tool_results: list[dict[str, Any]]) -> str:
        compact = []
        for result in tool_results:
            compact.append(
                {
                    "count": result.get("count"),
                    "aggregates": result.get("aggregates"),
                    "items": result.get("items", [])[:3],
                    "latest_evidence_at": result.get("latest_evidence_at"),
                    "truncated": result.get("truncated", False),
                }
            )
        return (
            "Preloaded cluster evidence is available below. Use it directly when it answers the question, "
            "and call additional tools only when needed.\n"
            f"{json.dumps(compact, ensure_ascii=True)}"
        )

    def _issue_time_window_args(self, question: str) -> dict[str, Any]:
        match = re.search(r"last\s+(\d+)\s+(minute|minutes|hour|hours|day|days)\b", question)
        if not match:
            return {"hours": 24}
        amount = int(match.group(1))
        unit = match.group(2)
        if unit.startswith("minute"):
            return {"minutes": amount}
        if unit.startswith("hour"):
            return {"hours": amount}
        return {"hours": max(1, amount * 24)}

    def _parse_final_answer(self, question: str, content: str | None, tool_results: list[dict[str, Any]]) -> AgentFinalAnswer:
        deterministic = self._deterministic_answer(question, tool_results)
        if content:
            try:
                parsed = self._post_process_answer(question, AgentFinalAnswer.model_validate_json(content), tool_results)
                return parsed
            except Exception:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    try:
                        parsed = self._post_process_answer(question, AgentFinalAnswer.model_validate_json(match.group(0)), tool_results)
                        return parsed
                    except Exception:
                        pass
                if deterministic:
                    return deterministic
                log.warning("agent returned malformed output; using fallback parser")
                text = content.strip()
                if text:
                    return AgentFinalAnswer(
                        answer=text,
                        evidence=self._collect_evidence(tool_results),
                        confidence="low",
                        data_freshness=merge_data_freshness(tool_results),
                    )
        if deterministic:
            return deterministic
        return self._fallback_answer(question, tool_results)

    def _post_process_answer(self, question: str, answer: AgentFinalAnswer, tool_results: list[dict[str, Any]]) -> AgentFinalAnswer:
        text = answer.answer.strip()
        if not text.startswith("{"):
            return answer
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return answer
        humanized = self._humanize_json_answer(question, payload)
        if not humanized:
            return answer
        return answer.model_copy(update={"answer": humanized, "evidence": self._collect_evidence(tool_results) or answer.evidence})

    def _collect_evidence(self, tool_results: list[dict[str, Any]]) -> list[Any]:
        evidence = []
        for result in tool_results:
            for item in result.get("items", [])[:6]:
                ref = normalize_evidence_reference(item)
                if ref:
                    evidence.append(ref)
        return evidence[:8]

    def _fallback_answer(self, question: str | list[dict[str, Any]], tool_results: list[dict[str, Any]] | None = None) -> AgentFinalAnswer:
        if tool_results is None:
            tool_results = question if isinstance(question, list) else []
            question = ""
        deterministic = self._deterministic_answer(question, tool_results)
        if deterministic:
            return deterministic
        evidence = self._collect_evidence(tool_results)
        freshness = merge_data_freshness(tool_results)
        if evidence:
            return AgentFinalAnswer(
                answer="I gathered cluster evidence, but I could not produce a fully structured answer. Review the cited evidence and continue with a narrower follow-up if needed.",
                evidence=evidence,
                confidence="low",
                data_freshness=freshness,
            )
        return AgentFinalAnswer(
            answer="I could not find enough evidence in the stored cluster data to answer confidently.",
            evidence=[],
            confidence="low",
            data_freshness=freshness,
        )

    def _deterministic_answer(self, question: str, tool_results: list[dict[str, Any]]) -> AgentFinalAnswer | None:
        normalized = question.lower()
        freshness = merge_data_freshness(tool_results)
        evidence = self._collect_evidence(tool_results)
        snapshot_item = next(
            (
                item
                for result in tool_results
                for item in result.get("items", [])
                if isinstance(item, dict) and item.get("source_type") == "snapshot"
            ),
            None,
        )
        issue_summary = next((result for result in tool_results if isinstance(result.get("aggregates"), list)), None)
        incident_summary = next(
            (
                result
                for result in tool_results
                if any(isinstance(item, dict) and item.get("source_type") == "incident" for item in result.get("items", []))
            ),
            None,
        )

        if snapshot_item and any(token in normalized for token in ["how many", "count", "number of"]):
            if "namespace" in normalized and isinstance(snapshot_item.get("namespaces"), int):
                count = snapshot_item["namespaces"]
                return AgentFinalAnswer(
                    answer=f"The latest stored cluster snapshot shows {count} namespace{'s' if count != 1 else ''}.",
                    evidence=evidence,
                    confidence="high",
                    data_freshness=freshness,
                )
            if "pod" in normalized and isinstance(snapshot_item.get("pods"), int):
                count = snapshot_item["pods"]
                return AgentFinalAnswer(
                    answer=f"The latest stored cluster snapshot shows {count} pod{'s' if count != 1 else ''}.",
                    evidence=evidence,
                    confidence="high",
                    data_freshness=freshness,
                )
            if "deployment" in normalized and isinstance(snapshot_item.get("deployments"), int):
                count = snapshot_item["deployments"]
                return AgentFinalAnswer(
                    answer=f"The latest stored cluster snapshot shows {count} deployment{'s' if count != 1 else ''}.",
                    evidence=evidence,
                    confidence="high",
                    data_freshness=freshness,
                )

        if any(token in normalized for token in ["error", "issue", "incident", "problem"]) and any(token in normalized for token in ["how many", "count", "number of"]):
            parts: list[str] = []
            if issue_summary and isinstance(issue_summary.get("count"), int):
                parts.append(f"{issue_summary['count']} recent issue{'s' if issue_summary['count'] != 1 else ''}")
            if incident_summary and isinstance(incident_summary.get("count"), int):
                parts.append(f"{incident_summary['count']} recent incident{'s' if incident_summary['count'] != 1 else ''}")
            if parts:
                window_label = self._time_window_label(normalized)
                return AgentFinalAnswer(
                    answer=f"From the stored cluster evidence, I found {' and '.join(parts)}{window_label}.",
                    evidence=evidence,
                    confidence="medium",
                    data_freshness=freshness,
                )
        return None

    def _time_window_label(self, question: str) -> str:
        match = re.search(r"last\s+(\d+)\s+(minute|minutes|hour|hours|day|days)\b", question)
        if not match:
            return " in the recent window I checked"
        amount = int(match.group(1))
        unit = match.group(2)
        return f" in the last {amount} {unit}"

    def _humanize_json_answer(self, question: str, payload: dict[str, Any]) -> str | None:
        if "namespace_count" in payload:
            count = payload["namespace_count"]
            return f"The latest stored cluster snapshot shows {count} namespace{'s' if count != 1 else ''}."
        if "deployment_count" in payload:
            count = payload["deployment_count"]
            return f"The latest stored cluster snapshot shows {count} deployment{'s' if count != 1 else ''}."
        if "pod_count" in payload:
            count = payload["pod_count"]
            return f"The latest stored cluster snapshot shows {count} pod{'s' if count != 1 else ''}."
        details = payload.get("details")
        if any(key.startswith("errors_in_last_") for key in payload.keys()) and isinstance(details, list):
            truthy_key = next(key for key in payload.keys() if key.startswith("errors_in_last_"))
            has_errors = bool(payload.get(truthy_key))
            if not has_errors:
                return f"No, I did not find any errors in {truthy_key.removeprefix('errors_in_').replace('_', ' ')}."
            summary = self._summarize_detail_rows(details)
            return f"Yes. I found {summary}."
        if "total_errors" in payload and isinstance(details, list):
            total = payload["total_errors"]
            summary = self._summarize_detail_rows(details)
            return f"I found {total} error signal{'s' if total != 1 else ''} in the stored cluster evidence. {summary}."
        return None

    def _summarize_detail_rows(self, details: list[Any]) -> str:
        phrases: list[str] = []
        for item in details[:3]:
            if not isinstance(item, dict):
                continue
            label = item.get("issue_type") or item.get("type") or item.get("title") or "issue"
            count = item.get("count")
            namespace = item.get("namespace")
            phrase = f"{count} {label}" if isinstance(count, int) else str(label)
            if namespace:
                phrase += f" in {namespace}"
            summary = item.get("summary") or item.get("description")
            if isinstance(summary, str) and summary:
                phrase += f" ({summary})"
            phrases.append(phrase)
        if not phrases:
            return "cluster issues in the latest stored evidence"
        if len(phrases) == 1:
            return phrases[0]
        return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
