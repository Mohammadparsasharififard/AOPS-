"""Tag listing routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from database.models import Tag


router = APIRouter()


class TagItem(BaseModel):
    id: str
    name: str
    slug: str


@router.get("", response_model=list[TagItem])
async def list_tags(db: Session = Depends(get_db_session)) -> list[TagItem]:
    tags = db.execute(select(Tag).order_by(Tag.name)).scalars().all()
    return [TagItem(id=t.id, name=t.name, slug=t.slug) for t in tags]
