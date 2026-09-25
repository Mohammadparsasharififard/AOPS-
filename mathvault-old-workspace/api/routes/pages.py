"""Page routes — view raw archived pages + version history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import Page, PageVersion

router = APIRouter()


class PageVersionItem(BaseModel):
    version_no: int
    sha256: str
    fetched_at: str
    is_current: bool
    is_complete: bool
    byte_size: int | None


@router.get("/{page_id}", response_class=HTMLResponse)
async def get_page(page_id: str, db: Session = Depends(get_db_session)) -> HTMLResponse:
    """Return the current HTML snapshot of a page."""
    page = db.get(Page, page_id)
    if not page:
        raise HTTPException(404, "Page not found")
    version = db.execute(
        select(PageVersion)
        .where(PageVersion.page_id == page_id, PageVersion.is_current == True)  # noqa: E712
        .order_by(PageVersion.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not version or not version.content_html:
        return HTMLResponse(
            content="<h1>Offline</h1><p>This content is not available offline.</p>",
            status_code=200,
        )
    return HTMLResponse(content=version.content_html)


@router.get("/{page_id}/versions", response_model=list[PageVersionItem])
async def list_page_versions(page_id: str, db: Session = Depends(get_db_session)) -> list[PageVersionItem]:
    page = db.get(Page, page_id)
    if not page:
        raise HTTPException(404, "Page not found")
    versions = db.execute(
        select(PageVersion)
        .where(PageVersion.page_id == page_id)
        .order_by(PageVersion.version_no.desc())
    ).scalars().all()
    return [
        PageVersionItem(
            version_no=v.version_no,
            sha256=v.sha256,
            fetched_at=v.fetched_at.isoformat() if v.fetched_at else "",
            is_current=v.is_current,
            is_complete=v.is_complete,
            byte_size=v.byte_size,
        )
        for v in versions
    ]


@router.get("/{page_id}/versions/{version_no}", response_class=HTMLResponse)
async def get_page_version(page_id: str, version_no: int, db: Session = Depends(get_db_session)) -> HTMLResponse:
    v = db.execute(
        select(PageVersion).where(
            PageVersion.page_id == page_id, PageVersion.version_no == version_no
        )
    ).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "Version not found")
    return HTMLResponse(content=v.content_html or "")
