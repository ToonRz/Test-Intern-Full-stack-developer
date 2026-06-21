from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.storage.database import get_db, UserDB
from backend.models.schemas import LoginRequest, Token, User
from backend.auth.jwt import verify_password, get_password_hash, create_access_token, get_current_user
from backend.config import get_settings
from backend.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


def _set_auth_cookie(response: Response, token: str, request: Request) -> None:
    """Attach the JWT as an HttpOnly cookie (Low #27).

    HttpOnly: `document.cookie` cannot read this value, so XSS payloads can't
    exfiltrate the session. Secure: only sent over HTTPS in production; local
    dev (HTTP) keeps working because we tie the flag to the actual request
    scheme. SameSite=Lax: blocks cross-origin POST/PUT/DELETE (the CSRF vector
    that matters) while still allowing top-level navigation. Path=/api/v1: the
    cookie is not attached to static frontend asset requests.
    """
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=settings.AUTH_COOKIE_PATH,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Login and receive JWT token per spec.md section 5.4.

    Rate-limited to 5 attempts per minute per remote IP (Critical #4).
    The slowapi middleware converts overflow into HTTP 429.

    Low #27: also sets the token as an HttpOnly cookie so the browser SPA
    authenticates subsequent requests without exposing the JWT to JavaScript.
    The body still carries `access_token` for non-browser clients (CLI, curl,
    future mobile apps) that can't rely on cookie storage.
    """
    result = await db.execute(select(UserDB).where(UserDB.username == data.username))
    user = result.scalar_one_or_none()

    # Constant-time login: always run bcrypt, even when the user doesn't exist.
    # Without this, an attacker timing-distinguishes "unknown username" (~1 ms)
    # from "wrong password" (~50 ms bcrypt verify) and enumerates valid users.
    # The dummy hash below is a real bcrypt digest so the work is identical
    # regardless of which branch fires.
    DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RqHpwQJW."
    password_to_check = user.hashed_password if user else DUMMY_HASH
    password_ok = verify_password(data.password, password_to_check)

    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "tenant": user.tenant}
    )
    _set_auth_cookie(response, access_token, request)
    return Token(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: Request, response: Response):
    """Clear the auth cookie. Idempotent — safe to call when no cookie is set."""
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return {"status": "ok"}


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
