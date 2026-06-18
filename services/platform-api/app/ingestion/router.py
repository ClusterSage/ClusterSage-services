import gzip
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.ai import AIIncidentAnalysisService
from app.audit.service import write_audit
from app.auth.dependencies import get_current_agent
from app.core.config import settings
from app.db.session import get_session
from app.issues.detection import detect_from_events, detect_from_snapshot
from app.models.entities import Cluster, ClusterMetricSample, ClusterSnapshot, LogBatch
from app.schemas.api import EventsIngestRequest, LogsIngestRequest, MetricsIngestRequest, SnapshotIngestRequest
from app.storage.blob import BlobWriter

router = APIRouter(tags=["ingestion"])
log = logging.getLogger(__name__)
ai_incident_analysis_service = AIIncidentAnalysisService()

async def parse_payload(request: Request) -> dict:
    body = await request.body()
    if request.headers.get("content-encoding", "").lower() == "gzip":
        body = gzip.decompress(body)
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

@router.post("/api/ingest/logs")
async def ingest_logs(request: Request, cluster: Cluster = Depends(get_current_agent), session: AsyncSession = Depends(get_session)):
    payload = LogsIngestRequest.model_validate(await parse_payload(request))
    blob_path, size = BlobWriter().upload_json_gz("logs", str(cluster.organization_id), str(cluster.id), "batch", {"cluster_id": str(cluster.id), "logs": payload.logs})
    batch = LogBatch(organization_id=cluster.organization_id, cluster_id=cluster.id, blob_path=blob_path, log_count=len(payload.logs), size_bytes=size, start_time=payload.start_time, end_time=payload.end_time)
    session.add(batch)
    await session.commit()
    try:
        analysis_result = await ai_incident_analysis_service.analyze_log_records(session, cluster, payload.logs)
        await write_audit(
            session,
            "logs.ingested",
            "agent",
            cluster.organization_id,
            cluster_id=cluster.id,
            agent_id=cluster.id,
            ip_address=request.client.host if request.client else None,
            details={
                "blob_path": blob_path,
                "size_bytes": size,
                "log_count": len(payload.logs),
                "groups_processed": analysis_result.groups_processed,
                "incidents_upserted": analysis_result.incidents_upserted,
                "suggestions_upserted": analysis_result.suggestions_upserted,
                "ai_analysis_enabled": settings.ai_analysis_enabled,
            },
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        log.exception("log ingestion AI analysis failed for cluster %s: %s", cluster.id, exc)
    return {"ok": True, "blob_path": blob_path, "log_count": len(payload.logs)}

@router.post("/api/ingest/events")
async def ingest_events(request: Request, cluster: Cluster = Depends(get_current_agent), session: AsyncSession = Depends(get_session)):
    payload = EventsIngestRequest.model_validate(await parse_payload(request))
    blob_path, size = BlobWriter().upload_json_gz("events", str(cluster.organization_id), str(cluster.id), "events", {"cluster_id": str(cluster.id), "events": payload.events})
    await detect_from_events(session, cluster.organization_id, cluster.id, payload.events)
    await write_audit(session, "events.ingested", "agent", cluster.organization_id, cluster_id=cluster.id, details={"blob_path": blob_path, "size_bytes": size, "event_count": len(payload.events)})
    await session.commit()
    return {"ok": True, "blob_path": blob_path, "event_count": len(payload.events)}

@router.post("/api/ingest/snapshot")
async def ingest_snapshot(request: Request, cluster: Cluster = Depends(get_current_agent), session: AsyncSession = Depends(get_session)):
    payload = SnapshotIngestRequest.model_validate(await parse_payload(request))
    blob_path, size = BlobWriter().upload_json_gz("snapshots", str(cluster.organization_id), str(cluster.id), "snapshot", {"cluster_id": str(cluster.id), "snapshot_type": payload.snapshot_type, "snapshot": payload.snapshot})
    session.add(ClusterSnapshot(organization_id=cluster.organization_id, cluster_id=cluster.id, snapshot_type=payload.snapshot_type, blob_path=blob_path))
    await detect_from_snapshot(session, cluster.organization_id, cluster.id, payload.snapshot)
    await write_audit(session, "snapshot.ingested", "agent", cluster.organization_id, cluster_id=cluster.id, details={"blob_path": blob_path, "size_bytes": size})
    await session.commit()
    return {"ok": True, "blob_path": blob_path}

@router.post("/api/ingest/metrics")
async def ingest_metrics(request: Request, cluster: Cluster = Depends(get_current_agent), session: AsyncSession = Depends(get_session)):
    if not settings.metrics_ingestion_enabled:
        raise HTTPException(status_code=403, detail="Metrics ingestion is disabled in this environment")
    payload = MetricsIngestRequest.model_validate(await parse_payload(request))
    session.add_all(
        [
            ClusterMetricSample(
                organization_id=cluster.organization_id,
                cluster_id=cluster.id,
                scope=sample.scope,
                namespace=sample.namespace,
                resource_kind=sample.resource_kind,
                resource_name=sample.resource_name,
                container_name=sample.container_name,
                node_name=sample.node_name,
                metric_name=sample.metric_name,
                unit=sample.unit,
                value=sample.value,
                collected_at=payload.collected_at,
            )
            for sample in payload.samples
        ]
    )
    await write_audit(
        session,
        "metrics.ingested",
        "agent",
        cluster.organization_id,
        cluster_id=cluster.id,
        details={
            "sample_count": len(payload.samples),
            "collected_at": payload.collected_at.isoformat(),
        },
    )
    await session.commit()
    return {"ok": True, "sample_count": len(payload.samples), "collected_at": payload.collected_at.isoformat()}
