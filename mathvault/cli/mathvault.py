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


if __name__ == "__main__":
    cli()
