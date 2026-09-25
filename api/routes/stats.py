"""Stats route — overall archive stats (homepage + admin dashboard)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import (
    Asset, BlockedUrl, Contest, CountryRegion, CrawlRun,
    Discussion, Page, Post, Problem,
)


router = APIRouter()


class StatsResponse(BaseModel):
    contests: int
    problems: int
    countries: int
    pages: int
    assets: int
    discussions: int
    posts: int
    blocked_urls: int
    last_sync_at: Optional[datetime]
    next_sync_at: Optional[datetime]
    last_run_status: Optional[str]
    last_run_pages_discovered: int
    last_run_pages_new: int
    last_run_pages_changed: int
    last_run_pages_unchanged: int
    last_run_pages_failed: int
    last_run_pages_blocked: int
    last_run_bytes_downloaded: int
    sync_interval_hours: int


@router.get("/stats", response_model=StatsResponse)
async def stats(db: Session = Depends(get_db_session)) -> StatsResponse:
    from config import get_settings
    settings = get_settings()
    contests = db.scalar(select(func.count(Contest.id))) or 0
    problems = db.scalar(select(func.count(Problem.id))) or 0
    countries = db.scalar(select(func.count(CountryRegion.id))) or 0
    pages = db.scalar(select(func.count(Page.id))) or 0
    assets = db.scalar(select(func.count(Asset.id))) or 0
    discussions = db.scalar(select(func.count(Discussion.id))) or 0
    posts = db.scalar(select(func.count(Post.id))) or 0
    blocked = db.scalar(select(func.count(BlockedUrl.id))) or 0
    last_run = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    last_sync = last_run.started_at if last_run else None
    next_sync = None
    if last_sync and last_run.finished_at and last_run.status == "completed":
        next_sync = last_run.finished_at + timedelta(hours=settings.sync_interval_hours)
    return StatsResponse(
        contests=contests,
        problems=problems,
        countries=countries,
        pages=pages,
        assets=assets,
        discussions=discussions,
        posts=posts,
        blocked_urls=blocked,
        last_sync_at=last_sync,
        next_sync_at=next_sync,
        last_run_status=last_run.status if last_run else None,
        last_run_pages_discovered=last_run.pages_discovered if last_run else 0,
        last_run_pages_new=last_run.pages_new if last_run else 0,
        last_run_pages_changed=last_run.pages_changed if last_run else 0,
        last_run_pages_unchanged=last_run.pages_unchanged if last_run else 0,
        last_run_pages_failed=last_run.pages_failed if last_run else 0,
        last_run_pages_blocked=last_run.pages_blocked if last_run else 0,
        last_run_bytes_downloaded=last_run.bytes_downloaded if last_run else 0,
        sync_interval_hours=settings.sync_interval_hours,
    )
