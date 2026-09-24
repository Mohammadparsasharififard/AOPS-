#!/usr/bin/env python3
"""Seed script — register servers from servers.local.json into the local DB.

Reads `scripts/servers.local.json` (gitignored — never committed), encrypts
the SSH credentials with the user's master password, and inserts/updates
each server in the local SQLite database.

Usage:
    python scripts/seed-servers.py

Workflow:
1. Asks for the master password (set during `setup.py`).
2. Verifies the master password against the bcrypt hash in .env.
3. For each server in `servers.local.json`:
   - If the server name already exists in DB → update credentials
   - Otherwise → insert new server
4. All credentials are encrypted with the master password (sealed box).

Requirements:
- setup.py must have been run first (master password + keypair must exist)
"""
from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))


def info(msg: str) -> None:
    print(f"\033[36m[seed]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m[seed]\033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m[seed]\033[0m {msg}", file=sys.stderr)


def venv_python() -> str:
    """Return path to venv python."""
    if os.name == "nt":
        candidates = [
            PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
            PROJECT_ROOT / ".venv" / "Scripts" / "python",
        ]
    else:
        candidates = [PROJECT_ROOT / ".venv" / "bin" / "python"]
    for c in candidates:
        if c.exists():
            return str(c)
    err("Virtualenv not found. Run: python scripts/setup.py")
    sys.exit(1)


def main() -> int:
    print("=" * 60)
    print("  Personal Server Manager — Server Seeder")
    print("=" * 60)
    print()

    # Step 1: Check prerequisites
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        err(".env not found. Run: python scripts/setup.py first.")
        return 1

    content = env_path.read_text(encoding="utf-8")
    master_hash = None
    for line in content.splitlines():
        if line.startswith("MASTER_PASSWORD_HASH=") and len(line.split("=", 1)[1].strip()) > 0:
            master_hash = line.split("=", 1)[1].strip()
            break
    if not master_hash:
        err("MASTER_PASSWORD_HASH not set in .env. Run: python scripts/setup.py first.")
        return 1

    # Step 2: Find servers.local.json
    json_path = PROJECT_ROOT / "scripts" / "servers.local.json"
    example_path = PROJECT_ROOT / "scripts" / "servers.local.json.example"
    if not json_path.exists():
        err(f"{json_path.name} not found.")
        if example_path.exists():
            err(f"Copy {example_path.name} to {json_path.name} and edit it:")
            err(f"  cp scripts/servers.local.json.example scripts/servers.local.json")
        return 1

    # Step 3: Load servers JSON
    try:
        servers_config = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"Invalid JSON in {json_path.name}: {e}")
        return 1
    if not isinstance(servers_config, list) or not servers_config:
        err(f"{json_path.name} must contain a non-empty JSON array of server objects.")
        return 1

    info(f"Found {len(servers_config)} server(s) to register:")
    for s in servers_config:
        info(f"  - {s.get('name', '?')} ({s.get('username', '?')}@{s.get('host', '?')}:{s.get('port', 22)})")
    print()

    # Step 4: Ask for master password
    print("Enter your master password to encrypt the SSH credentials.")
    print("(The master password is NOT stored — it's only used to encrypt")
    print(" the credentials during this seed operation.)")
    print()
    pw = getpass.getpass("Master password: ")

    # Step 5: Verify master password
    from config import get_settings
    get_settings.cache_clear()
    settings = get_settings()

    from crypto import verify_master_password, encrypt_credential, load_private_key
    if not verify_master_password(pw, settings.master_password_hash):
        err("Master password is incorrect.")
        return 1
    # Also test that we can decrypt the private key (sanity check)
    if load_private_key(pw) is None:
        err("Master password verified but keypair decryption failed. The keypair.json may be corrupted.")
        return 1
    ok("Master password verified.")
    print()

    # Step 6: Initialize DB
    from database.session import init_db, session_scope
    from database.models import Server
    init_db()

    # Step 7: Seed each server
    registered = 0
    updated = 0
    for cfg in servers_config:
        name = cfg.get("name")
        host = cfg.get("host")
        port = cfg.get("port", 22)
        username = cfg.get("username", "root")
        auth_method = cfg.get("auth_method", "password")
        password = cfg.get("password")
        private_key = cfg.get("private_key")
        notes = cfg.get("notes", "")

        if not name or not host:
            err(f"  Skipping invalid server entry (missing name/host): {cfg}")
            continue

        if auth_method == "password" and not password:
            err(f"  Skipping {name}: auth_method=password but no password provided")
            continue
        if auth_method == "key" and not private_key:
            err(f"  Skipping {name}: auth_method=key but no private_key provided")
            continue

        # Encrypt credentials
        try:
            encrypted_password = encrypt_credential(password) if password else None
            encrypted_key = encrypt_credential(private_key) if private_key else None
        except Exception as e:
            err(f"  Encryption failed for {name}: {e}")
            continue

        with session_scope() as db:
            existing = db.query(Server).filter_by(name=name).first()
            if existing:
                # Update
                existing.host = host
                existing.port = port
                existing.username = username
                existing.auth_method = auth_method
                if encrypted_password:
                    existing.encrypted_password = encrypted_password
                if encrypted_key:
                    existing.encrypted_private_key = encrypted_key
                if notes:
                    existing.notes = notes
                updated += 1
                ok(f"  Updated: {name} ({username}@{host}:{port})")
            else:
                # Insert
                server = Server(
                    name=name, host=host, port=port, username=username,
                    auth_method=auth_method,
                    encrypted_password=encrypted_password,
                    encrypted_private_key=encrypted_key,
                    notes=notes,
                )
                db.add(server)
                registered += 1
                ok(f"  Registered: {name} ({username}@{host}:{port})")

    # Clear the master password from memory
    del pw

    print()
    print("=" * 60)
    ok(f"Done! {registered} new + {updated} updated = {registered + updated} server(s) ready.")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Start the app:  python scripts/start.py")
    print("  2. Open in browser: http://127.0.0.1:3001")
    print("  3. Sign in with your master password")
    print("  4. Your servers will appear in the dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
