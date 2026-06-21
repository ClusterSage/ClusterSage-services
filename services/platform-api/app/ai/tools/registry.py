from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.evidence import compact_tool_result
from app.ai.agent.models import AgentExecutionContext, ToolExecutionRecord
from app.ai.tools.blobs import (
    ListClusterDocumentsInput,
    ReadClusterDocumentExcerptInput,
    list_cluster_documents,
    read_cluster_document_excerpt,
)
from app.ai.tools.deployments import RecentDeploymentsInput, get_recent_deployments
from app.ai.tools.incidents import (
    GetIncidentDetailsInput,
    ListClusterIncidentsInput,
    get_incident_details,
    list_cluster_incidents,
)
from app.ai.tools.issues import ClusterIssueSummaryInput, get_cluster_issue_summary
from app.ai.tools.knowledge_base import KnowledgeBaseSearchInput, search_knowledge_base
from app.ai.tools.logs import SearchClusterLogsInput, search_cluster_logs
from app.ai.tools.snapshots import EmptyToolInput, WorkloadStatusInput, get_latest_cluster_snapshot_summary, get_workload_status
from app.core.config import settings

ToolExecutor = Callable[[AsyncSession, AgentExecutionContext, BaseModel], Awaitable[dict[str, Any]]]
ContextToolExecutor = Callable[[AgentExecutionContext, BaseModel], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class RegisteredTool:
    name: str
    description: str
    schema: type[BaseModel]
    executor: ToolExecutor | None = None
    context_executor: ContextToolExecutor | None = None

    def openai_schema(self) -> dict[str, Any]:
        json_schema = self.schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": json_schema,
            },
        }


def _knowledge_base_executor(_: AsyncSession, __: AgentExecutionContext, args: BaseModel) -> Awaitable[dict[str, Any]]:
    async def run() -> dict[str, Any]:
        return search_knowledge_base(args)  # type: ignore[arg-type]
    return run()


def _context_only(executor: ContextToolExecutor) -> ToolExecutor:
    async def wrapped(_: AsyncSession, ctx: AgentExecutionContext, args: BaseModel) -> dict[str, Any]:
        return await executor(ctx, args)
    return wrapped


TOOLS = [
    RegisteredTool("search_knowledge_base", "Search the curated ClusterSage knowledge base for short relevant sections.", KnowledgeBaseSearchInput, executor=_knowledge_base_executor),
    RegisteredTool("list_cluster_incidents", "List recent incidents for the selected cluster with optional filters.", ListClusterIncidentsInput, executor=list_cluster_incidents),
    RegisteredTool("get_incident_details", "Get details for one incident that belongs to the selected cluster.", GetIncidentDetailsInput, executor=get_incident_details),
    RegisteredTool("get_cluster_issue_summary", "Summarize recent issues for the selected cluster.", ClusterIssueSummaryInput, executor=get_cluster_issue_summary),
    RegisteredTool("get_latest_cluster_snapshot_summary", "Return a compact summary of the latest stored cluster snapshot.", EmptyToolInput, executor=get_latest_cluster_snapshot_summary),
    RegisteredTool("get_workload_status", "Return compact stored workload status, related pods, and restart counts.", WorkloadStatusInput, executor=get_workload_status),
    RegisteredTool("get_recent_deployments", "Return recent stored deployments from the selected cluster.", RecentDeploymentsInput, executor=get_recent_deployments),
    RegisteredTool("search_cluster_logs", "Search bounded recent stored logs for matching text or failure patterns.", SearchClusterLogsInput, executor=search_cluster_logs),
    RegisteredTool("list_cluster_documents", "List approved cluster documents under the allowed blob prefix.", ListClusterDocumentsInput, executor=_context_only(list_cluster_documents)),
    RegisteredTool("read_cluster_document_excerpt", "Read a bounded excerpt from an approved cluster document.", ReadClusterDocumentExcerptInput, executor=_context_only(read_cluster_document_excerpt)),
]

TOOL_MAP = {tool.name: tool for tool in TOOLS}


def tool_schemas() -> list[dict[str, Any]]:
    return [tool.openai_schema() for tool in TOOLS]


async def execute_tool(
    session: AsyncSession,
    ctx: AgentExecutionContext,
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], ToolExecutionRecord]:
    started_at = datetime.now(timezone.utc)
    tool = TOOL_MAP[tool_name]
    try:
        parsed = tool.schema.model_validate(arguments)
    except ValidationError as exc:
        finished_at = datetime.now(timezone.utc)
        return (
            {"count": 0, "items": [], "truncated": False, "message": f"{tool_name} arguments were invalid"},
            ToolExecutionRecord(
                tool_name=tool_name,
                status="error",
                started_at=started_at,
                finished_at=finished_at,
                arguments=arguments,
                result_summary={"tool": tool_name, "error": "invalid_arguments", "details": exc.errors(include_url=False)},
            ),
        )
    try:
        result = await asyncio.wait_for(
            tool.executor(session, ctx, parsed),  # type: ignore[misc]
            timeout=settings.ai_agent_tool_timeout_seconds,
        )
        finished_at = datetime.now(timezone.utc)
        return result, ToolExecutionRecord(
            tool_name=tool_name,
            status="ok",
            started_at=started_at,
            finished_at=finished_at,
            arguments=arguments,
            result_summary=compact_tool_result(tool_name, result),
        )
    except asyncio.TimeoutError:
        finished_at = datetime.now(timezone.utc)
        return (
            {"count": 0, "items": [], "truncated": True, "message": f"{tool_name} timed out"},
            ToolExecutionRecord(
                tool_name=tool_name,
                status="timeout",
                started_at=started_at,
                finished_at=finished_at,
                arguments=arguments,
                result_summary={"tool": tool_name, "timeout": True},
            ),
        )
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        return (
            {"count": 0, "items": [], "truncated": False, "message": f"{tool_name} failed"},
            ToolExecutionRecord(
                tool_name=tool_name,
                status="error",
                started_at=started_at,
                finished_at=finished_at,
                arguments=arguments,
                result_summary={"tool": tool_name, "error": type(exc).__name__},
            ),
        )
