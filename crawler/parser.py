"""HTML parser.

Extracts:
- Discovered links (for navigation following)
- Page text content (for search indexing)
- Embedded assets (images, PDFs) for download
- Optional structured data via configured selectors

This parser is GENERIC — no domain-specific knowledge. Selectors are loaded
from a YAML config (see `selectors.example.yaml`).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class ParsedPage:
    title: Optional[str]
    text: str
    html: str
    links: list[str] = field(default_factory=list)  # absolute URLs
    assets: list[str] = field(default_factory=list)  # absolute asset URLs (img, a[href=.pdf])
    meta_description: Optional[str] = None
    language: Optional[str] = None


_BLOCK_TAGS = (
    "p", "div", "section", "article", "li", "td", "th", "h1", "h2", "h3",
    "h4", "h5", "h6", "pre", "blockquote", "dt", "dd", "tr", "header", "footer",
)


def parse_html(html: str, base_url: str) -> ParsedPage:
    """Parse HTML and extract text + links.

    The HTML returned in ParsedPage is the SANITIZED HTML (after bleach clean
    in storage layer). Here we return the raw HTML; sanitization happens at
    storage time so we keep the parser pure.
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    if title and len(title) > 500:
        title = title[:500]

    # Meta description
    meta_desc = None
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    # Language
    lang = soup.html.get("lang") if soup.html else None

    # Text content — strip script/style/nav/header for cleaner extraction
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Extract text in a sensible order
    text_parts: list[str] = []
    for el in soup.find_all(_BLOCK_TAGS):
        # Skip if descendant of another already-collected block? We just join
        # and dedupe later — perf is acceptable.
        t = el.get_text(separator=" ", strip=True)
        if t:
            text_parts.append(t)

    # Dedupe while preserving order
    seen: set[str] = set()
    text_dedupe: list[str] = []
    for t in text_parts:
        if t not in seen:
            seen.add(t)
            text_dedupe.append(t)
    text = "\n".join(text_dedupe)

    # Limit body text size (10MB sanity cap)
    if len(text) > 10 * 1024 * 1024:
        text = text[: 10 * 1024 * 1024]

    # Links — every <a href>
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith(("mailto:", "javascript:", "tel:", "data:")):
            continue
        absolute = urljoin(base_url, href)
        # Drop fragment
        if "#" in absolute:
            absolute = absolute.split("#", 1)[0]
        if absolute and absolute not in links:
            links.append(absolute)

    # Assets — images + downloadable files
    assets: list[str] = []
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if not src or src.startswith("data:"):
            continue
        assets.append(urljoin(base_url, src))
    # PDF / downloadable links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip().lower()
        if href.endswith((".pdf", ".zip", ".epub", ".doc", ".docx", ".tex", ".png", ".jpg", ".jpeg", ".gif")):
            full = urljoin(base_url, a["href"].strip())
            if full not in assets:
                assets.append(full)

    return ParsedPage(
        title=title,
        text=text,
        html=str(soup),
        links=links,
        assets=assets,
        meta_description=meta_desc,
        language=lang,
    )


def extract_main_content(html: str) -> str:
    """Heuristic extraction of main content area.

    Tries <main>, <article>, then #content / .content / #main / .main. Returns
    the HTML of the matched element, or the full body as fallback.
    """
    soup = BeautifulSoup(html, "lxml")
    for selector in ["main", "article", "#content", ".content", "#main", ".main", "#primary"]:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 100:
            return str(el)
    body = soup.body or soup
    return str(body)


def is_html_content_type(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    ct = content_type.lower().split(";")[0].strip()
    return ct in ("text/html", "application/xhtml+xml")


_TAG_PATTERN = re.compile(r"\b(algebra|geometry|number theory|combinatorics|inequalities?"
                          r"|calculus|trigonometry|polynomials|sequences|probabil)"
                          r"[a-z]*\b", re.IGNORECASE)


def detect_tags(text: str) -> list[str]:
    """Heuristic tag detection. Used when source site has no machine-readable tags."""
    if not text:
        return []
    found = set()
    for m in _TAG_PATTERN.finditer(text):
        found.add(m.group(1).lower())
    return sorted(found)
