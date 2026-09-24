"""Master-password session management.

The master password is held in process memory only. The session is a signed
cookie (itsdangerous) that proves the user entered the master password.

This is intentionally simple — not a multi-user auth system. The master
password unlocks ALL stored SSH credentials.

The session expires after 4 hours of inactivity.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import get_settings


SESSION_COOKIE_NAME = "sm_session"
SESSION_TTL_SECONDS = 4 * 3600  # 4 hours


_serializer: URLSafeTimedSerializer | None = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        s = get_settings()
        secret = s.master_password_hash or "dev-only-insecure"
        _serializer = URLSafeTimedSerializer(secret, salt="server-manager-session")
    return _serializer


def create_session_token() -> str:
    """Create a session token — assumes master password was just verified."""
    return _get_serializer().dumps({"ts": int(time.time())})


def verify_session_token(token: str) -> bool:
    try:
        _get_serializer().loads(token, max_age=SESSION_TTL_SECONDS)
        return True
    except (BadSignature, SignatureExpired):
        return False


async def require_session(request: Request) -> None:
    """FastAPI dependency — 401 if no valid session."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not verify_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Master password required",
        )
