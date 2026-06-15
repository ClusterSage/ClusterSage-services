from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.audit.service import write_audit
from app.auth.dependencies import get_current_user
from app.auth.security import create_user_token, hash_password, verify_password
from app.db.session import get_session
from app.models.entities import Organization, User
from app.schemas.api import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)):
    existing = (await session.execute(select(User).where(User.email == payload.email.lower()))).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    org = Organization(name=payload.organization_name)
    session.add(org)
    await session.flush()
    user = User(organization_id=org.id, email=payload.email.lower(), password_hash=hash_password(payload.password), full_name=payload.full_name, role="owner")
    session.add(user)
    await session.flush()
    await write_audit(session, "user.registration", "user", org.id, user.id, details={"email": user.email})
    await session.commit()
    return TokenResponse(access_token=create_user_token(str(user.id), str(org.id), user.role))

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.email == payload.email.lower()))).scalars().first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    await write_audit(session, "user.login", "user", user.organization_id, user.id, details={"email": user.email})
    await session.commit()
    return TokenResponse(access_token=create_user_token(str(user.id), str(user.organization_id), user.role))

@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
