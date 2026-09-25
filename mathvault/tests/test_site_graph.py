"""Tests for SiteGraph service + new CLI commands + failure semantics."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
os.environ.setdefault("MATHVAULT_SKIP_ALLOWLIST_CHECK", "1")
os.environ.setdefault("ARCHIVE_ALLOWED_DOMAINS", "example.com")
os.environ.setdefault("ARCHIVE_ALLOWED_PATH_PREFIXES", "/contests/")
os.environ.setdefault("ARCHIVE_START_URLS", "https://example.com/contests/")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test.db")
os.environ.setdefault("DB_ENGINE", "sqlite")

sys.path.insert(0, str(PROJECT_ROOT))

import shutil


def _reset_modules():
    """Clean DB + reset module state."""
    for p in [PROJECT_ROOT / "data", PROJECT_ROOT / "archive", PROJECT_ROOT / "logs"]:
        if p.exists():
            shutil.rmtree(p)
    for m in list(sys.modules):
        if m.startswith(("database", "config", "crawler", "api")):
            del sys.modules[m]
    for k in list(os.environ):
        if k.startswith(("DATABASE_URL", "MASTER_PASSWORD", "ARCHIVE_", "MATHVAULT_")):
            del os.environ[k]
    os.environ["MATHVAULT_SKIP_ALLOWLIST_CHECK"] = "1"
    os.environ["ARCHIVE_ALLOWED_DOMAINS"] = "example.com"
    os.environ["ARCHIVE_ALLOWED_PATH_PREFIXES"] = "/contests/"
    os.environ["ARCHIVE_START_URLS"] = "https://example.com/contests/"
    os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
    os.environ["DB_ENGINE"] = "sqlite"
    os.chdir(PROJECT_ROOT)
    from config import get_settings
    get_settings.cache_clear()
    import database.session as sess_mod
    sess_mod._engine = None
    sess_mod._SessionLocal = None
    from database.session import init_db
    init_db()


def test_site_node_creation_and_status():
    """SiteNode can be created with status='discovered' (default)."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph, NODE_STATUSES
    import database.models

    with database.session.session_scope() as db:
        graph = SiteGraph(db)
        node = graph.get_or_create_node(
            node_type="page",
            source_url="https://example.com/contests/2024/p1",
            name="Problem 1",
        )
        assert node.id is not None
        assert node.node_type == "page"
        assert node.status == "discovered"
        assert node.source_url == "https://example.com/contests/2024/p1"


def test_site_node_dedup_by_canonical_url():
    """get_or_create_node deduplicates by canonical URL."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph
    from database.models import SiteNode
    from sqlalchemy import select, func

    with database.session.session_scope() as db:
        graph = SiteGraph(db)
        # Create with trailing slash
        n1 = graph.get_or_create_node(
            node_type="page",
            source_url="https://example.com/contests/p1/",
        )
        # Same URL without trailing slash → should return same node
        n2 = graph.get_or_create_node(
            node_type="page",
            source_url="https://example.com/contests/p1",
        )
        assert n1.id == n2.id, "Same canonical URL should return same node"
        # Count nodes in DB
        count = db.execute(select(func.count(SiteNode.id))).scalar()
        assert count == 1


def test_site_node_status_transitions():
    """Status can transition: discovered → archived → unchanged."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph, NODE_STATUSES

    with database.session.session_scope() as db:
        graph = SiteGraph(db)
        node = graph.get_or_create_node(
            node_type="page",
            source_url="https://example.com/p1",
        )
        # Initial
        assert node.status == "discovered"

        # Set to archived
        graph.set_node_status(node, "archived", local_url="/archive/p1")
        assert node.status == "archived"
        assert node.local_url == "/archive/p1"
        assert node.last_archived is not None

        # Set to unchanged (after second fetch)
        graph.set_node_status(node, "unchanged")
        assert node.status == "unchanged"

        # Invalid status raises
        try:
            graph.set_node_status(node, "invalid_status")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


