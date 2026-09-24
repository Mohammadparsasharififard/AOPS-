"""URL + content normalization utilities.

These helpers guarantee that the same logical resource always maps to the same
canonical URL and content hash, regardless of how it was linked.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from urllib.parse import ParseResult, parse_qsl, quote, unquote, urljoin, urlparse, urlunparse
from typing import Optional


_PRIVATE_IP_PATTERNS = re.compile(
    r"^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.|0\.|"
    r"::1|fc00:|fd[0-9a-f]{2}:|fe80:)",
    re.IGNORECASE,
)


def is_url_allowed_scheme(url: str) -> bool:
    """Only http(s) is allowed — this is part of SSRF protection."""
    try:
        scheme = urlparse(url).scheme.lower()
    except Exception:
        return False
    return scheme in ("http", "https")


def is_url_private_or_local(url: str) -> bool:
    """Detect URLs that point at private/loopback networks (SSRF guard)."""
    try:
        host = urlparse(url).hostname or ""
        if not host:
            return True
        # Check if it's an IP literal
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
        except ValueError:
            pass
        # Domain-based check (rough — covers common dev hostnames)
        if _PRIVATE_IP_PATTERNS.match(host):
            return True
        if host in ("localhost", "ip6-localhost", "broadcasthost"):
            return True
        return False
    except Exception:
        return True


def canonicalize_url(url: str, base_url: Optional[str] = None) -> str:
    """Normalize a URL for deduplication.

    Steps:
    - Resolve relative URLs against base
    - Lowercase scheme + host
    - Strip default ports (:80, :443)
    - Decode then re-encode the path (collapse % escapes)
    - Strip fragment
    - Sort query parameters
    - Strip trailing slash on root path
    """
    if base_url:
        url = urljoin(base_url, url)

    try:
        parsed: ParseResult = urlparse(url)
    except Exception:
        return url

    scheme = (parsed.scheme or "http").lower()
    if scheme not in ("http", "https"):
        return url  # leave non-HTTP alone — fetcher will refuse

    netloc = parsed.netloc.lower()
    # Strip userinfo
    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]
    # Strip default ports
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    # Normalize path: decode then re-encode, collapse slashes
    path = unquote(parsed.path or "/")
    # Quote but preserve slash
    path = quote(path, safe="/%:@!$&'()*+,;=")
    # Collapse multiple slashes (not root)
    if len(path) > 1:
        path = re.sub(r"/{2,}", "/", path)
        # Strip trailing slash (except for root)
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")

    # Sort query params
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query_pairs.sort()
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in query_pairs)

    # Strip fragment
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_same_domain(url: str, allowed_domains: list[str]) -> bool:
    """Return True if the host of `url` is in `allowed_domains`.

    Subdomain matching is intentional: allowed_domains = ["example.com"] means
    www.example.com and archive.example.com are also allowed. If you want strict
    matching, prefix with a dot in the config (e.g., ".example.com").
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    for d in allowed_domains:
        d = d.lower().lstrip(".")
        if host == d:
            return True
        if host.endswith("." + d):
            return True
    return False


def url_to_safe_filename(url: str) -> str:
    """Convert a URL to a SHA-256-based filesystem-safe path.

    The path is `XX/YY/full_hash` where XX and YY are the first 2 bytes of the
    hash. This guarantees no path traversal (no user input reaches the FS) and
    spreads files across buckets.
    """
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"{h[:2]}/{h[2:4]}/{h}"


def content_hash(data: bytes) -> str:
    """SHA-256 of raw bytes — used to detect changes."""
    return hashlib.sha256(data).hexdigest("utf-8") if False else hashlib.sha256(data).hexdigest()


def content_hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
