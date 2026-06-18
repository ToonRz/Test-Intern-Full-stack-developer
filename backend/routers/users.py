"""User Management API — Admin-only user CRUD."""
import bcrypt
"""User Management API — Admin-only user CRUD."""
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from backend.storage.database import get_db, UserDB
from backend.auth.jwt import get_current_user, get_password_hash, verify_password

router = APIRouter(prefix="/users", tags=["Users"])

MAX_PASSWORD_BYTES = 72  # bcrypt limit


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: Optional[EmailStr] = None
    password: str = Field(min_length=8, max_length=128)
    role: str = "Viewer"
    tenant: str = ""


class UserUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    role: Optional[str] = None
    tenant: Optional[str] = None
    email: Optional[EmailStr] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    tenant: str
    created_at: Optional[str]


def _require_admin(user: UserDB) -> None:
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")


def _to_response(u: UserDB) -> UserResponse:
    return UserResponse(
        id=u.id,
        username=u.username,
        email=u.email,
        role=u.role,
        tenant=u.tenant,
        created_at=u.created_at.isoformat() if u.created_at else None,
    )


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /users — list all users (Admin only)."""
    _require_admin(current_user)
    result = await db.execute(select(UserDB).order_by(UserDB.created_at.desc()))
    return [_to_response(u) for u in result.scalars().all()]


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /users — create new user (Admin only)."""
    _require_admin(current_user)

    if data.role not in ("Admin", "Viewer"):
        raise HTTPException(status_code=400, detail="role must be Admin or Viewer")

    existing = (await db.execute(
        select(UserDB).where(UserDB.username == data.username)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = UserDB(
        username=data.username,
        email=data.email,
        role=data.role,
        tenant=data.tenant or ("*" if data.role == "Admin" else ""),
        hashed_password=get_password_hash(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """PATCH /users/{id} — update user (Admin only)."""
    _require_admin(current_user)

    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.password:
        user.hashed_password = get_password_hash(data.password)
    if data.role:
        if data.role not in ("Admin", "Viewer"):
            raise HTTPException(status_code=400, detail="role must be Admin or Viewer")
        user.role = data.role
    if data.tenant is not None:
        user.tenant = data.tenant
    if data.email is not None:
        user.email = data.email

    await db.commit()
    await db.refresh(user)
    return _to_response(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DELETE /users/{id} — delete user (Admin only)."""
    _require_admin(current_user)

    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete the built-in admin user")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    await db.delete(user)
    await db.commit()
    return {"status": "deleted", "username": user.username}
