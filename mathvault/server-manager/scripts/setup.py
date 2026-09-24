#!/usr/bin/env python3
"""Cross-platform setup script for Personal Server Manager.

Works on Windows, macOS, and Linux. Run with:
    python scripts/setup.py

This script:
1. Creates a Python virtualenv (.venv/)
2. Installs Python dependencies
3. Copies .env.example to .env if missing
4. Initializes the database
5. Prompts for a master password (interactive)
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


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
]


def info(msg: str) -> None:
    print(f"\033[36m[setup]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m[setup]\033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m[setup]\033[0m {msg}", file=sys.stderr)


def find_python() -> str:
    """Return a Python interpreter that works (python or python3)."""
    for candidate in ("python3", "python"):
        try:
            r = subprocess.run(
                [candidate, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and "Python 3." in (r.stdout + r.stderr):
                return candidate
        except FileNotFoundError:
            continue
    err("Could not find a Python 3 interpreter. Install Python 3.11+ from https://python.org")
    sys.exit(2)


def venv_executable(name: str) -> str | None:
    """Return path to a venv executable (python/pip), or None if venv doesn't exist."""
    venv_dir = PROJECT_ROOT / ".venv"
    if not venv_dir.is_dir():
        return None
    if os.name == "nt":
        # Windows: .venv\Scripts\python.exe
        candidates = [
            venv_dir / "Scripts" / f"{name}.exe",
            venv_dir / "Scripts" / name,
        ]
    else:
        candidates = [
            venv_dir / "bin" / name,
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def step_venv(python: str) -> str:
    """Step 1: Create venv if missing; return path to venv python."""
    info("Creating Python virtualenv…")
    venv_dir = PROJECT_ROOT / ".venv"
    if venv_dir.exists():
        ok("  venv already exists.")
    else:
        r = subprocess.run([python, "-m", "venv", str(venv_dir)])
        if r.returncode != 0:
            err(f"venv creation failed (exit {r.returncode})")
            sys.exit(1)
        ok(f"  venv created at {venv_dir}")

    py = venv_executable("python")
    if py is None:
        err("Could not find python in venv")
        sys.exit(1)
    return py


def step_install_deps(venv_python: str) -> None:
    """Step 2: Install Python deps via pip."""
    info("Installing Python dependencies (this may take a minute)…")
    r = subprocess.run(
        [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        err("pip upgrade failed")
        err(r.stderr[-500:] if r.stderr else "(no stderr)")
        sys.exit(1)

    r = subprocess.run(
        [venv_python, "-m", "pip", "install", *DEPS],
    )
    if r.returncode != 0:
        err("dependency installation failed")
        sys.exit(1)
    ok("  dependencies installed.")


def step_env_file() -> None:
    """Step 3: Copy .env.example to .env if missing."""
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"
    if env_path.exists():
        ok(".env already exists.")
        return
    if not example_path.exists():
        err(f"{example_path} not found — repo may be incomplete")
        sys.exit(1)
    shutil.copy(example_path, env_path)
    ok(f"  copied {example_path.name} → {env_path.name}")


def step_init_db(venv_python: str) -> None:
    """Step 4: Initialize DB."""
    info("Initializing database…")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    r = subprocess.run(
        [venv_python, "-c", "from database.session import init_db; init_db()"],
        env=env, cwd=str(PROJECT_ROOT),
    )
    if r.returncode != 0:
        err("DB init failed")
        sys.exit(1)
    ok("  database initialized.")


def step_master_password(venv_python: str) -> None:
    """Step 5: Set master password (interactive)."""
    env_path = PROJECT_ROOT / ".env"
    needs_setup = True
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("MASTER_PASSWORD_HASH=") and len(line.split("=", 1)[1].strip()) > 0:
                needs_setup = False
                break

    if not needs_setup:
        ok("Master password already set — skipping.")
        return

    info("Master password setup:")
    print("  The master password encrypts ALL SSH credentials stored by this app.")
    print("  It is NOT recoverable if lost. Choose something strong (>= 12 chars).")
    print()

    import getpass
    pw1 = getpass.getpass("  Master password: ")
    pw2 = getpass.getpass("  Confirm:          ")

    if pw1 != pw2:
        err("Passwords do not match.")
        sys.exit(1)
    if len(pw1) < 12:
        err("Password must be at least 12 characters.")
        sys.exit(1)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    # Use the CLI's setup command
    r = subprocess.run(
        [venv_python, "-c",
         "import sys; sys.argv=['server-manager','setup']; "
         "import getpass; "
         "pw=__import__('builtins').input if False else None; "
         "from cli.server_manager import cli; cli()"],
        env=env, cwd=str(PROJECT_ROOT),
        input=f"{pw1}\n{pw2}\n",
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        err(f"Setup command failed: {r.stderr}")
        sys.exit(1)
    ok("  master password set.")


def step_frontend() -> None:
    """Step 6: Install frontend deps if Node.js is available."""
    frontend_dir = PROJECT_ROOT / "frontend"
    if not frontend_dir.is_dir():
        # Frontend not present (server-manager API-only mode)
        return
    node_modules = frontend_dir / "node_modules"
    if node_modules.exists():
        ok("Frontend node_modules already exists.")
        return

    # Check npm
    npm = shutil.which("npm")
    if npm is None:
        info("npm not found — skipping frontend install.")
        print("  To install frontend later:")
        print("    cd frontend")
        print("    npm install --legacy-peer-deps")
        return

    info("Installing frontend dependencies (this may take a few minutes)…")
    r = subprocess.run(
        [npm, "install", "--legacy-peer-deps"],
        cwd=str(frontend_dir),
    )
    if r.returncode != 0:
        err("Frontend install failed — you can still use the API without the UI.")
        return
    ok("  frontend dependencies installed.")


def main() -> None:
    print("=" * 60)
    print("  Personal Server Manager — First-run Setup")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print("=" * 60)
    print()

    python = find_python()
    info(f"Using Python: {python}")
    info(f"Project root: {PROJECT_ROOT}")

    venv_python = step_venv(python)
    step_install_deps(venv_python)
    step_env_file()
    step_init_db(venv_python)
    step_master_password(venv_python)
    step_frontend()

    print()
    print("=" * 60)
    ok("Setup complete!")
    print("=" * 60)
    print()
    print("To start the app:")
    print("  python scripts/start.py")
    print()
    print("Then open: http://127.0.0.1:3001")


if __name__ == "__main__":
    main()
