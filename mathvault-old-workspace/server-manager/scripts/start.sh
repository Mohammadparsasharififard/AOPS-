#!/usr/bin/env bash
# Start both API and frontend of Personal Server Manager locally.
# Useful for development. For production, use docker compose.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "[start] Starting Personal Server Manager"
echo "  API:     http://127.0.0.1:7700"
echo "  Frontend: http://127.0.0.1:3001"
echo ""

# Check first-run setup
if [[ ! -f .env ]] || ! grep -q MASTER_PASSWORD_HASH .env || \
   [[ "$(grep -E '^MASTER_PASSWORD_HASH=' .env | cut -d= -f2)" == "" ]]; then
  echo "[start] First-run setup required. Run: ./scripts/setup.sh"
  exit 1
fi

# Start API in background
.venv/bin/python -m cli.server_manager serve &
API_PID=$!
echo "[start] API PID: $API_PID"

# Start frontend in foreground (Ctrl-C kills both via trap)
trap "kill $API_PID 2>/dev/null || true" EXIT INT TERM

cd frontend
if [[ ! -d node_modules ]]; then
  echo "[start] Installing frontend deps…"
  npm install --legacy-peer-deps
fi
npm run dev
