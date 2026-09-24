#!/usr/bin/env bash
# =============================================================================
# MathVault backup script
# =============================================================================
# Backs up:
#   1. Database (SQLite file or PostgreSQL via pg_dump)
#   2. Archive directory (HTML snapshots + assets)
#   3. Configuration (".env" only — never commit to git)
#
# Output: ./backups/mathvault-<timestamp>.tar.gz
#
# Usage:
#   ./scripts/backup.sh [output_path] [--retention N]
#
# Optional crontab entry (daily at 3am):
#   0 3 * * * /opt/mathvault/scripts/backup.sh >> /var/log/mathvault-backup.log 2>&1
# =============================================================================
set -euo pipefail

# Resolve project root (this script lives in /scripts)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Source env
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
OUTPUT_PATH="${1:-./backups/mathvault-${TIMESTAMP}.tar.gz}"
RETENTION="${RETENTION_DAYS:-14}"  # days to keep backups

# Determine database backend
DB_URL="${DATABASE_URL:-sqlite:///./data/mathvault.db}"
DB_ENGINE="${DB_ENGINE:-sqlite}"

echo "[backup] Starting backup at $(date -u)"
echo "[backup] Output: $OUTPUT_PATH"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# --- 1. Database -----------------------------------------------------------------
if [[ "$DB_ENGINE" == "sqlite" ]]; then
    # Extract SQLite file path
    DB_PATH="${DB_URL#sqlite:///}"
    DB_PATH="${DB_PATH#sqlite://}"
    if [[ -f "$DB_PATH" ]]; then
        echo "[backup] SQLite backup via VACUUM INTO"
        # Use sqlite3 if available
        if command -v sqlite3 &>/dev/null; then
            sqlite3 "$DB_PATH" "VACUUM INTO '$TMP_DIR/mathvault.db'"
        else
            cp "$DB_PATH" "$TMP_DIR/mathvault.db"
        fi
        # Also back up WAL/SHM if present
        [[ -f "${DB_PATH}-wal" ]] && cp "${DB_PATH}-wal" "$TMP_DIR/mathvault.db-wal"
        [[ -f "${DB_PATH}-shm" ]] && cp "${DB_PATH}-shm" "$TMP_DIR/mathvault.db-shm"
    else
        echo "[backup] [WARN] SQLite file not found at $DB_PATH"
    fi
elif [[ "$DB_ENGINE" == "postgres" ]] || [[ "$DB_URL" == postgres* ]]; then
    echo "[backup] PostgreSQL backup via pg_dump"
    if ! command -v pg_dump &>/dev/null; then
        echo "[backup] [ERROR] pg_dump not installed"
        exit 2
    fi
    PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump "$DB_URL" -F c -f "$TMP_DIR/mathvault.dump"
else
    echo "[backup] [ERROR] Unknown DB engine: $DB_ENGINE"
    exit 2
fi

# --- 2. Archive ------------------------------------------------------------------
ARCHIVE_DIR="${ARCHIVE_DIR:-./archive}"
if [[ -d "$ARCHIVE_DIR" ]]; then
    echo "[backup] Archiving $ARCHIVE_DIR"
    cp -r "$ARCHIVE_DIR" "$TMP_DIR/archive"
else
    echo "[backup] [WARN] Archive directory not found at $ARCHIVE_DIR"
    mkdir -p "$TMP_DIR/archive"
fi

# --- 3. Config -------------------------------------------------------------------
if [[ -f .env ]]; then
    cp .env "$TMP_DIR/env"
fi
# Also back up selectors if present
if [[ -f config/selectors.yaml ]]; then
    mkdir -p "$TMP_DIR/config"
    cp config/selectors.yaml "$TMP_DIR/config/"
fi

# --- 4. Tar ---------------------------------------------------------------------
mkdir -p "$(dirname "$OUTPUT_PATH")"
echo "[backup] Compressing…"
tar -czf "$OUTPUT_PATH" -C "$TMP_DIR" .

# Compute SHA256 for integrity check
SHA=$(sha256sum "$OUTPUT_PATH" | awk '{print $1}')
echo "$SHA  $(basename "$OUTPUT_PATH")" > "${OUTPUT_PATH}.sha256"

echo "[backup] Backup complete: $OUTPUT_PATH"
echo "[backup] SHA256: $SHA"

# --- 5. Retention cleanup -------------------------------------------------------
find "$(dirname "$OUTPUT_PATH")" -name "mathvault-*.tar.gz" -mtime "+$RETENTION" -delete 2>/dev/null || true
find "$(dirname "$OUTPUT_PATH")" -name "mathvault-*.tar.gz.sha256" -mtime "+$RETENTION" -delete 2>/dev/null || true
echo "[backup] Removed backups older than $RETENTION days"