def test_all_failure_semantics_statuses():
    """All status values from NODE_STATUSES are valid (failure semantics)."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph, NODE_STATUSES

    expected = {"not_verified", "discovered", "archived", "unchanged",
                "failed", "blocked", "skipped"}
    assert set(NODE_STATUSES) == expected, f"Got: {set(NODE_STATUSES)}"

    with database.session.session_scope() as db:
        graph = SiteGraph(db)
        # Each status should be assignable
        for status in NODE_STATUSES:
            node = graph.get_or_create_node(
                node_type="page",
                source_url=f"https://example.com/test/{status}",
            )
            graph.set_node_status(node, status)
            assert node.status == status


def test_site_edge_creation():
    """Typed edges between nodes work + are idempotent."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph
    from database.models import SiteEdge
    from sqlalchemy import select, func

    with database.session.session_scope() as db:
        graph = SiteGraph(db)
        parent = graph.get_or_create_node(
            node_type="contest",
            source_url="https://example.com/contests/imo",
        )
        child = graph.get_or_create_node(
            node_type="year",
            source_url="https://example.com/contests/imo/2024",
        )

        # Create parent → child edge
        edge1 = graph.upsert_edge(parent, child, "parent", weight=1)
        assert edge1 is not None
        assert edge1.edge_type == "parent"

        # Idempotent — same edge shouldn't duplicate
        edge2 = graph.upsert_edge(parent, child, "parent", weight=2)
        assert edge2.id == edge1.id, "Same edge should be reused"
        assert edge2.weight == 2, "Weight should be updated"

        # Count edges
        count = db.execute(select(func.count(SiteEdge.id))).scalar()
        assert count == 1


def test_local_url_mapping():
    """map_local_url + get_local_url work for offline navigation."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph

    with database.session.session_scope() as db:
        graph = SiteGraph(db)

        # Map a URL
        graph.map_local_url(
            source_url="https://example.com/contests/p1",
            local_url="/archive/contests/p1",
        )

        # Lookup
        result = graph.get_local_url("https://example.com/contests/p1")
        assert result == "/archive/contests/p1"

        # Same URL with different canonical form
        result = graph.get_local_url("https://example.com/contests/p1/")
        assert result == "/archive/contests/p1"

        # Unmapped URL returns None
        result = graph.get_local_url("https://example.com/other")
        assert result is None


def test_mark_not_archived():
    """mark_not_archived marks a URL as discovered but NOT archived."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph

    with database.session.session_scope() as db:
        graph = SiteGraph(db)

        # Mark a URL as not archived
        graph.mark_not_archived("https://example.com/blocked")

        # Lookup returns None (not archived)
        result = graph.get_local_url("https://example.com/blocked")
        assert result is None

        # But the mapping exists in the DB (with archived=False)
        from database.models import LocalUrlMapping
        from sqlalchemy import select
        mapping = db.execute(
            select(LocalUrlMapping).where(LocalUrlMapping.source_url == "https://example.com/blocked")
        ).scalar_one_or_none()
        assert mapping is not None
        assert mapping.archived is False


