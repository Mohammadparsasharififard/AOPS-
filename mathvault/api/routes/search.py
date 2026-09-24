"""Search route — FTS5 (SQLite) or pg_trgm (PostgreSQL)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.deps import get_db_session
from config import get_settings


router = APIRouter()


class SearchHit(BaseModel):
    doc_type: str
    ref_id: str
    title: Optional[str]
    snippet: Optional[str]
    contest_name: Optional[str]
    year: Optional[int]
    country: Optional[str]
    tags: Optional[str]
    url: Optional[str]
    rank: float


@router.get("", response_model=list[SearchHit])
async def search(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    doc_type: Optional[str] = Query(None, description="Filter by type: problem | contest | page | discussion | resource"),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> list[SearchHit]:
    settings = get_settings()
    query = q.strip()
    if not query:
        return []

    if settings.db_engine == "sqlite":
        # FTS5 — wrap each word in quotes for safe matching
        words = [w for w in query.split() if w]
        if not words:
            return []
        fts_query = " OR ".join(f'"{w.replace(chr(34), "")}"' for w in words)

        # Build SQL with optional doc_type filter
        type_filter = "AND f.doc_type = :dt" if doc_type else ""
        sql_str = f"""
            SELECT
                f.doc_id AS ref_id,
                f.doc_type,
                s.title,
                s.body,
                s.contest_name,
                s.year,
                s.country,
                s.tags,
                s.url,
                bm25(search_doc_fts) AS rank,
                snippet(search_doc_fts, 4, '<mark>', '</mark>', '…', 12) AS snippet
            FROM search_doc_fts f
            JOIN search_doc s ON s.id = f.doc_id
            WHERE search_doc_fts MATCH :q
            {type_filter}
            ORDER BY rank
            LIMIT :lim OFFSET :off
        """
        params: dict = {"q": fts_query, "lim": limit, "off": offset}
        if doc_type:
            params["dt"] = doc_type
    else:
        # PostgreSQL: simple ILIKE
        type_filter = "AND doc_type = :dt" if doc_type else ""
        sql_str = f"""
            SELECT
                id AS ref_id,
                doc_type,
                title,
                body,
                contest_name,
                year,
                country,
                tags,
                url,
                0.0 AS rank,
                LEFT(body, 200) AS snippet
            FROM search_doc
            WHERE
                title ILIKE '%' || :q || '%' OR
                body  ILIKE '%' || :q || '%' OR
                contest_name ILIKE '%' || :q || '%' OR
                tags ILIKE '%' || :q || '%' OR
                country ILIKE '%' || :q || '%'
            {type_filter}
            ORDER BY title
            LIMIT :lim OFFSET :off
        """
        params = {"q": query, "lim": limit, "off": offset}
        if doc_type:
            params["dt"] = doc_type

    rows = db.execute(text(sql_str), params).mappings().all()
    return [
        SearchHit(
            doc_type=row["doc_type"],
            ref_id=str(row["ref_id"]),
            title=row.get("title"),
            snippet=row.get("snippet") or (row.get("body") or "")[:200],
            contest_name=row.get("contest_name"),
            year=row.get("year"),
            country=row.get("country"),
            tags=row.get("tags"),
            url=row.get("url"),
            rank=float(row.get("rank") or 0.0),
        )
        for row in rows
    ]
