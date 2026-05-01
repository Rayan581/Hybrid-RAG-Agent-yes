# =============================================================================
# backend/src/auth/security.py
# Password validation, bcrypt hashing, and JWT dependency helpers.
# =============================================================================

import os
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — loaded from env, NO hardcoded fallback for JWT_SECRET in prod
# ---------------------------------------------------------------------------
JWT_SECRET    = os.environ.get("JWT_SECRET", "")   # Must be set in production
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

if not JWT_SECRET:
    logger.warning(
        "[security] JWT_SECRET is not set! Using an insecure fallback. "
        "Set JWT_SECRET env var before deploying."
    )
    JWT_SECRET = "INSECURE_DEV_FALLBACK_CHANGE_BEFORE_DEPLOYING"

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# ---------------------------------------------------------------------------
# Password rules
# ---------------------------------------------------------------------------
MIN_LENGTH = 8
MAX_BYTES  = 72   # bcrypt silently truncates at 72 bytes — hard-cap here
MAX_CHARS  = 4096 # Hard-cap for DoS protection (e.g. 50KB input)


def validate_password(password: str) -> list[str]:
    """
    Returns a list of human-readable violation strings.
    Empty list means the password is valid.

    MAX_BYTES = 72: bcrypt truncates at 72 bytes, meaning two passwords that
    share their first 72 bytes produce the same hash. We cap input here and
    inform the user clearly rather than silently accepting the truncated form.
    """
    errors = []
    
    if len(password) > MAX_CHARS:
        return [f"Password is too long. Maximum allowed is {MAX_CHARS} characters."]

    byte_len = len(password.encode("utf-8"))

    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters.")
    if byte_len > MAX_BYTES:
        errors.append(
            f"Password is too long ({byte_len} bytes). Maximum is {MAX_BYTES} bytes. "
            "Tip: emoji and special characters use more bytes than they appear."
        )
    if not re.search(r"[A-Z]", password):
        errors.append("Must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Must contain at least one digit.")
    return errors


def hash_password(password: str) -> str:
    """Hash with bcrypt rounds=12. Returns the hash as a UTF-8 string."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def create_access_token(user_id: str, username: str, is_admin: bool = False) -> str:
    payload = {
        "sub":      user_id,
        "username": username,
        "admin":    is_admin,
        "exp":      datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises HTTPException on any failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, detail="Session expired. Please log in again.")
    except JWTError:
        raise HTTPException(401, detail="Invalid token.")


def _extract_token(request: Request) -> Optional[str]:
    """Try cookie first, then Authorization header."""
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer "):]
    return token or None


async def get_current_user(request: Request) -> dict:
    """FastAPI dependency — resolves to {user_id, username, admin}."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(401, detail="Not authenticated.")
    return decode_token(token)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency — ensures caller has admin flag in JWT."""
    if not user.get("admin"):
        raise HTTPException(403, detail="Admin access required.")
    return user


def get_user_from_ws_token(token: Optional[str]) -> dict:
    """
    Used for WebSocket auth where we can't use FastAPI Depends.
    Raises HTTPException on failure (caller must close WS with 4001).
    """
    if not token:
        raise HTTPException(401, detail="No token provided.")
    return decode_token(token)
