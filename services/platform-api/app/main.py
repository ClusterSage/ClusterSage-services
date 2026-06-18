import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.alerts.loop import alert_evaluation_loop
from app.alerts.router import router as alerts_router
from app.agent_keys.router import router as agent_keys_router
from app.agents.router import router as agents_router
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.clusters.router import router as clusters_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from app.ingestion.router import router as ingestion_router
from app.remediation.router import router as remediation_router

configure_logging()
app = FastAPI(title=settings.app_name, version="0.1.0", docs_url="/docs", openapi_url="/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.log_batch_max_size_mb * 1024 * 1024)
app.add_middleware(RateLimitMiddleware, requests_per_minute=600)


@app.on_event("startup")
async def start_alert_evaluator() -> None:
    if settings.alert_evaluation_enabled:
        app.state.alert_evaluation_task = asyncio.create_task(alert_evaluation_loop())


@app.on_event("shutdown")
async def stop_alert_evaluator() -> None:
    task = getattr(app.state, "alert_evaluation_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}

app.include_router(auth_router)
app.include_router(agent_keys_router)
app.include_router(agents_router)
app.include_router(ingestion_router)
app.include_router(clusters_router)
app.include_router(alerts_router)
app.include_router(audit_router)
app.include_router(remediation_router)
