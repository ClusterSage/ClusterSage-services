import gzip
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.audit.service import write_audit
from app.auth.dependencies import get_current_agent
from app.db.session import get_session
from app.issues.detection import detect_from_events, detect_from_snapshot
from app.models.entities import Cluster, ClusterSnapshot, LogBatch
from app.schemas.api import EventsIngestRequest, LogsIngestRequest, SnapshotIngestRequest
from app.storage.blob import BlobWriter

router = APIRouter(tags=["ingestion"])

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
