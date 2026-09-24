"""Stats route — overall archive stats (homepage + admin dashboard)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import (
    Asset, Contest, ContestYear, CountryRegion, CrawlRun, Discussion, Page, Post, Problem,
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
    last_sync_at: Optional[datetime]
    next_sync_at: Optional[datetime]
    sync_interval_hours: int


@router.get("/stats", response_model=StatsResponse)
async def stats(db: Session = Depends(get_db_session)) -> StatsResponse:
    from config import get_settings
    settings = get_settings()
    contests = db.scalar(select(func.count(Contest.id)))
    problems = db.scalar(select(func.count(Problem.id)))
    countries = db.scalar(select(func.count(CountryRegion.id)))
    pages = db.scalar(select(func.count(Page.id)))
    assets = db.scalar(select(func.count(Asset.id)))
    discussions = db.scalar(select(func.count(Discussion.id)))
    posts = db.scalar(select(func.count(Post.id)))
    last_run = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    last_sync = last_run.started_at if last_run else None
    next_sync = None
    if last_sync:
        from datetime import timedelta
        next_sync = last_sync + timedelta(hours=settings.sync_interval_hours)
    return StatsResponse(
        contests=contests or 0,
        problems=problems or 0,
        countries=countries or 0,
        pages=pages or 0,
        assets=assets or 0,
        discussions=discussions or 0,
        posts=posts or 0,
        last_sync_at=last_sync,
        next_sync_at=next_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )
