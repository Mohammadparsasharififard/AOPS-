"""Country/Region routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import Contest, CountryRegion

router = APIRouter()


class CountryListItem(BaseModel):
    id: str
    name: str
    slug: str
    type: str
    contest_count: int


class CountryDetail(BaseModel):
    id: str
    name: str
    slug: str
    type: str
    contests: list[dict]


@router.get("", response_model=list[CountryListItem])
async def list_countries(db: Session = Depends(get_db_session)) -> list[CountryListItem]:
    stmt = (
        select(
            CountryRegion,
            func.count(Contest.id).label("contest_count"),
        )
        .select_from(CountryRegion)
        .outerjoin(Contest, Contest.country_region_id == CountryRegion.id)
        .group_by(CountryRegion.id)
        .order_by(CountryRegion.name)
    )
    results = db.execute(stmt).all()
    return [
        CountryListItem(
            id=c.id, name=c.name, slug=c.slug, type=c.type,
            contest_count=cc or 0,
        )
        for c, cc in results
    ]


@router.get("/{slug}", response_model=CountryDetail)
async def get_country(slug: str, db: Session = Depends(get_db_session)) -> CountryDetail:
    country = db.execute(
        select(CountryRegion).where(CountryRegion.slug == slug)
    ).scalar_one_or_none()
    if not country:
        raise HTTPException(404, "Country/Region not found")
    contests = db.execute(
        select(Contest)
        .where(Contest.country_region_id == country.id)
        .order_by(Contest.name)
    ).scalars().all()
    return CountryDetail(
        id=country.id, name=country.name, slug=country.slug, type=country.type,
        contests=[
            {
                "id": c.id, "name": c.name, "slug": c.slug, "category": c.category,
                "is_international": c.is_international,
                "last_synced": c.last_synced.isoformat() if c.last_synced else None,
            }
            for c in contests
        ],
    )
