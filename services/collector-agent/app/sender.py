import asyncio
import gzip
import json
import logging
from typing import Any
import httpx
from app.config import settings
from app.models import AgentState

log = logging.getLogger(__name__)

async def request_json_with_retry(
    state: AgentState,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    gzip_body: bool = False,
) -> dict[str, Any]:
    if not state.agent_token:
        raise RuntimeError("agent is not registered")
    headers = {"Authorization": f"Bearer {state.agent_token}", "Content-Type": "application/json"}
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload, default=str).encode("utf-8")
    if gzip_body:
        if body is None:
            raise RuntimeError("gzip_body requires a request payload")
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    delay = 1
    for attempt in range(1, 6):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.request(method, f"{settings.clusterwatch_backend_url.rstrip('/')}{path}", content=body, headers=headers)
                response.raise_for_status()
                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()
        except Exception as exc:
            log.warning("request failed method=%s path=%s attempt=%s error=%s", method, path, attempt, exc)
            if attempt == 5:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

async def post_with_retry(state: AgentState, path: str, payload: dict[str, Any], gzip_body: bool = True) -> None:
    await request_json_with_retry(state, "POST", path, payload, gzip_body=gzip_body)

async def post_json_with_retry(state: AgentState, path: str, payload: dict[str, Any], gzip_body: bool = False) -> dict[str, Any]:
    return await request_json_with_retry(state, "POST", path, payload, gzip_body=gzip_body)
