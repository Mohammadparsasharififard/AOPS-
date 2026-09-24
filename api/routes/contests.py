"""Contest routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db_session
from database.models import Contest, ContestYear, CountryRegion, Problem, ProblemSet

router = APIRouter()


class ContestListItem(BaseModel):
    id: str
    name: str
    slug: str
    category: Optional[str]
    is_international: bool
    country: Optional[str]
    year_count: int
    last_synced: Optional[str]


class ContestYearItem(BaseModel):
    id: str
    year: int
    round: Optional[str]
    date: Optional[str]
    duration: Optional[str]
    problem_count: Optional[int]
    problem_set_count: int


class ContestDetail(BaseModel):
    id: str
    name: str
    slug: str
    category: Optional[str]
    is_international: bool
    country: Optional[str]
    source_url: Optional[str]
    archive_url: Optional[str]
    last_synced: Optional[str]
    years: list[ContestYearItem]


class ContestYearDetail(BaseModel):
    id: str
    contest_name: str
    contest_slug: str
    year: int
    round: Optional[str]
    date: Optional[str]
    duration: Optional[str]
    problem_count: Optional[int]
    problems: list[dict]
    problem_sets: list[dict]


@router.get("", response_model=list[ContestListItem])
async def list_contests(
    international: Optional[bool] = Query(None),
    country_slug: Optional[str] = Query(None),
    db: Session = Depends(get_db_session),
) -> list[ContestListItem]:
    stmt = (
        select(
            Contest,
            CountryRegion.name.label("country_name"),
            func_count_years(),
        )
        .select_from(Contest)
        .outerjoin(CountryRegion, Contest.country_region_id == CountryRegion.id)
        .order_by(Contest.name)
    )
    if international is not None:
        stmt = stmt.where(Contest.is_international == international)
    if country_slug:
        stmt = stmt.where(CountryRegion.slug == country_slug)

    results = db.execute(stmt).all()
    return [
        ContestListItem(
            id=c.id, name=c.name, slug=c.slug, category=c.category,
            is_international=c.is_international,
            country=country_name,
            year_count=yc,
            last_synced=c.last_synced.isoformat() if c.last_synced else None,
        )
        for c, country_name, yc in results
    ]


# Use a subquery for year count
from sqlalchemy import func

def func_count_years():
    return (
        select(func.count(ContestYear.id))
        .where(ContestYear.contest_id == Contest.id)
        .correlate(Contest)
        .scalar_subquery()
        .label("year_count")
    )


@router.get("/{slug}", response_model=ContestDetail)
async def get_contest(slug: str, db: Session = Depends(get_db_session)) -> ContestDetail:
    contest = db.execute(
        select(Contest).options(selectinload(Contest.years)).where(Contest.slug == slug)
    ).scalar_one_or_none()
    if not contest:
        raise HTTPException(404, "Contest not found")
    country = None
    if contest.country_region_id:
        country_region = db.get(CountryRegion, contest.country_region_id)
        country = country_region.name if country_region else None
    return ContestDetail(
        id=contest.id,
        name=contest.name,
        slug=contest.slug,
        category=contest.category,
        is_international=contest.is_international,
        country=country,
        source_url=contest.source_url,
        archive_url=contest.archive_url,
        last_synced=contest.last_synced.isoformat() if contest.last_synced else None,
        years=[
            ContestYearItem(
                id=y.id, year=y.year, round=y.round, date=y.date,
                duration=y.duration, problem_count=y.problem_count,
                problem_set_count=db.scalar(
                    select(func.count(ProblemSet.id)).where(ProblemSet.contest_year_id == y.id)
                ) or 0,
            )
            for y in sorted(contest.years, key=lambda y: y.year, reverse=True)
        ],
    )


@router.get("/{slug}/{year}", response_model=ContestYearDetail)
async def get_contest_year(slug: str, year: int, db: Session = Depends(get_db_session)) -> ContestYearDetail:
    contest = db.execute(select(Contest).where(Contest.slug == slug)).scalar_one_or_none()
    if not contest:
        raise HTTPException(404, "Contest not found")
    cy = db.execute(
        select(ContestYear)
        .options(selectinload(ContestYear.problems), selectinload(ContestYear.problem_sets))
        .where(ContestYear.contest_id == contest.id, ContestYear.year == year)
    ).scalar_one_or_none()
    if not cy:
        raise HTTPException(404, "Year not found for this contest")
    return ContestYearDetail(
        id=cy.id,
        contest_name=contest.name,
        contest_slug=contest.slug,
        year=cy.year,
        round=cy.round,
        date=cy.date,
        duration=cy.duration,
        problem_count=cy.problem_count,
        problems=[
            {
                "id": p.id,
                "number": p.number,
                "title": p.title,
                "archive_status": p.archive_status,
                "url": p.archive_url or p.source_url,
            }
            for p in sorted(cy.problems, key=lambda p: int(p.number) if p.number and p.number.isdigit() else 0)
        ],
        problem_sets=[
            {
                "id": ps.id,
                "type": ps.type,
                "name": ps.name,
                "url": ps.source_url,
                "archive_path": ps.archive_path,
            }
            for ps in cy.problem_sets
        ],
    )
