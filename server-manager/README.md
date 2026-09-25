# Personal Server Manager

**Laptop-side control panel for SSH-reachable personal servers.**

Run this app on your **laptop** (not your server). Register SSH credentials
for your personal servers, then deploy code, view status, restart services,
and access the offline archive — all from a single web UI.

---

## Security model

- **Encrypted at rest** — SSH passwords/keys are encrypted with a public key
  (PyNaCl sealed box). The private key is itself encrypted with your master
  password (Argon2-derived symmetric key).
- **Master password** is set on first run, **not stored** — only its bcrypt hash
  is in `.env`. The plaintext master password lives only in process memory while
  the app is running.
- **Local-only** — Both API (port 7700) and frontend (port 3001) bind to
  `127.0.0.1`. They are not reachable from outside your laptop.
- **Audit log** — Every SSH command, deploy, and service action is logged to
  an append-only `audit_log` table.
- **No bypass logic** — This app does not include any site-targeting code or
  CAPTCHA/access-control bypass logic. It is a generic SSH operations tool.

---

## Quick start

<<<<<<< HEAD
```bash
git clone <repo> server-manager
cd server-manager

# First-run setup (creates venv, installs deps, sets master password)
./scripts/setup.sh

# Start the app
./scripts/start.sh
=======
### On Windows

```powershell
# First-run setup (PowerShell — no bash required)
.\scripts\setup.ps1
# or just double-click scripts\setup.bat

# Start the app
.\scripts\start.ps1
# or double-click scripts\start.bat
>>>>>>> 5ff3975d193301b6e482120120274a12949b6e9c

# Open in browser:
#   http://127.0.0.1:3001
```

<<<<<<< HEAD
Or with Docker Compose:
=======
**Requirements**: Python 3.11+ from https://python.org (check "Add Python to PATH" during install).

### On macOS / Linux

```bash
./scripts/setup.sh
./scripts/start.sh
```

Or the cross-platform Python script (works everywhere):

```bash
python scripts/setup.py
python scripts/start.py
```

### With Docker Compose
>>>>>>> 5ff3975d193301b6e482120120274a12949b6e9c

```bash
cp .env.example .env
# Edit .env — set MASTER_PASSWORD_HASH via `python -m cli.server_manager setup`
docker compose up -d
```

---

## Usage

### 1. Set master password (first run only)

<<<<<<< HEAD
```bash
./scripts/setup.sh
# or manually:
python -m cli.server_manager setup
```

### 2. Start the app

=======
**Windows (PowerShell):**
```powershell
.\scripts\setup.ps1
```

**Windows (CMD):**
```cmd
scripts\setup.bat
```

**macOS / Linux:**
```bash
./scripts/setup.sh
```

**Cross-platform:**
```bash
python scripts/setup.py
```

### 1b. (Optional) Pre-seed your servers

If you have a fixed list of personal servers with their SSH credentials, you
can register them all at once via a JSON file instead of typing them through
the UI.

1. Copy the example file:
   - Windows: `copy scripts\servers.local.json.example scripts\servers.local.json`
   - macOS/Linux: `cp scripts/servers.local.json.example scripts/servers.local.json`
2. Edit `scripts/servers.local.json` with your server's name, host, username,
   password, and notes (see the example file for the schema).
3. Run the seed script (will ask for your master password to encrypt the
   credentials):
   ```
   python scripts/seed-servers.py
   ```

**Security**: `servers.local.json` is gitignored — it will never be committed
to GitHub. The plaintext password is read once, encrypted with the master
password (sealed box), and inserted into the local DB. The plaintext is
discarded immediately.

You can re-run the seed script any time — it will **update** existing servers
by name (so changing a password is as simple as editing the JSON and re-running).

### 2. Start the app

**Windows (PowerShell):**
```powershell
.\scripts\start.ps1
```

**Windows (CMD):**
```cmd
scripts\start.bat
```

**macOS / Linux:**
>>>>>>> 5ff3975d193301b6e482120120274a12949b6e9c
```bash
./scripts/start.sh
```

<<<<<<< HEAD
=======
**Cross-platform:**
```bash
python scripts/start.py
```

>>>>>>> 5ff3975d193301b6e482120120274a12949b6e9c
### 3. Sign in

Open `http://127.0.0.1:3001`, enter your master password.

### 4. Register a server

Click "Add server". Provide:
- Name (display)
- Host (IP or domain)
- Port (default 22)
- Username (default `root`)
- Authentication method:
  - **Password** — paste the SSH password
  - **Private key** — paste a PEM-format key

