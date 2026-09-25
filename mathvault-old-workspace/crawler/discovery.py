"""URL frontier + BFS/DFS discovery.

The frontier is the crawler's work queue. URLs are added when discovered, and
popped in FIFO (BFS) or LIFO (DFS) order based on config.

Allowlist is enforced here too — even links extracted from an allowed page
are filtered before enqueue.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from crawler.fetcher import AllowList
from crawler.normalizer import canonicalize_url

logger = logging.getLogger(__name__)


@dataclass
class FrontierEntry:
    url: str
    depth: int
    parent_url: Optional[str] = None


class Frontier:
    """In-memory URL frontier with canonicalization + dedupe + allowlist.

    For large crawls (>100k URLs), swap this for a SQLite-backed queue. The
    interface is kept minimal to allow that swap.
    """

    def __init__(
        self,
        allowlist: AllowList,
        max_depth: int,
        max_pages: int,
        mode: str = "bfs",
    ) -> None:
        self.allowlist = allowlist
        self.max_depth = max_depth
        self.max_pages = max_pages
        self._seen: set[str] = set()
        self._deque: deque[FrontierEntry] = deque()
        self.mode = mode  # "bfs" | "dfs"

    def add(self, url: str, depth: int = 0, parent_url: Optional[str] = None) -> bool:
        """Enqueue a URL if it passes all checks.

        Returns True if added (newly discovered), False otherwise.
        """
        if depth > self.max_depth:
            return False
        if not self.allowlist.is_allowed(url):
            return False
        canon = canonicalize_url(url)
        if canon in self._seen:
            return False
        self._seen.add(canon)
        entry = FrontierEntry(url=canon, depth=depth, parent_url=parent_url)
        if self.mode == "dfs":
            self._deque.append(entry)
        else:
            self._deque.append(entry)
        return True

    def pop(self) -> Optional[FrontierEntry]:
        if not self._deque:
            return None
        if self.mode == "dfs":
            return self._deque.pop()
        return self._deque.popleft()

    def __len__(self) -> int:
        return len(self._deque)

    def empty(self) -> bool:
        return len(self._deque) == 0

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    def has_seen(self, url: str) -> bool:
        return canonicalize_url(url) in self._seen

    def mark_seen(self, url: str) -> None:
        self._seen.add(canonicalize_url(url))


def discover_links(
    source_url: str,
    raw_links: list[str],
    allowlist: AllowList,
    frontier: Frontier,
    current_depth: int,
    max_pages_reached: bool = False,
) -> int:
    """Process discovered links: canonicalize, filter, enqueue.

    Returns the count of newly-added URLs.
    """
    if max_pages_reached:
        return 0
    added = 0
    for raw in raw_links:
        canon = canonicalize_url(raw, base_url=source_url)
        if frontier.add(canon, depth=current_depth + 1, parent_url=source_url):
            added += 1
    return added
