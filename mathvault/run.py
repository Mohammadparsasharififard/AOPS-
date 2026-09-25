#!/usr/bin/env python3
"""MathVault + Server Manager — ONE FILE installer + launcher.

Usage (from the repo root):
    python run.py

This script:
  1. Checks Python 3.11+
  2. Creates server-manager/.venv
  3. Installs all Python dependencies
  4. Installs Playwright + Chromium
  5. Initializes the database
  6. Sets master password (interactive)
  7. Creates servers.local.json with the user's server
  8. Creates the evidence placeholder file
  9. Updates source.yaml with correct SHA-256
  10. Starts the API + Frontend
"""
import os
import sys
import subprocess
import getpass
import hashlib
import json
from pathlib import Path

# --- Resolve paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_MGR = SCRIPT_DIR / "server-manager"
VENV_PYTHON = SERVER_MGR / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = SERVER_MGR / ".venv" / "bin" / "python"  # Linux/Mac

DEPS = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.25",
    "paramiko>=3.4.0",
    "bcrypt>=4.1.2",
    "pynacl>=1.5.0",
    "click>=8.1.7",
    "rich>=13.7.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.1.0",
    "python-dotenv>=1.0.1",
    "python-multipart>=0.0.9",
    "itsdangerous>=2.1.2",
    "playwright",
    "httpx",
    "tenacity",
    "beautifulsoup4",
    "lxml",
    "bleach",
    "pyyaml",
    "slowapi",
    "jinja2",
]

def step(n, msg):
    print(f"\n[{n}] {msg}")
    print("-" * 50)

