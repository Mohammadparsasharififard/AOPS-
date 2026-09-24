"""Problem routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db_session
from database.models import (
    ArchiveStatus, Contest, ContestYear, CountryRegion, Discussion, Problem, Tag,
)


router = APIRouter()


class ProblemListItem(BaseModel):
    id: str
    number: Optional[str]
    title: Optional[str]
    contest_name: Optional[str]
    contest_slug: Optional[str]
    year: Optional[int]
    archive_status: str


class ProblemDetail(BaseModel):
    id: str
    number: Optional[str]
    title: Optional[str]
    statement_html: Optional[str]
    statement_text: Optional[str]
    contest_name: Optional[str]
    contest_slug: Optional[str]
    year: Optional[int]
    source_url: Optional[str]
    archive_url: Optional[str]
    solution_available: bool
    discussion_available: bool
    archive_status: str
    tags: list[str]
    prev_id: Optional[str]
    next_id: Optional[str]
    position: Optional[int]
    total_in_contest: Optional[int]


@router.get("", response_model=list[ProblemListItem])
async def list_problems(
    q: Optional[str] = Query(None, description="Substring filter on title"),
    tag: Optional[str] = Query(None),
    contest_slug: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> list[ProblemListItem]:
    stmt = (
        select(
            Problem,
            Contest.name.label("contest_name"),
            Contest.slug.label("contest_slug"),
            ContestYear.year.label("year"),
        )
        .select_from(Problem)
        .join(ContestYear, Problem.contest_year_id == ContestYear.id)
        .join(Contest, ContestYear.contest_id == Contest.id)
    )
    if q:
        stmt = stmt.where(Problem.title.ilike(f"%{q}%"))
    if contest_slug:
        stmt = stmt.where(Contest.slug == contest_slug)
    if year:
        stmt = stmt.where(ContestYear.year == year)
    if tag:
        stmt = stmt.join(Problem.tags).where(Tag.slug == tag)
    stmt = stmt.order_by(Contest.name, ContestYear.year.desc(), Problem.number).limit(limit).offset(offset)
    results = db.execute(stmt).all()
    return [
        ProblemListItem(
            id=p.id, number=p.number, title=p.title,
            contest_name=contest_name, contest_slug=contest_slug, year=year,
            archive_status=p.archive_status,
        )
        for p, contest_name, contest_slug, year in results
    ]


@router.get("/{problem_id}", response_model=ProblemDetail)
async def get_problem(problem_id: str, db: Session = Depends(get_db_session)) -> ProblemDetail:
    problem = db.execute(
        select(Problem)
        .options(selectinload(Problem.tags), selectinload(Problem.contest_year))
        .where(Problem.id == problem_id)
    ).scalar_one_or_none()
    if not problem:
        raise HTTPException(404, "Problem not found")
    cy = problem.contest_year
    contest = db.get(Contest, cy.contest_id) if cy else None

    # Determine prev/next within same contest_year
    sibling_numbers = db.execute(
        select(Problem.id, Problem.number)
        .where(Problem.contest_year_id == cy.id)
        .order_by(Problem.number)
    ).all()
    sorted_ids = [row[0] for row in sibling_numbers]
    total = len(sorted_ids)
    try:
        idx = sorted_ids.index(problem.id)
        prev_id = sorted_ids[idx - 1] if idx > 0 else None
        next_id = sorted_ids[idx + 1] if idx < total - 1 else None
        position = idx + 1
    except ValueError:
        prev_id = next_id = None
        position = total

    return ProblemDetail(
        id=problem.id,
        number=problem.number,
        title=problem.title,
        statement_html=problem.statement_html,
        statement_text=problem.statement_text,
        contest_name=contest.name if contest else None,
        contest_slug=contest.slug if contest else None,
        year=cy.year if cy else None,
        source_url=problem.source_url,
        archive_url=problem.archive_url,
        solution_available=problem.solution_available,
        discussion_available=problem.discussion_available,
        archive_status=problem.archive_status,
        tags=[t.name for t in problem.tags],
        prev_id=prev_id,
        next_id=next_id,
        position=position,
        total_in_contest=total,
    )


@router.get("/{problem_id}/discussion")
async def get_problem_discussion(problem_id: str, db: Session = Depends(get_db_session)) -> dict:
    """Return discussion threads + posts for a problem."""
    problem = db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    threads = db.execute(
        select(Discussion).where(Discussion.problem_id == problem_id)
    ).scalars().all()
    return {
        "problem_id": problem_id,
        "threads": [
            {
                "id": t.id,
                "title": t.title,
                "source_url": t.source_url,
                "last_synced": t.last_synced.isoformat() if t.last_synced else None,
                "posts": _render_posts(db, t.id),
            }
            for t in threads
        ],
    }


def _render_posts(db: Session, discussion_id: str) -> list[dict]:
    from database.models import Post
    posts = db.execute(
        select(Post).where(Post.discussion_id == discussion_id, Post.parent_post_id.is_(None))
        .order_by(Post.posted_at)
    ).scalars().all()
    return [_post_tree(db, p) for p in posts]


def _post_tree(db: Session, post) -> dict:
    from database.models import Post
    replies = db.execute(
        select(Post).where(Post.parent_post_id == post.id).order_by(Post.posted_at)
    ).scalars().all()
    return {
        "id": post.id,
        "author": post.author_name,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "content_html": post.content_html,
        "content_text": post.content_text,
        "source_url": post.source_url,
        "replies": [_post_tree(db, r) for r in replies],
    }
