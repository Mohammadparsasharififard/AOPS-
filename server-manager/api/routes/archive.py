"""Archive routes — link to MathVault offline archive."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import require_session
from config import get_settings


router = APIRouter()


@router.get("/offline-url", dependencies=[Depends(require_session)])
async def offline_url() -> dict:
    """Return the configured MathVault URLs for the frontend to embed/redirect."""
    s = get_settings()
    return {
        "frontend_url": s.mathvault_frontend_url,
        "api_url": s.mathvault_api_url,
    }
