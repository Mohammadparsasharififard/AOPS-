"""SQLAlchemy models for MathVault.

Design principles:
1. Storage layer (Page, PageVersion, Asset) is decoupled from semantic layer
   (Contest, Problem, Discussion). This keeps the schema stable when source
   site structure changes.
2. Every fetched resource has a content_hash for incremental sync.
3. Version history is automatic: updating a Page creates a new PageVersion,
   never overwrites the old one.
4. Search uses a denormalized index table for both SQLite FTS5 and PostgreSQL
   FTS — chosen at runtime via DB engine.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    """Base for all models."""


# =============================================================================
# Storage layer (raw crawled pages + assets)
# =============================================================================

class Page(Base):
    """A canonical URL we have crawled (or intend to crawl).

    A page may map to a Contest, Problem, Discussion, etc. via foreign keys
    on those tables, but Page itself is the source-of-truth for HTTP state
    (status, ETag, hash) and versioning.
    """
    __tablename__ = "page"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    etag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    archive_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_fetched: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_changed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetch_failures: Mapped[int] = mapped_column(Integer, default=0)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    versions: Mapped[list["PageVersion"]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
        order_by="PageVersion.version_no.desc()",
    )

    __table_args__ = (
        Index("ix_page_last_changed", "last_changed"),
    )


class PageVersion(Base):
    """Immutable snapshot of a page at a point in time.

    When a page changes, we INSERT a new row here, never UPDATE an existing one.
    This guarantees we can always roll back if a fetch was incomplete.
    """
    __tablename__ = "page_version"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    page_id: Mapped[str] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    byte_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    page: Mapped["Page"] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("page_id", "version_no", name="uq_page_version"),
    )


class Asset(Base):
    """Binary resources (images, PDFs, downloadable problem sets).

    Asset files live on disk under archive/assets/. The DB row stores
    metadata + a SHA256-based path so user input never reaches the filesystem.
    """
    __tablename__ = "asset"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    page_id: Mapped[Optional[str]] = mapped_column(ForeignKey("page.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# =============================================================================
# Semantic layer (contests, problems, discussions)
# =============================================================================

class CountryRegion(Base):
    """A country or region. Discovered by crawler, never hardcoded."""
    __tablename__ = "country_region"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # country | region
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("country_region.id"), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    parent: Mapped[Optional["CountryRegion"]] = relationship(
        remote_side="CountryRegion.id", back_populates="children"
    )
    children: Mapped[list["CountryRegion"]] = relationship(back_populates="parent")
    contests: Mapped[list["Contest"]] = relationship(back_populates="country_region")

    __table_args__ = (
        Index("ix_country_region_parent", "parent_id"),
    )


class Contest(Base):
    """A competition (e.g., IMO, BMO, USAMO).

    The `is_international` flag distinguishes international vs. national contests.
    country_region_id is null for international contests.
    """
    __tablename__ = "contest"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    country_region_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("country_region.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_international: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archive_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_id: Mapped[Optional[str]] = mapped_column(ForeignKey("page.id"), nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    country_region: Mapped[Optional["CountryRegion"]] = relationship(back_populates="contests")
    page: Mapped[Optional["Page"]] = relationship()
    years: Mapped[list["ContestYear"]] = relationship(
        back_populates="contest", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_contest_category", "category"),
    )


class ContestYear(Base):
    """A specific year/round of a contest."""
    __tablename__ = "contest_year"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    contest_id: Mapped[str] = mapped_column(ForeignKey("contest.id", ondelete="CASCADE"), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    round: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    problem_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archive_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_id: Mapped[Optional[str]] = mapped_column(ForeignKey("page.id"), nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    contest: Mapped["Contest"] = relationship(back_populates="years")
    page: Mapped[Optional["Page"]] = relationship()
    problem_sets: Mapped[list["ProblemSet"]] = relationship(
        back_populates="contest_year", cascade="all, delete-orphan"
    )
    problems: Mapped[list["Problem"]] = relationship(
        back_populates="contest_year", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("contest_id", "year", "round", name="uq_contest_year_round"),
    )


class ProblemSetType(str, enum.Enum):
    PROBLEM_SET = "problem_set"
    SOLUTIONS = "solutions"
    ANSWER_KEY = "answer_key"
    SHORTLIST = "shortlist"
    SELECTION = "selection"
    RESOURCE_PACK = "resource_pack"
    OTHER = "other"


class ProblemSet(Base):
    """A downloadable pack for a contest year (problem set, solutions, etc.)."""
    __tablename__ = "problem_set"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    contest_year_id: Mapped[str] = mapped_column(ForeignKey("contest_year.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    asset_id: Mapped[Optional[str]] = mapped_column(ForeignKey("asset.id"), nullable=True)
    archive_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    contest_year: Mapped["ContestYear"] = relationship(back_populates="problem_sets")
    asset: Mapped[Optional["Asset"]] = relationship()


class ArchiveStatus(str, enum.Enum):
    NOT_ARCHIVED = "not_archived"
    ARCHIVED = "archived"
    PARTIAL = "partial"
    FAILED = "failed"


class Problem(Base):
    """An individual problem within a contest year."""
    __tablename__ = "problem"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    contest_year_id: Mapped[str] = mapped_column(ForeignKey("contest_year.id", ondelete="CASCADE"), nullable=False, index=True)
    number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    statement_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    statement_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    archive_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_id: Mapped[Optional[str]] = mapped_column(ForeignKey("page.id"), nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    solution_available: Mapped[bool] = mapped_column(Boolean, default=False)
    discussion_available: Mapped[bool] = mapped_column(Boolean, default=False)
    archive_status: Mapped[str] = mapped_column(String(50), default=ArchiveStatus.NOT_ARCHIVED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    contest_year: Mapped["ContestYear"] = relationship(back_populates="problems")
    page: Mapped[Optional["Page"]] = relationship()
    tags: Mapped[list["Tag"]] = relationship(
        secondary="problem_tag", back_populates="problems"
    )
    discussions: Mapped[list["Discussion"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )


class Tag(Base):
    """A topic tag (e.g., 'geometry', 'number theory')."""
    __tablename__ = "tag"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    problems: Mapped[list["Problem"]] = relationship(
        secondary="problem_tag", back_populates="tags"
    )


# Association: problem_tag
from sqlalchemy import Table, Column

problem_tag = Table(
    "problem_tag",
    Base.metadata,
    Column("problem_id", ForeignKey("problem.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_problem_tag_tag", "tag_id"),
)


class Discussion(Base):
    """A discussion thread attached to a problem or page."""
    __tablename__ = "discussion"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    problem_id: Mapped[Optional[str]] = mapped_column(ForeignKey("problem.id", ondelete="CASCADE"), nullable=True, index=True)
    page_id: Mapped[Optional[str]] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    problem: Mapped[Optional["Problem"]] = relationship(back_populates="discussions")
    posts: Mapped[list["Post"]] = relationship(
        back_populates="discussion", cascade="all, delete-orphan"
    )


class Post(Base):
    """A single post in a discussion. Posts form a tree via parent_post_id."""
    __tablename__ = "post"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    discussion_id: Mapped[str] = mapped_column(ForeignKey("discussion.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_post_id: Mapped[Optional[str]] = mapped_column(ForeignKey("post.id"), nullable=True)
    author_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    content_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    discussion: Mapped["Discussion"] = relationship(back_populates="posts")
    # Self-referential adjacency list:
    #   - parent (many-to-one): remote_side is the PK column (Post.id)
    #   - replies (one-to-many): no remote_side — FK column is implicit remote
    parent: Mapped[Optional["Post"]] = relationship(
        back_populates="replies", remote_side="Post.id"
    )
    replies: Mapped[list["Post"]] = relationship(
        back_populates="parent"
    )

    __table_args__ = (
        Index("ix_post_posted_at", "posted_at"),
    )


# =============================================================================
# Crawl run metadata
# =============================================================================

class CrawlRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class CrawlRun(Base):
    """A single crawl/sync execution. Used by admin dashboard + CLI."""
    __tablename__ = "crawl_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CrawlRunStatus.RUNNING.value, index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | timer | cli
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0)
    pages_new: Mapped[int] = mapped_column(Integer, default=0)
    pages_changed: Mapped[int] = mapped_column(Integer, default=0)
    pages_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    pages_blocked: Mapped[int] = mapped_column(Integer, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)

    errors: Mapped[list["CrawlError"]] = relationship(
        back_populates="crawl_run", cascade="all, delete-orphan"
    )


class CrawlError(Base):
    """Errors recorded during a crawl run, for diagnosis + retry logic."""
    __tablename__ = "crawl_error"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    crawl_run_id: Mapped[str] = mapped_column(ForeignKey("crawl_run.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    crawl_run: Mapped["CrawlRun"] = relationship(back_populates="errors")


class BlockedUrl(Base):
    """URLs the crawler refused to fetch because they triggered an access
    control (CAPTCHA / login / paywall / robots / rate-limit / 403 / 429).

    These are NEVER bypassed — they are recorded and the crawler continues.

    Reasons:
    - captcha
    - login_required
    - paywall
    - robots_disallow
    - access_denied (HTTP 401, 403)
    - rate_limited (HTTP 429)
    - forbidden (HTTP 403)
    - server_error (HTTP 5xx — also recorded as failure, not blocked)
    """
    __tablename__ = "blocked_url"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_attempted: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_crawl_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("crawl_run.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_blocked_url_url", "url"),
        Index("ix_blocked_url_canonical_url", "canonical_url"),
        Index("ix_blocked_url_reason", "reason"),
        Index("ix_blocked_url_first_detected", "first_detected"),
    )


# =============================================================================
# Search index (denormalized; mirrors Problem, Contest, Discussion, Resource)
# =============================================================================

class SearchDoc(Base):
    """A search document. Indexed by FTS5 (SQLite) or via trigger (PG).

    We keep this denormalized so the search query is a single SELECT against
    a dedicated table — no JOINs at query time.
    """
    __tablename__ = "search_doc"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # problem | contest | discussion | resource
    ref_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contest_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("doc_type", "ref_id", name="uq_search_doc_ref"),
    )


# =============================================================================
# Site Graph — typed relationships between nodes (resources, pages, etc.)
# =============================================================================

class SiteNode(Base):
    """A node in the site graph.

    A node represents any resource the crawler has discovered or archived:
    a domain, section, contest, year, round, problem set, problem,
    solution, resource, discussion, thread, post, reply, asset, etc.

    Relationships are stored separately in SiteEdge (typed, directional).
    """
    __tablename__ = "site_node"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Node type — drives semantic interpretation
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # domain | section | contest | year | round | problem_set | problem |
    # solution | resource | discussion | thread | post | reply | asset | page

    # Display + identifiers
    name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    slug: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Source URL (canonical) — null for synthetic nodes (e.g. "domain" node)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Local archive URL — set by Local URL Mapping layer
    local_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Reference to the corresponding semantic entity (if any)
    page_id: Mapped[Optional[str]] = mapped_column(ForeignKey("page.id"), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(ForeignKey("asset.id"), nullable=True)
    contest_id: Mapped[Optional[str]] = mapped_column(ForeignKey("contest.id"), nullable=True)
    contest_year_id: Mapped[Optional[str]] = mapped_column(ForeignKey("contest_year.id"), nullable=True)
    problem_id: Mapped[Optional[str]] = mapped_column(ForeignKey("problem.id"), nullable=True)
    problem_set_id: Mapped[Optional[str]] = mapped_column(ForeignKey("problem_set.id"), nullable=True)
    discussion_id: Mapped[Optional[str]] = mapped_column(ForeignKey("discussion.id"), nullable=True)
    post_id: Mapped[Optional[str]] = mapped_column(ForeignKey("post.id"), nullable=True)

    # Status — distinguishes ARCHIVED from BLOCKED/FAILED/SKIPPED/NOT_VERIFIED
    status: Mapped[str] = mapped_column(String(20), default="not_verified")
    # not_verified | discovered | archived | unchanged | failed | blocked | skipped

    # Metadata
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_archived: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("node_type", "source_url", name="uq_site_node_type_url"),
        Index("ix_site_node_type", "node_type"),
        Index("ix_site_node_slug", "slug"),
        Index("ix_site_node_source_url", "source_url"),
        Index("ix_site_node_status", "status"),
        Index("ix_site_node_status_type", "status", "node_type"),
        Index("ix_site_node_first_seen", "first_seen"),
    )


class SiteEdge(Base):
    """A typed, directional relationship between two SiteNodes.

    Edge types (semantic):
    - parent → child : hierarchical (contest → year, problem → discussion)
    - next → prev : pagination order (problem 2 → problem 3)
    - related : non-hierarchical (problem ↔ related resource)
    - belongs_to : reverse of parent→child (problem belongs_to contest_year)
    - has_problem, has_solution, has_resource, has_discussion, has_post
    - replies_to : post → parent post
    - references : arbitrary cross-link
    - contains_asset : page → asset
    """
    __tablename__ = "site_edge"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("site_node.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("site_node.id", ondelete="CASCADE"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # parent | child | next | prev | related | belongs_to | has_problem |
    # has_solution | has_resource | has_discussion | has_post | replies_to |
    # references | contains_asset
    weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # for ordering
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "edge_type", name="uq_site_edge"),
        Index("ix_site_edge_source", "source_node_id"),
        Index("ix_site_edge_target", "target_node_id"),
        Index("ix_site_edge_type", "edge_type"),
        Index("ix_site_edge_type_source", "edge_type", "source_node_id"),
        Index("ix_site_edge_type_target", "edge_type", "target_node_id"),
    )


class LocalUrlMapping(Base):
    """Maps every archived source URL to a local canonical URL.

    Used by the offline navigation layer to rewrite internal links so the
    archived snapshot is browsable offline (no external requests).

    If local_url is null, the source URL was NOT archived — the frontend
    shows "This content is not available offline."
    """
    __tablename__ = "local_url_mapping"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    canonical_source_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # /archive/...
    node_id: Mapped[Optional[str]] = mapped_column(ForeignKey("site_node.id"), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_local_url_mapping_source", "source_url"),
        Index("ix_local_url_mapping_canon", "canonical_source_url"),
        Index("ix_local_url_mapping_archived", "archived"),
        Index("ix_local_url_mapping_node", "node_id"),
    )
