#!/usr/bin/env bash
# =============================================================================
# MathVault restore script
# =============================================================================
# Restores from a backup created by `scripts/backup.sh`.
#
# Usage:
#   ./scripts/restore.sh <backup.tar.gz>
#
# This script:
#   - Stops the API/worker services (if running under docker compose)
#   - Extracts the backup to a temp dir
#   - Restores the database file(s)
#   - Restores the archive directory
#   - Restores .env (with confirmation)
#   - Prompts you to restart services
# =============================================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <backup.tar.gz>"
    exit 1
fi

BACKUP_FILE="$1"
if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "[restore] [ERROR] Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Resolve project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Verify SHA256 if available
SHA_FILE="${BACKUP_FILE}.sha256"
if [[ -f "$SHA_FILE" ]]; then
    if ! sha256sum -c "$SHA_FILE" 2>/dev/null; then
        echo "[restore] [ERROR] SHA256 verification failed!"
        exit 2
    fi
    echo "[restore] SHA256 OK"
fi

echo "[restore] Reading .env from current install (if any)…"
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi
DB_ENGINE="${DB_ENGINE:-sqlite}"
DB_URL="${DATABASE_URL:-sqlite:///./data/mathvault.db}"

# Stop services if docker compose present
if [[ -f docker-compose.yml ]]; then
    echo "[restore] Stopping docker compose services…"
    docker compose stop mathvault-api mathvault-worker 2>/dev/null || true
fi

# Extract to temp dir
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
echo "[restore] Extracting to $TMP_DIR"
tar -xzf "$BACKUP_FILE" -C "$TMP_DIR"

# --- Database restore ----------------------------------------------------------
if [[ "$DB_ENGINE" == "sqlite" ]]; then
    DB_PATH="${DB_URL#sqlite:///}"
    DB_PATH="${DB_PATH#sqlite://}"
    mkdir -p "$(dirname "$DB_PATH")"
    if [[ -f "$TMP_DIR/mathvault.db" ]]; then
        echo "[restore] Restoring SQLite to $DB_PATH"
        cp "$TMP_DIR/mathvault.db" "$DB_PATH"
        [[ -f "$TMP_DIR/mathvault.db-wal" ]] && cp "$TMP_DIR/mathvault.db-wal" "${DB_PATH}-wal"
        [[ -f "$TMP_DIR/mathvault.db-shm" ]] && cp "$TMP_DIR/mathvault.db-shm" "${DB_PATH}-shm"
    else
        echo "[restore] [WARN] No SQLite file in backup"
    fi
elif [[ "$DB_ENGINE" == "postgres" ]] || [[ "$DB_URL" == postgres* ]]; then
    if [[ -f "$TMP_DIR/mathvault.dump" ]]; then
        echo "[restore] Restoring PostgreSQL from pg_dump -Fc"
        if ! command -v pg_restore &>/dev/null; then
            echo "[restore] [ERROR] pg_restore not installed"
            exit 2
        fi
        PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_restore -d "$DB_URL" --clean --if-exists "$TMP_DIR/mathvault.dump" || \
            echo "[restore] [WARN] pg_restore had non-fatal errors"
    fi
fi

# --- Archive restore -----------------------------------------------------------
ARCHIVE_DIR="${ARCHIVE_DIR:-./archive}"
mkdir -p "$ARCHIVE_DIR"
if [[ -d "$TMP_DIR/archive" ]]; then
    echo "[restore] Restoring archive to $ARCHIVE_DIR"
    # Remove old archive contents (with confirmation)
    read -r -p "Wipe existing $ARCHIVE_DIR contents? [y/N] " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
        rm -rf "${ARCHIVE_DIR:?}/pages" "${ARCHIVE_DIR:?}/assets" "${ARCHIVE_DIR:?}/index"
    fi
    cp -r "$TMP_DIR/archive/pages" "$ARCHIVE_DIR/" 2>/dev/null || true
    cp -r "$TMP_DIR/archive/assets" "$ARCHIVE_DIR/" 2>/dev/null || true
    cp -r "$TMP_DIR/archive/index" "$ARCHIVE_DIR/" 2>/dev/null || true
fi

# --- Config restore ------------------------------------------------------------
if [[ -f "$TMP_DIR/env" ]]; then
    if [[ -f .env ]]; then
        read -r -p "Overwrite existing .env with backup? [y/N] " CONFIRM
        if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
            cp "$TMP_DIR/env" .env
            echo "[restore] .env restored"
        fi
    else
        cp "$TMP_DIR/env" .env
        echo "[restore] .env created"
    fi
fi
if [[ -f "$TMP_DIR/config/selectors.yaml" ]]; then
    mkdir -p config
    cp "$TMP_DIR/config/selectors.yaml" config/
    echo "[restore] selectors.yaml restored"
fi

echo ""
echo "[restore] Restore complete."
echo "[restore] Restart services with: docker compose up -d   (or: systemctl restart mathvault-update.service)"
