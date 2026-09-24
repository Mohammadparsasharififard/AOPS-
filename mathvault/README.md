# MathVault

**Personal Offline Mathematics Competition Archive** — production-ready.

MathVault crawls **publicly accessible, archive-permitted** competition content
from allowlisted sources, stores it locally, and serves a searchable offline
web app so you can read and search it without internet.

> **Important**: The crawler respects `robots.txt`, only fetches URLs whose
> domain AND path prefix are in your allowlist, and never bypasses any
> login, CAPTCHA, paywall, or access control. There is no bypass code in
> this repository.

---

## Features

- Generic archive engine — change config, not code, to point at a different source
- BFS discovery with depth/page limits, politeness delay, retry/backoff
- ETag / Last-Modified conditional requests for incremental sync
- Full version history (every change creates a new immutable PageVersion)
- Offline-first: once archived, the web app needs no internet
- SQLite FTS5 (dev) / PostgreSQL FTS (prod) full-text search
- Admin sync dashboard with manual trigger
- CLI for crawl / sync / status / search / backup / restore
- Docker Compose deployment with persistent volumes
- Systemd timer for automatic sync
- Security: allowlist, SSRF guard, path traversal guard, HTML sanitization,
  basic-auth admin, rate limiting, no proxy
- Lightweight UI: dark mode, responsive, LaTeX rendering (KaTeX)

---

## Repository structure

```
mathvault/
├── crawler/         # Generic crawler (discovery, fetcher, parser, scheduler, storage)
├── api/             # FastAPI backend (routes, services)
├── database/        # SQLAlchemy models + migrations
├── cli/             # `mathvault` CLI
├── frontend/        # Next.js lightweight UI
├── scripts/         # backup.sh, restore.sh, entrypoint.sh
├── systemd/         # systemd timer + service
├── config/          # selectors.example.yaml
├── docker-compose.yml
├── Dockerfile.api
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Installation

### Option A — Local Python (development with SQLite)

```bash
git clone <your-repo> mathvault
cd mathvault

# Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .

# Configure
cp .env.example .env
# Edit .env — fill in ARCHIVE_ALLOWED_DOMAINS, ARCHIVE_ALLOWED_PATH_PREFIXES,
# ARCHIVE_START_URLS

# Initialize database
mathvault init-db

# Generate admin password hash (optional for dev)
mathvault hash-password "your-admin-password"
# Copy the output into ADMIN_PASSWORD_HASH in .env

# Run a dry-run crawl to see what would be fetched
mathvault crawl --dry-run

# Run a real crawl
mathvault crawl

# Check status
mathvault status

# Start the API
mathvault serve
```

### Option B — Docker Compose (production with PostgreSQL)

```bash
git clone <your-repo> mathvault
cd mathvault

cp .env.example .env
# Edit .env — fill in allowlist, POSTGRES_PASSWORD, ADMIN_PASSWORD_HASH, SECRET_KEY

# Start services
docker compose up -d

# Run an initial crawl inside the API container
docker compose exec mathvault-api python -m cli.mathvault crawl

# Frontend: http://localhost:3000
# API docs:    http://localhost:8000/api/docs
```

### Option C — Bare-metal Ubuntu + systemd

```bash
sudo mkdir /opt/mathvault
sudo chown $USER /opt/mathvault
git clone <your-repo> /opt/mathvault
cd /opt/mathvault

python3 -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env
# Edit .env

.venv/bin/python -m cli.mathvault init-db

# Install systemd units
sudo cp systemd/mathvault-update.service /etc/systemd/system/
sudo cp systemd/mathvault-update.timer  /etc/systemd/system/
# Edit the .service file if your install path differs from /opt/mathvault

sudo systemctl daemon-reload
sudo systemctl enable --now mathvault-update.timer

# Run the API as a systemd service too (optional):
# sudo tee /etc/systemd/system/mathvault-api.service <<EOF
# [Unit]
# Description=MathVault API
# After=network.target
#
# [Service]
# WorkingDirectory=/opt/mathvault
# EnvironmentFile=/opt/mathvault/.env
# ExecStart=/opt/mathvault/.venv/bin/python -m cli.mathvault serve
# Restart=always
#
# [Install]
# WantedBy=multi-user.target
# EOF
# sudo systemctl enable --now mathvault-api
```

---

## Configuration

All config is in `.env`. See `.env.example` for the full list. Key settings:

| Variable | Purpose |
|----------|---------|
| `ARCHIVE_ALLOWED_DOMAINS` | Comma-separated domains. **Required.** |
| `ARCHIVE_ALLOWED_PATH_PREFIXES` | Comma-separated path prefixes. |
| `ARCHIVE_START_URLS` | Comma-separated start URLs for the crawler. |
| `CRAWL_MAX_DEPTH` | BFS depth limit (default 5). |
| `CRAWL_MAX_PAGES` | Hard cap on pages per crawl run (default 1000). |
| `CRAWL_DELAY_SECONDS` | Politeness delay (default 2, minimum 0.5). |
| `CRAWL_RESPECT_ROBOTS` | Boolean (default true). |
| `SYNC_INTERVAL_HOURS` | Systemd timer interval (default 2). |
| `DATABASE_URL` | SQLite (`sqlite:///./data/mathvault.db`) or PostgreSQL. |
| `DB_ENGINE` | `sqlite` or `postgres`. |
| `SECRET_KEY` | Secret for session signing. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` | Admin basic-auth credentials. |

---

## First crawl (sanity check)

```bash
# Dry run — lists URLs the crawler WOULD fetch
mathvault crawl --dry-run

