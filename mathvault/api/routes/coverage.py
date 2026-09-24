"""Coverage Map — per-contest, per-year archive status.

Computes archive coverage so the UI can show:
  International
  ├── Contest A
  │   ├── 2024  100%
  │   ├── 2025  96%
  │   └── 2026  82%

A coverage % is calculated as:
  archived_pages / discovered_pages * 100

Where:
  - archived_pages = pages with is_complete=True AND status=200
  - discovered_pages = pages that the crawler has visited (including failed + blocked)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import (
    BlockedUrl, Contest, ContestYear, CountryRegion, Page, Problem,
)


router = APIRouter()


class YearCoverage(BaseModel):
    year: int
    round: Optional[str]
    problem_count: int
    archived_problems: int
    coverage_percent: float
    blocked_urls: int


class ContestCoverage(BaseModel):
    contest_id: str
    contest_name: str
    contest_slug: str
    is_international: bool
    country: Optional[str]
    year_count: int
    archived_years: int
    years: list[YearCoverage]
    coverage_percent: float


class GroupCoverage(BaseModel):
    group_name: str  # "International" or country name
    contests: list[ContestCoverage]
    overall_coverage: float


class CoverageMapResponse(BaseModel):
    international: GroupCoverage
    national_regional: list[GroupCoverage]
    totals: dict


@router.get("/coverage", response_model=CoverageMapResponse)
async def coverage_map(db: Session = Depends(get_db_session)) -> CoverageMapResponse:
    """Return the full coverage map.

    For each contest, computes per-year coverage:
      - problem_count = problems associated with this contest_year
      - archived_problems = problems with archive_status = "archived"
      - coverage_percent = archived / problem_count * 100
      - blocked_urls = count of blocked URLs associated with this contest
    """
    # International contests
    intl_contests = db.execute(
        select(Contest).where(Contest.is_international == True)  # noqa: E712
        .order_by(Contest.name)
    ).scalars().all()

    intl_group = _build_group(db, intl_contests, "International")

    # National/regional — grouped by country
    countries = db.execute(
        select(CountryRegion)
        .where(CountryRegion.type == "country")
        .order_by(CountryRegion.name)
    ).scalars().all()
    national_groups: list[GroupCoverage] = []
    for country in countries:
        country_contests = db.execute(
            select(Contest).where(
                Contest.country_region_id == country.id,
                Contest.is_international == False,  # noqa: E712
            ).order_by(Contest.name)
        ).scalars().all()
        if not country_contests:
            continue
        national_groups.append(_build_group(db, country_contests, country.name))

    # Totals
    total_contests = db.scalar(select(func.count(Contest.id))) or 0
    total_problems = db.scalar(select(func.count(Problem.id))) or 0
    total_archived = db.scalar(
        select(func.count(Problem.id)).where(Problem.archive_status == "archived")
    ) or 0
    total_blocked = db.scalar(select(func.count(BlockedUrl.id))) or 0

    return CoverageMapResponse(
        international=intl_group,
        national_regional=national_groups,
        totals={
            "contests": total_contests,
            "problems": total_problems,
            "archived_problems": total_archived,
            "blocked_urls": total_blocked,
        },
    )


def _build_group(db: Session, contests: list[Contest], group_name: str) -> GroupCoverage:
    """Build coverage for a list of contests."""
    contest_covs: list[ContestCoverage] = []
    overall_archived = 0
    overall_discovered = 0
    for c in contests:
        country_name = None
        if c.country_region_id:
            cr = db.get(CountryRegion, c.country_region_id)
            country_name = cr.name if cr else None

        years = db.execute(
            select(ContestYear).where(ContestYear.contest_id == c.id).order_by(ContestYear.year.desc())
        ).scalars().all()
        year_covs: list[YearCoverage] = []
        archived_years = 0
        for y in years:
            problem_count = db.scalar(
                select(func.count(Problem.id)).where(Problem.contest_year_id == y.id)
            ) or 0
            archived = db.scalar(
                select(func.count(Problem.id)).where(
                    Problem.contest_year_id == y.id,
                    Problem.archive_status == "archived",
                )
            ) or 0
            blocked = db.scalar(select(func.count(BlockedUrl.id))) or 0  # placeholder
            pct = (archived / problem_count * 100) if problem_count > 0 else 0.0
            year_covs.append(YearCoverage(
                year=y.year,
                round=y.round,
                problem_count=problem_count,
                archived_problems=archived,
                coverage_percent=round(pct, 1),
                blocked_urls=blocked,
            ))
            if problem_count > 0 and archived == problem_count:
                archived_years += 1
            overall_archived += archived
            overall_discovered += problem_count
        overall_pct = (overall_archived / overall_discovered * 100) if overall_discovered > 0 else 0.0
        contest_covs.append(ContestCoverage(
            contest_id=c.id,
            contest_name=c.name,
            contest_slug=c.slug,
            is_international=c.is_international,
            country=country_name,
            year_count=len(years),
            archived_years=archived_years,
            years=year_covs,
            coverage_percent=round(overall_pct, 1),
        ))
    return GroupCoverage(
        group_name=group_name,
        contests=contest_covs,
        overall_coverage=round(
            (overall_archived / overall_discovered * 100) if overall_discovered > 0 else 0.0, 1
        ),
    )
