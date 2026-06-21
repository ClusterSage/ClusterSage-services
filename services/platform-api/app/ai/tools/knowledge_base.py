from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings

KB_DIR = Path(__file__).resolve().parents[1] / "knowledge_base"


class KnowledgeBaseSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    max_results: int = Field(default=3, ge=1, le=5)


@dataclass(slots=True)
class KnowledgeBaseSection:
    document_id: str
    title: str
    tags: list[str]
    source: str
    section_title: str
    content: str


def _load_manifest() -> list[dict[str, Any]]:
    return json.loads((KB_DIR / "manifest.json").read_text(encoding="utf-8"))


def _split_sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"^##\s+", text, flags=re.MULTILINE)
    sections: list[tuple[str, str]] = []
    if parts and parts[0].strip():
        sections.append(("Overview", parts[0].strip()))
    for part in parts[1:]:
        lines = part.splitlines()
        heading = lines[0].strip() if lines else "Section"
        body = "\n".join(lines[1:]).strip()
        if body:
            sections.append((heading, body))
    return sections


def _score(query: str, *, title: str, tags: list[str], section_title: str, content: str) -> int:
    words = [word for word in re.findall(r"[a-z0-9-]+", query.lower()) if len(word) > 1]
    score = 0
    haystacks = [title.lower(), section_title.lower(), " ".join(tags).lower(), content.lower()]
    for word in words:
        if word in haystacks[0]:
            score += 6
        if word in haystacks[1]:
            score += 5
        if word in haystacks[2]:
            score += 4
        if word in haystacks[3]:
            score += 1
    if query.lower() in content.lower():
        score += 8
    return score


def search_knowledge_base(args: KnowledgeBaseSearchInput) -> dict[str, Any]:
    matches: list[tuple[int, KnowledgeBaseSection]] = []
    for entry in _load_manifest():
        if args.category and args.category not in entry.get("tags", []):
            continue
        text = (KB_DIR / entry["path"]).read_text(encoding="utf-8")
        for section_title, section_content in _split_sections(text):
            score = _score(
                args.query,
                title=entry["title"],
                tags=list(entry.get("tags", [])),
                section_title=section_title,
                content=section_content,
            )
            if score <= 0:
                continue
            matches.append(
                (
                    score,
                    KnowledgeBaseSection(
                        document_id=entry["id"],
                        title=entry["title"],
                        tags=list(entry.get("tags", [])),
                        source=entry["source"],
                        section_title=section_title,
                        content=section_content[:2000],
                    ),
                )
            )
    matches.sort(key=lambda item: item[0], reverse=True)
    deduped: list[KnowledgeBaseSection] = []
    seen: set[tuple[str, str]] = set()
    for _, section in matches:
        key = (section.document_id, section.section_title)
        if key in seen:
            continue
        deduped.append(section)
        seen.add(key)
        if len(deduped) >= min(args.max_results, settings.ai_agent_knowledge_base_max_results):
            break
    return {
        "count": len(deduped),
        "items": [
            {
                "source_type": "knowledge_base",
                "source_id": section.document_id,
                "title": f"{section.title}: {section.section_title}",
                "section_title": section.section_title,
                "content_excerpt": section.content,
                "source": section.source,
            }
            for section in deduped
        ],
    }
