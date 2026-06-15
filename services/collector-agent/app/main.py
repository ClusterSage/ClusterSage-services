import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.heartbeat import heartbeat_loop
from app.kubernetes_client import snapshot_loop
from app.log_receiver import flush_loop, router as log_router
from app.models import AgentState
from app.registration import register

logging.basicConfig(level=getattr(logging, settings.clusterwatch_log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
state = AgentState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    while not state.agent_token:
        try:
            await register(state)
        except Exception as exc:
            logging.getLogger(__name__).error("registration failed: %s", exc)
            await asyncio.sleep(10)
    tasks = [asyncio.create_task(heartbeat_loop(state)), asyncio.create_task(snapshot_loop(state)), asyncio.create_task(flush_loop(state))]
    yield
    for task in tasks:
        task.cancel()

app = FastAPI(title="ClusterWatch Collector", lifespan=lifespan)
app.include_router(log_router)

@app.get("/healthz")
async def healthz():
    return {"ok": True, "cluster_id": state.cluster_id}
