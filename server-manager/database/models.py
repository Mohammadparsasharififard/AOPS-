"""Database models — encrypted SSH credential storage + server registry."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index, JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Server(Base):
    """A registered remote server.

    The encrypted_password / encrypted_key fields hold ciphertext encrypted
    with the master password (sealed box via PyNaCl). They are decryptable
    ONLY while the master password is loaded in memory.
    """
    __tablename__ = "server"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(100), default="root")
    encrypted_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_private_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_method: Mapped[str] = mapped_column(String(20), default="password")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    deployments: Mapped[list["Deployment"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_server_name"),
        Index("ix_server_host", "host"),
    )


class Deployment(Base):
    __tablename__ = "deployment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    server_id: Mapped[str] = mapped_column(ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    deploy_path: Mapped[str] = mapped_column(Text, nullable=False)
    git_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    git_branch: Mapped[str] = mapped_column(String(100), default="main")
    service_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deploy_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_deploy_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_deploy_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    server: Mapped["Server"] = relationship(back_populates="deployments")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    server_id: Mapped[Optional[str]] = mapped_column(ForeignKey("server.id"), nullable=True)
    deployment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("deployment.id"), nullable=True)
    command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_audit_started", "started_at"),)
