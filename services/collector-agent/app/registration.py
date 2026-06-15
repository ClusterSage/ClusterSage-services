import logging
import httpx
from app.config import settings
from app.models import AgentState

log = logging.getLogger(__name__)

async def register(state: AgentState) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{settings.clusterwatch_backend_url.rstrip('/')}/api/agent/register", json={"email": settings.clusterwatch_email, "access_key": settings.clusterwatch_access_key, "cluster_name": settings.clusterwatch_cluster_name, "provider": settings.clusterwatch_cluster_provider, "agent_version": settings.clusterwatch_agent_version})
        response.raise_for_status()
        data = response.json()
        state.cluster_id = data["cluster_id"]
        state.agent_token = data["agent_token"]
        log.info("registered cluster_id=%s", state.cluster_id)
