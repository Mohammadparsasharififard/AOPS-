#!/usr/bin/env bash
# Entrypoint for MathVault API/worker container.
# Initializes DB on first run, then dispatches to the requested command.
set -euo pipefail

# Wait for DB if PostgreSQL
if [[ "${DATABASE_URL:-}" == postgres* ]]; then
    echo "[mathvault] Waiting for PostgreSQL…"
    # Extract host/port
    PG_HOST="$(echo "$DATABASE_URL" | sed -E 's#.*@([^:/]+)(:[0-9]+)?/.*#\1#')"
    PG_PORT="$(echo "$DATABASE_URL" | sed -E 's#.*:(4[0-9]{3}|5[0-9]{3}|6[0-9]{3}).*#\1#')"
    PG_PORT="${PG_PORT:-5432}"
    for i in $(seq 1 30); do
        if python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('$PG_HOST', $PG_PORT)); s.close()" 2>/dev/null; then
            echo "[mathvault] PostgreSQL is up."
            break
        fi
        echo "  retry $i/30…"
        sleep 2
    done
fi

# Initialize DB schema (idempotent)
echo "[mathvault] Ensuring DB schema…"
MATHVAULT_SKIP_ALLOWLIST_CHECK=1 python -c "from database.session import init_db; init_db()"

case "${1:-serve}" in
    serve)
        shift || true
        exec uvicorn api.main:app \
            --host "${API_HOST:-0.0.0.0}" \
            --port "${API_PORT:-8000}" \
            --workers "${API_WORKERS:-2}" \
            "${@}"
        ;;
    crawl|sync)
        exec python -m cli.mathvault "$@"
        ;;
    worker)
        # Long-running worker: loop with SYNC_INTERVAL_HOURS
        INTERVAL="${SYNC_INTERVAL_HOURS:-2}"
        INTERVAL_SEC=$((INTERVAL * 3600))
        while true; do
            echo "[mathvault-worker] Running sync at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            python -m cli.mathvault sync || true
            echo "[mathvault-worker] Sleeping ${INTERVAL}h…"
            sleep "$INTERVAL_SEC"
        done
        ;;
    *)
        exec "$@"
        ;;
esac
