# AOPS- Repository

This repository contains **two separate applications**:

## 1. `mathvault/` — Personal Offline Mathematics Competition Archive

A generic archive engine that crawls publicly accessible, archive-permitted
content from allowlisted sources and stores it locally for offline browsing
and search.

**Important**: The MathVault crawler respects `robots.txt` and the configured
allowlist. It does NOT bypass CAPTCHA, login walls, paywalls, or any access
control. There is no site-specific crawling code in the repository —
pointing it at a specific source is done via `.env` configuration only.

See `mathvault/README.md` for installation, configuration, and usage.

## 2. `server-manager/` — Personal Server Manager

A laptop-side control panel for managing SSH-reachable personal servers.
Stores SSH credentials encrypted with a master password, deploys code via
SSH/git, restarts services, and shows server status.

**Important**: The Server Manager is a generic SSH operations tool. It
contains NO CAPTCHA bypass logic and NO site-targeting code.

See `server-manager/README.md` for installation, configuration, and usage.

---

## Quick reference

| App | Path | Runs on | Port |
|-----|------|---------|------|
| MathVault API | `mathvault/api/` | Server (or local) | 8000 |
| MathVault UI | `mathvault/frontend/` | Server (or local) | 3000 |
| MathVault Crawler | `mathvault/crawler/` | Server (CLI or systemd timer) | — |
| Server Manager API | `server-manager/api/` | **Laptop only** | 7700 |
| Server Manager UI | `server-manager/app/` | **Laptop only** | 3001 |

---

## Security disclaimers

- **MathVault** respects robots.txt and your allowlist. It will refuse to
  fetch URLs outside the allowlist. It does not bypass CAPTCHA or any other
  access control. You are responsible for ensuring you have permission to
  archive any source you point it at.
- **Server Manager** stores SSH credentials encrypted at rest with your
  master password. It binds to `127.0.0.1` only — it is not reachable from
  outside your laptop. You are responsible for the security of your master
  password and the consequences of any commands you run via the tool.

Neither application includes:
- CAPTCHA bypass logic
- Site-specific crawling code
- Authentication bypass logic
- Access-control circumvention

If you need to archive a specific source, verify you have written permission
from the source, then configure MathVault's `.env` accordingly.

---

## License

MIT. See each app's README for details.