def test_graph_traversal_children_parents():
    """children_of and parents_of traverse the graph correctly."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph

    with database.session.session_scope() as db:
        graph = SiteGraph(db)

        # Build a small graph: contest → year → problem
        contest = graph.get_or_create_node(
            node_type="contest", source_url="https://example.com/c1")
        year = graph.get_or_create_node(
            node_type="year", source_url="https://example.com/c1/2024")
        problem = graph.get_or_create_node(
            node_type="problem", source_url="https://example.com/c1/2024/p1")

        graph.upsert_edge(contest, year, "parent")
        graph.upsert_edge(year, problem, "parent")

        # Children of contest
        children = graph.children_of(contest)
        assert len(children) == 1
        assert children[0].id == year.id

        # Parents of problem
        parents = graph.parents_of(problem)
        assert len(parents) == 1
        assert parents[0].id == year.id


def test_status_counts_for_dashboard():
    """status_counts returns counts by status."""
    _reset_modules()
    import database.session
    from crawler.site_graph import SiteGraph

    with database.session.session_scope() as db:
        graph = SiteGraph(db)

        # Create some nodes with different statuses
        n1 = graph.get_or_create_node(node_type="page", source_url="https://example.com/p1")
        graph.set_node_status(n1, "archived")

        n2 = graph.get_or_create_node(node_type="page", source_url="https://example.com/p2")
        graph.set_node_status(n2, "archived")

        n3 = graph.get_or_create_node(node_type="page", source_url="https://example.com/p3")
        graph.set_node_status(n3, "blocked")

        n4 = graph.get_or_create_node(node_type="page", source_url="https://example.com/p4")
        # n4 stays 'discovered'

        counts = graph.status_counts()
        assert counts.get("archived") == 2
        assert counts.get("blocked") == 1
        assert counts.get("discovered") == 1


def test_parser_extracts_nav_features():
    """Parser extracts navbar/sidebar/breadcrumb/pagination links."""
    _reset_modules()
    from crawler.parser import parse_html

    html = """
    <html><head><title>Test Page</title>
    <link rel="stylesheet" href="/style.css">
    <script src="/script.js"></script>
    </head><body>
    <nav class="navbar"><a href="/home">Home</a><a href="/about">About</a></nav>
    <aside class="sidebar"><a href="/side1">Side1</a></aside>
    <nav class="breadcrumb"><a href="/bc1">BC1</a><a href="/bc2">BC2</a></nav>
    <div class="pagination"><a href="/page1">1</a><a href="/page2">Next</a></div>
    <main>Content</main>
    <a href="/next-page" rel="next">Next</a>
    <a href="/prev-page" rel="prev">Previous</a>
    </body></html>
    """
    p = parse_html(html, "https://example.com/page")
    assert p.title == "Test Page"
    # Navbar
    assert len(p.navbar_links) >= 1
    assert "/home" in " ".join(p.navbar_links)
    # Sidebar
    assert len(p.sidebar_links) >= 1
    # Breadcrumbs
    assert len(p.breadcrumb_links) >= 1
    # Pagination
    assert len(p.pagination_links) >= 1
    # Next/Prev
    assert p.next_link is not None
    assert p.prev_link is not None
    # Stylesheets
    assert len(p.stylesheet_links) >= 1
    # Scripts
    assert len(p.script_links) >= 1


def test_cli_validate_archive_runs():
    """`mathvault validate-archive` runs without crashing on empty archive."""
    _reset_modules()
    from click.testing import CliRunner
    from cli.mathvault import cli as cli_obj
    runner = CliRunner()
    r = runner.invoke(cli_obj, ["validate-archive"])
    assert r.exit_code == 0, f"validate-archive failed: {r.output}"


def test_cli_offline_test_runs():
    """`mathvault offline-test` runs (with no pages, reports cannot run)."""
    _reset_modules()
    from click.testing import CliRunner
    from cli.mathvault import cli as cli_obj
    runner = CliRunner()
    r = runner.invoke(cli_obj, ["offline-test"])
    assert r.exit_code == 0, f"offline-test failed: {r.output}"
    # Should mention "No archived pages" since DB is empty
    assert "No archived pages" in r.output or "PASS" in r.output


def test_cli_coverage_runs():
    """`mathvault coverage` runs without crashing."""
    _reset_modules()
    from click.testing import CliRunner
    from cli.mathvault import cli as cli_obj
    runner = CliRunner()
    r = runner.invoke(cli_obj, ["coverage"])
    assert r.exit_code == 0, f"coverage failed: {r.output}"


if __name__ == "__main__":
    _reset_modules()
    tests = [
        test_site_node_creation_and_status,
        test_site_node_dedup_by_canonical_url,
        test_site_node_status_transitions,
        test_all_failure_semantics_statuses,
        test_site_edge_creation,
        test_local_url_mapping,
        test_mark_not_archived,
        test_graph_traversal_children_parents,
        test_status_counts_for_dashboard,
        test_parser_extracts_nav_features,
        test_cli_validate_archive_runs,
        test_cli_offline_test_runs,
        test_cli_coverage_runs,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
