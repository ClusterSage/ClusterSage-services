from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.agent.models import AgentExecutionContext
from app.ai.agent.safeguards import safe_reference, sanitize_text
from app.core.config import settings
from app.storage.blob import BlobReader

ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".log"}


class ListClusterDocumentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=20)


class ReadClusterDocumentExcerptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=400)
    search_terms: str | None = Field(default=None, max_length=200)
    section: str | None = Field(default=None, max_length=200)
    max_characters: int = Field(default=1200, ge=100, le=4000)


def _document_prefix(ctx: AgentExecutionContext) -> str:
    return f"documents/orgId={ctx.tenant_id}/clusterId={ctx.cluster_id}/"


async def list_cluster_documents(ctx: AgentExecutionContext, args: ListClusterDocumentsInput) -> dict[str, Any]:
    try:
        reader = BlobReader()
    except Exception:
        return {"count": 0, "items": []}
    items = []
    for blob_name in reader.list_blob_names(prefix=_document_prefix(ctx), limit=args.limit):
        extension = reader.blob_extension(blob_name)
        if extension not in ALLOWED_EXTENSIONS:
            continue
        items.append(
            {
                "source_type": "document",
                "source_id": blob_name,
                "title": blob_name.rsplit("/", 1)[-1],
            }
        )
    return {"count": len(items), "items": items}


async def read_cluster_document_excerpt(ctx: AgentExecutionContext, args: ReadClusterDocumentExcerptInput) -> dict[str, Any]:
    if not args.document_id.startswith(_document_prefix(ctx)):
        return {"count": 0, "items": []}
    reader = BlobReader()
    extension = reader.blob_extension(args.document_id)
    if extension not in ALLOWED_EXTENSIONS:
        return {"count": 0, "items": [], "message": "Unsupported document type"}
    body = reader.read_bytes(args.document_id, max_bytes=settings.ai_agent_max_blob_bytes)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return {"count": 0, "items": [], "message": "Unsupported document encoding"}
    excerpt = text
    if extension == ".json":
        try:
            excerpt = json.dumps(json.loads(text), indent=2)
        except Exception:
            excerpt = text
    if args.search_terms and args.search_terms.lower() in excerpt.lower():
        idx = excerpt.lower().index(args.search_terms.lower())
        start = max(0, idx - args.max_characters // 4)
        excerpt = excerpt[start : start + args.max_characters]
    else:
        excerpt = excerpt[: args.max_characters]
    return {
        "count": 1,
        "items": [
            {
                "source_type": "document",
                "source_id": args.document_id,
                "title": args.document_id.rsplit("/", 1)[-1],
                "content_excerpt": sanitize_text(excerpt, max_chars=args.max_characters),
            }
        ],
        "truncated": len(text) > len(excerpt),
    }
