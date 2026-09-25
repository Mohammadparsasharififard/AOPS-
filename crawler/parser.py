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
    # Phase 3 — full navigation discovery
    navbar_links: list[str] = field(default_factory=list)
    sidebar_links: list[str] = field(default_factory=list)
    breadcrumb_links: list[str] = field(default_factory=list)
    tab_links: list[str] = field(default_factory=list)
    pagination_links: list[str] = field(default_factory=list)
    next_link: Optional[str] = None
    prev_link: Optional[str] = None
    stylesheet_links: list[str] = field(default_factory=list)
    script_links: list[str] = field(default_factory=list)
    iframe_links: list[str] = field(default_factory=list)
    font_links: list[str] = field(default_factory=list)


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

    # Pre-extract script/style/stylesheet links BEFORE decomposing them
    script_links_pre: list[str] = []
    for script in soup.find_all("script", src=True):
        src = script["src"].strip()
        if src:
            absolute = urljoin(base_url, src)
            if absolute not in script_links_pre:
                script_links_pre.append(absolute)

    stylesheet_links_pre: list[str] = []
    for link in soup.find_all("link", rel=True):
        rel = link.get("rel", [])
        if isinstance(rel, list) and "stylesheet" in rel:
            href = link.get("href", "").strip()
            if href:
                absolute = urljoin(base_url, href)
                if absolute not in stylesheet_links_pre:
                    stylesheet_links_pre.append(absolute)

    iframe_links_pre: list[str] = []
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"].strip()
        if src and not src.startswith("data:"):
            absolute = urljoin(base_url, src)
            if absolute not in iframe_links_pre:
                iframe_links_pre.append(absolute)

    font_links_pre: list[str] = []
    for link in soup.find_all("link", attrs={"as": "font"}, href=True):
        absolute = urljoin(base_url, link["href"])
        if absolute not in font_links_pre:
            font_links_pre.append(absolute)

    # Text content — strip script/style/noscript for cleaner text extraction
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

    # === Phase 3: full navigation discovery (uses pre-extracted values
    #              where appropriate to avoid losing links after decompose) ===

    # Navbar links — typically <nav> or <header> <ul> structure
    navbar_links: list[str] = []
    for sel in ["nav", "header nav", ".navbar", "#navbar", ".main-nav"]:
        nav_el = soup.select_one(sel)
        if nav_el:
            for a in nav_el.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#"):
                    continue
                absolute = urljoin(base_url, href)
                if "#" in absolute:
                    absolute = absolute.split("#", 1)[0]
                if absolute and absolute not in navbar_links:
                    navbar_links.append(absolute)
            if navbar_links:
                break

    # Sidebar links — typically <aside> or .sidebar / .menu
    sidebar_links: list[str] = []
    for sel in ["aside", ".sidebar", "#sidebar", ".side-nav", "#side", ".menu"]:
        side_el = soup.select_one(sel)
        if side_el:
            for a in side_el.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#"):
                    continue
                absolute = urljoin(base_url, href)
                if "#" in absolute:
                    absolute = absolute.split("#", 1)[0]
                if absolute and absolute not in sidebar_links:
                    sidebar_links.append(absolute)
            if sidebar_links:
                break

    # Breadcrumb links — typically .breadcrumb / .breadcrumbs / nav.breadcrumb
    breadcrumb_links: list[str] = []
    for sel in [".breadcrumb", ".breadcrumbs", "nav.breadcrumb", "#breadcrumbs", ".breadcrumb-inner"]:
        bc_el = soup.select_one(sel)
        if bc_el:
            for a in bc_el.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#"):
                    continue
                absolute = urljoin(base_url, href)
                if "#" in absolute:
                    absolute = absolute.split("#", 1)[0]
                if absolute and absolute not in breadcrumb_links:
                    breadcrumb_links.append(absolute)
            if breadcrumb_links:
                break
    # MediaWiki categories as breadcrumbs
    if not breadcrumb_links:
        catlinks = soup.select(".mw-normal-catlinks a")
        for a in catlinks:
            href = a.get("href", "").strip()
            if href and not href.startswith("#"):
                absolute = urljoin(base_url, href)
                if absolute not in breadcrumb_links:
                    breadcrumb_links.append(absolute)

    # Tab links — MediaWiki vector-tabs, .nav-tabs, etc.
    tab_links: list[str] = []
    for sel in [".vector-tabs", ".nav-tabs", "#p-namespaces", ".tabs", ".mw-body-content .tabs"]:
        tabs_el = soup.select_one(sel)
        if tabs_el:
            for a in tabs_el.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#"):
                    continue
                absolute = urljoin(base_url, href)
                if "#" in absolute:
                    absolute = absolute.split("#", 1)[0]
                if absolute and absolute not in tab_links:
                    tab_links.append(absolute)
            if tab_links:
                break

    # Pagination — explicit pagination links
    pagination_links: list[str] = []
    for sel in ["a.next", 'a[rel="next"]', "a.prevnext", ".pagination a", ".pager a",
                "a.next-page", "a.prev-page", ".page-link"]:
        for a in soup.select(sel)[:10]:
            href = a.get("href", "").strip()
            if not href or href.startswith("#"):
                continue
            absolute = urljoin(base_url, href)
            if absolute not in pagination_links:
                pagination_links.append(absolute)
    # MediaWiki pagination patterns
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if "offset=" in href or "&limit=" in href or "page=" in href:
            absolute = urljoin(base_url, a["href"])
            if absolute not in pagination_links:
                pagination_links.append(absolute)

    # Next/Previous navigation
    next_link: Optional[str] = None
    prev_link: Optional[str] = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if not next_link and text in ("next", "next page", "→", ">"):
            next_link = urljoin(base_url, a["href"])
        elif not prev_link and text in ("previous", "prev", "previous page", "←", "<"):
            prev_link = urljoin(base_url, a["href"])
        # Also check rel attributes
        rel = a.get("rel", [])
        if isinstance(rel, list):
            if "next" in rel and not next_link:
                next_link = urljoin(base_url, a["href"])
            elif "prev" in rel and not prev_link:
                prev_link = urljoin(base_url, a["href"])
        if next_link and prev_link:
            break

    # Stylesheets / scripts / iframes / fonts — pre-extracted BEFORE
    # decompose() so we don't lose them
    stylesheet_links = stylesheet_links_pre
    script_links = script_links_pre
    iframe_links = iframe_links_pre
    font_links = font_links_pre

    return ParsedPage(
        title=title,
        text=text,
        html=str(soup),
        links=links,
        assets=assets,
        meta_description=meta_desc,
        language=lang,
        navbar_links=navbar_links,
        sidebar_links=sidebar_links,
        breadcrumb_links=breadcrumb_links,
        tab_links=tab_links,
        pagination_links=pagination_links,
        next_link=next_link,
        prev_link=prev_link,
        stylesheet_links=stylesheet_links,
        script_links=script_links,
        iframe_links=iframe_links,
        font_links=font_links,
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
