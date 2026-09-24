"""Audit log routes — view history of sensitive actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_session
from database.models import AuditLog
from database.session import get_db


router = APIRouter()


@router.get("", dependencies=[Depends(require_session)])
async def list_audit(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    logs = db.execute(
        select(AuditLog).order_by(AuditLog.started_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": l.id,
            "action": l.action,
            "server_id": l.server_id,
            "deployment_id": l.deployment_id,
            "command": l.command,
            "exit_code": l.exit_code,
            "started_at": l.started_at.isoformat() if l.started_at else None,
            "finished_at": l.finished_at.isoformat() if l.finished_at else None,
            "success": l.success,
            "error": l.error,
        }
        for l in logs
    ]
