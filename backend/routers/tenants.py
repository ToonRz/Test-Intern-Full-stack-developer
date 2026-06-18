"""
Tenant Management — Tenant registry for UI listing and admin workflows.

Per spec §6, multi-tenant isolation is **field-level** (every `LogEntry` row
carries a `tenant` column, every API request is scoped by JWT tenant claim).
There is no schema-per-tenant isolation — all logs live in `public.logs` and
are filtered at query time. This module manages the *registry* of tenants
(used by the User Management UI to populate the tenant dropdown) but does
not create separate database schemas.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from backend.storage.database import get_db, TenantDB, UserDB
from backend.auth.jwt import get_current_user

router = APIRouter(prefix="/tenants", tags=["Tenants"])


class TenantCreate(BaseModel):
    name: str
    description: Optional[str] = None


class TenantResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    created_at: str


def _require_admin(user: UserDB) -> None:
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /tenants — list all registered tenants (Admin only)."""
    _require_admin(current_user)
    result = await db.execute(select(TenantDB).order_by(TenantDB.created_at.desc()))
    tenants = result.scalars().all()
    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            is_active=t.is_active,
            created_at=t.created_at.isoformat() if t.created_at else None,
        )
        for t in tenants
    ]


@router.post("", response_model=TenantResponse)
async def create_tenant(
    data: TenantCreate,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /tenants — register a new tenant (Admin only).

    Note: this only adds the tenant to the registry table used by the UI. It
    does NOT create a separate database schema — logs for all tenants continue
    to land in `public.logs`, partitioned by the `tenant` column.
    """
    _require_admin(current_user)

    existing = await db.execute(select(TenantDB).where(TenantDB.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant already exists")

    tenant = TenantDB(
        name=data.name,
        description=data.description,
        is_active=True,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        description=tenant.description,
        is_active=tenant.is_active,
        created_at=tenant.created_at.isoformat() if tenant.created_at else None,
    )


@router.delete("/{tenant_id}")
async def delete_tenant(
    tenant_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DELETE /tenants/{id} — remove a tenant from the registry (Admin only).

    Historical logs for the tenant remain in `public.logs` for the 7-day
    retention window and are filtered out of Viewer queries only after the
    registry entry is gone. Active users tied to this tenant must be
    reassigned first.
    """
    _require_admin(current_user)

    result = await db.execute(select(TenantDB).where(TenantDB.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    await db.delete(tenant)
    await db.commit()
    return {"status": "deleted", "tenant": tenant.name}
