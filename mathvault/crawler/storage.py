"""Storage layer — writes parsed pages, assets, and version history.

This module bridges the crawler and the database. It guarantees:
1. New versions are INSERTED, never UPDATEd.
2. Incomplete downloads do not destroy existing versions.
3. Filesystem paths are always SHA-256-based (no user input).
4. Search index is updated incrementally.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bleach
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from config import get_settings
from crawler.normalizer import (
    canonicalize_url,
    content_hash,
    content_hash_str,
    url_to_safe_filename,
)
from database.models import (
    ArchiveStatus,
    Asset,
    CrawlRun,
    Page,
    PageVersion,
    SearchDoc,
)

logger = logging.getLogger(__name__)


# --- HTML sanitization (XSS protection) ---------------------------------------
_ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "span", "div",
    "table", "thead", "tbody", "tr", "td", "th",
    "ul", "ol", "li",
    "blockquote", "pre", "code",
    "img", "a", "figure", "figcaption",
    "sup", "sub",
    "math", "mrow", "mi", "mo", "mn", "msup", "msub", "mfrac", "msqrt", "mroot",
    "annotation",
]
_ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "*": ["class", "id", "data-*"],
    "math": ["xmlns", "display"],
    "annotation": ["encoding"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(html: str) -> str:
    """Strip dangerous HTML (scripts, inline JS, JS URLs)."""
    if not html:
        return ""
    return bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )


class Storage:
    """Handles DB writes for crawled pages and assets."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    # --- Pages + version history -------------------------------------------

    def upsert_page(
        self,
        url: str,
        canonical: str,
        content_type: Optional[str],
        status_code: int,
        etag: Optional[str],
        last_modified: Optional[str],
        content_bytes: bytes,
        content_text: str,
        content_html: str,
        is_complete: bool = True,
    ) -> tuple[Page, str]:
        """Insert or update a Page; always create a new PageVersion if changed.

        Returns (Page, status) where status ∈ {"new", "changed", "unchanged", "incomplete"}.
        """
        canonical = canonical or canonicalize_url(url)
        new_hash = content_hash(content_bytes) if content_bytes else content_hash_str(content_text or "")

        # Find existing page
        page = self.db.execute(
            select(Page).where(Page.url == canonical)
        ).scalar_one_or_none()

        if page is None:
            page = Page(
                url=canonical,
                canonical_url=canonical,
                content_type=content_type,
                status_code=status_code,
                etag=etag,
                last_modified=last_modified,
                content_hash=new_hash,
                archive_path=url_to_safe_filename(canonical),
                last_fetched=datetime.now(timezone.utc),
                last_changed=datetime.now(timezone.utc),
                fetch_failures=0,
                is_complete=is_complete,
            )
            self.db.add(page)
            self.db.flush()
            version_no = 1
            status = "new" if is_complete else "incomplete"
        else:
            page.content_type = content_type
            page.status_code = status_code
            page.etag = etag
            page.last_modified = last_modified
            page.last_fetched = datetime.now(timezone.utc)
            page.fetch_failures = 0
            page.is_complete = is_complete

            if page.content_hash == new_hash and is_complete:
                # No change
                status = "unchanged"
                version_no = self._current_version_no(page)
                # Don't touch last_changed
            else:
                page.content_hash = new_hash
                page.last_changed = datetime.now(timezone.utc)
                version_no = self._current_version_no(page) + 1
                status = "changed" if is_complete else "incomplete"

        # Insert new version (always — even if unchanged, to record fetch attempt? No.)
        # Only insert a new version when content changed OR first time.
        if status in ("new", "changed", "incomplete"):
            self.db.execute(
                update(PageVersion)
                .where(PageVersion.page_id == page.id, PageVersion.is_current == True)  # noqa: E712
                .values(is_current=False)
            )
            new_version = PageVersion(
                page_id=page.id,
                version_no=version_no,
                content_html=content_html if is_complete else None,
                content_text=content_text if is_complete else None,
                sha256=new_hash,
                fetched_at=datetime.now(timezone.utc),
                is_current=True,
                is_complete=is_complete,
                byte_size=len(content_bytes) if content_bytes else len(content_text or ""),
            )
            self.db.add(new_version)

        self._write_page_file(page, content_html if is_complete else "", status)
        return page, status

    def _current_version_no(self, page: Page) -> int:
        latest = self.db.execute(
            select(PageVersion.version_no)
            .where(PageVersion.page_id == page.id)
            .order_by(PageVersion.version_no.desc())
            .limit(1)
        ).scalar_one_or_none()
        return latest or 0

    def _write_page_file(self, page: Page, html: str, status: str) -> None:
        """Write the page's current HTML snapshot to disk.

        Only write if complete — preserves previous version on failure.
        """
        if status not in ("new", "changed"):
            return
        if not html:
            return
        rel = url_to_safe_filename(page.canonical_url)
        # rel looks like XX/YY/HASH
        page_dir = self.settings.archive_path / "pages" / rel.split("/")[0] / rel.split("/")[1]
        page_dir.mkdir(parents=True, exist_ok=True)
        file_path = page_dir / rel.split("/")[-1]
        # Write current version (atomically — write to .tmp then rename)
        tmp = file_path.with_suffix(".html.tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(file_path.with_suffix(".html"))
        # Page.archive_path is the relative dir
        page.archive_path = rel

    # --- Assets ------------------------------------------------------------

    def upsert_asset(
        self,
        page_id: Optional[str],
        asset_url: str,
        content_bytes: bytes,
        content_type: Optional[str],
    ) -> Asset:
        """Save an asset to disk and upsert its DB row."""
        new_hash = content_hash(content_bytes)
        asset = self.db.execute(
            select(Asset).where(Asset.asset_url == asset_url)
        ).scalar_one_or_none()
        if asset and asset.sha256 == new_hash:
            return asset  # unchanged

        # Write file
        rel = url_to_safe_filename(asset_url)
        asset_dir = self.settings.archive_path / "assets" / rel.split("/")[0] / rel.split("/")[1]
        asset_dir.mkdir(parents=True, exist_ok=True)
        # Determine extension from content type
        ext_map = {
            "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
            "image/svg+xml": ".svg", "image/webp": ".webp",
            "application/pdf": ".pdf",
            "application/zip": ".zip",
            "application/postscript": ".ps",
            "text/plain": ".txt",
        }
        ext = ext_map.get((content_type or "").lower(), ".bin")
        file_path = asset_dir / (rel.split("/")[-1] + ext)
        tmp = file_path.with_suffix(ext + ".tmp")
        tmp.write_bytes(content_bytes)
        tmp.replace(file_path)

        local_path = str(file_path.relative_to(self.settings.archive_path))
        if asset is None:
            asset = Asset(
                page_id=page_id,
                asset_url=asset_url,
                local_path=local_path,
                content_type=content_type,
                sha256=new_hash,
                size_bytes=len(content_bytes),
                fetched_at=datetime.now(timezone.utc),
            )
            self.db.add(asset)
        else:
            asset.local_path = local_path
            asset.content_type = content_type
            asset.sha256 = new_hash
            asset.size_bytes = len(content_bytes)
            asset.fetched_at = datetime.now(timezone.utc)
        return asset

    # --- Search index ------------------------------------------------------

    def upsert_search_doc(
        self,
        doc_type: str,
        ref_id: str,
        title: Optional[str],
        body: Optional[str],
        contest_name: Optional[str] = None,
        year: Optional[int] = None,
        country: Optional[str] = None,
        tags: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        """Upsert into the search_doc table.

        Also handles FTS5 sync (SQLite) — see FTS triggers in api/services/search.py.
        """
        existing = self.db.execute(
            select(SearchDoc).where(SearchDoc.doc_type == doc_type, SearchDoc.ref_id == ref_id)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is None:
            doc = SearchDoc(
                doc_type=doc_type, ref_id=ref_id, title=title, body=body,
                contest_name=contest_name, year=year, country=country,
                tags=tags, url=url, last_synced=now, updated_at=now,
            )
            self.db.add(doc)
            self.db.flush()  # populate doc.id
            doc_id_db = doc.id
        else:
            existing.title = title
            existing.body = body
            existing.contest_name = contest_name
            existing.year = year
            existing.country = country
            existing.tags = tags
            existing.url = url
            existing.last_synced = now
            existing.updated_at = now
            doc_id_db = existing.id

        # If SQLite, mirror to FTS5 virtual table
        if self.settings.db_engine == "sqlite":
            from sqlalchemy import text as sql_text
            self.db.execute(sql_text(
                "DELETE FROM search_doc_fts WHERE doc_id = :id"
            ), {"id": doc_id_db})
            self.db.execute(sql_text(
                """
                INSERT INTO search_doc_fts (doc_id, doc_type, title, body, contest_name, country, tags, url)
                VALUES (:id, :dt, :t, :b, :cn, :c, :tg, :u)
                """
            ), {
                "id": doc_id_db, "dt": doc_type, "t": title, "b": body,
                "cn": contest_name, "c": country, "tg": tags, "u": url,
            })

    # --- CrawlRun update ---------------------------------------------------

    def record_crawl_stats(self, crawl_run_id: str, **stats) -> None:
        self.db.execute(
            update(CrawlRun).where(CrawlRun.id == crawl_run_id).values(**stats)
        )
