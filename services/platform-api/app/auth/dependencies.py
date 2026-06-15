import uuid
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.security import decode_agent_token, decode_user_token
from app.db.session import get_session
from app.models.entities import Cluster, User

bearer = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: AsyncSession = Depends(get_session)) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = decode_user_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

async def get_current_agent(authorization: str | None = Header(default=None), session: AsyncSession = Depends(get_session)) -> Cluster:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing agent token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_agent_token(token)
        cluster_id = uuid.UUID(payload["cluster_id"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")
    cluster = await session.get(Cluster, cluster_id)
    if not cluster or cluster.status == "deactivated":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cluster inactive")
    return cluster
