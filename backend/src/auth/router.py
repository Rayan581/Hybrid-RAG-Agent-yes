# =============================================================================
# backend/src/auth/router.py
# /auth/register, /auth/login, /auth/logout, /auth/refresh endpoints.
# Replaces the stub login in main.py.
# =============================================================================

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from src import db
from src.auth.security import (
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    JWT_EXPIRY_HOURS,
    create_access_token,
    hash_password,
    validate_password,
    verify_password,
    get_current_user,
)

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)

auth_router = APIRouter(prefix="/auth", tags=["Auth"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str
    email:    str
    password: str

    @field_validator("username")
    @classmethod
    def username_clean(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters.")
        if len(v) > 32:
            raise ValueError("Username must be at most 32 characters.")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, hyphens, and underscores.")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@auth_router.post("/register")
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest):
    # 1. Validate password
    errors = validate_password(body.password)
    if errors:
        raise HTTPException(422, detail={"password_errors": errors})

    # 2. Check uniqueness
    if await db.get_user_by_username(body.username):
        raise HTTPException(409, detail="Username already taken.")
    if await db.get_user_by_email(body.email):
        raise HTTPException(409, detail="Email already registered.")

    # 3. Hash + create
    pw_hash = hash_password(body.password)
    user_id = await db.create_user(body.username, body.email, pw_hash)

    # 4. Create empty CRM profile
    await db.upsert_crm_profile(user_id, {})

    logger.info(f"[auth] New user registered: {body.username} ({user_id})")
    return {"message": "Account created.", "user_id": user_id}


@auth_router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, response: Response, body: LoginRequest):
    # Hardcoded admin credentials
    if body.username == "admin" and body.password == "admin123":
        token = create_access_token("admin_hardcoded_id", "admin", is_admin=True)
        _secure = str(os.getenv("COOKIE_SECURE", "false")).lower() == "true"
        response.set_cookie(
            "access_token",
            token,
            httponly=True,
            secure=_secure,
            samesite="lax",
            max_age=JWT_EXPIRY_HOURS * 3600,
        )
        return {"access_token": token, "message": "Admin login successful."}

    user = await db.get_user_by_username(body.username)

    # Timing-safe: always do a dummy hash check if user not found to prevent
    # username enumeration via timing side-channel
    if not user:
        # Timing-safe: do a real-looking bcrypt check to prevent username enumeration
        # via timing side-channel. Use a real pre-computed hash of a dummy password.
        _dummy_hash = "$2b$12$KIXQu7Ti4eUiW5ILs5VPcuoSmHtfpHHHEuRqTfY7SyV3cnVEqOlDW"
        try:
            verify_password("dummy_timing_password", _dummy_hash)
        except Exception:
            pass
        raise HTTPException(401, detail="Invalid credentials.")

    # Account lockout check
    if user.get("locked_until"):
        locked_until = datetime.fromisoformat(user["locked_until"])
        if datetime.now(timezone.utc) < locked_until:
            remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
            raise HTTPException(
                429,
                detail=f"Account locked. Try again in {remaining} minute(s).",
            )

    # Inactive account
    if not user.get("is_active", 1):
        raise HTTPException(403, detail="Account is disabled. Contact support.")

    # Verify password
    if not verify_password(body.password, user["password_hash"]):
        await db.update_login_attempt(
            user["id"], success=False,
            max_attempts=MAX_FAILED_ATTEMPTS, lockout_minutes=LOCKOUT_MINUTES
        )
        current_failures = (user.get("failed_attempts") or 0) + 1
        remaining = MAX_FAILED_ATTEMPTS - current_failures
        if remaining <= 0:
            raise HTTPException(
                429,
                detail=f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes.",
            )
        raise HTTPException(
            401,
            detail=f"Invalid credentials. {remaining} attempt(s) remaining before lockout.",
        )

    # Success
    await db.update_login_attempt(user["id"], success=True)
    is_admin = bool(user.get("is_admin", 0))
    token = create_access_token(user["id"], user["username"], is_admin=is_admin)

    _secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=_secure,
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )
    logger.info(f"[auth] Login successful: {body.username}")
    return {"access_token": token, "token_type": "bearer", "username": user["username"]}


@auth_router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out."}


@auth_router.post("/refresh")
@limiter.limit("10/minute")
async def refresh_token(request: Request, response: Response, user: dict = Depends(get_current_user)):
    # Re-fetch user to pick up any admin flag changes
    db_user = await db.get_user_by_id(user["sub"])
    if not db_user:
        raise HTTPException(401, detail="User no longer exists.")
    is_admin = bool(db_user.get("is_admin", 0))
    token = create_access_token(user["sub"], user["username"], is_admin=is_admin)
    _secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        "access_token", token,
        httponly=True, secure=_secure, samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )
    return {"access_token": token, "message": "Token refreshed."}
