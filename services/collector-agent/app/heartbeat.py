import asyncio
import logging
from app.config import settings
from app.models import AgentState
from app.sender import post_with_retry

log = logging.getLogger(__name__)

async def heartbeat_loop(state: AgentState) -> None:
    while True:
        try:
            await post_with_retry(state, "/api/agent/heartbeat", {"status": "healthy", "agent_version": settings.clusterwatch_agent_version}, gzip_body=False)
        except Exception as exc:
            log.error("heartbeat failed: %s", exc)
        await asyncio.sleep(settings.clusterwatch_heartbeat_interval_seconds)
