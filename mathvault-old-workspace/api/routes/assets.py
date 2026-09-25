"""Asset serving — read-only, safe path resolution."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from config import get_settings
from database.models import Asset

router = APIRouter()


@router.get("/{asset_id}")
async def serve_asset(asset_id: str, db: Session = Depends(get_db_session)) -> FileResponse:
    """Serve an archived asset (image, PDF, etc.)."""
    asset = db.execute(
        select(Asset).where(Asset.id == asset_id)
    ).scalar_one_or_none()
    if not asset or not asset.local_path:
        raise HTTPException(404, "Asset not archived")
    settings = get_settings()
    # safe_join — prevent path traversal. local_path was generated as
    # sha256-prefixed path, but defense in depth:
    archive_root = settings.archive_path.resolve()
    candidate = (archive_root / asset.local_path).resolve()
    # Ensure the resolved path is inside archive_root
    try:
        candidate.relative_to(archive_root)
    except ValueError:
        raise HTTPException(403, "Path traversal rejected")
    if not candidate.is_file():
        raise HTTPException(404, "Asset file missing")
    return FileResponse(
        path=str(candidate),
        media_type=asset.content_type or "application/octet-stream",
        filename=candidate.name,
    )