# Verify the output is sane. Then run a real crawl:
mathvault crawl

# See the result
mathvault status
```

If the dry-run shows no URLs:
- Check `ARCHIVE_ALLOWED_DOMAINS` is set
- Check `ARCHIVE_START_URLS` is correct
- Check `ARCHIVE_ALLOWED_PATH_PREFIXES` matches the source URL paths

---

## Using the Web App

After starting the API (`mathvault serve`) and the frontend (`cd frontend && npm install && npm run dev`):

| Page | Purpose |
|------|---------|
| `/` | Homepage with archive stats |
| `/contests` | All contests |
| `/contests/international` | International contests only |
| `/contests/national-regional` | National & regional contests |
| `/contests/{slug}` | Contest detail with year list |
| `/contests/{slug}/{year}` | Year detail with problems + packs |
| `/countries` | Countries / regions (auto-discovered) |
| `/countries/{slug}` | Country detail with contests |
| `/problems` | Problem browser (paginated) |
| `/problems/{id}` | Problem detail with prev/next navigation + LaTeX rendering |
| `/search` | Full-text search |
| `/admin/sync` | Admin sync dashboard (basic-auth) |
| `/updates` | Recent crawl runs |

---

## CLI reference

```bash
mathvault crawl            # Run a crawl pass
mathvault crawl --dry-run  # List URLs without fetching
mathvault sync             # Alias of `crawl` (timer-equivalent)
mathvault status           # Show archive stats + last crawl
mathvault search "query"   # Search archive
mathvault search "geometry" --type problem --limit 20
mathvault backup           # Create a backup
mathvault restore FILE     # Restore from a backup
mathvault init-db          # Initialize database tables
mathvault hash-password P  # Generate admin password hash
mathvault serve            # Start API server (uvicorn)
```

---

## Backup & restore

### Backup

```bash
./scripts/backup.sh                          # default output: ./backups/mathvault-<ts>.tar.gz
./scripts/backup.sh /path/to/backup.tar.gz   # custom output path
RETENTION_DAYS=30 ./scripts/backup.sh         # keep last 30 days
```

Backs up:
- Database (SQLite copy OR PostgreSQL pg_dump)
- `archive/pages/` and `archive/assets/`
- `.env` (if present)
- `config/selectors.yaml` (if present)

### Restore

```bash
./scripts/restore.sh ./backups/mathvault-20260101-120000.tar.gz
```

Verifies SHA256, stops services, extracts, restores DB + archive, prompts for `.env` overwrite.

For automated daily backups (crontab):
```
0 3 * * * /opt/mathvault/scripts/backup.sh >> /var/log/mathvault-backup.log 2>&1
```

---

## Systemd timer

The timer runs every 2 hours by default. To change:

```bash
sudo systemctl edit mathvault-update.timer
# Add an override:
[Timer]
OnCalendar=*-*-* 00/4:00:00   # every 4 hours instead
```

To check status:
```bash
systemctl status mathvault-update.timer
systemctl list-timers mathvault-update.timer
journalctl -u mathvault-update.service -n 200
```

---

## Security model summary

| Layer | Protection |
|-------|------------|
| Crawler | Allowlist (domain + path + content-type), robots.txt, SSRF guard, no proxies |
| Storage | SHA-256-based filesystem paths (no user input) |
| DB | Foreign keys ON, no raw SQL without bound params |
| API | CORS restricted, rate limit, GZip, basic-auth for admin |
| HTML | Sanitized with `bleach` (XSS protection) |
| Admin | HTTP Basic Auth (bcrypt-hashed password) |
| .env | Git-ignored, mode 600 recommended |
| PostgreSQL | Listens on 127.0.0.1 only (inside Docker network when composed) |
| Path traversal | `safe_join` + `Path.resolve()` + `relative_to()` checks |

---

## Troubleshooting

### "ARCHIVE_ALLOWED_DOMAINS is empty"
The crawler refuses to start without an allowlist. Set this in `.env`.

### Crawler fetches 0 pages
1. Check `mathvault crawl --dry-run` output.
2. Verify the start URL's domain matches `ARCHIVE_ALLOWED_DOMAINS`.
3. Verify the start URL's path starts with one of `ARCHIVE_ALLOWED_PATH_PREFIXES`.
4. Check `logs/crawler.log` for allowlist rejections.

### "FTS5 not available"
You're on an older SQLite without FTS5. Either:
- Upgrade SQLite (≥3.9.0), or
- Set `DB_ENGINE=postgres` and use PostgreSQL.

### Frontend can't reach API
- Check `NEXT_PUBLIC_API_BASE` in `frontend/.env.local` (defaults to `http://localhost:8000`).
- In Docker: both containers are on the same network; the API is at `http://mathvault-api:8000`.

### `mathvault restore` fails
- Verify SHA256 file exists alongside the backup (`<file>.sha256`).
- Run with `bash -x scripts/restore.sh <file>` for verbose output.

### Disk full
- Check `archive/pages/` size: `du -sh archive/pages`
- Consider lowering `CRAWL_MAX_PAGES` or `CRAWL_MAX_DEPTH`.
- Old PageVersions are NOT auto-pruned — implement a retention script if needed.

### API returns 401 for admin
- Verify `ADMIN_PASSWORD_HASH` is set (not empty) in `.env`.
- Generate a hash: `mathvault hash-password "your-password"`.
- Restart the API.

---

## License

MIT. Use at your own risk. **You are responsible for ensuring your use
complies with the terms of service / license of any source you archive.**
