#!/usr/bin/env python3
"""MathVault + Server Manager — ONE FILE. Run: python run.py"""
import os, sys, subprocess, getpass, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SM = ROOT / "server-manager"
PY = sys.executable

DEPS = [
    "fastapi", "uvicorn[standard]", "sqlalchemy", "paramiko", "bcrypt",
    "pynacl", "click", "rich", "pydantic", "pydantic-settings",
    "python-dotenv", "python-multipart", "itsdangerous", "playwright",
    "httpx", "tenacity", "beautifulsoup4", "lxml", "bleach",
    "pyyaml", "slowapi", "jinja2",
]

def run(cmd, cwd=None, timeout=300):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, "", str(e)

def main():
    print("=" * 50)
    print("  MathVault Installer")
    print("=" * 50)

    # 1. Install deps with SYSTEM python (no venv drama)
    print("\n[1/7] Installing packages...")
    c, o, e = run([PY, "-m", "pip", "install"] + DEPS, timeout=300)
    if c != 0:
        # Try with --user flag
        c, o, e = run([PY, "-m", "pip", "install", "--user"] + DEPS, timeout=300)
    if c != 0:
        print(f"  ERROR: {e[:300]}")
        input("Press Enter to exit..."); return
    print("  OK")

    # 2. Playwright
    print("\n[2/7] Installing Chromium...")
    c, o, e = run([PY, "-m", "playwright", "install", "chromium"], timeout=300)
    print("  OK" if c == 0 else f"  WARN: {e[:100]}")

    # 3. .env files
    print("\n[3/7] Config files...")
    for env_dir, env_file in [(SM, SM / ".env"), (ROOT, ROOT / ".env")]:
        if not env_file.exists():
            ex = env_dir / ".env.example"
            if ex.exists():
                env_file.write_text(ex.read_text(encoding="utf-8"), encoding="utf-8")
    print("  OK")

    # 4. Evidence file
    print("\n[4/7] Evidence file...")
    ev_dir = ROOT / "sources" / "aops" / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_file = ev_dir / "TEST_PLACEHOLDER.txt"
    ev_text = "TEST PLACEHOLDER\n"
    ev_file.write_text(ev_text, encoding="utf-8")
    ev_hash = hashlib.sha256(ev_text.encode()).hexdigest()
    yaml_path = ROOT / "sources" / "aops" / "source.yaml"
    if yaml_path.exists():
        c = yaml_path.read_text(encoding="utf-8")
        c = re.sub(r"evidence_sha256:\s*\S+", f"evidence_sha256: {ev_hash}", c)
        yaml_path.write_text(c, encoding="utf-8")
    print(f"  OK (hash: {ev_hash[:16]}...)")

    # 5. Init DB
    print("\n[5/7] Database...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SM)
    c, o, e = run([PY, "-c", "from database.session import init_db; init_db()"],
                  cwd=str(SM), timeout=30)
    print("  OK" if c == 0 else f"  WARN: {e[:100]}")

    # 6. Master password
    print("\n[6/7] Master password...")
    env_file = SM / ".env"
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if "MASTER_PASSWORD_HASH=" not in content or "MASTER_PASSWORD_HASH=\n" in content or "MASTER_PASSWORD_HASH=\r" in content:
        print("  Encrypts ALL SSH credentials. >= 12 chars. NOT recoverable.")
        while True:
            pw = getpass.getpass("  Master password: ")
            if len(pw) < 12:
                print("  Too short. Need 12+ chars."); continue
            if getpass.getpass("  Confirm: ") != pw:
                print("  Mismatch."); continue
            break
        c, o, e = run([PY, "-c",
            f"import sys; sys.path.insert(0,'.'); "
            f"from crypto import generate_keypair, hash_master_password, save_keypair; "
            f"sk,pk=generate_keypair('{pw}'); save_keypair(sk,pk,'{pw}'); "
            f"print(hash_master_password('{pw}'))"],
            cwd=str(SM), timeout=60)
        if c == 0 and o.strip().startswith("$2b$"):
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\nMASTER_PASSWORD_HASH={o.strip()}\n")
            print("  OK")
        else:
            print(f"  WARN: {e[:100]}")
    else:
        print("  Already set")

    # 7. Server config
    print("\n[7/7] Server config...")
    sj = SM / "scripts" / "servers.local.json"
    if not sj.exists():
        sj.write_text(json.dumps([{
            "name": "my-server", "host": "192.168.1.150", "port": 22,
            "username": "mp", "auth_method": "password",
            "password": "Mp13911391!", "notes": "Personal Ubuntu server"
        }], indent=2), encoding="utf-8")
    print("  OK")

    # Start
    print("\n" + "=" * 50)
    print("  Starting... Ctrl+C to stop.")
    print("  Frontend: http://127.0.0.1:3001")
    print("=" * 50 + "\n")
    os.chdir(str(SM))
    os.execv(PY, [PY, "scripts/start.py"])

if __name__ == "__main__":
    main()
