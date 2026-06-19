import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.config import get_settings
from backend.storage.database import get_db, UserDB

settings = get_settings()

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


def _extract_token(request: Request) -> Optional[str]:
    """Pull JWT from cookie (browser path) or Authorization header (CLI/curl).

    Low #27: cookie is the preferred path for the SPA — HttpOnly means an
    XSS payload cannot exfiltrate the token via `document.cookie`. The
    Authorization header fallback exists so non-browser clients (curl, the
    test suite, future mobile apps) don't need a separate code path.
    """
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if token:
        return token
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB:
    # Per spec §6, missing and invalid auth both return 401.
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(UserDB).where(UserDB.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # Critical #5: re-validate token against the user's last update. If an admin
    # changed role/tenant/password after this token was issued, the cached
    # claims are stale — force re-login so the user gets a fresh token that
    # reflects the new state. Prevents privilege escalation after demote.
    if user.updated_at is not None:
        iat = payload.get("iat")
        if iat is not None:
            # JWT iat may be int (unix seconds) or ISO string depending on
            # encoder — normalize to datetime for comparison.
            iat_dt = (
                datetime.fromtimestamp(iat, tz=timezone.utc)
                if isinstance(iat, (int, float))
                else datetime.fromisoformat(str(iat))
            )
            # SQLite drops tzinfo on read; treat naive values as UTC so the
            # comparison stays safe across dialects.
            updated_at = user.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            # Truncate to seconds before comparing — iat is second-precision
            # by spec, while updated_at carries microseconds. Without this,
            # a token issued microseconds after the user was created/updated
            # would falsely look "stale" because updated_at > iat by 0.000001s.
            updated_at_seconds = updated_at.replace(microsecond=0)
            if iat_dt < updated_at_seconds:
                raise HTTPException(
                    status_code=401,
                    detail="Token revoked — credentials changed. Please log in again.",
                )
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
