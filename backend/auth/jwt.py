import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.config import get_settings
from backend.storage.database import get_db, UserDB

settings = get_settings()
# auto_error=False so we can return a uniform 401 (spec §6) for both missing
# and invalid tokens. FastAPI's HTTPBearer default returns 403, which the spec
# reserves for "authorized but not allowed" cases.
security = HTTPBearer(auto_error=False)

# bcrypt silently truncates passwords >72 bytes. Pre-hash with SHA-256 to
# safely accept longer passwords without warning the user.
BCRYPT_MAX_BYTES = 72


def _bcrypt_input(password: str) -> bytes:
    pw = password.encode("utf-8")
    if len(pw) > BCRYPT_MAX_BYTES:
        pw = hashlib.sha256(pw).hexdigest().encode("utf-8")
    return pw


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_input(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> UserDB:
    # Per spec §6, missing and invalid auth both return 401.
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(UserDB).where(UserDB.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(user: UserDB = Depends(get_current_user)) -> UserDB:
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class TenantFilter:
    """Extract tenant from request — supports header, query param, or JWT claim."""

    @staticmethod
    async def get_tenant(
        request: Request,
        user: UserDB = Depends(get_current_user),
    ) -> str:
        if user.role == "Admin":
            tenant = request.headers.get("X-Tenant") or request.query_params.get("tenant")
            return tenant if tenant else "*"
        return user.tenant
