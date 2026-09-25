"""Crawl stats + retry API endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import (
    Asset, BlockedUrl, CrawlError, CrawlRun, Page, PageVersion,
)


router = APIRouter()


class CrawlStatsResponse(BaseModel):
    total_pages: int
    total_assets: int
    total_blocked: int
    total_failed: int
    total_search_docs: int
    archive_size_bytes: int
    last_crawl_status: Optional[str]
    last_crawl_started_at: Optional[str]
    last_crawl_finished_at: Optional[str]
    last_crawl_pages_discovered: int
    last_crawl_pages_new: int
    last_crawl_pages_changed: int
    last_crawl_pages_unchanged: int
    last_crawl_pages_failed: int
    last_crawl_pages_blocked: int
    last_crawl_bytes_downloaded: int
    blocked_by_reason: dict[str, int]


@router.get("/crawl-stats", response_model=CrawlStatsResponse)
async def crawl_stats(db: Session = Depends(get_db_session)) -> CrawlStatsResponse:
    """Return comprehensive crawl statistics for dashboard display."""
    total_pages = db.scalar(select(func.count(Page.id))) or 0
    total_assets = db.scalar(select(func.count(Asset.id))) or 0
    total_blocked = db.scalar(select(func.count(BlockedUrl.id))) or 0
    total_search_docs = db.scalar(select(func.count(PageVersion.id))) or 0

    # Compute archive size on disk
    import os
    from config import get_settings
    settings = get_settings()
    archive_size = 0
    archive_root = settings.archive_path
    if archive_root.exists():
        for root, dirs, files in os.walk(archive_root):
            for f in files:
                try:
                    archive_size += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass

    # Last crawl run
    last_run = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()

    # Blocked URLs by reason
    blocked_rows = db.execute(
        select(BlockedUrl.reason, func.count(BlockedUrl.id))
        .group_by(BlockedUrl.reason)
    ).all()
    blocked_by_reason = {r: c for r, c in blocked_rows}

    # Failed URLs (from CrawlError table)
    total_failed = db.scalar(select(func.count(CrawlError.id))) or 0

    return CrawlStatsResponse(
        total_pages=total_pages,
        total_assets=total_assets,
        total_blocked=total_blocked,
        total_failed=total_failed,
        total_search_docs=total_search_docs,
        archive_size_bytes=archive_size,
        last_crawl_status=last_run.status if last_run else None,
        last_crawl_started_at=last_run.started_at.isoformat() if last_run and last_run.started_at else None,
        last_crawl_finished_at=last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
        last_crawl_pages_discovered=last_run.pages_discovered if last_run else 0,
        last_crawl_pages_new=last_run.pages_new if last_run else 0,
        last_crawl_pages_changed=last_run.pages_changed if last_run else 0,
        last_crawl_pages_unchanged=last_run.pages_unchanged if last_run else 0,
        last_crawl_pages_failed=last_run.pages_failed if last_run else 0,
        last_crawl_pages_blocked=last_run.pages_blocked if last_run else 0,
        last_crawl_bytes_downloaded=last_run.bytes_downloaded if last_run else 0,
        blocked_by_reason=blocked_by_reason,
    )


class BlockedUrlItem(BaseModel):
    id: str
    url: str
    reason: str
    detail: Optional[str]
    http_status: Optional[int]
    first_detected: Optional[str]
    last_attempted: Optional[str]
    retry_count: int


@router.get("/blocked-urls", response_model=list[BlockedUrlItem])
async def list_blocked_urls(
    reason: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db_session),
) -> list[BlockedUrlItem]:
    """List blocked URLs with full details for retry analysis."""
    stmt = select(BlockedUrl).order_by(BlockedUrl.last_attempted.desc().nulls_last())
    if reason:
        stmt = stmt.where(BlockedUrl.reason == reason)
    stmt = stmt.limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        BlockedUrlItem(
            id=b.id, url=b.url, reason=b.reason, detail=b.detail,
            http_status=b.http_status,
            first_detected=b.first_detected.isoformat() if b.first_detected else None,
            last_attempted=b.last_attempted.isoformat() if b.last_attempted else None,
            retry_count=b.retry_count,
        )
        for b in rows
    ]
