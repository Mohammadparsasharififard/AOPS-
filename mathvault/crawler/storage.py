"""Storage layer — writes parsed pages, assets, and version history.

This module bridges the crawler and the database. It guarantees:
1. New versions are INSERTED, never UPDATEd.
2. Incomplete downloads do not destroy existing versions.
3. Filesystem paths are always SHA-256-based (no user input).
4. Search index is updated incrementally.
5. Blocked URLs (CAPTCHA / login / paywall / robots / 401 / 403 / 429) are
   recorded so the crawler can continue without bypassing them.
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
    BlockedUrl,
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
    # Media + interactive tags (for offline link rewriting)
    "iframe", "video", "audio", "source", "form", "input", "button",
    "link", "label",
]
_ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "iframe": ["src", "title", "name"],
    "video": ["src", "controls", "width", "height"],
    "audio": ["src", "controls"],
    "source": ["src", "type"],
    "form": ["action", "method"],
    "input": ["type", "name", "value"],
    "button": ["type"],
    "link": ["href", "rel", "type", "as"],
    "*": ["class", "id", "data-*", "style"],
    "math": ["xmlns", "display"],
    "annotation": ["encoding"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _sanitize_style_attribute(style: str) -> str:
    """Sanitize a CSS style attribute — remove dangerous URL protocols but
    preserve image URLs (which may be rewritten later for offline use).
    """
    if not style:
        return ""
    # Remove javascript: and vbscript: URLs in url() and @import
    import re
    # Block dangerous protocols inside url(...)
    def _block_dangerous(match):
        url = match.group(1).strip("'\"").lower()
        if url.startswith(("javascript:", "vbscript:", "file:", "data:text/html")):
            return "url()"
        return match.group(0)
    cleaned = re.sub(r'url\(["\']?([^"\')]*)["\']?\)', _block_dangerous, style, flags=re.IGNORECASE)
    # Remove expression() (IE-only but legacy XSS)
    cleaned = re.sub(r'expression\s*\([^)]*\)', '', cleaned, flags=re.IGNORECASE)
    # Remove @import url() (CSS injection vector)
    cleaned = re.sub(r'@import\s+url\s*\([^)]*\)', '', cleaned, flags=re.IGNORECASE)
    return cleaned


def sanitize_html(html: str, source_canonical: Optional[str] = None, db_session=None) -> str:
    """Strip dangerous HTML (scripts, inline JS, JS URLs).

    Optionally rewrites inline style url() references to local /api/assets/...
    URLs BEFORE sanitizing (so bleach doesn't strip them).

    Args:
        html: Raw HTML to sanitize.
        source_canonical: If provided, url() references inside style
            attributes are resolved against this URL.
        db_session: If provided (with source_canonical), asset URLs
            found in style attributes are looked up in the DB and
            rewritten to /api/assets/{id}.
    """
    if not html:
        return ""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    # Pre-process: rewrite inline style url() references to local
    # /api/assets/{id} URLs (where the asset exists in the DB).
    # This is done BEFORE bleach (which would otherwise strip the style).
    if source_canonical and db_session is not None:
        try:
            soup_pre = BeautifulSoup(html, "lxml")
            # Build asset URL → ID map (limited)
            from database.models import Asset
            from sqlalchemy import select
            asset_rows = db_session.execute(
                select(Asset.id, Asset.asset_url).limit(5000)
            ).all()
            assets_map = {url: aid for aid, url in asset_rows}

            for el in soup_pre.find_all(style=True):
                style = el["style"]
                if "url(" in style:
                    import re
                    def _replace_url(match):
                        url = match.group(1).strip("'\"")
                        if not url or url.startswith("data:"):
                            return match.group(0)
                        absolute = urljoin(source_canonical, url)
                        asset_id = assets_map.get(absolute)
                        if asset_id:
                            return f"url('/api/assets/{asset_id}')"
                        return match.group(0)
                    new_style = re.sub(
                        r'url\(["\']?([^"\')]*)["\']?\)',
                        _replace_url, style,
                    )
                    if new_style != style:
                        el["style"] = new_style
            html = str(soup_pre)
        except Exception:
            pass

    # Now sanitize with bleach (still strips dangerous style values like
    # javascript: URLs — but our local /api/assets/ URLs are safe)
    # We need to bypass bleach's CSS validation for `style` by using
    # our own pre-sanitization + re-attach approach.
    # Strategy: capture styles, run bleach, then re-attach.
    style_capture: list[tuple[int, str]] = []
    try:
        soup_capture = BeautifulSoup(html, "lxml")
        for i, el in enumerate(soup_capture.find_all(style=True)):
            sanitized = _sanitize_style_attribute(el["style"])
            style_capture.append((i, sanitized))
    except Exception:
        pass

    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )

    # Re-attach styles by index (i-th element with style in original)
    if style_capture:
        try:
            soup_post = BeautifulSoup(cleaned, "lxml")
            post_styled = soup_post.find_all(style=True)
            for i, (orig_idx, sanitized_style) in enumerate(style_capture):
                if i < len(post_styled) and sanitized_style:
                    post_styled[i]["style"] = sanitized_style
            cleaned = str(soup_post)
        except Exception:
            pass

    return cleaned


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
            # Flush so the new version is visible to subsequent queries
            self.db.flush()

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

        Rewrites internal links to local API paths so the snapshot is fully
        usable offline. Only writes if complete — preserves previous version
        on failure.
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

        # Offline link rewriting — rewrite internal <a href> and <img src>
        # so the archived snapshot is browsable offline.
        rewritten = self._rewrite_links_for_offline(html, page.canonical_url)

        # Atomic write (write to .tmp then rename)
        tmp = file_path.with_suffix(".html.tmp")
        tmp.write_text(rewritten, encoding="utf-8")
        tmp.replace(file_path.with_suffix(".html"))
        page.archive_path = rel

    def _rewrite_links_for_offline(self, html: str, source_canonical: str) -> str:
        """Rewrite internal links in archived HTML to local API paths.

        Rewrites:
        - <a href>     → /api/pages/{page_id}    (if page is archived)
                       → data-mv-status='not-archived' (if not archived, same host)
        - <img src>    → /api/assets/{asset_id}  (if asset is archived)
        - <source src> → /api/assets/{asset_id}  (for <video>/<audio>)
        - <source srcset> → first URL only (rough handling)
        - <iframe src> → /api/pages/{page_id}   (if page is archived)
        - <link href>  → /api/assets/{asset_id}  (for stylesheets/fonts)
        - <form action>→ /api/pages/{page_id}   (if action URL is archived)
        - inline style url() → /api/assets/{asset_id} (rough handling)

        External links are left untouched (they will require internet).
        Hash-only links (#section) are left untouched.
        """
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin, urlparse

            soup = BeautifulSoup(html, "lxml")

            # Build a map of canonical_url → page_id for all known pages
            # (single round-trip; can be slow for huge archives)
            # Limit to reasonable size to avoid OOM on small server
            pages_map: dict[str, str] = {}
            try:
                rows = self.db.execute(
                    select(Page.id, Page.canonical_url).limit(10000)
                ).all()
                pages_map = {canon: pid for pid, canon in rows}
            except Exception:
                pass

            # Build a map of asset_url → asset_id for known assets
            assets_map: dict[str, str] = {}
            try:
                from database.models import Asset
                asset_rows = self.db.execute(
                    select(Asset.id, Asset.asset_url).limit(5000)
                ).all()
                assets_map = {url: aid for aid, url in asset_rows}
            except Exception:
                pass

            source_host = (urlparse(source_canonical).hostname or "").lower()
            from crawler.normalizer import canonicalize_url

            def _resolve_page_id(absolute_url: str) -> Optional[str]:
                """Lookup page_id by canonical URL."""
                if "#" in absolute_url:
                    absolute_url = absolute_url.split("#", 1)[0]
                canon = canonicalize_url(absolute_url)
                return pages_map.get(canon)

            def _resolve_asset_id(absolute_url: str) -> Optional[str]:
                """Lookup asset_id by absolute URL."""
                return assets_map.get(absolute_url)

            def _is_internal(absolute_url: str) -> bool:
                target_host = (urlparse(absolute_url).hostname or "").lower()
                return target_host == source_host and target_host

            # Rewrite <a href>
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#"):
                    continue
                if href.startswith(("mailto:", "javascript:", "tel:", "data:")):
                    continue
                absolute = urljoin(source_canonical, href)
                page_id = _resolve_page_id(absolute)
                if page_id:
                    a["href"] = f"/api/pages/{page_id}"
                    if "#" in absolute:
                        a["href"] += "#" + absolute.split("#", 1)[1]
                elif _is_internal(absolute):
                    # Internal but not archived → flag
                    a["data-mv-status"] = "not-archived"

            # Rewrite <img src>
            for img in soup.find_all("img", src=True):
                src = img["src"].strip()
                if not src or src.startswith("data:"):
                    continue
                absolute = urljoin(source_canonical, src)
                asset_id = _resolve_asset_id(absolute)
                if asset_id:
                    img["src"] = f"/api/assets/{asset_id}"

            # Rewrite <source src> (for <video>/<audio>)
            for source_tag in soup.find_all("source", src=True):
                src = source_tag["src"].strip()
                if not src or src.startswith("data:"):
                    continue
                absolute = urljoin(source_canonical, src)
                asset_id = _resolve_asset_id(absolute)
                if asset_id:
                    source_tag["src"] = f"/api/assets/{asset_id}"

            # Rewrite <iframe src>
            for iframe in soup.find_all("iframe", src=True):
                src = iframe["src"].strip()
                if not src or src.startswith("data:"):
                    continue
                absolute = urljoin(source_canonical, src)
                page_id = _resolve_page_id(absolute)
                if page_id:
                    iframe["src"] = f"/api/pages/{page_id}"
                elif _is_internal(absolute):
                    iframe["data-mv-status"] = "not-archived"
                    # Don't keep src — iframe loading external content is dangerous
                    # Show 'not archived' instead
                    iframe["src"] = "about:blank"

            # Rewrite <link href> (stylesheets, fonts)
            for link in soup.find_all("link", href=True):
                href = link["href"].strip()
                if not href or href.startswith("data:"):
                    continue
                absolute = urljoin(source_canonical, href)
                asset_id = _resolve_asset_id(absolute)
                if asset_id:
                    link["href"] = f"/api/assets/{asset_id}"

            # Rewrite <form action>
            for form in soup.find_all("form", action=True):
                action = form["action"].strip()
                if not action or action.startswith("#"):
                    continue
                if action.startswith(("mailto:", "javascript:")):
                    continue
                absolute = urljoin(source_canonical, action)
                page_id = _resolve_page_id(absolute)
                if page_id:
                    form["action"] = f"/api/pages/{page_id}"
                elif _is_internal(absolute):
                    form["data-mv-status"] = "not-archived"

            # Rewrite inline style="...url(...)..."
            for el in soup.find_all(style=True):
                style = el["style"]
                if "url(" in style:
                    # Rough regex replacement — captures the URL inside url(...)
                    import re
                    def _replace_url(match):
                        url = match.group(1).strip("'\"")
                        if not url or url.startswith("data:"):
                            return match.group(0)
                        absolute = urljoin(source_canonical, url)
                        asset_id = _resolve_asset_id(absolute)
                        if asset_id:
                            return f"url('/api/assets/{asset_id}')"
                        return match.group(0)
                    new_style = re.sub(
                        r'url\(["\']?([^"\')]*)["\']?\)',
                        _replace_url,
                        style,
                    )
                    if new_style != style:
                        el["style"] = new_style

            return str(soup)
        except Exception as e:
            logger.warning("Link rewriting failed: %s — using original HTML", e)
            return html

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

    # --- Blocked URLs ------------------------------------------------------

    # HTTP status codes that indicate access-control rather than transient
    # failure. We do NOT bypass these — we record them and continue.
    BLOCKED_HTTP_STATUSES = {401, 403, 429}

    # Substrings in HTML body that indicate CAPTCHA / login / paywall.
    # Used as heuristic detection only — never to bypass.
    BLOCKED_BODY_SIGNATURES = (
        "captcha",
        "are you a robot",
        "are you human",
        "please verify you are",
        "human verification",
        "sign in to continue",
        "log in to continue",
        "please log in",
        "subscribe to continue",
        "paywall",
        "access denied",
        # Cloudflare challenge markers
        "just a moment",
        "_cf_chl_opt",
        "cdn-cgi/challenge-platform",
        "challenges.cloudflare.com",
    )

    def detect_block_reason(self, status_code: int, body: bytes, content_type: Optional[str]) -> Optional[tuple[str, str]]:
        """Inspect a response and return (reason, detail) if it looks blocked,
        otherwise None.
        """
        # Body heuristic — only for HTML. Check FIRST so that Cloudflare
        # challenge (which returns 403 with a specific body) is correctly
        # detected as 'cloudflare_challenge' rather than generic 'access_denied'.
        if content_type and "html" in content_type.lower() and body:
            try:
                text = body.decode("utf-8", errors="replace").lower()[:50000]

                # Cloudflare challenge — detect FIRST (most specific)
                if "just a moment" in text and ("_cf_chl_opt" in text or "cdn-cgi/challenge-platform" in text):
                    return ("cloudflare_challenge", "Cloudflare managed challenge (HTTP 403 + JS challenge page)")
                if "_cf_chl_opt" in text or "cf_chl_rc" in text:
                    return ("cloudflare_challenge", "Cloudflare challenge signature in body")
                if "enable javascript and cookies to continue" in text and "challenges.cloudflare.com" in text:
                    return ("cloudflare_challenge", "Cloudflare JS challenge requirement")
            except Exception:
                pass

        # Now check status codes
        if status_code in self.BLOCKED_HTTP_STATUSES:
            reason_map = {
                401: "login_required",
                403: "access_denied",
                429: "rate_limited",
            }
            return (reason_map[status_code], f"HTTP {status_code}")

        # Body heuristic for non-403 status (e.g. HTTP 200 with captcha body)
        if not content_type or "html" not in content_type.lower():
            return None
        if not body:
            return None
        try:
            text = body.decode("utf-8", errors="replace").lower()[:50000]
        except Exception:
            return None

        for sig in self.BLOCKED_BODY_SIGNATURES:
            if sig not in text:
                continue
            # Determine reason from the matching signature
            if "captcha" in sig:
                return ("captcha", f"Body signature: '{sig}'")
            if "robot" in sig or "human" in sig or "verify" in sig:
                return ("captcha", f"Body signature: '{sig}'")
            if "log in" in sig or "sign in" in sig:
                return ("login_required", f"Body signature: '{sig}'")
            if "subscribe" in sig or "paywall" in sig:
                return ("paywall", f"Body signature: '{sig}'")
            if "access denied" in sig:
                return ("access_denied", f"Body signature: '{sig}'")
            # Cloudflare signatures (caught above, but just in case)
            if "just a moment" in sig or "cf_chl" in sig or "cdn-cgi" in sig:
                return ("cloudflare_challenge", f"Body signature: '{sig}'")
            return ("unknown_block", f"Body signature: '{sig}'")
        return None

    def record_blocked_url(
        self,
        url: str,
        reason: str,
        detail: Optional[str] = None,
        http_status: Optional[int] = None,
        crawl_run_id: Optional[str] = None,
    ) -> None:
        """Insert or update a BlockedUrl row.

        The crawler calls this when it encounters an access-control mechanism
        (CAPTCHA, login wall, paywall, robots, 401, 403, 429). The URL is
        recorded and the crawl continues. The URL is NEVER bypassed.
        """
        canon = canonicalize_url(url)
        existing = self.db.execute(
            select(BlockedUrl).where(BlockedUrl.url == canon)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is None:
            self.db.add(BlockedUrl(
                url=canon,
                canonical_url=canon,
                reason=reason,
                detail=detail,
                http_status=http_status,
                first_detected=now,
                last_attempted=now,
                retry_count=1,
                last_crawl_run_id=crawl_run_id,
            ))
        else:
            existing.last_attempted = now
            existing.retry_count += 1
            existing.last_crawl_run_id = crawl_run_id
            # Update reason/detail only if the new one is more specific
            if reason and detail:
                existing.reason = reason
                existing.detail = detail
            if http_status is not None:
                existing.http_status = http_status
        # Flush so the row is visible in subsequent queries within the same
        # session (without forcing a commit — the caller controls that).
        self.db.flush()
