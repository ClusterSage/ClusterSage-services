from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import AuditLog

async def write_audit(session: AsyncSession, action: str, actor_type: str, organization_id: UUID | None = None, user_id: UUID | None = None, cluster_id: UUID | None = None, details: dict | None = None) -> None:
    session.add(AuditLog(action=action, actor_type=actor_type, organization_id=organization_id, user_id=user_id, cluster_id=cluster_id, details=details or {}))