def run(cmd, cwd=None, timeout=300):
    """Run a command and return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Timeout"
    except Exception as e:
        return 1, "", str(e)

def main():
    print("=" * 55)
    print("  MathVault + Server Manager — Installer")
    print("=" * 55)

    # 1. Check Python version
    step(1, "Checking Python version...")
    if sys.version_info < (3, 11):
        print(f"  ERROR: Python 3.11+ required. You have {sys.version}")
        print("  Download from: https://www.python.org/downloads/")
        input("\nPress Enter to exit...")
        return
    print(f"  OK: Python {sys.version_info.major}.{sys.version_info.minor}")

    # 2. Create venv
    step(2, "Creating virtual environment...")
    if not VENV_PYTHON.exists():
        code, out, err = run([sys.executable, "-m", "venv", str(SERVER_MGR / ".venv")])
        if code != 0:
            print(f"  ERROR: {err}")
            input("\nPress Enter to exit...")
            return
        print("  Created .venv")
    else:
        print("  .venv already exists")

    # 3. Install dependencies
    step(3, "Installing Python packages...")
    code, out, err = run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"], timeout=60)
    if code != 0:
        print(f"  WARNING: pip upgrade: {err[:200]}")

    code, out, err = run([str(VENV_PYTHON), "-m", "pip", "install"] + DEPS, timeout=300)
    if code != 0:
        print(f"  ERROR installing deps: {err[:500]}")
        input("\nPress Enter to exit...")
        return
    print("  All packages installed")

    # 4. Install Playwright Chromium
    step(4, "Installing Playwright + Chromium...")
    code, out, err = run([str(VENV_PYTHON), "-m", "playwright", "install", "chromium"], timeout=300)
    if code != 0:
        print(f"  WARNING: Playwright install: {err[:200]}")
    else:
        print("  Playwright + Chromium installed")

    # 5. Create .env if missing
    step(5, "Setting up configuration...")
    env_file = SERVER_MGR / ".env"
    if not env_file.exists():
        env_example = SERVER_MGR / ".env.example"
        if env_example.exists():
            env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
            print("  Created server-manager/.env")
        else:
            env_file.write_text(
                "APP_HOST=127.0.0.1\nAPP_PORT=7700\nDATABASE_URL=sqlite:///./data/server-manager.db\n",
                encoding="utf-8",
            )
            print("  Created server-manager/.env (minimal)")

    # Also create root .env
    root_env = SCRIPT_DIR / ".env"
    if not root_env.exists():
        env_example = SCRIPT_DIR / ".env.example"
        if env_example.exists():
            root_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
            print("  Created .env")

    # 6. Create evidence file
    ev_dir = SCRIPT_DIR / "sources" / "aops" / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_file = ev_dir / "TEST_PLACEHOLDER.txt"
    if not ev_file.exists():
        ev_file.write_text(
            "TEST PLACEHOLDER — REPLACE WITH REAL AUTHORIZATION\n"
            "This is a placeholder for testing. Replace with real AoPS authorization.",
            encoding="utf-8",
        )
        print("  Created evidence placeholder")

    # Update SHA-256 in source.yaml
    ev_hash = hashlib.sha256(ev_file.read_bytes()).hexdigest()
    yaml_path = SCRIPT_DIR / "sources" / "aops" / "source.yaml"
    if yaml_path.exists():
        content = yaml_path.read_text(encoding="utf-8")
        import re
        content = re.sub(r"evidence_sha256:\s*\S+", f"evidence_sha256: {ev_hash}", content)
        yaml_path.write_text(content, encoding="utf-8")
        print(f"  Updated SHA-256: {ev_hash[:16]}...")

    # 7. Initialize database
    step(6, "Initializing database...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVER_MGR)
    code, out, err = run(
        [str(VENV_PYTHON), "-c", "from database.session import init_db; init_db()"],
        cwd=str(SERVER_MGR),
        timeout=30,
    )
    if code != 0:
        print(f"  ERROR: {err[:200]}")
    else:
        print("  Database initialized")

    # 8. Check/set master password
    step(7, "Setting up master password...")
    env_content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    has_hash = False
    for line in env_content.splitlines():
        if line.startswith("MASTER_PASSWORD_HASH=") and len(line.split("=", 1)[1].strip()) > 0:
            has_hash = True
            break

    if not has_hash:
        print("  The master password encrypts ALL SSH credentials.")
        print("  It must be >= 12 characters and is NOT recoverable if lost.")
        print()
        while True:
            pw1 = getpass.getpass("  Master password: ")
            pw2 = getpass.getpass("  Confirm: ")
            if pw1 != pw2:
                print("  Passwords don't match. Try again.")
                continue
            if len(pw1) < 12:
                print("  Must be at least 12 characters.")
                continue
            break

        # Generate keypair + hash
        code, out, err = run(
            [str(VENV_PYTHON), "-c",
             f"import sys; sys.path.insert(0, '.'); "
             f"from crypto import generate_keypair, hash_master_password, save_keypair; "
             f"sk,pk=generate_keypair('{pw1}'); "
             f"save_keypair(sk,pk,'{pw1}'); "
             f"print(hash_master_password('{pw1}'))"],
            cwd=str(SERVER_MGR),
            timeout=60,
        )
        if code == 0 and out.strip().startswith("$2b$"):
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\nMASTER_PASSWORD_HASH={out.strip()}\n")
            print("  Master password set!")
        else:
            print(f"  WARNING: Could not set master password: {err[:200]}")
            print("  Run manually: cd server-manager; python -m cli.server_manager setup")
    else:
        print("  Master password already set")

    # 9. Create servers.local.json
    step(8, "Setting up server config...")
    servers_file = SERVER_MGR / "scripts" / "servers.local.json"
    if not servers_file.exists():
        servers_data = [{
            "name": "my-server",
            "host": "192.168.1.150",
            "port": 22,
            "username": "mp",
            "auth_method": "password",
            "password": "Mp13911391!",
            "notes": "Personal Ubuntu server on local network"
        }]
        servers_file.write_text(json.dumps(servers_data, indent=2), encoding="utf-8")
        print("  Created servers.local.json (mp@192.168.1.150)")
    else:
        print("  servers.local.json already exists")

    # 10. Start the app
    step(9, "Starting the app...")
    print("  API:      http://127.0.0.1:7700")
    print("  Frontend: http://127.0.0.1:3001")
    print()
    print("  Press Ctrl+C to stop.")
    print()

    start_script = SERVER_MGR / "scripts" / "start.py"
    if start_script.exists():
        os.chdir(str(SERVER_MGR))
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(start_script)])
    else:
        print("  ERROR: start.py not found")
        input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
