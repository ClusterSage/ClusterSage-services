import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def generate_agent_key() -> str:
    return "cw_live_" + secrets.token_urlsafe(32)

def hash_secret(secret: str) -> str:
    return pwd_context.hash(secret)

def verify_secret(secret: str, secret_hash: str) -> bool:
    return pwd_context.verify(secret, secret_hash)

def create_user_token(subject: str, organization_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "org": organization_id, "role": role, "exp": expire, "typ": "user"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def create_agent_token(cluster_id: str, organization_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.agent_token_expire_hours)
    payload = {"sub": cluster_id, "cluster_id": cluster_id, "org": organization_id, "exp": expire, "typ": "agent"}
    return jwt.encode(payload, settings.agent_token_secret, algorithm=settings.jwt_algorithm)

def decode_user_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("typ") != "user":
        raise JWTError("invalid token type")
    return payload

def decode_agent_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.agent_token_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("typ") != "agent":
        raise JWTError("invalid token type")
    return payload
