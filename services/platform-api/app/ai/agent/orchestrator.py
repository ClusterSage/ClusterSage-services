from __future__ import annotations

import asyncio
import json
import logging
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
            final = self._parse_final_answer(message.get("content"), tool_results)
            return final, tool_records, usage

        final = self._fallback_answer(tool_results)
        return final, tool_records, usage

    def _parse_final_answer(self, content: str | None, tool_results: list[dict[str, Any]]) -> AgentFinalAnswer:
        if content:
            try:
                parsed = AgentFinalAnswer.model_validate_json(content)
                return parsed
            except Exception:
                log.warning("agent returned malformed output; using fallback parser")
        return self._fallback_answer(tool_results)

    def _fallback_answer(self, tool_results: list[dict[str, Any]]) -> AgentFinalAnswer:
        evidence = []
        for result in tool_results:
            for item in result.get("items", [])[:6]:
                ref = normalize_evidence_reference(item)
                if ref:
                    evidence.append(ref)
        freshness = merge_data_freshness(tool_results)
        if evidence:
            return AgentFinalAnswer(
                answer="I gathered cluster evidence, but I could not produce a fully structured answer. Review the cited evidence and continue with a narrower follow-up if needed.",
                evidence=evidence[:8],
                confidence="low",
                data_freshness=freshness,
            )
        return AgentFinalAnswer(
            answer="I could not find enough evidence in the stored cluster data to answer confidently.",
            evidence=[],
            confidence="low",
            data_freshness=freshness,
        )
