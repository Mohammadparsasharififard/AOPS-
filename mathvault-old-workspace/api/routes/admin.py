"""Admin routes — sync status + manual trigger."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db_session, require_admin
from config import get_settings
from crawler.scheduler import CrawlScheduler
from database.models import CrawlError, CrawlRun


router = APIRouter()


class SyncStatus(BaseModel):
    last_sync_started_at: Optional[datetime]
    last_sync_finished_at: Optional[datetime]
    last_status: Optional[str]
    next_sync_at: Optional[datetime]
    sync_interval_hours: int
    pages_discovered: int
    pages_new: int
    pages_changed: int
    pages_unchanged: int
    pages_failed: int
    bytes_downloaded: int
    trigger: Optional[str]
    error_message: Optional[str]
    errors: list[dict]


class TriggerResponse(BaseModel):
    triggered: bool
    crawl_run_id: Optional[str]


# Simple in-process lock to avoid concurrent runs on a small server
_RUNNING_LOCK = False


@router.get("/sync-status", response_model=SyncStatus)
async def sync_status(
    db: Session = Depends(get_db_session),
    _: str = Depends(require_admin),
) -> SyncStatus:
    global _RUNNING_LOCK
    settings = get_settings()
    last = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    next_sync = None
    if last and last.finished_at and last.status == "completed":
        next_sync = last.finished_at + timedelta(hours=settings.sync_interval_hours)
    elif _RUNNING_LOCK:
        next_sync = datetime.now(timezone.utc)  # currently running
    errors: list[dict] = []
    if last:
        errs = db.execute(
            select(CrawlError).where(CrawlError.crawl_run_id == last.id).order_by(CrawlError.occurred_at.desc()).limit(20)
        ).scalars().all()
        errors = [
            {
                "url": e.url,
                "type": e.error_type,
                "message": e.message,
                "http_status": e.http_status,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in errs
        ]
    return SyncStatus(
        last_sync_started_at=last.started_at if last else None,
        last_sync_finished_at=last.finished_at if last else None,
        last_status=last.status if last else None,
        next_sync_at=next_sync,
        sync_interval_hours=settings.sync_interval_hours,
        pages_discovered=last.pages_discovered if last else 0,
        pages_new=last.pages_new if last else 0,
        pages_changed=last.pages_changed if last else 0,
        pages_unchanged=last.pages_unchanged if last else 0,
        pages_failed=last.pages_failed if last else 0,
        bytes_downloaded=last.bytes_downloaded if last else 0,
        trigger=last.trigger if last else None,
        error_message=last.error_message if last else None,
        errors=errors,
    )


@router.post("/run-sync", response_model=TriggerResponse)
async def run_sync(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
    _: str = Depends(require_admin),
) -> TriggerResponse:
    global _RUNNING_LOCK
    if _RUNNING_LOCK:
        raise HTTPException(409, "A sync is already running")
    _RUNNING_LOCK = True
    # Schedule in background; return immediately
    def _run():
        global _RUNNING_LOCK
        try:
            from database.session import session_scope
            with session_scope() as inner_db:
                scheduler = CrawlScheduler(db=inner_db, trigger="manual")
                scheduler.run()
        except Exception as e:
            from fastapi import HTTPException as _Exc
            # Swallow — background tasks can't raise to client
            import logging
            logging.getLogger(__name__).exception("Background sync failed: %s", e)
        finally:
            _RUNNING_LOCK = False

    background_tasks.add_task(_run)
    return TriggerResponse(triggered=True, crawl_run_id=None)


@router.get("/crawl-runs")
async def list_crawl_runs(
    limit: int = 20,
    db: Session = Depends(get_db_session),
    _: str = Depends(require_admin),
) -> list[dict]:
    runs = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "trigger": r.trigger,
            "dry_run": r.dry_run,
            "pages_discovered": r.pages_discovered,
            "pages_new": r.pages_new,
            "pages_changed": r.pages_changed,
            "pages_unchanged": r.pages_unchanged,
            "pages_failed": r.pages_failed,
            "bytes_downloaded": r.bytes_downloaded,
            "error_message": r.error_message,
        }
        for r in runs
    ]