Credentials are encrypted immediately and stored in SQLite locally.

### 5. Check server status

Click a server → "Status" tab → "Refresh status" to get:
- Online check
- Hostname + kernel
- Uptime + load average
- CPU cores
- Memory used / total
- Disk used / total

### 6. Add a deployment

Server detail → "Deployments" tab → "+ Add deployment". Configure:
- **Deploy path** — absolute path on server (e.g., `/opt/myapp`)
- **Git URL** — optional. If set, the deploy will `git clone` or `git pull`
- **Systemd service** — optional. Restart after deploy
- **Deploy script** — optional. Path relative to deploy_path that runs after pull

### 7. Deploy

Click "Deploy" button. The manager will:
1. SSH in
2. `mkdir -p` the deploy path
3. `git clone` (first time) or `git fetch && git reset --hard origin/<branch>`
4. Run the deploy script if configured
5. Restart the systemd service if configured
6. Log everything to the audit log

### 8. View audit log

"Logs" page shows the last 100 actions with command, exit code, status, timestamps.

### 9. Access MathVault offline archive

"Archive" page links to your MathVault instance (configured via
`MATHVAULT_FRONTEND_URL` in `.env`).

---

## CLI

```bash
server-manager init          # initialize DB
server-manager setup        # set master password (first-run)
server-manager serve        # start API server
server-manager hash-password P  # generate bcrypt hash (utility)
```

---

## Configuration

All config in `.env`. Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_HOST` | `127.0.0.1` | API bind host (don't change to 0.0.0.0!) |
| `APP_PORT` | `7700` | API port |
| `DATABASE_URL` | `sqlite:///./data/server-manager.db` | Local SQLite only |
| `MASTER_PASSWORD_HASH` | (set on first run) | Bcrypt hash of master password |
| `SSH_DEFAULT_PORT` | `22` | Default port for new servers |
| `SSH_DEFAULT_USER` | `root` | Default user for new servers |
| `MATHVAULT_FRONTEND_URL` | `http://localhost:3000` | MathVault UI URL |
| `MATHVAULT_API_URL` | `http://localhost:8000` | MathVault API URL |

---

## What this app is NOT

- ❌ It is **not** a CAPTCHA bypass tool
- ❌ It does **not** contain site-specific crawling logic
- ❌ It does **not** authenticate to any third-party service on your behalf
- ❌ It is **not** a multi-user system — single master password only

If you need to crawl a specific source, use MathVault (the **separate** generic
archive engine) and configure its `.env` with the source's domain + start URLs.
MathVault will respect the source's `robots.txt` and ToS — it will not bypass
access controls.

---

## Troubleshooting

<<<<<<< HEAD
### "Master password not set"
Run `./scripts/setup.sh` (or `python -m cli.server_manager setup`).

### "Failed to decrypt password — wrong master password?"
Either the master password you entered at login is wrong, or the keypair file
(`data/keypair.json`) is corrupted. Re-run setup after deleting `data/`.
=======
### "The system cannot find the path specified" (Windows + bash)
You probably ran `setup.sh` from a bash emulator on Windows (Git Bash / VSCode bash).
Use the Windows-native scripts instead:
- PowerShell: `.\scripts\setup.ps1`
- CMD: `scripts\setup.bat`
- Or universal: `python scripts\setup.py`

### "python is not recognized" (Windows)
Python is not installed or not on PATH. Install Python 3.11+ from https://python.org
— during install, **check "Add Python to PATH"**. Then close and reopen your terminal.

### "Master password not set"
- Windows: `.\scripts\setup.ps1`
- macOS/Linux: `./scripts/setup.sh`
- Cross-platform: `python scripts/setup.py`

### "Failed to decrypt password — wrong master password?"
Either the master password you entered at login is wrong, or the keypair file
(`data/keypair.json`) is corrupted. Re-run setup after deleting the `data/`
directory.
>>>>>>> 5ff3975d193301b6e482120120274a12949b6e9c

### "Connection refused" when testing server
- Verify the server is reachable: `ssh user@host` from your laptop
- Verify the SSH port is open on the server's firewall
- Verify the username has shell access

### "Permission denied (publickey)"
- For password auth: verify the password is correct
- For key auth: verify the private key matches a public key in the server's `~/.ssh/authorized_keys`

### Frontend can't reach API
Check `NEXT_PUBLIC_API_BASE` in `frontend/.env.local` (defaults to `http://127.0.0.1:7700`).

---

## License

MIT. Use at your own risk. **You are responsible for the security of your
SSH credentials and the consequences of any commands you run via this tool.**
