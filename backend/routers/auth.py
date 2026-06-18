from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.storage.database import get_db, UserDB
from backend.models.schemas import LoginRequest, Token, User
from backend.auth.jwt import verify_password, get_password_hash, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Token)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login and receive JWT token per spec.md section 5.4"""
    result = await db.execute(select(UserDB).where(UserDB.username == request.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": user.username, "role": user.role, "tenant": user.tenant})
    return Token(access_token=access_token)


@router.get("/me", response_model=User)
async def get_me(current_user: UserDB = Depends(get_current_user)):
    """Get current user profile per spec.md section 5.4"""
    return User(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
        tenant=current_user.tenant
    )
