"""Blocked URLs route — shows what the crawler refused to bypass."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import BlockedUrl


router = APIRouter()


class BlockedUrlItem(BaseModel):
    id: str
    url: str
    canonical_url: str
    reason: str
    detail: Optional[str]
    http_status: Optional[int]
    first_detected: str
    last_attempted: Optional[str]
    retry_count: int


class BlockedStatsResponse(BaseModel):
    total: int
    by_reason: dict[str, int]


@router.get("", response_model=list[BlockedUrlItem])
async def list_blocked(
    reason: Optional[str] = Query(None, description="Filter by reason (captcha, login_required, paywall, robots_disallow, access_denied, rate_limited)"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> list[BlockedUrlItem]:
    """List URLs that were blocked during crawl (never bypassed)."""
    stmt = select(BlockedUrl).order_by(BlockedUrl.last_attempted.desc().nulls_last())
    if reason:
        stmt = stmt.where(BlockedUrl.reason == reason)
    stmt = stmt.limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return [
        BlockedUrlItem(
            id=b.id,
            url=b.url,
            canonical_url=b.canonical_url,
            reason=b.reason,
            detail=b.detail,
            http_status=b.http_status,
            first_detected=b.first_detected.isoformat() if b.first_detected else "",
            last_attempted=b.last_attempted.isoformat() if b.last_attempted else None,
            retry_count=b.retry_count,
        )
        for b in rows
    ]


@router.get("/stats", response_model=BlockedStatsResponse)
async def blocked_stats(db: Session = Depends(get_db_session)) -> BlockedStatsResponse:
    """Aggregate blocked URL counts by reason."""
    total = db.scalar(select(func.count(BlockedUrl.id))) or 0
    rows = db.execute(
        select(BlockedUrl.reason, func.count(BlockedUrl.id))
        .group_by(BlockedUrl.reason)
    ).all()
    return BlockedStatsResponse(
        total=total,
        by_reason={r: c for r, c in rows},
    )
