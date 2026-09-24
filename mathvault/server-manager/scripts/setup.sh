#!/usr/bin/env bash
# First-run setup for Personal Server Manager.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Personal Server Manager — First-run setup ==="

# Step 1: Python venv
if [[ ! -d .venv ]]; then
  echo "[setup] Creating Python virtualenv…"
  python3 -m venv .venv
fi

echo "[setup] Installing Python dependencies…"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet \
  "fastapi>=0.110.0" \
  "uvicorn[standard]>=0.27.0" \
  "sqlalchemy>=2.0.25" \
  "paramiko>=3.4.0" \
  "bcrypt>=4.1.2" \
  "pynacl>=1.5.0" \
  "click>=8.1.7" \
  "rich>=13.7.0" \
  "pydantic>=2.6.0" \
  "pydantic-settings>=2.1.0" \
  "python-dotenv>=1.0.1" \
  "python-multipart>=0.0.9" \
  "itsdangerous>=2.1.2"

# Step 2: Copy .env.example to .env if missing
if [[ ! -f .env ]]; then
  echo "[setup] Copying .env.example to .env…"
  cp .env.example .env
fi

# Step 3: Initialize DB
echo "[setup] Initializing database…"
.venv/bin/python -c "from database.session import init_db; init_db()"

# Step 4: Set master password (interactive)
echo ""
echo "=== Master Password Setup ==="
echo "The master password encrypts ALL SSH credentials stored by this app."
echo "It is NOT recoverable if lost. Choose something strong (≥12 chars)."
echo ""
.venv/bin/python -m cli.server_manager setup

# Step 5: Frontend deps
echo ""
echo "=== Frontend setup ==="
cd frontend
if [[ ! -d node_modules ]]; then
  echo "[setup] Installing frontend dependencies…"
  npm install --legacy-peer-deps
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the app:"
echo "  ./scripts/start.sh"
echo ""
echo "Then open http://127.0.0.1:3001 in your browser."
