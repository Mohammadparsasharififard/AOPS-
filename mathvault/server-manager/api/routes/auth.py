"""Auth routes — master password setup + login."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from auth import SESSION_COOKIE_NAME, create_session_token, require_session, verify_session_token
from config import get_settings
from crypto import generate_keypair, hash_master_password, save_keypair, verify_master_password
from database.models import Server
from database.session import get_db, init_db, session_scope

router = APIRouter()


class SetupRequest(BaseModel):
    master_password: str

    @field_validator("master_password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Master password must be at least 12 characters")
        return v


class LoginRequest(BaseModel):
    master_password: str


class StatusResponse(BaseModel):
    setup_required: bool
    authenticated: bool
    server_count: int


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    settings = get_settings()
    setup_required = not settings.master_password_hash
    # Count servers (no auth needed for setup-status)
    try:
        with session_scope() as db:
            server_count = len(db.query(Server).all())
    except Exception:
        server_count = 0
    return StatusResponse(
        setup_required=setup_required,
        authenticated=False,  # We don't check session here — frontend can
        server_count=server_count,
    )


@router.post("/setup")
async def setup(req: SetupRequest, response: Response) -> dict:
    """First-time setup — set master password + generate keypair."""
    settings = get_settings()
    if settings.master_password_hash:
        raise HTTPException(400, "Master password already set. Use the .env to reset.")
    # Generate keypair
    private_key_bytes, public_key_bytes = generate_keypair(req.master_password)
    save_keypair(private_key_bytes, public_key_bytes, req.master_password)

    # Save hash to .env (append)
    h = hash_master_password(req.master_password)
    env_path = ".env"
    if env_path.exists():
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nMASTER_PASSWORD_HASH={h}\n")
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"MASTER_PASSWORD_HASH={h}\n")
    # Reinitialize settings (the lru_cache needs to be cleared)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    # Re-initialize DB
    init_db()

    # Set session cookie
    token = create_session_token()
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=token, httponly=True,
        samesite="strict", max_age=4 * 3600, secure=False,  # set secure=True if HTTPS
    )
    return {"status": "ok", "message": "Master password set, keypair generated."}


@router.post("/login")
async def login(req: LoginRequest, response: Response) -> dict:
    settings = get_settings()
    if not settings.master_password_hash:
        raise HTTPException(400, "Master password not set. POST /api/auth/setup first.")
    if not verify_master_password(req.master_password, settings.master_password_hash):
        raise HTTPException(401, "Invalid master password")
    # Test that the master password can actually decrypt the private key
    from crypto import load_private_key
    if load_private_key(req.master_password) is None:
        raise HTTPException(500, "Master password verified but keypair decryption failed")
    token = create_session_token()
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=token, httponly=True,
        samesite="strict", max_age=4 * 3600, secure=False,
    )
    return {"status": "ok"}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "ok"}


# Store master password in process memory only when authenticated
# This is a hack — we use a module-level dict keyed by session token
# A cleaner approach uses a TTL cache; this is sufficient for personal use
_MASTER_PASSWORD_CACHE: dict[str, str] = {}


def cache_master_password(token: str, password: str) -> None:
    _MASTER_PASSWORD_CACHE[token] = password


def get_cached_master_password(token: str) -> Optional[str]:
    return _MASTER_PASSWORD_CACHE.get(token)


def clear_master_password_cache(token: str) -> None:
    _MASTER_PASSWORD_CACHE.pop(token, None)
