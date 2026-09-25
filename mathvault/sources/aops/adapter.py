"""AoPS source adapter — MediaWiki parser, NOT a bypass mechanism.

This module parses AoPS Wiki HTML structure (which is a standard MediaWiki
installation) into MathVault's semantic schema:
    Contest → Year → Problem → Discussion / Solution / Asset

CRITICAL: This adapter is a PARSER ONLY. It does NOT:
- Bypass any access control
- Use browser automation directly
- Make any HTTP request
- Solve CAPTCHA or Cloudflare challenges
- Stash or share cf_clearance cookies

The fetcher layer (HttpFetcher or AuthorizedBrowserFetcher) handles HTTP
requests. The adapter only inspects HTML that has already been legitimately
fetched.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class AoPSContestInfo:
    """Information extracted from an AoPS Wiki contest index page."""
    name: str
    slug: str
    category_chain: list[str]  # MediaWiki category breadcrumbs
    year_page_urls: list[str]
    is_international: bool
    country: Optional[str] = None


@dataclass
class AoPSYearInfo:
    """Information extracted from an AoPS Wiki year page."""
    contest_name: str
    year: int
    round: Optional[str]
    problem_urls: list[str]
    solution_urls: list[str]
    resource_urls: list[str]


@dataclass
class AoPSProblemInfo:
    """Information extracted from an AoPS Wiki individual problem page."""
    contest_name: str
    year: int
    problem_number: Optional[str]
    statement_html: str
    statement_text: str
    image_urls: list[str]
    solution_url: Optional[str]
    discussion_url: Optional[str]


# Patterns that indicate an international competition
INTERNATIONAL_NAMES = {"IMO", "IPhO", "IChO", "IBO", "IOI", "EGMO", "RMM", "APMOS"}
# Patterns that indicate a national competition
NATIONAL_PREFIXES = ("AMC", "AIME", "USAMO", "USA TST", "BMO", "CMO", "JMO", "MOP")


def parse_contest_index(html: str, base_url: str) -> AoPSContestInfo:
    """Parse a contest index page (e.g., /wiki/index.php/AMC_Problems_and_Solutions).

    Extracts:
    - Contest name (from <h1> or <title>)
    - MediaWiki category chain (breadcrumbs)
    - List of year page URLs (links like /wiki/index.php/2024_AMC_10A_Problems)
    - International vs. national classification
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
    name = ""
    if soup.find("h1", attrs={"id": "firstHeading"}):
        name = soup.find("h1", attrs={"id": "firstHeading"}).get_text(strip=True)
    elif soup.title:
        name = soup.title.string.strip()
    # Strip " - AoPS Wiki" suffix
    name = re.sub(r"\s*-\s*AoPS\s*Wiki\s*$", "", name)

    # Category chain (MediaWiki breadcrumbs)
    category_chain: list[str] = []
    catlinks = soup.select(".mw-normal-catlinks a")
    if catlinks:
        for a in catlinks:
            category_chain.append(a.get_text(strip=True))

    # Year page URLs — typically pattern /wiki/index.php/YYYY_<Contest>_*_Problems
    year_pattern = re.compile(r"/wiki/index\.php/(\d{4})_", re.IGNORECASE)
    year_urls: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if year_pattern.search(href):
            absolute = urljoin(base_url, href)
            if absolute not in seen:
                seen.add(absolute)
                year_urls.append(absolute)

    # International vs. national
    name_upper = name.upper()
    is_international = any(intl in name_upper for intl in INTERNATIONAL_NAMES)
    country = None
    if not is_international:
        # Try to infer country from name (rough heuristic — not authoritative)
        if name_upper.startswith(("AMC", "AIME", "USAMO", "USA")):
            country = "USA"
        elif name_upper.startswith("BMO"):
            country = "UK"

    # Slug — last path segment
    slug = base_url.rstrip("/").rsplit("/", 1)[-1] if base_url else name

    return AoPSContestInfo(
        name=name,
        slug=slug,
        category_chain=category_chain,
        year_page_urls=year_urls,
        is_international=is_international,
        country=country,
    )


