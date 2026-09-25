# AoPS Source Adapter

This directory contains the AoPS-specific source adapter for MathVault.

## What's here

- `source.yaml` — AoPS source configuration (default: UNAUTHORIZED)
- `adapter.py` — Parses AoPS Wiki (MediaWiki) structure into MathVault's
  Contest → Year → Problem schema. **Parser only** — does NOT bypass any
  access control.
- `README.md` — This file

## Authorization

By default, this source is configured as **UNAUTHORIZED**. The crawler
will refuse to use any browser-based fetcher for AoPS until the user:

1. Places a real authorization evidence file at
   `sources/aops/evidence/authorization.{pdf,txt,png}`
2. Computes its SHA-256 and records it in `source.yaml`
3. Sets `authorization.evidence_verified: true`
4. Explicitly opts-in to each scope flag (each is `false` by default)

## What the adapter does (when authorized)

When `authorization.status = authorized` AND the user has explicitly opted
into `browser_session_allowed = true`:

1. The crawler uses `AuthorizedBrowserFetcher` (Playwright + headless Chromium)
2. The browser navigates only to URLs in `allowed_paths`
3. Cloudflare's JS challenge runs naturally (same as a human in Chrome) —
   this is NOT a bypass
4. The resulting `cf_clearance` cookie lives in the browser session only —
   never shared, exported, or committed
5. If a real CAPTCHA puzzle (image, click-X) appears, the system pauses
   and waits for human verification — never solves programmatically

## What the adapter NEVER does

- ❌ CAPTCHA-solving services (2captcha, anti-captcha)
- ❌ Stolen cf_clearance cookies from other sessions
- ❌ Third-party challenge-bypass libraries
- ❌ Credential sharing
- ❌ User-agent spoofing to look like a real browser
- ❌ Crawling URLs outside `allowed_paths`
- ❌ Archiving content from `/community/` (forum — requires login)
- ❌ Archiving content from `/school/` (classes — paywalled)
- ❌ Archiving content from `/store/` (e-commerce)
- ❌ Bypassing robots.txt (always respected)

## Coverage (when authorized)

What CAN be archived (under explicit authorization):
- ✅ AoPS Wiki contest index pages (`/wiki/index.php/AMC_Problems_and_Solutions`)
- ✅ Year pages (`/wiki/index.php/2024_AMC_10A_Problems`)
- ✅ Problem pages (`/wiki/index.php/2024_AMC_10A_Problems/Problem_1`)
- ✅ Solution pages (`/wiki/index.php/2024_AMC_10A_Solutions`)
- ✅ Embedded images and PDFs (linked from above pages)
- ✅ MediaWiki pagination (`?offset=` / `&limit=`)
- ✅ Previous/Next navigation links

What CANNOT be archived (regardless of authorization):
- ❌ AoPS Community forum threads (require login — recorded as `login_required`)
- ❌ AoPS Classes (paywalled — recorded as `paywall`)
- ❌ User-generated content behind authentication

## Adapter responsibilities

The adapter (`adapter.py`) parses:
1. MediaWiki breadcrumbs (Category: chain) → Contest/Year/Problem hierarchy
2. Problem list pages → list of Problem page URLs
3. Problem pages → problem statement + linked images/PDFs/solutions
4. Solution pages → solution HTML + linked assets

The adapter is **PARSER ONLY**. It does NOT:
- Bypass any access control
- Use browser automation directly (the fetcher layer does that, with authorization)
- Make any HTTP request (the fetcher layer does that)
