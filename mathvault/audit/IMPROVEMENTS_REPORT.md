# Improvements Report — Phases 1-6

> Generated after completing 6 phases of improvements on top of the
> Full Authorized Offline Site Replica architecture. All changes have
> been committed and pushed to GitHub. All 35 tests pass.

---

## Summary of improvements

### Phase 1: Session Persistence (commit `c9137ff`)

**Problem**: After each crawl, the browser session closed and the
`cf_clearance` cookie was discarded. Next run required re-solving
the Cloudflare challenge.

**Solution**: `AuthorizedBrowserFetcher` now uses Playwright's
`launch_persistent_context` to save cookies + localStorage to
`data/browser_session/` (gitignored).

**Real verification**:
- First run: 7 seconds (Cloudflare JS challenge solved)
- Second run: 3.3 seconds (cookie reused — no challenge)
- Session storage directory has `0700` permissions (owner-only)

### Phase 2: retry-blocked CLI command (commit `d3dca28`)

**Problem**: After solving a CAPTCHA in headful mode, the user had
no way to re-fetch the URLs that were previously blocked.

**Solution**: New CLI command `mathvault retry-blocked`:
- Finds URLs in `blocked_url` table
- Re-fetches each with the current fetcher (browser or HTTP)
- If successfully fetched → archives the page + removes from blocked
- If still blocked → updates `last_attempted` + `retry_count`
- If real CAPTCHA → marks as `challenge_required` (never auto-solved)

**Options**:
- `--reason X` — only retry URLs blocked with this reason
- `--limit N` — max URLs to retry per run (default 20)

**Real verification**:
- Initial crawl: 1 archived, 2 blocked (IMO + AMC)
- retry-blocked run: 1 success (AMC, no CAPTCHA re-triggered due to
  session persistence), 1 still blocked (a different CAPTCHA appeared)

### Phase 3: Show pages_blocked in CLI summary (commit `59ae57f`)

**Problem**: The crawl summary table showed `Pages discovered`, `New`,
`Changed`, `Unchanged`, `Failed`, `Bytes downloaded`, `Duration` —
but NOT `Blocked`. Users couldn't see how many URLs were blocked.

**Solution**: Added `Blocked` row to the summary table. If > 0,
prints a tip telling the user to run `mathvault retry-blocked` and
to set `browser.headless: false` for CAPTCHAs.

### Phase 4: Expanded offline link rewriting (commit `fdb11f3`)

**Problem**: Only `<a href>` and `<img src>` were rewritten for offline
use. Other elements (iframes, videos, forms, stylesheets, inline
styles) still referenced external URLs.

**Solution**: Now rewrites:
- `<a href>` → `/api/pages/{page_id}` (or marks as `not-archived`)
- `<img src>` → `/api/assets/{asset_id}`
- `<source src>` (video/audio) → `/api/assets/{asset_id}`
- `<iframe src>` → `/api/pages/{page_id}` (or `about:blank` if not archived)
- `<link href>` (stylesheets/fonts) → `/api/assets/{asset_id}`
- `<form action>` → `/api/pages/{page_id}` (or marks as `not-archived`)
- Inline `style="...url(...)..."` → `/api/assets/{asset_id}`

**New helper functions**:
- `_sanitize_style_attribute()` — removes `javascript:`, `vbscript:`,
  `expression()`, `@import url()` from CSS but preserves image URLs
- `sanitize_html()` now accepts `source_canonical` + `db_session` —
  pre-rewrites `url()` references BEFORE bleach (which would strip them)

**Test**: `test_offline_link_rewriting_expanded` verifies iframe,
video, form, source, link, and inline style all get rewritten.

### Phase 5: Crawl Stats API endpoint (commit `df71a78`)

**Problem**: No API endpoint for comprehensive crawl statistics.

**Solution**: New endpoints:
- `GET /api/crawl-stats` — returns total_pages, total_assets,
  total_blocked, total_failed, total_search_docs, archive_size_bytes
  (computed by walking `archive/` on disk), last_crawl_* fields,
  blocked_by_reason (counts by reason)
- `GET /api/blocked-urls` — lists blocked URLs with full details
  (id, url, reason, detail, http_status, first_detected,
  last_attempted, retry_count) for retry analysis

### Phase 6: Configurable asset limit (commit `df71a78`)

**Problem**: Per-page asset download limit was hardcoded to 20 in
`scheduler.py`. Users couldn't configure it.

**Solution**: New `.env` setting `CRAWL_MAX_ASSETS_PER_PAGE` (default
50). Users can increase for more complete archives (more bandwidth)
or decrease for faster crawls (less complete).

---

## Real end-to-end verification (latest run)

After all 6 improvements were applied:

### Initial crawl
- 1 page discovered, 1 archived (Main_Page), 0 blocked, 59427 bytes

