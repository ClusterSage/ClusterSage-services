from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.audit.service import write_audit
from app.auth.dependencies import get_current_user
from app.auth.security import generate_agent_key, hash_secret
from app.db.session import get_session
from app.models.entities import AgentKey, User
from app.schemas.api import AgentKeyCreate, AgentKeyResponse

router = APIRouter(prefix="/api/agent-keys", tags=["agent-keys"])

@router.post("", response_model=AgentKeyResponse, status_code=201)
async def create_agent_key(payload: AgentKeyCreate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    raw_key = generate_agent_key()
    entity = AgentKey(organization_id=user.organization_id, created_by_user_id=user.id, name=payload.name, key_hash=hash_secret(raw_key), key_last4=raw_key[-4:], expires_at=payload.expires_at)
    session.add(entity)
    await session.flush()
    await write_audit(session, "agent_key.created", "user", user.organization_id, user.id, details={"key_id": str(entity.id), "name": entity.name})
    await session.commit()
    response = AgentKeyResponse.model_validate(entity)
    response.raw_key = raw_key
    return response

@router.get("", response_model=list[AgentKeyResponse])
async def list_agent_keys(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(AgentKey).where(AgentKey.organization_id == user.organization_id).order_by(AgentKey.created_at.desc()))).scalars().all()
    return rows

@router.delete("/{keyId}", status_code=204)
async def revoke_agent_key(keyId: UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    key = await session.get(AgentKey, keyId)
    if not key or key.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Agent key not found")
    key.revoked_at = datetime.now(timezone.utc)
    await write_audit(session, "agent_key.revoked", "user", user.organization_id, user.id, details={"key_id": str(key.id)})
    await session.commit()
    return None
