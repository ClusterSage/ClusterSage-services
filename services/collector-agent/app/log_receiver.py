import asyncio
import logging
from fastapi import APIRouter, Request
from app.models import AgentState
from app.sender import post_with_retry

log = logging.getLogger(__name__)
router = APIRouter()
queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10000)

@router.post("/logs")
async def receive_logs(request: Request):
    payload = await request.json()
    records = payload if isinstance(payload, list) else [payload]
    accepted = 0
    for record in records:
        try:
            queue.put_nowait(record)
            accepted += 1
        except asyncio.QueueFull:
            log.warning("log queue full; dropping record")
            break
    return {"ok": True, "accepted": accepted}

async def flush_loop(state: AgentState) -> None:
    batch: list[dict] = []
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=5)
            batch.append(item)
            if len(batch) < 500:
                continue
        except asyncio.TimeoutError:
            pass
        if not batch:
            continue
        sending, batch = batch, []
        try:
            await post_with_retry(state, "/api/ingest/logs", {"logs": sending})
        except Exception as exc:
            log.error("log batch send failed; requeueing %s records: %s", len(sending), exc)
            for record in sending[:1000]:
                try: queue.put_nowait(record)
                except asyncio.QueueFull: break
            await asyncio.sleep(10)
