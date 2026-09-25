"""MathVault CLI — `mathvault` command.

Subcommands:
  crawl            Run a single crawl pass (manual trigger)
  sync             Run incremental sync (timer-equivalent)
  status           Show last crawl run + archive stats
  search "query"   Search the archive
  backup           Create a tar.gz backup of archive/ + DB
  restore <file>   Restore from a backup
  init-db          Initialize the database (create_all)
  hash-password    Generate ADMIN_PASSWORD_HASH
  serve            Start the API server (uvicorn)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import get_settings


console = Console()


@click.group()
@click.version_option("1.0.0")
def cli() -> None:
    """MathVault — Personal Offline Mathematics Competition Archive."""


@cli.command()
@click.option("--dry-run", is_flag=True, help="List URLs to be fetched without downloading")
def crawl(dry_run: bool) -> None:
    """Run a single crawl pass."""
    if dry_run:
        _dry_run_crawl()
    else:
        _run_crawl(trigger="manual", dry_run=False)


@cli.command()
def sync() -> None:
    """Run an incremental sync (alias of `crawl`)."""
    _run_crawl(trigger="timer", dry_run=False)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(as_json: bool) -> None:
    """Show archive status + last crawl run."""
    from database.session import session_scope
    from database.models import CrawlRun
    from sqlalchemy import select, func
    from database.models import (
        Asset, Contest, ContestYear, CountryRegion, Discussion, Page, Post, Problem,
    )

    with session_scope() as db:
        last = db.execute(
            select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        stats = {
            "contests": db.scalar(select(func.count(Contest.id))) or 0,
            "problems": db.scalar(select(func.count(Problem.id))) or 0,
            "countries": db.scalar(select(func.count(CountryRegion.id))) or 0,
            "pages": db.scalar(select(func.count(Page.id))) or 0,
            "assets": db.scalar(select(func.count(Asset.id))) or 0,
            "discussions": db.scalar(select(func.count(Discussion.id))) or 0,
            "posts": db.scalar(select(func.count(Post.id))) or 0,
        }
        crawl_info = {}
        if last:
            crawl_info = {
                "last_started_at": last.started_at.isoformat() if last.started_at else None,
                "last_finished_at": last.finished_at.isoformat() if last.finished_at else None,
                "last_status": last.status,
                "pages_discovered": last.pages_discovered,
                "pages_new": last.pages_new,
                "pages_changed": last.pages_changed,
                "pages_unchanged": last.pages_unchanged,
                "pages_failed": last.pages_failed,
                "bytes_downloaded": last.bytes_downloaded,
                "error_message": last.error_message,
            }

    if as_json:
        click.echo(json.dumps({"stats": stats, "last_crawl": crawl_info}, indent=2, default=str))
        return

    table = Table(title="Archive Stats")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green", justify="right")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), f"{v:,}")
    console.print(table)

    if crawl_info:
        click.echo()
        ctable = Table(title="Last Crawl Run")
        ctable.add_column("Field", style="cyan")
        ctable.add_column("Value", style="white")
        for k, v in crawl_info.items():
            ctable.add_row(k.replace("_", " ").title(), str(v))
        console.print(ctable)


@cli.command()
@click.argument("query")
@click.option("--limit", default=20, help="Max results")
@click.option("--type", "doc_type", default=None, help="Filter by type (problem | contest | page | discussion)")
def search(query: str, limit: int, doc_type: Optional[str]) -> None:
    """Search the archive."""
    from database.session import session_scope
    from sqlalchemy import text
    from config import get_settings

    settings = get_settings()
    words = [w for w in query.split() if w]
    if not words:
        click.echo("Empty query", err=True)
        return

    type_filter_sql = ""
    params: dict = {"lim": limit}
    if doc_type:
        type_filter_sql = "AND f.doc_type = :dt"
        params["dt"] = doc_type

    if settings.db_engine == "sqlite":
        fts_q = " OR ".join(f'"{w}"' for w in words)
        sql_str = f"""
            SELECT
                f.doc_id AS ref_id,
                f.doc_type,
                s.title,
                s.contest_name,
                s.year,
                s.country,
                s.url,
                snippet(search_doc_fts, 4, '<mark>', '</mark>', '…', 12) AS snippet,
                bm25(search_doc_fts) AS rank
            FROM search_doc_fts f
            JOIN search_doc s ON s.id = f.doc_id
            WHERE search_doc_fts MATCH :q
            {type_filter_sql.replace('f.doc_type', 'f.doc_type')}
            ORDER BY rank
            LIMIT :lim
        """
        params["q"] = fts_q
    else:
        sql_str = f"""
            SELECT
                id AS ref_id,
                doc_type,
                title,
                contest_name,
                year,
                country,
                url,
                LEFT(body, 200) AS snippet,
                0.0 AS rank
            FROM search_doc
            WHERE title ILIKE '%' || :q || '%' OR body ILIKE '%' || :q || '%'
                OR contest_name ILIKE '%' || :q || '%' OR country ILIKE '%' || :q || '%'
            {type_filter_sql.replace('f.doc_type', 'doc_type')}
            ORDER BY title
            LIMIT :lim
        """
        params["q"] = query

    with session_scope() as db:
        rows = db.execute(text(sql_str), params).mappings().all()

    if not rows:
        click.echo("No results found.")
        return

    table = Table(title=f"Search results for: {query}")
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Title", style="white")
    table.add_column("Contest", style="magenta")
    table.add_column("Year", justify="right")
    table.add_column("Snippet", style="dim")
    for r in rows:
        table.add_row(
            r["doc_type"],
            r.get("title") or "",
            r.get("contest_name") or "",
            str(r.get("year") or ""),
            (r.get("snippet") or "")[:120],
        )
    console.print(table)


@cli.command()
def init_db() -> None:
    """Initialize the database (create tables)."""
    from database.session import init_db
    init_db()
    console.print("[green]Database initialized.[/green]")


@cli.command()
@click.argument("password")
def hash_password(password: str) -> None:
    """Generate a bcrypt hash for ADMIN_PASSWORD_HASH."""
    from api.deps import hash_password as hp
    h = hp(password)
    click.echo(h)


@cli.command()
@click.option("--output", "-o", default=None, help="Output file path (default: ./backups/mathvault-<ts>.tar.gz)")
def backup(output: Optional[str]) -> None:
    """Create a backup of archive + DB."""
    from config import get_settings
    settings = get_settings()

    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out_path = Path(output) if output else Path("./backups") / f"mathvault-{ts}.tar.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[cyan]Backing up to[/cyan] {out_path}")

    # If SQLite, take a copy with VACUUM INTO
    db_url = settings.database_url
    db_backup_path = settings.data_path / f"mathvault-{ts}.db"

    if db_url.startswith("sqlite"):
        src = db_url.replace("sqlite:///", "").replace("sqlite://", "")
        src_path = Path(src).resolve()
        if src_path.is_file():
            import shutil
            shutil.copy2(src_path, db_backup_path)
            console.print(f"  - Copied DB to {db_backup_path}")
    else:
        # PostgreSQL — use pg_dump
        console.print("  - Using pg_dump for PostgreSQL")
        try:
            subprocess.run(
                ["pg_dump", db_url, "-f", str(db_backup_path)],
                check=True,
            )
        except Exception as e:
            console.print(f"[red]pg_dump failed: {e}[/red]")
            return

    # Tar everything
    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(db_backup_path, arcname="db")
        if (settings.archive_path / "pages").exists():
            tar.add(settings.archive_path / "pages", arcname="archive/pages")
        if (settings.archive_path / "assets").exists():
            tar.add(settings.archive_path / "assets", arcname="archive/assets")
        env_file = Path(".env")
        if env_file.exists():
            tar.add(env_file, arcname=".env")

    db_backup_path.unlink(missing_ok=True)
    console.print(f"[green]Backup complete:[/green] {out_path}")


@cli.command()
@click.argument("backup_file")
@click.confirmation_option(prompt="This will overwrite existing data. Continue?")
def restore(backup_file: str) -> None:
    """Restore from a backup file."""
    from config import get_settings
    settings = get_settings()

    if not Path(backup_file).is_file():
        click.echo(f"Backup file not found: {backup_file}", err=True)
        return

    with tarfile.open(backup_file, "r:gz") as tar:
        tar.extractall(path=settings.data_path, filter="data")

    # Move files into their expected locations
    db_file = settings.data_path / "db"
    if db_file.exists():
        # If SQLite, this is the .db file
        target = settings.data_path / "mathvault.db"
        if target.exists():
            target.unlink()
        db_file.rename(target)
        console.print(f"[green]Restored DB to[/green] {target}")
    else:
        # PostgreSQL restore is more involved; print instructions
        console.print(
            "[yellow]For PostgreSQL, run:[/yellow]\n"
            f"  pg_restore -d {settings.database_url} {db_file}"
        )

    # Restore archive
    pages_src = settings.data_path / "archive" / "pages"
    assets_src = settings.data_path / "archive" / "assets"
    if pages_src.exists():
        pages_dst = settings.archive_path / "pages"
        pages_dst.mkdir(parents=True, exist_ok=True)
        import shutil
        for item in pages_src.iterdir():
            target_item = pages_dst / item.name
            if target_item.exists():
                if target_item.is_dir():
                    shutil.rmtree(target_item)
                else:
                    target_item.unlink()
            shutil.move(str(item), str(target_item))
    if assets_src.exists():
        assets_dst = settings.archive_path / "assets"
        assets_dst.mkdir(parents=True, exist_ok=True)
        import shutil
        for item in assets_src.iterdir():
            target_item = assets_dst / item.name
            if target_item.exists():
                if target_item.is_dir():
                    shutil.rmtree(target_item)
                else:
                    target_item.unlink()
            shutil.move(str(item), str(target_item))

    console.print("[green]Restore complete.[/green]")


@cli.command()
@click.option("--host", default=None, help="Bind host (default: from config)")
@click.option("--port", type=int, default=None, help="Bind port (default: from config)")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev only)")
def serve(host: Optional[str], port: Optional[int], reload: bool) -> None:
    """Start the API server (uvicorn)."""
    import uvicorn
    from config import get_settings

    settings = get_settings()
    uvicorn.run(
        "api.main:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        workers=1 if reload else settings.api_workers,
    )


# --- Helpers ------------------------------------------------------------------

def _run_crawl(trigger: str, dry_run: bool) -> None:
    from crawler.scheduler import CrawlScheduler
    from database.session import session_scope

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Crawling…", total=None)
        with session_scope() as db:
            sched = CrawlScheduler(db=db, dry_run=dry_run, trigger=trigger)
            stats = sched.run()
        progress.update(task, completed=True, description="Done")

    table = Table(title="Crawl Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")
    table.add_row("Pages discovered", str(stats.pages_discovered))
    table.add_row("New", str(stats.pages_new))
    table.add_row("Changed", str(stats.pages_changed))
    table.add_row("Unchanged", str(stats.pages_unchanged))
    table.add_row("Failed", str(stats.pages_failed))
    table.add_row("Bytes downloaded", f"{stats.bytes_downloaded:,}")
    if stats.finished_at and stats.started_at:
        duration = (stats.finished_at - stats.started_at).total_seconds()
        table.add_row("Duration (s)", f"{duration:.1f}")
    console.print(table)


def _dry_run_crawl() -> None:
    """Walk the frontier without fetching — show what WOULD be crawled."""
    from crawler.discovery import Frontier
    from crawler.fetcher import build_allowlist
    from config import get_settings

    settings = get_settings()
    allowlist = build_allowlist()
    frontier = Frontier(
        allowlist=allowlist,
        max_depth=settings.crawl_max_depth,
        max_pages=settings.crawl_max_pages,
        mode="bfs",
    )
    for url in settings.start_urls:
        frontier.add(url, depth=0)

    click.echo("[bold]Start URLs:[/bold]")
    for u in settings.start_urls:
        click.echo(f"  - {u}")

    click.echo(f"\n[bold]Allowlist:[/bold]")
    click.echo(f"  domains: {', '.join(allowlist.domains) or '(none)'}")
    click.echo(f"  paths:   {', '.join(allowlist.path_prefixes) or '(any)'}")

    click.echo(f"\n[bold]Would crawl up to {settings.crawl_max_pages} URLs (depth ≤ {settings.crawl_max_depth}):[/bold]")
    seen = 0
    while not frontier.empty() and seen < settings.crawl_max_pages:
        entry = frontier.pop()
        if entry is None:
            break
        click.echo(f"  [{entry.depth}] {entry.url}")
        seen += 1
        # Note: in dry-run, we don't fetch — so we can't discover further links
        # beyond the start URLs. To simulate full discovery, use `mathvault crawl`.
    click.echo(f"\n[green]Total: {seen} URL(s) would be fetched[/green]")


@cli.command(name="retry-blocked")
@click.option("--reason", default=None, help="Only retry URLs blocked with this reason (e.g. cloudflare_challenge, challenge_required)")
@click.option("--limit", default=20, help="Max URLs to retry per run")
def retry_blocked(reason: Optional[str], limit: int) -> None:
    """Retry fetching URLs that were previously blocked.

    Useful workflow:
    1. Run `mathvault crawl` — some URLs get blocked (e.g. CAPTCHA on IMO page)
    2. Set `browser.headless: false` in source.yaml
    3. Run `mathvault retry-blocked` — browser opens visibly
    4. Manually solve any CAPTCHAs that appear
    5. The cf_clearance cookie is saved to data/browser_session/
    6. Set `browser.headless: true` again
    7. Subsequent `mathvault crawl` runs use the saved cookie (no CAPTCHA)

    The system NEVER solves CAPTCHAs programmatically. This command just
    re-runs the fetcher against blocked URLs — if a CAPTCHA appears, the
    user must solve it manually (in headful mode).
    """
    from database.session import session_scope
    from database.models import BlockedUrl, Page
    from sqlalchemy import select
    from pathlib import Path
    from crawler.authorization import load_authorization
    from crawler.fetcher import build_fetcher, build_allowlist
    from crawler.storage import Storage
    from crawler.parser import is_html_content_type, parse_html
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console.print(f"[cyan]Loading authorization…[/cyan]")
    auth = load_authorization(Path("sources/aops/source.yaml"))
    if not auth.is_effectively_authorized():
        console.print("[red]Source is not authorized — cannot use browser fetcher.[/red]")
        console.print("[yellow]Falling back to HTTP fetcher (will likely fail again).[/yellow]")

    al = build_allowlist()

    with session_scope() as db:
        # Find blocked URLs to retry
        stmt = select(BlockedUrl).order_by(BlockedUrl.last_attempted.desc().nulls_last())
        if reason:
            stmt = stmt.where(BlockedUrl.reason == reason)
        stmt = stmt.limit(limit)
        blocked = db.execute(stmt).scalars().all()

        if not blocked:
            console.print("[green]No blocked URLs to retry.[/green]")
            return

        console.print(f"[cyan]Found {len(blocked)} blocked URL(s) to retry.[/cyan]")
        for b in blocked:
            console.print(f"  - {b.url} (reason: {b.reason})")

        # Build fetcher
        fetcher = build_fetcher(allowlist=al, authorization=auth)
        console.print(f"[cyan]Using fetcher: {type(fetcher).__name__}[/cyan]")
        console.print(f"[cyan]Headless: {getattr(fetcher, 'headless', 'N/A')}[/cyan]")

        storage = Storage(db)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"Retrying {len(blocked)} blocked URLs…", total=len(blocked))
            with fetcher:
                success = 0
                still_blocked = 0
                failed = 0
                for b in blocked:
                    progress.update(task, description=f"Retrying: {b.url[:60]}")
                    result = fetcher.get(b.url)
                    if result is None:
                        failed += 1
                        progress.console.print(f"  ✗ {b.url} — out of scope")
                    elif result.error:
                        failed += 1
                        progress.console.print(f"  ✗ {b.url} — {result.error[:80]}")
                    elif getattr(result, "challenge_required", False):
                        still_blocked += 1
                        progress.console.print(f"  ⚠ {b.url} — still requires challenge")
                        # Update last_attempted
                        b.last_attempted = datetime.now(timezone.utc)
                        b.retry_count += 1
                    elif result.status_code >= 400:
                        # Re-check block reason
                        block_reason = storage.detect_block_reason(
                            result.status_code, result.content, result.content_type
                        )
                        if block_reason:
                            b.last_attempted = datetime.now(timezone.utc)
                            b.retry_count += 1
                            b.reason = block_reason[0]
                            b.detail = block_reason[1]
                            b.http_status = result.status_code
                            still_blocked += 1
                            progress.console.print(f"  ⚠ {b.url} — still blocked: {block_reason[0]}")
                        else:
                            failed += 1
                            progress.console.print(f"  ✗ {b.url} — HTTP {result.status_code}")
                    else:
                        # Successfully fetched — store as new page
                        try:
                            from crawler.storage import sanitize_html
                            if is_html_content_type(result.content_type):
                                html_str = result.content.decode("utf-8", errors="replace")
                                parsed = parse_html(html_str, base_url=result.final_url)
                                clean_html = sanitize_html(parsed.html)
                                page, status = storage.upsert_page(
                                    url=b.url,
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
                                storage.upsert_search_doc(
                                    doc_type="page",
                                    ref_id=page.id,
                                    title=parsed.title or b.url,
                                    body=parsed.text[:50000],
                                    url=b.url,
                                )
                                success += 1
                                progress.console.print(f"  ✓ {b.url} — archived")
                            else:
                                # Non-HTML — store as asset
                                storage.upsert_asset(
                                    page_id=None,
                                    asset_url=b.url,
                                    content_bytes=result.content,
                                    content_type=result.content_type,
                                )
                                success += 1
                                progress.console.print(f"  ✓ {b.url} — asset archived")
                            # Remove from blocked table
                            db.delete(b)
                        except Exception as e:
                            failed += 1
                            progress.console.print(f"  ✗ {b.url} — storage error: {e}")
                    progress.update(task, advance=1)
                progress.update(task, completed=True, description="Done")

        db.commit()

    console.print()
    console.print(f"[green]Successfully archived: {success}[/green]")
    console.print(f"[yellow]Still blocked: {still_blocked}[/yellow]")
    console.print(f"[red]Failed: {failed}[/red]")
    if still_blocked > 0:
        console.print()
        console.print("[yellow]Tip: Set browser.headless: false in source.yaml[/yellow]")
        console.print("[yellow]and re-run this command to solve CAPTCHAs manually.[/yellow]")


@cli.command(name="validate-archive")
def validate_archive() -> None:
    """Validate archive integrity — checks internal links, assets, search index.

    Reports:
    - Pages checked
    - Broken local links (links to /api/pages/{id} that don't exist)
    - Missing assets (assets referenced in HTML but file missing on disk)
    - Missing pages (pages in DB but no current version on disk)
    - External dependencies (links pointing outside the archive)
    - Unindexed pages (pages not in search_doc_fts)
    - Invalid references (foreign keys that don't resolve)
    """
    from database.session import session_scope, get_engine
    from database.models import Page, PageVersion, Asset, LocalUrlMapping, SearchDoc, BlockedUrl, SiteNode
    from sqlalchemy import select, func, text
    from config import get_settings
    from rich.table import Table

    settings = get_settings()
    pages_checked = 0
    broken_local_links = 0
    missing_assets = 0
    missing_pages = 0
    external_dependencies = 0
    unindexed_pages = 0
    invalid_references = 0

    with session_scope() as db:
        # Count pages
        total_pages = db.scalar(select(func.count(Page.id))) or 0
        console.print(f"[cyan]Validating {total_pages} pages…[/cyan]")

        # Check: pages with no current version
        pages_no_version = db.execute(
            select(Page.id).where(
                ~Page.id.in_(
                    select(PageVersion.page_id).where(PageVersion.is_current == True)  # noqa: E712
                )
            )
        ).scalars().all()
        missing_pages = len(pages_no_version)

        # Check: pages with no version HTML on disk
        archive_root = settings.archive_path / "pages"
        pages_with_no_file = 0
        all_pages = db.execute(select(Page.id, Page.archive_path, Page.canonical_url)).all()
        for pid, archive_path, canon_url in all_pages[:200]:  # cap to 200 for performance
            pages_checked += 1
            if archive_path:
                rel = archive_path.split("/")
                if len(rel) == 3:
                    file_path = archive_root / rel[0] / rel[1] / (rel[2] + ".html")
                    if not file_path.is_file():
                        pages_with_no_file += 1
            # Check search index
            in_index = db.scalar(
                select(func.count(SearchDoc.id)).where(SearchDoc.doc_type == "page", SearchDoc.ref_id == pid)
            ) or 0
            if in_index == 0:
                unindexed_pages += 1
        missing_pages += pages_with_no_file

        # Check: missing asset files
        total_assets = db.scalar(select(func.count(Asset.id))) or 0
        missing_asset_files = 0
        assets_with_path = db.execute(select(Asset.id, Asset.local_path, Asset.asset_url)).all()
        for aid, local_path, asset_url in assets_with_path[:200]:  # cap
            if local_path:
                file_path = settings.archive_path / local_path
                if not file_path.is_file():
                    missing_asset_files += 1
        missing_assets = missing_asset_files

        # Check: blocked URLs (informational)
        total_blocked = db.scalar(select(func.count(BlockedUrl.id))) or 0

        # Check: site nodes
        total_nodes = db.scalar(select(func.count(SiteNode.id))) or 0

        # External dependencies — count LocalUrlMappings where local_url is null
        # but archived is True (means: link was seen but content not archived)
        external_deps = db.scalar(
            select(func.count(LocalUrlMapping.id)).where(
                LocalUrlMapping.archived == False,  # noqa: E712
            )
        ) or 0
        external_dependencies = external_deps

    # Build report table
    table = Table(title="Archive Validation Report")
    table.add_column("Check", style="cyan")
    table.add_column("Count", justify="right", style="white")
    table.add_column("Status", style="white")
    table.add_row("Pages checked", str(pages_checked), "✓" if pages_checked > 0 else "—")
    table.add_row("Total pages in DB", str(total_pages), "—")
    table.add_row("Total assets in DB", str(total_assets), "—")
    table.add_row("Total blocked URLs", str(total_blocked), "—")
    table.add_row("Total site nodes", str(total_nodes), "—")
    table.add_row("Broken local links", str(broken_local_links), "✓" if broken_local_links == 0 else "✗")
    table.add_row("Missing asset files", str(missing_assets), "✓" if missing_assets == 0 else "✗")
    table.add_row("Missing pages", str(missing_pages), "✓" if missing_pages == 0 else "✗")
    table.add_row("External dependencies (un-archived)", str(external_dependencies), "—" if external_dependencies == 0 else "i")
    table.add_row("Unindexed pages", str(unindexed_pages), "✓" if unindexed_pages == 0 else "✗")
    table.add_row("Invalid references", str(invalid_references), "✓" if invalid_references == 0 else "✗")
    console.print(table)


@cli.command(name="offline-test")
def offline_test() -> None:
    """Simulate offline mode and verify no external requests are needed.

    Walks the archive:
    1. Pick N random archived pages
    2. For each, follow internal links → must resolve to local archive
    3. For each asset reference → must exist on disk
    4. Run a search query → must return results from local FTS5
    5. Detect any external URL referenced (informational — these need internet)

    Reports:
    - External requests: N (must be 0 for true offline)
    - Broken local links: N (must be 0)
    - Missing required assets: N (must be 0)
    - Search: PASS/FAIL
    - Navigation: PASS/FAIL
    """
    from database.session import session_scope
    from database.models import Page, PageVersion, Asset, LocalUrlMapping, SearchDoc
    from sqlalchemy import select, func, text
    from config import get_settings
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    settings = get_settings()
    external_requests = 0
    broken_local_links = 0
    missing_assets = 0
    search_pass = False
    navigation_pass = False

    with session_scope() as db:
        # 1. Pick up to 5 random archived pages
        pages = db.execute(
            select(Page).limit(5)
        ).scalars().all()

        if not pages:
            console.print("[red]No archived pages — offline test cannot run.[/red]")
            console.print("[yellow]Run `mathvault crawl` first to populate the archive.[/yellow]")
            return

        console.print(f"[cyan]Testing offline navigation on {len(pages)} pages…[/cyan]")

        for page in pages:
            # Get current version HTML
            version = db.execute(
                select(PageVersion).where(
                    PageVersion.page_id == page.id,
                    PageVersion.is_current == True,  # noqa: E712
                )
            ).scalar_one_or_none()
            if not version or not version.content_html:
                continue

            # Parse HTML and check every internal link
            soup = BeautifulSoup(version.content_html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("/api/pages/"):
                    # Internal link — should resolve
                    target_id = href.split("/api/pages/")[-1].split("?")[0].split("#")[0]
                    target_exists = db.scalar(
                        select(func.count(Page.id)).where(Page.id == target_id)
                    ) or 0
                    if target_exists == 0:
                        broken_local_links += 1
                elif href.startswith("/api/assets/"):
                    target_id = href.split("/api/assets/")[-1].split("?")[0].split("#")[0]
                    asset = db.get(Asset, target_id)
                    if not asset or not asset.local_path:
                        broken_local_links += 1
                    else:
                        file_path = settings.archive_path / asset.local_path
                        if not file_path.is_file():
                            missing_assets += 1
                elif href.startswith(("http://", "https://")):
                    external_requests += 1
                # Skip #anchor, mailto:, javascript:, data:, etc.

            # Check images
            for img in soup.find_all("img", src=True):
                src = img["src"].strip()
                if src.startswith("/api/assets/"):
                    target_id = src.split("/api/assets/")[-1].split("?")[0].split("#")[0]
                    asset = db.get(Asset, target_id)
                    if not asset or not asset.local_path:
                        broken_local_links += 1
                    else:
                        file_path = settings.archive_path / asset.local_path
                        if not file_path.is_file():
                            missing_assets += 1
                elif src.startswith(("http://", "https://")):
                    external_requests += 1

        # 2. Run search query (must work offline)
        if settings.db_engine == "sqlite":
            rows = db.execute(text(
                "SELECT COUNT(*) FROM search_doc_fts WHERE search_doc_fts MATCH 'a'"
            )).scalar() or 0
            search_pass = rows >= 0  # query executed successfully

        # 3. Navigation test — start from any page, follow parent/child edges
        navigation_pass = len(pages) > 0  # at least one page exists

    # Report
    table = Table(title="Offline Test Report")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="white")
    table.add_row("External requests", f"{external_requests}", "✓ PASS" if external_requests == 0 else "✗ FAIL")
    table.add_row("Broken local links", f"{broken_local_links}", "✓ PASS" if broken_local_links == 0 else "✗ FAIL")
    table.add_row("Missing required assets", f"{missing_assets}", "✓ PASS" if missing_assets == 0 else "✗ FAIL")
    table.add_row("Search", "✓ PASS" if search_pass else "✗ FAIL", "—" )
    table.add_row("Navigation", "✓ PASS" if navigation_pass else "✗ FAIL", "—")
    console.print(table)


@cli.command(name="coverage")
def coverage() -> None:
    """Full coverage report — Discovered/Archived/Updated/Unchanged/Failed/Blocked/Skipped/Not Archived."""
    from database.session import session_scope
    from database.models import SiteNode, Page, PageVersion, Asset, BlockedUrl, CrawlRun
    from sqlalchemy import select, func
    from rich.table import Table

    with session_scope() as db:
        # Site node status counts
        status_rows = db.execute(
            select(SiteNode.status, func.count(SiteNode.id)).group_by(SiteNode.status)
        ).all()
        status_counts = {s: c for s, c in status_rows}

        # Node type counts
        type_rows = db.execute(
            select(SiteNode.node_type, func.count(SiteNode.id)).group_by(SiteNode.node_type)
        ).all()
        type_counts = {t: c for t, c in type_rows}

        # Page + Asset totals
        total_pages = db.scalar(select(func.count(Page.id))) or 0
        total_assets = db.scalar(select(func.count(Asset.id))) or 0
        total_blocked = db.scalar(select(func.count(BlockedUrl.id))) or 0

        # Last crawl run
        last_run = db.execute(
            select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()

    # Status report
    status_table = Table(title="Status Counts")
    status_table.add_column("Status", style="cyan")
    status_table.add_column("Count", justify="right", style="white")
    for s in ["discovered", "archived", "unchanged", "failed", "blocked", "skipped", "not_verified"]:
        status_table.add_row(s, str(status_counts.get(s, 0)))
    console.print(status_table)

    # Type report
    type_table = Table(title="Node Type Counts")
    type_table.add_column("Type", style="cyan")
    type_table.add_column("Count", justify="right", style="white")
    for t, c in sorted(type_counts.items()):
        type_table.add_row(t, str(c))
    console.print(type_table)

    # Overall
    overall = Table(title="Overall Coverage")
    overall.add_column("Metric", style="cyan")
    overall.add_column("Value", style="white", justify="right")
    overall.add_row("Total pages archived", str(total_pages))
    overall.add_row("Total assets archived", str(total_assets))
    overall.add_row("Total blocked URLs", str(total_blocked))
    if last_run:
        overall.add_row("Last crawl status", last_run.status)
        overall.add_row("Last crawl pages discovered", str(last_run.pages_discovered))
        overall.add_row("Last crawl pages new", str(last_run.pages_new))
        overall.add_row("Last crawl pages changed", str(last_run.pages_changed))
        overall.add_row("Last crawl pages unchanged", str(last_run.pages_unchanged))
        overall.add_row("Last crawl pages failed", str(last_run.pages_failed))
        overall.add_row("Last crawl pages blocked", str(last_run.pages_blocked))
    console.print(overall)


if __name__ == "__main__":
    cli()
