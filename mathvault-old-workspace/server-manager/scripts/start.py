#!/usr/bin/env python3
"""Cross-platform start script for Personal Server Manager.

Works on Windows, macOS, and Linux. Run with:
    python scripts/start.py

Starts both:
- API on 127.0.0.1:7700 (uvicorn)
- Frontend on 127.0.0.1:3001 (Next.js dev)

Press Ctrl+C to stop both.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


def info(msg: str) -> None:
    print(f"\033[36m[start]\033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m[start]\033[0m {msg}", file=sys.stderr)


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


def check_first_run() -> None:
    """Refuse to start if first-run setup not done."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        err(".env not found. Run: python scripts/setup.py")
        sys.exit(1)
    content = env_path.read_text(encoding="utf-8")
    has_hash = any(
        line.startswith("MASTER_PASSWORD_HASH=") and len(line.split("=", 1)[1].strip()) > 0
        for line in content.splitlines()
    )
    if not has_hash:
        err("Master password not set. Run: python scripts/setup.py")
        sys.exit(1)


def start_api() -> subprocess.Popen:
    py = venv_python()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    info(f"Starting API: http://127.0.0.1:7700  (PID will be shown)")
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "7700", "--reload"],
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    info(f"  API PID: {proc.pid}")
    return proc


def start_frontend() -> subprocess.Popen:
    frontend_dir = PROJECT_ROOT / "frontend"
    if not frontend_dir.is_dir() or not (frontend_dir / "package.json").is_file():
        info("Frontend not found — API-only mode.")
        return None
    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        info("Installing frontend deps (first time)…")
        npm = os.environ.get("npm") or "npm"
        subprocess.run([npm, "install", "--legacy-peer-deps"], cwd=str(frontend_dir))

    # Find npm
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    info(f"Starting Frontend: http://127.0.0.1:3001")
    proc = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=str(frontend_dir),
    )
    info(f"  Frontend PID: {proc.pid}")
    return proc


def main() -> None:
    print("=" * 60)
    print("  Personal Server Manager — Starting")
    print("=" * 60)
    check_first_run()

    api_proc = start_api()
    time.sleep(1.0)
    frontend_proc = start_frontend()

    def cleanup(*_):
        print()
        info("Shutting down…")
        for p in (frontend_proc, api_proc):
            if p is None:
                continue
            try:
                if os.name == "nt":
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    p.terminate()
            except Exception:
                pass
        # Wait briefly
        for p in (frontend_proc, api_proc):
            if p is None:
                continue
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    if os.name != "nt":
        signal.signal(signal.SIGTERM, cleanup)

    print()
    print("=" * 60)
    print("  Server Manager running:")
    print("    API:       http://127.0.0.1:7700")
    print("    Frontend:  http://127.0.0.1:3001")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1.0)
            # If either process has died, exit
            if api_proc.poll() is not None:
                err(f"API exited with code {api_proc.returncode}")
                cleanup()
            if frontend_proc is not None and frontend_proc.poll() is not None:
                err(f"Frontend exited with code {frontend_proc.returncode}")
                # Don't exit — keep API running, just notify
                info("Frontend stopped — API still running.")
                frontend_proc = None
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