def parse_year_page(html: str, base_url: str) -> AoPSYearInfo:
    """Parse a year page (e.g., /wiki/index.php/2024_AMC_10A_Problems).

    Extracts:
    - Contest name + year
    - Problem URLs (Problem 1, Problem 2, ...)
    - Solution URLs (if linked)
    - Resource URLs (PDFs, images)
    """
    soup = BeautifulSoup(html, "lxml")

    # Title — pattern: "2024 AMC 10A Problems" or similar
    title = ""
    if soup.find("h1", attrs={"id": "firstHeading"}):
        title = soup.find("h1", attrs={"id": "firstHeading"}).get_text(strip=True)
    elif soup.title:
        title = soup.title.string.strip()

    # Extract year + contest name
    year_match = re.search(r"(\d{4})", title)
    year = int(year_match.group(1)) if year_match else 0
    # Strip year and "Problems"/"Solutions" suffix
    contest_name = re.sub(r"^\d{4}\s*", "", title)
    contest_name = re.sub(r"\s+(Problems?|Solutions?)\s*$", "", contest_name, flags=re.IGNORECASE)
    # Extract round (e.g., "AMC 10A" → round "A")
    round_match = re.search(r"\b([AB])\b\s*(?:Problems?|Solutions?)?$", contest_name)
    round_name = round_match.group(1) if round_match else None

    # Problem URLs — links like /Problem_1, /Problem_2, ...
    problem_pattern = re.compile(r"/Problem_\d+", re.IGNORECASE)
    solution_pattern = re.compile(r"/Solutions?(?:_and_Solutions)?$", re.IGNORECASE)
    resource_pattern = re.compile(r"\.(?:pdf|png|jpg|jpeg|gif|svg)$", re.IGNORECASE)

    problem_urls: list[str] = []
    solution_urls: list[str] = []
    resource_urls: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        if problem_pattern.search(href):
            problem_urls.append(absolute)
        elif solution_pattern.search(href):
            solution_urls.append(absolute)
        elif resource_pattern.search(href):
            resource_urls.append(absolute)

    return AoPSYearInfo(
        contest_name=contest_name,
        year=year,
        round=round_name,
        problem_urls=problem_urls,
        solution_urls=solution_urls,
        resource_urls=resource_urls,
    )


def parse_problem_page(html: str, base_url: str) -> AoPSProblemInfo:
    """Parse an individual problem page.

    Extracts:
    - Contest + year + problem number (from title or h1)
    - Problem statement HTML + plain text
    - Image URLs embedded in the statement
    - Solution URL (if linked)
    - Discussion URL (if linked — usually null in AoPS Wiki)
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
    title = ""
    if soup.find("h1", attrs={"id": "firstHeading"}):
        title = soup.find("h1", attrs={"id": "firstHeading"}).get_text(strip=True)

    # Parse: "2024 AMC 10A Problems/Problem 1"
    contest_name = ""
    year = 0
    problem_number = None
    year_match = re.search(r"(\d{4})", title)
    if year_match:
        year = int(year_match.group(1))
    # Extract problem number
    pnum_match = re.search(r"Problem\s+(\d+)", title, re.IGNORECASE)
    if pnum_match:
        problem_number = pnum_match.group(1)
    # Contest name — strip year + "/Problem N"
    contest_name = re.sub(r"^\d{4}\s*", "", title)
    contest_name = re.sub(r"\s*/\s*Problem\s+\d+.*$", "", contest_name, flags=re.IGNORECASE)
    contest_name = re.sub(r"\s+Problems?\s*$", "", contest_name, flags=re.IGNORECASE)

    # Problem statement — MediaWiki content is in #mw-content-text
    statement_el = soup.find("div", attrs={"id": "mw-content-text"}) or soup.find("div", class_="mw-parser-output")
    statement_html = ""
    statement_text = ""
    image_urls: list[str] = []
    if statement_el:
        statement_html = str(statement_el)
        statement_text = statement_el.get_text(separator=" ", strip=True)
        for img in statement_el.find_all("img", src=True):
            image_urls.append(urljoin(base_url, img["src"]))

    # Solution URL — usually "/Solutions" link
    solution_url = None
    for a in soup.find_all("a", href=True):
        if re.search(r"/Solutions?", a["href"], re.IGNORECASE):
            solution_url = urljoin(base_url, a["href"])
            break

    # Discussion URL — AoPS Wiki doesn't usually have these; AoPS Community does
    # (but that's outside the authorized scope unless explicitly allowed)
    discussion_url = None

    return AoPSProblemInfo(
        contest_name=contest_name,
        year=year,
        problem_number=problem_number,
        statement_html=statement_html,
        statement_text=statement_text,
        image_urls=image_urls,
        solution_url=solution_url,
        discussion_url=discussion_url,
    )