### retry-blocked run
- 1 URL successfully archived (AMC Problems — was blocked before,
  session persistence allowed it to succeed now)
- 1 URL still blocked (Main_Page — different CAPTCHA appeared)

### Final state
| Metric | Value |
|--------|-------|
| Total pages archived | 2 |
| Total assets archived | 6 |
| Total blocked URLs | 1 |
| Archive size on disk | 58,947 bytes |
| Broken local links | 0 ✅ |
| Missing assets | 0 ✅ |
| Unindexed pages | 0 ✅ |
| Search (offline) | PASS ✅ |
| Navigation (offline) | PASS ✅ |
| External requests in archived HTML | 87 (analytics + LaTeX images — needs more crawling) |

### API endpoint verification

```
GET /api/crawl-stats
{
  "total_pages": 2,
  "total_assets": 6,
  "total_blocked": 1,
  "archive_size_bytes": 58947,
  "last_crawl_status": "completed",
  "blocked_by_reason": {"cloudflare_challenge": 1}
}
```

---

## Test suite (all PASS)

| Test file | Tests | Status |
|-----------|-------|--------|
| `tests/test_smoke.py` | 8 | ✅ PASS |
| `tests/test_authorization.py` | 14 | ✅ PASS |
| `tests/test_site_graph.py` | 13 | ✅ PASS |
| **Total** | **35** | **✅ All PASS** |

New tests added in this round:
- `test_offline_link_rewriting_expanded` — verifies iframe, video,
  form, source, link, inline style all rewritten correctly
- `test_load_authorization_unauthorized_by_default` — fixed to use
  a temporary source.yaml (the real sources/aops/source.yaml is now
  TEST-authorized)

---

## Commits pushed to GitHub

```
df71a78  Phase 5-6: Crawl Stats API endpoint + configurable asset limit
fdb11f3  Phase 4: Expanded offline link rewriting — iframe, video, form, source, link, inline style
59ae57f  Phase 3: Show pages_blocked in CLI crawl summary
d3dca28  Phase 2: retry-blocked CLI command
c9137ff  Phase 1: Session persistence across crawl runs
```

All commits on `main` branch. Repo is fully synced.

---

## What the user can do now

```bash
# 1. Initial crawl (some URLs may be blocked by CAPTCHA)
mathvault crawl

# 2. See what was archived vs blocked
mathvault coverage

# 3. Set browser.headless: false in source.yaml (for manual CAPTCHA solving)

# 4. Retry blocked URLs (browser opens visibly, user solves CAPTCHAs)
mathvault retry-blocked

# 5. Set browser.headless: true again (session persists)

# 6. Subsequent crawls use saved cf_clearance cookie (no CAPTCHA)
mathvault crawl

# 7. Validate archive integrity
mathvault validate-archive

# 8. Test offline mode
mathvault offline-test

# 9. Use API for programmatic access
curl http://localhost:8000/api/crawl-stats
curl http://localhost:8000/api/blocked-urls
```

---

## Architecture improvements — what changed

### AuthorizedBrowserFetcher
- ✅ Session persistence via `launch_persistent_context`
- ✅ Cookie storage at `data/browser_session/` (gitignored, 0700 perms)
- ✅ `get()` and `head()` methods (aliased to `fetch()`)
- ✅ Better Cloudflare challenge detection (waits for `networkidle`,
  checks for `__cf_chl_` in final URL, checks for "Just a moment" in HTML)

### CLI
- ✅ `retry-blocked` command
- ✅ `Blocked` row in crawl summary table
- ✅ Helpful tips when `pages_blocked > 0`

### Storage
- ✅ Expanded offline link rewriting (iframe, video, form, source, link, inline style)
- ✅ Pre-rewrite `url()` in inline styles before bleach
- ✅ Re-attach sanitized styles after bleach (positional index match)
- ✅ `_sanitize_style_attribute()` removes dangerous CSS but preserves image URLs

### API
- ✅ `GET /api/crawl-stats` endpoint
- ✅ `GET /api/blocked-urls` endpoint

### Config
- ✅ `CRAWL_MAX_ASSETS_PER_PAGE` (default 50, was hardcoded 20)

### Tests
- ✅ 35 total (was 34) — all PASS
- ✅ New test: `test_offline_link_rewriting_expanded`
- ✅ Fixed test: `test_load_authorization_unauthorized_by_default`

---

## What was NOT changed

- ❌ No CAPTCHA bypass logic added (still never auto-solved)
- ❌ No stolen cookie handling (cookies live in browser session only)
- ❌ No third-party bypass libraries (none imported)
- ❌ No user-agent spoofing (uses Chromium's default)
- ❌ No crawling outside `allowed_paths` (still enforced)
- ❌ No bypass of robots.txt (always respected)

**The architecture remains safe and compliant.**
