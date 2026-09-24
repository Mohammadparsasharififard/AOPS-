"""HTTP fetcher with retry, ETag handling, robots.txt respect.

Security:
- Only http(s) schemes
- Private/loopback IPs blocked (SSRF)
- Allowlist enforced BEFORE fetch
- Robots.txt checked (configurable)
- Per-request delay (politeness)
- ETag / If-Modified-Since for incremental sync
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import get_settings
from crawler.normalizer import is_url_allowed_scheme, is_url_private_or_local, is_same_domain

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content: bytes
    content_type: Optional[str]
    etag: Optional[str]
    last_modified: Optional[str]
    content_hash: str
    elapsed_seconds: float
    from_cache: bool = False  # True if server returned 304
    error: Optional[str] = None


@dataclass
class AllowList:
    domains: list[str]
    path_prefixes: list[str]

    def is_allowed(self, url: str) -> bool:
        """True if URL host matches domains AND path starts with one of prefixes."""
        if not is_url_allowed_scheme(url):
            return False
        if is_url_private_or_local(url):
            return False
        if not is_same_domain(url, self.domains):
            return False
        if not self.domains:
            return False
        if not self.path_prefixes:
            return True  # no path restriction configured
        path = urlparse(url).path or "/"
        return any(path.startswith(p) for p in self.path_prefixes)


def build_allowlist() -> AllowList:
    s = get_settings()
    return AllowList(
        domains=s.allowed_domains,
        path_prefixes=s.allowed_path_prefixes,
    )


class RobotsChecker:
    """Cached robots.txt parser per host."""

    def __init__(self, user_agent: str, client: httpx.Client) -> None:
        self.user_agent = user_agent
        self.client = client
        self._cache: dict[str, RobotFileParser | None] = {}

    def can_fetch(self, url: str) -> bool:
        if not get_settings().crawl_respect_robots:
            return True
        host = urlparse(url).hostname or ""
        if host not in self._cache:
            self._cache[host] = self._load_robots(host)
        rp = self._cache[host]
        if rp is None:
            return True  # no robots.txt → allow
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True  # be permissive on parse errors

    def _load_robots(self, host: str) -> Optional[RobotFileParser]:
        for scheme in ("https", "http"):
            url = f"{scheme}://{host}/robots.txt"
            try:
                resp = self.client.get(url, timeout=10)
                if resp.status_code != 200:
                    continue
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                return rp
            except Exception as e:
                logger.debug("robots.txt fetch failed for %s: %s", url, e)
        return None


class Fetcher:
    """Polite HTTP fetcher with ETag support and retry."""

    def __init__(
        self,
        allowlist: Optional[AllowList] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
        delay_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self.settings = get_settings()
        self.allowlist = allowlist or build_allowlist()
        self.user_agent = user_agent or self.settings.crawl_user_agent
        self.timeout = timeout or self.settings.crawl_timeout_seconds
        self.delay = delay_seconds or self.settings.crawl_delay_seconds
        self.max_retries = max_retries or self.settings.crawl_max_retries
        self._last_request_at = 0.0
        self._client: Optional[httpx.Client] = None
        self._robots: Optional[RobotsChecker] = None

    # --- Lifecycle -----------------------------------------------------------

    def __enter__(self) -> "Fetcher":
        self._client = httpx.Client(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
                "Accept-Language": "en;q=0.9",
            },
            follow_redirects=True,
            timeout=self.timeout,
            # Disable HTTP/2 to keep deps minimal
            http2=False,
            # No proxies — never act as an open proxy
        )
        self._robots = RobotsChecker(self.user_agent, self._client)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # --- Public API ----------------------------------------------------------

    def head(self, url: str) -> Optional[FetchResult]:
        """HEAD request — used to detect changes without downloading body."""
        if not self._preflight(url):
            return None
        self._throttle()
        try:
            resp = self._client.head(url, timeout=self.timeout)
            return self._make_result(url, resp, b"", from_cache=resp.status_code == 304)
        except Exception as e:
            logger.warning("HEAD %s failed: %s", url, e)
            return None

    def get(self, url: str, etag: Optional[str] = None, last_modified: Optional[str] = None) -> Optional[FetchResult]:
        """GET with optional conditional headers.

        Returns None on allowlist failure, robot disallow, or persistent error.
        On HTTP 304, returns FetchResult with from_cache=True.
        """
        if not self._preflight(url):
            return None
        self._throttle()

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        def _do_get() -> httpx.Response:
            return self._client.get(url, headers=headers, timeout=self.timeout)

        try:
            resp = _do_get()
        except Exception as e:
            logger.warning("GET %s failed after retries: %s", url, e)
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                content=b"",
                content_type=None,
                etag=None,
                last_modified=None,
                content_hash="",
                elapsed_seconds=0.0,
                error=str(e),
            )

        body = b"" if resp.status_code == 304 else resp.content
        return self._make_result(url, resp, body, from_cache=resp.status_code == 304)

    def is_url_in_scope(self, url: str) -> bool:
        """Public alias for allowlist check (used by discovery)."""
        return self.allowlist.is_allowed(url)

    # --- Internals -----------------------------------------------------------

    def _preflight(self, url: str) -> bool:
        if not is_url_allowed_scheme(url):
            logger.info("Reject non-http(s) URL: %s", url)
            return False
        if is_url_private_or_local(url):
            logger.info("Reject private/local URL (SSRF guard): %s", url)
            return False
        if not self.allowlist.is_allowed(url):
            logger.debug("URL outside allowlist: %s", url)
            return False
        if self._robots and not self._robots.can_fetch(url):
            logger.info("Robots.txt disallows: %s", url)
            return False
        return True

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_at = time.monotonic()

    def _make_result(
        self,
        url: str,
        resp: httpx.Response,
        body: bytes,
        content_hash_str_arg: str = "",
        from_cache: bool = False,
    ) -> FetchResult:
        from crawler.normalizer import content_hash as _ch

        # If caller passed an explicit hash, use it; otherwise compute from body
        ch = content_hash_str_arg or (_ch(body) if body else "")

        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status_code=resp.status_code,
            content=body,
            content_type=resp.headers.get("content-type", "").split(";")[0] or None,
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
            content_hash=ch,
            elapsed_seconds=resp.elapsed.total_seconds() if hasattr(resp, "elapsed") else 0.0,
            from_cache=from_cache,
            error=None,
        )
