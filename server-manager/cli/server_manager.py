"""Personal Server Manager CLI.

Commands:
  init             Initialize database (create_all)
  setup            Set master password (first-time setup)
  serve            Start the API server
  hash-password    Generate a bcrypt hash for a given password
"""
from __future__ import annotations

import getpass
import sys

import click
from rich.console import Console

from config import get_settings


console = Console()


@click.group()
@click.version_option("1.0.0")
def cli() -> None:
    """Personal Server Manager — laptop-side control panel for SSH-reachable servers."""


@cli.command()
def init() -> None:
    """Initialize the database."""
    from database.session import init_db
    init_db()
    console.print("[green]Database initialized.[/green]")


@cli.command()
def setup() -> None:
    """First-time setup: set master password + generate keypair."""
    from config import get_settings
    settings = get_settings()
    if settings.master_password_hash:
        console.print("[red]Master password already set.[/red]")
        console.print("To reset: edit .env to clear MASTER_PASSWORD_HASH, then re-run setup.")
        sys.exit(1)

    console.print("[cyan]Setting up master password.[/cyan]")
    console.print("This password protects all SSH credentials stored by the app.")
    console.print("It must be at least 12 characters and is [bold]NOT[/bold] recoverable if lost.")
    console.print()

    pw1 = getpass.getpass("Master password: ")
    pw2 = getpass.getpass("Confirm: ")

    if pw1 != pw2:
        console.print("[red]Passwords do not match.[/red]")
        sys.exit(1)
    if len(pw1) < 12:
        console.print("[red]Password must be at least 12 characters.[/red]")
        sys.exit(1)

    from crypto import generate_keypair, hash_master_password, save_keypair
    sk_bytes, pk_bytes = generate_keypair(pw1)
    save_keypair(sk_bytes, pk_bytes, pw1)
    h = hash_master_password(pw1)
    # Append to .env
    with open(".env", "a", encoding="utf-8") as f:
        f.write(f"\nMASTER_PASSWORD_HASH={h}\n")
    console.print("[green]Keypair generated and saved.[/green]")
    console.print(f"[green]Master password hash saved to .env (MASTER_PASSWORD_HASH).[/green]")

    from database.session import init_db
    init_db()
    console.print("[green]Database initialized.[/green]")
    console.print()
    console.print("[bold]Next:[/bold] run `server-manager serve` to start the API.")


@cli.command()
@click.option("--host", default=None)
@click.option("--port", type=int, default=None)
@click.option("--reload", is_flag=True)
def serve(host, port, reload) -> None:
    """Start the API server."""
    import uvicorn
    s = get_settings()
    uvicorn.run(
        "api.main:app",
        host=host or s.app_host,
        port=port or s.app_port,
        reload=reload,
        workers=1 if reload else 1,
    )


@cli.command()
@click.argument("password")
def hash_password(password: str) -> None:
    """Generate a bcrypt hash for a password (utility)."""
    from crypto import hash_master_password
    click.echo(hash_master_password(password))


if __name__ == "__main__":
    cli()
