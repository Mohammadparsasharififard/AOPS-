"""Database engine + session factory.

SQLite is used in development; PostgreSQL in production. The engine is chosen
based on DATABASE_URL scheme.
"""
from __future__ import annotations

import contextlib
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings


def _engine_from_url(database_url: str, echo: bool = False) -> Engine:
    """Create an SQLAlchemy engine configured for the URL scheme."""
    if database_url.startswith("sqlite"):
        # Enable foreign keys + WAL mode for better concurrent reads.
        engine = create_engine(
            database_url,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine

    # PostgreSQL (and others)
    return create_engine(
        database_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
        pool_recycle=1800,
    )


@contextlib.contextmanager
def _engine_cm() -> Iterator[Engine]:
    global _engine
    if _engine is None:
        _engine = _engine_from_url(get_settings().database_url)
    yield _engine


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _engine_from_url(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SessionLocal


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager that commits on success, rolls back on exception."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Used on first run + tests."""
    from database import models  # noqa: F401 — ensure models loaded

    from sqlalchemy import inspect

    engine = get_engine()
    models.Base.metadata.create_all(bind=engine)

    # Initialize FTS5 for SQLite
    if get_settings().db_engine == "sqlite":
        _init_sqlite_fts(db_session=None)


def _init_sqlite_fts(db_session) -> None:
    """Create FTS5 virtual table mirroring `search_doc`."""
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        # Drop if exists (idempotent on first init)
        conn.execute(text("DROP TABLE IF EXISTS search_doc_fts"))
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE search_doc_fts USING fts5(
                    doc_id UNINDEXED,
                    doc_type,
                    title,
                    body,
                    contest_name,
                    country,
                    tags,
                    url UNINDEXED,
                    tokenize='unicode61'
                )
                """
            )
        )
        conn.commit()
