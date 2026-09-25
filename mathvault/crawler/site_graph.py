"""Site Graph service — manages typed relationships between archived resources.

The graph is the SEMANTIC LAYER on top of the storage layer (Page,
PageVersion, Asset). The crawler populates the graph as it discovers
and archives resources. The frontend uses the graph to render
hierarchical navigation (Contest → Year → Problem → Discussion → Posts).

Key methods:
- upsert_node: insert or update a SiteNode (by canonical source_url)
- upsert_edge: insert or update a typed edge between two nodes
- get_or_create_node: lookup by (node_type, source_url) — create if missing
- set_status: ARCHIVED / FAILED / BLOCKED / SKIPPED / NOT_VERIFIED
- map_local_url: record source → local URL mapping for offline nav
- get_local_url: lookup local URL by source URL (offline navigation)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from crawler.normalizer import canonicalize_url
from database.models import LocalUrlMapping, SiteEdge, SiteNode


logger = logging.getLogger(__name__)


# Valid status values for SiteNode.status
NODE_STATUSES = (
    "not_verified",   # discovered but not yet checked
    "discovered",     # URL seen in HTML but not fetched yet
    "archived",       # fetched + stored successfully
    "unchanged",      # fetched but content hash matches previous → no new version
    "failed",         # fetch error (network / timeout / parse)
    "blocked",        # access control (CAPTCHA / login / paywall / robots / 403 / 429)
    "skipped",        # explicitly out of scope per policy
)


class SiteGraph:
    """Operations on the site graph (SiteNode + SiteEdge + LocalUrlMapping)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Node operations ---------------------------------------------------

    def get_or_create_node(
        self,
        node_type: str,
        source_url: Optional[str] = None,
        name: Optional[str] = None,
        slug: Optional[str] = None,
        depth: Optional[int] = None,
    ) -> SiteNode:
        """Find or create a SiteNode by (node_type, canonical source_url).

        For synthetic nodes (e.g., 'domain' node), source_url may be None
        and lookup is by (node_type, slug) instead.
        """
        canonical = canonicalize_url(source_url) if source_url else None
        if canonical:
            node = self.db.execute(
                select(SiteNode).where(
                    SiteNode.node_type == node_type,
                    SiteNode.source_url == canonical,
                )
            ).scalar_one_or_none()
            if node is not None:
                # Update last_seen
                node.last_seen = datetime.now(timezone.utc)
                if name and not node.name:
                    node.name = name
                if slug and not node.slug:
                    node.slug = slug
                if depth is not None and node.depth is None:
                    node.depth = depth
                self.db.flush()
                return node
        elif slug:
            node = self.db.execute(
                select(SiteNode).where(
                    SiteNode.node_type == node_type,
                    SiteNode.slug == slug,
                )
            ).scalar_one_or_none()
            if node is not None:
                node.last_seen = datetime.now(timezone.utc)
                self.db.flush()
                return node

        # Create new
        node = SiteNode(
            node_type=node_type,
            source_url=canonical,
            name=name,
            slug=slug,
            depth=depth,
            status="discovered",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        self.db.add(node)
        self.db.flush()
        return node

    def set_node_status(
        self,
        node: SiteNode,
        status: str,
        local_url: Optional[str] = None,
    ) -> None:
        """Update a node's status. If status='archived', set last_archived."""
        if status not in NODE_STATUSES:
            raise ValueError(f"Invalid node status: {status}")
        node.status = status
        if status == "archived":
            node.last_archived = datetime.now(timezone.utc)
            if local_url:
                node.local_url = local_url
        self.db.flush()

    # --- Edge operations ---------------------------------------------------

    def upsert_edge(
        self,
        source_node: SiteNode,
        target_node: SiteNode,
        edge_type: str,
        weight: Optional[int] = None,
    ) -> Optional[SiteEdge]:
        """Insert or update a typed edge between two nodes.

        Idempotent: if the edge already exists, updates weight (if provided).
        """
        if source_node.id == target_node.id:
            return None  # no self-edges
        edge = self.db.execute(
            select(SiteEdge).where(
                SiteEdge.source_node_id == source_node.id,
                SiteEdge.target_node_id == target_node.id,
                SiteEdge.edge_type == edge_type,
            )
        ).scalar_one_or_none()
        if edge is not None:
            if weight is not None:
                edge.weight = weight
            self.db.flush()
            return edge
        edge = SiteEdge(
            source_node_id=source_node.id,
            target_node_id=target_node.id,
            edge_type=edge_type,
            weight=weight,
            discovered_at=datetime.now(timezone.utc),
        )
        self.db.add(edge)
        self.db.flush()
        return edge

    # --- Local URL mapping -------------------------------------------------

    def map_local_url(
        self,
        source_url: str,
        local_url: str,
        node_id: Optional[str] = None,
    ) -> None:
        """Record a source → local URL mapping for offline navigation."""
        canonical = canonicalize_url(source_url)
        mapping = self.db.execute(
            select(LocalUrlMapping).where(LocalUrlMapping.source_url == canonical)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if mapping is None:
            mapping = LocalUrlMapping(
                source_url=canonical,
                canonical_source_url=canonical,
                local_url=local_url,
                node_id=node_id,
                archived=True,
                last_updated=now,
            )
            self.db.add(mapping)
        else:
            mapping.local_url = local_url
            mapping.archived = True
            mapping.last_updated = now
            if node_id:
                mapping.node_id = node_id
        self.db.flush()

    def get_local_url(self, source_url: str) -> Optional[str]:
        """Lookup local URL by source URL (offline navigation).

        Returns None if the source URL was NOT archived — the frontend
        should then show 'This content is not available offline.'
        """
        canonical = canonicalize_url(source_url)
        mapping = self.db.execute(
            select(LocalUrlMapping).where(LocalUrlMapping.source_url == canonical)
        ).scalar_one_or_none()
        if mapping is None or not mapping.archived:
            return None
        return mapping.local_url

    def mark_not_archived(self, source_url: str) -> None:
        """Mark a source URL as discovered but NOT archived.

        Used when the crawler refuses to fetch (blocked, out of scope, etc.)
        so the offline navigator can show 'Not archived' instead of
        silently redirecting to the source site.
        """
        canonical = canonicalize_url(source_url)
        mapping = self.db.execute(
            select(LocalUrlMapping).where(LocalUrlMapping.source_url == canonical)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if mapping is None:
            mapping = LocalUrlMapping(
                source_url=canonical,
                canonical_source_url=canonical,
                local_url=None,
                archived=False,
                last_updated=now,
            )
            self.db.add(mapping)
        else:
            # Already mapped — don't downgrade if previously archived
            if not mapping.archived:
                mapping.last_updated = now
        self.db.flush()

    # --- Query helpers -----------------------------------------------------

    def children_of(self, parent_node: SiteNode, edge_type: str = "parent") -> list[SiteNode]:
        """Return child nodes of `parent_node` via `edge_type` edges.

        For 'parent' edges, returns ordered by weight (if set).
        """
        rows = self.db.execute(
            select(SiteNode, SiteEdge.weight)
            .join(SiteEdge, SiteEdge.target_node_id == SiteNode.id)
            .where(
                SiteEdge.source_node_id == parent_node.id,
                SiteEdge.edge_type == edge_type,
            )
            .order_by(SiteEdge.weight.nulls_last(), SiteNode.name)
        ).all()
        return [r[0] for r in rows]

    def parents_of(self, child_node: SiteNode, edge_type: str = "parent") -> list[SiteNode]:
        """Return parent nodes of `child_node` (reverse lookup)."""
        rows = self.db.execute(
            select(SiteNode)
            .join(SiteEdge, SiteEdge.source_node_id == SiteNode.id)
            .where(
                SiteEdge.target_node_id == child_node.id,
                SiteEdge.edge_type == edge_type,
            )
        ).scalars().all()
        return list(rows)

    def next_node(self, current: SiteNode) -> Optional[SiteNode]:
        """Return the 'next' node in pagination order, if any."""
        row = self.db.execute(
            select(SiteNode)
            .join(SiteEdge, SiteEdge.target_node_id == SiteNode.id)
            .where(
                SiteEdge.source_node_id == current.id,
                SiteEdge.edge_type == "next",
            )
            .limit(1)
        ).scalar_one_or_none()
        return row

    def prev_node(self, current: SiteNode) -> Optional[SiteNode]:
        """Return the 'previous' node in pagination order, if any."""
        row = self.db.execute(
            select(SiteNode)
            .join(SiteEdge, SiteEdge.target_node_id == SiteNode.id)
            .where(
                SiteEdge.source_node_id == current.id,
                SiteEdge.edge_type == "prev",
            )
            .limit(1)
        ).scalar_one_or_none()
        return row

    def related_nodes(self, current: SiteNode, edge_type: str = "related") -> list[SiteNode]:
        """Return nodes related to `current` via `edge_type` edges."""
        rows = self.db.execute(
            select(SiteNode)
            .join(SiteEdge, SiteEdge.target_node_id == SiteNode.id)
            .where(
                SiteEdge.source_node_id == current.id,
                SiteEdge.edge_type == edge_type,
            )
        ).scalars().all()
        return list(rows)

    # --- Status counts (for dashboard) -------------------------------------

    def status_counts(self) -> dict[str, int]:
        """Return counts of nodes by status. Used by the dashboard."""
        from sqlalchemy import func
        rows = self.db.execute(
            select(SiteNode.status, func.count(SiteNode.id))
            .group_by(SiteNode.status)
        ).all()
        return {s: c for s, c in rows}

    def node_type_counts(self) -> dict[str, int]:
        """Return counts of nodes by type. Used by the dashboard."""
        from sqlalchemy import func
        rows = self.db.execute(
            select(SiteNode.node_type, func.count(SiteNode.id))
            .group_by(SiteNode.node_type)
        ).all()
        return {t: c for t, c in rows}
