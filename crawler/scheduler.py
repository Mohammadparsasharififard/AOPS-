"""Scheduler — orchestrates a single crawl run.

Responsibilities:
- Take start URLs from config
- Run BFS to max_depth
- Respect max_pages, concurrency, delay
- Write to DB + filesystem via Storage
- Record CrawlRun + CrawlError

Concurrency is single-threaded by default (configurable CRAWL_CONCURRENCY).
For simplicity + politeness, we keep concurrency low.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import get_settings
from crawler.discovery import Frontier, discover_links
from crawler.fetcher import AllowList, Fetcher, HttpFetcher, FetchResult, build_allowlist, build_fetcher
from crawler.normalizer import canonicalize_url, is_url_allowed_scheme
from crawler.parser import is_html_content_type, parse_html
from crawler.storage import Storage
from crawler.authorization import Authorization, load_authorization
from database.models import BlockedUrl, CrawlError, CrawlRun, CrawlRunStatus, Page

logger = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    pages_discovered: int = 0
    pages_new: int = 0
    pages_changed: int = 0
    pages_unchanged: int = 0
    pages_failed: int = 0
    pages_blocked: int = 0
    bytes_downloaded: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None


class CrawlScheduler:
    """Runs a single crawl pass from start URLs."""

    def __init__(
        self,
        db: Session,
        allowlist: Optional[AllowList] = None,
        dry_run: bool = False,
        trigger: str = "manual",
        authorization: Optional[Authorization] = None,
    ) -> None:
        self.db = db
        self.settings = get_settings()
        self.allowlist = allowlist or build_allowlist()
        self.dry_run = dry_run
        self.trigger = trigger
        self.authorization = authorization  # None = unauthorized, use HttpFetcher
        self.stats = CrawlStats()
        self.crawl_run_id: Optional[str] = None

    def run(self) -> CrawlStats:
        """Execute one crawl run. Updates self.stats as it goes."""
        crawl_run = CrawlRun(
            started_at=self.stats.started_at,
            status=CrawlRunStatus.RUNNING.value,
            trigger=self.trigger,
            dry_run=self.dry_run,
        )
        self.db.add(crawl_run)
        self.db.commit()
        self.db.refresh(crawl_run)
        self.crawl_run_id = crawl_run.id

        frontier = Frontier(
            allowlist=self.allowlist,
            max_depth=self.settings.crawl_max_depth,
            max_pages=self.settings.crawl_max_pages,
            mode="bfs",
        )
        # Seed frontier with start URLs
        for url in self.settings.start_urls:
            frontier.add(url, depth=0)

        try:
            # Build fetcher based on authorization scope.
            # Without authorization (default), this returns HttpFetcher.
            # With explicit authorization + browser_session_allowed, returns
            # AuthorizedBrowserFetcher (Playwright + real Chromium).
            fetcher = build_fetcher(allowlist=self.allowlist,
                                    authorization=self.authorization)
            with fetcher:
                storage = Storage(self.db)

                while not frontier.empty() and self.stats.pages_discovered < self.settings.crawl_max_pages:
                    entry = frontier.pop()
                    if entry is None:
                        break
                    self._process_one(fetcher, storage, frontier, entry.url, entry.depth)
                    self._persist_progress()
        except Exception as e:
            logger.exception("Crawl run failed: %s", e)
            self._fail_run(str(e))
            raise
        else:
            self._finish_run()
        finally:
            self.stats.finished_at = datetime.now(timezone.utc)

        return self.stats

    # --- Per-URL processing -------------------------------------------------

    def _process_one(
        self,
        fetcher: Fetcher,
        storage: Storage,
        frontier: Frontier,
        url: str,
        depth: int,
    ) -> None:
        self.stats.pages_discovered += 1
        logger.info(
            "[%d/%d] depth=%d %s",
            self.stats.pages_discovered, self.settings.crawl_max_pages, depth, url,
        )

        if self.dry_run:
            logger.info("[dry-run] would fetch: %s", url)
            return

        # Find existing page (for ETag conditional request)
        existing_page = self.db.execute(
            select(Page).where(Page.url == canonicalize_url(url))
        ).scalar_one_or_none()

        result = fetcher.get(
            url,
            etag=existing_page.etag if existing_page else None,
            last_modified=existing_page.last_modified if existing_page else None,
        )
        if result is None:
            self.stats.pages_failed += 1
            self._record_error(url, "preflight_rejected", "URL rejected by allowlist/robots")
            # Robots-disallowed URLs are recorded as blocked too
            storage.record_blocked_url(
                url=url, reason="robots_disallow",
                detail="URL disallowed by robots.txt or allowlist",
                crawl_run_id=self.crawl_run_id,
            )
            return
        if result.error:
            self.stats.pages_failed += 1
            self._record_error(url, "fetch_error", result.error)
            return
        # Challenge required (real CAPTCHA puzzle — requires human, never auto-solved)
        if getattr(result, "challenge_required", False):
            storage.record_blocked_url(
                url=url, reason="challenge_required",
                detail="Real CAPTCHA puzzle (image/click-X) detected — requires human verification",
                http_status=result.status_code, crawl_run_id=self.crawl_run_id,
            )
            logger.info("Challenge required at %s — recorded as blocked (no bypass)", url)
            return
        if result.status_code == 304 and existing_page:
            self.stats.pages_unchanged += 1
            self._update_progress(pages_unchanged=self.stats.pages_unchanged)
            return
        if result.status_code >= 400:
            # 401/403/429 → blocked (access control), not just failed
            block_reason = storage.detect_block_reason(result.status_code, b"", None)
            if block_reason is not None:
                reason, detail = block_reason
                storage.record_blocked_url(
                    url=url, reason=reason, detail=detail,
                    http_status=result.status_code, crawl_run_id=self.crawl_run_id,
                )
                # Don't count as "failed" — it's blocked (intentional, not error)
                return
            self.stats.pages_failed += 1
            self._record_error(
                url, f"http_{result.status_code}",
                f"HTTP {result.status_code}",
                http_status=result.status_code,
            )
            return

        # Body heuristic — check if HTML body has CAPTCHA/login/paywall signatures
        # BEFORE storing. This is the user's explicit requirement: NEVER bypass
        # these. We detect, record as BLOCKED, and continue without storing.
        if is_html_content_type(result.content_type):
            block_reason = storage.detect_block_reason(
                result.status_code, result.content, result.content_type
            )
            if block_reason is not None:
                reason, detail = block_reason
                storage.record_blocked_url(
                    url=url, reason=reason, detail=detail,
                    http_status=result.status_code, crawl_run_id=self.crawl_run_id,
                )
                logger.info("Blocked URL detected (%s): %s", reason, url)
                return  # Do NOT store — content is access-protected

        self.stats.bytes_downloaded += len(result.content)

        if not is_html_content_type(result.content_type):
            # Treat as asset (download)
            storage.upsert_asset(
                page_id=existing_page.id if existing_page else None,
                asset_url=url,
                content_bytes=result.content,
                content_type=result.content_type,
            )
            return

        # Parse HTML
        try:
            html_str = result.content.decode("utf-8", errors="replace")
            parsed = parse_html(html_str, base_url=result.final_url)
        except Exception as e:
            self.stats.pages_failed += 1
            self._record_error(url, "parse_error", str(e))
            return

        # Store page + version
        try:
            from crawler.storage import sanitize_html

            clean_html = sanitize_html(
                parsed.html,
                source_canonical=result.final_url,
                db_session=self.db,
            )
            page, status = storage.upsert_page(
                url=url,
                canonical=result.final_url,
                content_type=result.content_type,
                status_code=result.status_code,
                etag=result.etag,
                last_modified=result.last_modified,
                content_bytes=result.content,
                content_text=parsed.text,
                content_html=clean_html,
                is_complete=True,
            )
            if status == "new":
                self.stats.pages_new += 1
            elif status == "changed":
                self.stats.pages_changed += 1
            elif status == "unchanged":
                self.stats.pages_unchanged += 1

            # Update search index
            storage.upsert_search_doc(
                doc_type="page",
                ref_id=page.id,
                title=parsed.title or url,
                body=parsed.text[:50000],
                url=url,
            )

            # Discover links
            maxed = self.stats.pages_discovered >= self.settings.crawl_max_pages
            discover_links(
                source_url=url,
                raw_links=parsed.links,
                allowlist=self.allowlist,
                frontier=frontier,
                current_depth=depth,
                max_pages_reached=maxed,
            )

            # Download assets (in same run — small images only)
            for asset_url in parsed.assets[:20]:  # cap per page
                if not is_url_allowed_scheme(asset_url):
                    continue
                asset_result = fetcher.get(asset_url)
                if asset_result and asset_result.content and not asset_result.error:
                    storage.upsert_asset(
                        page_id=page.id,
                        asset_url=asset_result.final_url,
                        content_bytes=asset_result.content,
                        content_type=asset_result.content_type,
                    )
                    self.stats.bytes_downloaded += len(asset_result.content)
        except Exception as e:
            logger.exception("Error storing page %s: %s", url, e)
            self.stats.pages_failed += 1
            self._record_error(url, "storage_error", str(e))

    # --- CrawlRun bookkeeping ----------------------------------------------

    def _record_error(self, url: str, error_type: str, message: str, http_status: Optional[int] = None) -> None:
        if self.crawl_run_id is None:
            return
        err = CrawlError(
            crawl_run_id=self.crawl_run_id,
            url=url,
            error_type=error_type,
            message=message[:2000],
            http_status=http_status,
        )
        self.db.add(err)
        self.db.commit()

    def _update_progress(self, **kwargs) -> None:
        if self.crawl_run_id is None:
            return
        from sqlalchemy import update
        self.db.execute(update(CrawlRun).where(CrawlRun.id == self.crawl_run_id).values(**kwargs))
        self.db.commit()

    def _persist_progress(self) -> None:
        self._update_progress(
            pages_discovered=self.stats.pages_discovered,
            pages_new=self.stats.pages_new,
            pages_changed=self.stats.pages_changed,
            pages_unchanged=self.stats.pages_unchanged,
            pages_failed=self.stats.pages_failed,
            pages_blocked=self.stats.pages_blocked,
            bytes_downloaded=self.stats.bytes_downloaded,
        )

    def _finish_run(self) -> None:
        if self.crawl_run_id is None:
            return
        from sqlalchemy import update
        # Compute total blocked count from DB (more accurate than self.stats,
        # since blocked URLs are recorded inline by storage.record_blocked_url)
        blocked_count = self.db.execute(
            select(func.count(BlockedUrl.id)).where(
                BlockedUrl.last_crawl_run_id == self.crawl_run_id
            )
        ).scalar() or 0
        self.stats.pages_blocked = blocked_count
        self.db.execute(
            update(CrawlRun).where(CrawlRun.id == self.crawl_run_id).values(
                finished_at=datetime.now(timezone.utc),
                status=CrawlRunStatus.COMPLETED.value,
                pages_discovered=self.stats.pages_discovered,
                pages_new=self.stats.pages_new,
                pages_changed=self.stats.pages_changed,
                pages_unchanged=self.stats.pages_unchanged,
                pages_failed=self.stats.pages_failed,
                pages_blocked=blocked_count,
                bytes_downloaded=self.stats.bytes_downloaded,
            )
        )
        self.db.commit()

    def _fail_run(self, message: str) -> None:
        if self.crawl_run_id is None:
            return
        from sqlalchemy import update
        self.db.execute(
            update(CrawlRun).where(CrawlRun.id == self.crawl_run_id).values(
                finished_at=datetime.now(timezone.utc),
                status=CrawlRunStatus.FAILED.value,
                error_message=message[:2000],
                pages_discovered=self.stats.pages_discovered,
                pages_new=self.stats.pages_new,
                pages_changed=self.stats.pages_changed,
                pages_unchanged=self.stats.pages_unchanged,
                pages_failed=self.stats.pages_failed,
                bytes_downloaded=self.stats.bytes_downloaded,
            )
        )
        self.db.commit()


def run_sync(trigger: str = "timer", dry_run: bool = False,
             authorization: Optional[Authorization] = None) -> CrawlStats:
    """Convenience wrapper used by CLI + systemd timer.

    If `authorization` is provided and explicitly authorizes browser use,
    the scheduler will use AuthorizedBrowserFetcher; otherwise it falls
    back to HttpFetcher.
    """
    from database.session import session_scope

    with session_scope() as db:
        scheduler = CrawlScheduler(db=db, dry_run=dry_run, trigger=trigger,
                                   authorization=authorization)
        return scheduler.run()
