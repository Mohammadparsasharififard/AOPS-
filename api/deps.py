"""FastAPI dependencies."""
from __future__ import annotations

import base64
import secrets
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import get_settings
from database.session import get_db


def get_db_session() -> Session:
    """Yield a fresh DB session. Used as `Depends(get_db_session)`."""
    gen = get_db()
    try:
        yield next(gen)
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def verify_admin_basic(request: Request) -> Optional[str]:
    """HTTP Basic Auth for admin endpoints.

    Returns the authenticated admin username on success.

    Falls back to a permissive mode only in dev when ADMIN_PASSWORD_HASH is
    empty (so the dev can experiment). In production this raises 401.
    """
    settings = get_settings()
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        if not settings.admin_password_hash:
            return "dev-admin"  # permissive dev mode
        raise HTTPException(status_code=401, detail="Basic auth required", headers={"WWW-Authenticate": "Basic"})

    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid auth header", headers={"WWW-Authenticate": "Basic"})

    if not secrets.compare_digest(username, settings.admin_username):
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})

    if not settings.admin_password_hash:
        return username  # permissive dev mode

    try:
        if not bcrypt.checkpw(password.encode("utf-8"), settings.admin_password_hash.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})

    return username


def require_admin(admin: str = Depends(verify_admin_basic)) -> str:
    """Convenience alias."""
    return admin


def hash_password(plain: str) -> str:
    """Helper for CLI to generate ADMIN_PASSWORD_HASH."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
