from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import get_current_user
from app.db.session import get_session
from app.models.entities import AuditLog, User
from app.schemas.api import AuditLogResponse

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])

@router.get("", response_model=list[AuditLogResponse])
async def audit_logs(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(AuditLog).where(AuditLog.organization_id == user.organization_id).order_by(AuditLog.created_at.desc()).limit(200))).scalars().all()
