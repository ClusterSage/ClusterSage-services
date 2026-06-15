import asyncio
import gzip
import json
import logging
from typing import Any
import httpx
from app.config import settings
from app.models import AgentState

log = logging.getLogger(__name__)

async def post_with_retry(state: AgentState, path: str, payload: dict[str, Any], gzip_body: bool = True) -> None:
    if not state.agent_token:
        raise RuntimeError("agent is not registered")
    body = json.dumps(payload, default=str).encode("utf-8")
    headers = {"Authorization": f"Bearer {state.agent_token}", "Content-Type": "application/json"}
    if gzip_body:
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    delay = 1
    for attempt in range(1, 6):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(f"{settings.clusterwatch_backend_url.rstrip('/')}{path}", content=body, headers=headers)
                response.raise_for_status()
                return
        except Exception as exc:
            log.warning("send failed path=%s attempt=%s error=%s", path, attempt, exc)
            if attempt == 5:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
