from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import AIConversation, AIMessage


async def load_recent_conversation_turns(session: AsyncSession, conversation: AIConversation) -> list[AIMessage]:
    rows = (
        await session.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation.id)
            .order_by(AIMessage.created_at.desc())
            .limit(settings.ai_agent_max_history_messages)
        )
    ).scalars().all()
    return list(reversed(rows))
