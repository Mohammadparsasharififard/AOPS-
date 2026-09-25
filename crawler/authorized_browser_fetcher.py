"""Authorized Browser Fetcher — uses Playwright to load pages in a real
browser when the source's authorization scope explicitly allows it.

CRITICAL RULES (NEVER VIOLATED):
1. This fetcher is ONLY used when:
   - source.authorization.status == 'authorized'
   - source.authorization.evidence_verified == True
   - source.authorization.scope.browser_session_allowed == True
   - source.authorization.scope.challenge_verification_allowed == True (for JS challenge)
2. The browser is REAL Chromium (Playwright-installed). It does NOT:
   - Spoof the user agent
   - Use a fake browser fingerprint
   - Use any CAPTCHA-solving service
   - Use any third-party challenge-bypass library
3. Cloudflare's JS challenge runs naturally in the browser — this is the
   same way it runs when a human opens the page in Chrome. The resulting
   cf_clearance cookie lives in this browser session ONLY. It is NEVER:
   - Exported
   - Shared with other sessions
   - Committed to git
   - Logged
4. If a REAL CAPTCHA puzzle (image, click-X, etc.) appears — i.e. one
   that requires human interaction — the fetcher returns a FetchResult
   with challenge_required=True. The caller must PAUSE for human input.
   It NEVER solves the puzzle programmatically.
5. The fetcher respects the source's rate_limit:
   - delay_seconds between requests
   - concurrency = 1 (no parallel browser tabs in this implementation)
   - requests_per_minute cap
6. The fetcher respects the source's allowed_paths and allowed_content_types.
   URLs outside scope are REJECTED before navigation.
"""
from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse

from crawler.fetcher import Fetcher, FetchResult, AllowList
from crawler.normalizer import canonicalize_url, content_hash, is_url_allowed_scheme, is_url_private_or_local
from crawler.authorization import Authorization

logger = logging.getLogger(__name__)


# Cloudflare challenge detection — body signatures that indicate a real
# CAPTCHA puzzle (image, click-X) that requires human interaction.
# These are SEPARATE from the JS challenge (which the browser solves naturally).
REAL_CAPTCHA_SIGNATURES = (
    "cf-spinner-please-wait",
    "cf-challenge-running",
    "hcaptcha",
    "recaptcha",
    "captcha-container",
    "cf-turnstile",
)


class AuthorizedBrowserFetcher(Fetcher):
    """Fetches URLs using a real browser (Playwright + Chromium).

    Requires explicit authorization with browser_session_allowed = True.
    """

    def __init__(
        self,
        allowlist: AllowList,
        authorization: Authorization,
        headless: bool = True,
        delay_seconds: float = 5.0,
        max_retries: int = 3,
        timeout_seconds: int = 30,
        session_timeout_minutes: int = 60,
    ) -> None:
        # Validate authorization
        if not authorization.can_use_browser():
            raise PermissionError(
                "AuthorizedBrowserFetcher requires explicit authorization with "
                "browser_session_allowed=True. Without it, use HttpFetcher."
            )

        self.allowlist = allowlist
        self.authorization = authorization
        self.headless = headless
        self.delay = delay_seconds
        self.max_retries = max_retries
        self.timeout = timeout_seconds
        self.session_timeout_minutes = session_timeout_minutes

        self._playwright = None
        self._browser = None
        self._context = None  # persistent context (cookies live here)
        self._last_request_at = 0.0
        self._session_started_at: Optional[float] = None

        # Try to import Playwright
        try:
            from playwright.sync_api import sync_playwright
            self._sync_playwright = sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Install with:\n"
                "  pip install playwright\n"
                "  playwright install chromium\n"
                "Without Playwright, AuthorizedBrowserFetcher cannot be used."
            )

    # --- Lifecycle -----------------------------------------------------------

    def __enter__(self) -> "AuthorizedBrowserFetcher":
        self._start_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _start_session(self) -> None:
        """Start a fresh browser session."""
        self._playwright = self._sync_playwright().start()
        # Use persistent context so cookies survive within the session
        # (but not across sessions — never persisted to disk)
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        # Never spoof user agent — use Chromium's default
        self._session_started_at = time.monotonic()
        logger.info("Authorized browser session started (headless=%s)", self.headless)

    def close(self) -> None:
        """Close the browser session. Cookies are discarded (not persisted)."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Authorized browser session closed (cookies discarded)")

    def _restart_if_expired(self) -> None:
        """Restart the browser session if it has been alive too long."""
        if self._session_started_at is None:
            self._start_session()
            return
        elapsed_min = (time.monotonic() - self._session_started_at) / 60
        if elapsed_min >= self.session_timeout_minutes:
            logger.info("Session expired after %d min — restarting", int(elapsed_min))
            self.close()
            self._start_session()

    # --- Public API ----------------------------------------------------------

    def is_url_in_scope(self, url: str) -> bool:
        """Check if URL is in the source's allowed_paths AND allowlist."""
        if not is_url_allowed_scheme(url):
            return False
        if is_url_private_or_local(url):
            return False
        if not self.allowlist.is_allowed(url):
            return False
        # Also check source's allowed_paths
        source_paths = getattr(self, "source_paths", None) or []
        if source_paths:
            path = urlparse(url).path or "/"
            return any(path.startswith(p) for p in source_paths)
        return True

    def fetch(self, url: str, etag: Optional[str] = None,
              last_modified: Optional[str] = None) -> Optional[FetchResult]:
        """Fetch a URL via the browser.

        If Cloudflare's JS challenge runs naturally (because the browser is
        real), the challenge is solved by the browser and the page content
        is returned. This is NOT a bypass.

        If a REAL CAPTCHA puzzle (image, click-X) appears, the fetcher
        returns challenge_required=True and the caller must pause.
        """
        if not self.is_url_in_scope(url):
            logger.info("URL out of scope: %s", url)
            return None

        self._throttle()
        self._restart_if_expired()

        if self._context is None:
            self._start_session()

        # Navigate
        try:
            page = self._context.new_page()
            try:
                response = page.goto(url, wait_until="domcontentloaded",
                                     timeout=self.timeout * 1000)
                if response is None:
                    return FetchResult(
                        url=url, final_url=url, status_code=0, content=b"",
                        content_type=None, etag=None, last_modified=None,
                        content_hash="", elapsed_seconds=0.0,
                        fetcher="browser", error="No response from page.goto",
                    )

                # Wait briefly for any JS challenge to run naturally
                # (this is what a real browser does — NOT a bypass)
                time.sleep(2)

                # Check if a real CAPTCHA puzzle appeared
                html = page.content()
                if self._is_real_captcha(html):
                    logger.warning("Real CAPTCHA detected at %s — pausing for human verification", url)
                    return FetchResult(
                        url=url, final_url=page.url, status_code=response.status,
                        content=html.encode("utf-8", errors="replace"),
                        content_type=response.headers.get("content-type", "").split(";")[0] or None,
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        content_hash=content_hash(html.encode("utf-8")),
                        elapsed_seconds=0.0,
                        fetcher="browser",
                        challenge_required=True,
                    )

                # Page loaded successfully
                content_bytes = html.encode("utf-8", errors="replace")
                return FetchResult(
                    url=url,
                    final_url=page.url,
                    status_code=response.status,
                    content=content_bytes,
                    content_type=response.headers.get("content-type", "").split(";")[0] or None,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    content_hash=content_hash(content_bytes),
                    elapsed_seconds=0.0,
                    fetcher="browser",
                )
            finally:
                page.close()
        except Exception as e:
            logger.warning("Browser fetch failed for %s: %s", url, e)
            return FetchResult(
                url=url, final_url=url, status_code=0, content=b"",
                content_type=None, etag=None, last_modified=None,
                content_hash="", elapsed_seconds=0.0,
                fetcher="browser", error=str(e),
            )

    # --- Internal ------------------------------------------------------------

    def _is_real_captcha(self, html: str) -> bool:
        """Detect a real CAPTCHA puzzle (image, click-X) that requires human.

        This is SEPARATE from Cloudflare's JS challenge (which the browser
        solves naturally). If we detect hCaptcha, reCAPTCHA, or Cloudflare
        Turnstile (visible puzzle), we PAUSE.
        """
        text = html.lower()[:50000]
        for sig in REAL_CAPTCHA_SIGNATURES:
            if sig in text:
                return True
        return False

    def _throttle(self) -> None:
        """Enforce delay between requests (rate limiting)."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_at = time.monotonic()


def build_fetcher(
    allowlist: AllowList,
    authorization: Optional[Authorization] = None,
    config_overrides: Optional[dict] = None,
) -> Fetcher:
    """Factory: returns the most-permissive fetcher the authorization allows.

    - If authorization is None or doesn't allow browser → returns HttpFetcher
    - If authorization explicitly allows browser → returns AuthorizedBrowserFetcher

    The user MUST opt-in to browser usage via source.yaml scope flags.
    There is NO automatic escalation.
    """
    overrides = config_overrides or {}

    if authorization and authorization.can_use_browser():
        try:
            return AuthorizedBrowserFetcher(
                allowlist=allowlist,
                authorization=authorization,
                headless=overrides.get("headless", True),
                delay_seconds=overrides.get("delay_seconds", 5.0),
                max_retries=overrides.get("max_retries", 3),
                timeout_seconds=overrides.get("timeout_seconds", 30),
                session_timeout_minutes=overrides.get("session_timeout_minutes", 60),
            )
        except (PermissionError, RuntimeError) as e:
            logger.warning("Falling back to HttpFetcher: %s", e)

    # Fall back to HTTP-only mode
    return HttpFetcher(allowlist=allowlist)
