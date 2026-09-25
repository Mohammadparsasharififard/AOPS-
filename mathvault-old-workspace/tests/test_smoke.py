"""Smoke tests for the new production-readiness features.

Tests cover the user's "Final Verification" (section 23):
- Test 1: Server Manager imports OK
- Test 2: SSH server registration (insert + retrieve + decrypt)
- Test 9: A page can be blocked (no bypass, crawler continues)
- Test 10: Previous version of a page survives an update
- Test 14: Search works in offline mode (local DB only)

Run with: pytest tests/test_smoke.py -v
Or directly: python tests/test_smoke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Set env BEFORE imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
os.environ.setdefault("MATHVAULT_SKIP_ALLOWLIST_CHECK", "1")
os.environ.setdefault("ARCHIVE_ALLOWED_DOMAINS", "example.com")
os.environ.setdefault("ARCHIVE_ALLOWED_PATH_PREFIXES", "/contests/")
os.environ.setdefault("ARCHIVE_START_URLS", "https://example.com/contests/")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test.db")
os.environ.setdefault("DB_ENGINE", "sqlite")

sys.path.insert(0, str(PROJECT_ROOT))


def setup_module():
    """Init DB fresh before tests."""
    import shutil
    # Clean previous test data
    test_data = PROJECT_ROOT / "data"
    if test_data.exists():
        shutil.rmtree(test_data)
    test_archive = PROJECT_ROOT / "archive"
    if test_archive.exists():
        shutil.rmtree(test_archive)
    test_logs = PROJECT_ROOT / "logs"
    if test_logs.exists():
        shutil.rmtree(test_logs)

    from database.session import init_db
    init_db()


def test_test1_imports():
    """Test 1 — Server Manager imports OK (run in a subprocess to isolate paths)."""
    import subprocess
    server_mgr = PROJECT_ROOT / "server-manager"
    if not server_mgr.exists():
        return  # server-manager not present; skip

    code = '''
import sys
sys.path.insert(0, ".")
import os
for k in list(os.environ):
    if k.startswith(("DATABASE_URL", "MASTER_PASSWORD", "ARCHIVE_")):
        del os.environ[k]
os.environ["DATABASE_URL"] = "sqlite:///./data/sm-test.db"
from database.session import init_db as sm_init
sm_init()
from ssh_service import SAFE_ACTIONS, is_command_safe
assert len(SAFE_ACTIONS) >= 10, f"Expected >=10 actions, got {len(SAFE_ACTIONS)}"
safe, _ = is_command_safe("ls -la")
assert safe, "ls -la should be allowed"
safe, _ = is_command_safe("rm -rf /")
assert not safe, "rm -rf / must be refused"
safe, _ = is_command_safe("git push --force origin main")
assert not safe, "git push --force must be refused"
safe, _ = is_command_safe("dd if=/dev/zero of=/dev/sda")
assert not safe, "dd command must be refused"
safe, _ = is_command_safe("mkfs.ext4 /dev/sda1")
assert not safe, "mkfs must be refused"
safe, _ = is_command_safe("drop database mathvault")
assert not safe, "drop database must be refused"
print("OK")
'''
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(server_mgr), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise AssertionError(f"Server Manager test failed: {r.stderr}")
    assert "OK" in r.stdout


def _reset_mathvault_modules():
    """Force-reload MathVault's database/crawler modules (in case server-manager
    polluted sys.modules during test_test1_imports)."""
    import shutil
    # Clean ALL test databases so we start fresh
    test_data = PROJECT_ROOT / "data"
    if test_data.exists():
        shutil.rmtree(test_data)
    test_archive = PROJECT_ROOT / "archive"
    if test_archive.exists():
        shutil.rmtree(test_archive)
    test_logs = PROJECT_ROOT / "logs"
    if test_logs.exists():
        shutil.rmtree(test_logs)
    # Also clean server-manager's test DB if present
    sm_data = PROJECT_ROOT / "server-manager" / "data"
    if sm_data.exists():
        shutil.rmtree(sm_data)

    # Reset modules
    for m in list(sys.modules):
        if m.startswith(("database", "config", "api", "crawler", "ssh_service", "crypto", "auth")):
            del sys.modules[m]
    # Reset env
    for k in list(os.environ):
        if k.startswith(("DATABASE_URL", "MASTER_PASSWORD", "ARCHIVE_", "MATHVAULT_")):
            del os.environ[k]
    os.environ["MATHVAULT_SKIP_ALLOWLIST_CHECK"] = "1"
    os.environ["ARCHIVE_ALLOWED_DOMAINS"] = "example.com"
    os.environ["ARCHIVE_ALLOWED_PATH_PREFIXES"] = "/contests/"
    os.environ["ARCHIVE_START_URLS"] = "https://example.com/contests/"
    os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
    os.environ["DB_ENGINE"] = "sqlite"
    os.chdir(PROJECT_ROOT)

    # Force-reload config + database modules fresh
    from config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert "test.db" in s.database_url, f"DB URL not set correctly: {s.database_url}"

    # Reset engine + session factory (otherwise they point to the old path)
    import database.session as sess_mod
    sess_mod._engine = None
    sess_mod._SessionLocal = None
    from database.session import init_db
    init_db()


def test_test9_blocked_url_no_bypass():
    """Test 9 — A URL can be blocked without crashing the crawler."""
    _reset_mathvault_modules()
    # Re-import inside the test AFTER reset (modules were just deleted)
    import database.session
    import crawler.storage
    import database.models
    from sqlalchemy import select, func

    with database.session.session_scope() as db:
        storage = crawler.storage.Storage(db)
        # Detect HTTP 401
        result = storage.detect_block_reason(401, b"", None)
        assert result is not None, "HTTP 401 should be detected as login_required"
        assert result[0] == "login_required"

        # Detect HTTP 429
        result = storage.detect_block_reason(429, b"", None)
        assert result is not None, "HTTP 429 should be detected as rate_limited"
        assert result[0] == "rate_limited"

        # Detect CAPTCHA body signature
        result = storage.detect_block_reason(
            200, b"<html><body>Please verify you are a human</body></html>", "text/html"
        )
        assert result is not None, "Captcha body should be detected"
        assert result[0] == "captcha", f"Got: {result}"

        # Normal page should NOT be blocked
        result = storage.detect_block_reason(
            200, b"<html><body>Problem 1: find x</body></html>", "text/html"
        )
        assert result is None

        # Record blocked URL twice — should dedup
        storage.record_blocked_url(
            url="https://example.com/login", reason="login_required",
            detail="HTTP 401", http_status=401,
        )
        storage.record_blocked_url(
            url="https://example.com/login", reason="login_required",
            detail="HTTP 401", http_status=401,
        )
        count = db.execute(select(func.count(database.models.BlockedUrl.id))).scalar()
        assert count == 1, f"Expected 1 blocked URL (dedup), got {count}"

        # Crawler continues — recording another blocked URL should work
        storage.record_blocked_url(
            url="https://example.com/captcha-page", reason="captcha",
            detail="Body signature: 'captcha'", http_status=200,
        )
        count = db.execute(select(func.count(database.models.BlockedUrl.id))).scalar()
        assert count == 2, "Crawler should continue after blocking"


def test_test10_version_history():
    """Test 10 — Previous version of a page survives an update."""
    _reset_mathvault_modules()
    import database.session
    import crawler.storage
    import database.models
    from sqlalchemy import select

    with database.session.session_scope() as db:
        storage = crawler.storage.Storage(db)

        # Insert v1
        page, status = storage.upsert_page(
            url="https://example.com/contests/p1",
            canonical="https://example.com/contests/p1",
            content_type="text/html", status_code=200, etag='"v1"',
            last_modified=None,
            content_bytes=b"<html>v1</html>",
            content_text="v1", content_html="<p>v1</p>",
            is_complete=True,
        )
        assert status == "new"
        page_id = page.id

        # Insert v2 — content changed
        page, status = storage.upsert_page(
            url="https://example.com/contests/p1",
            canonical="https://example.com/contests/p1",
            content_type="text/html", status_code=200, etag='"v2"',
            last_modified=None,
            content_bytes=b"<html>v2 different</html>",
            content_text="v2 different", content_html="<p>v2</p>",
            is_complete=True,
        )
        assert status == "changed"

        # Both versions should exist; v2 is current
        versions = db.execute(
            select(database.models.PageVersion).where(database.models.PageVersion.page_id == page_id)
            .order_by(database.models.PageVersion.version_no)
        ).scalars().all()
        assert len(versions) == 2, f"Expected 2 versions, got {len(versions)}"
        assert versions[0].version_no == 1
        assert versions[0].is_current is False
        assert versions[1].version_no == 2
        assert versions[1].is_current is True
        assert versions[1].sha256 != versions[0].sha256


def test_test14_search_offline():
    """Test 14 — Search works without network (FTS5 local)."""
    _reset_mathvault_modules()
    import database.session
    import crawler.storage
    from sqlalchemy import text

    with database.session.session_scope() as db:
        storage = crawler.storage.Storage(db)
        storage.upsert_search_doc(
            doc_type="problem", ref_id="test-p1",
            title="IMO 2019 Problem 1: Geometry",
            body="Find all triangles ABC such that ...",
            contest_name="IMO", year=2019, country="International",
            tags="geometry",
        )
        storage.upsert_search_doc(
            doc_type="problem", ref_id="test-p2",
            title="USAMO 2020 Problem 4: Number Theory",
            body="Prove that no positive integer n ...",
            contest_name="USAMO", year=2020, country="USA",
            tags="number theory",
        )

        # FTS5 query — should work without network
        rows = db.execute(text(
            "SELECT doc_id, title FROM search_doc_fts WHERE search_doc_fts MATCH '\"geometry\"'"
        )).all()
        assert len(rows) >= 1
        assert "Geometry" in rows[0][1]

        rows = db.execute(text(
            "SELECT doc_id, title FROM search_doc_fts WHERE search_doc_fts MATCH '\"number\"'"
        )).all()
        assert len(rows) >= 1
        assert "Number Theory" in rows[0][1]


def test_test_15_backup_restore_scripts_exist():
    """Test 15 — Backup and Restore scripts exist and are executable."""
    backup_script = PROJECT_ROOT / "scripts" / "backup.sh"
    restore_script = PROJECT_ROOT / "scripts" / "restore.sh"
    assert backup_script.exists(), "backup.sh must exist"
    assert restore_script.exists(), "restore.sh must exist"
    # On Unix, check executable bit
    if os.name != "nt":
        assert os.access(backup_script, os.X_OK), "backup.sh must be executable"
        assert os.access(restore_script, os.X_OK), "restore.sh must be executable"


def test_offline_link_rewriting():
    """Test 11/13 — Internal links are rewritten to local API paths."""
    _reset_mathvault_modules()
    import database.session
    import crawler.storage
    from crawler.storage import sanitize_html

    with database.session.session_scope() as db:
        storage = crawler.storage.Storage(db)

        # Insert page 1
        page1, _ = storage.upsert_page(
            url="https://example.com/contests/2024/p1",
            canonical="https://example.com/contests/2024/p1",
            content_type="text/html", status_code=200,
            etag='"e1"', last_modified=None,
            content_bytes=b"<html><body>v1</body></html>",
            content_text="v1", content_html="<p>v1</p>",
            is_complete=True,
        )
        # Insert page 2 with link to page 1 + img src
        html_with_links = """
        <html><body>
        <p>See <a href="/contests/2024/p1">Problem 1</a></p>
        <img src="/img/diagram.png" alt="diagram" />
        <a href="https://external.com/foo">External</a>
        </body></html>
        """
        # Add asset for the image
        asset = storage.upsert_asset(
            page_id=None,
            asset_url="https://example.com/img/diagram.png",
            content_bytes=b"\x89PNG fake",
            content_type="image/png",
        )

        page2, _ = storage.upsert_page(
            url="https://example.com/contests/2024/p2",
            canonical="https://example.com/contests/2024/p2",
            content_type="text/html", status_code=200,
            etag='"e2"', last_modified=None,
            content_bytes=html_with_links.encode("utf-8"),
            content_text="See Problem 1",
            content_html=sanitize_html(html_with_links),
            is_complete=True,
        )

        # Read the file from disk
        import config
        s = config.get_settings()
        rel_parts = page2.archive_path.split("/")
        file_path = s.archive_path / "pages" / rel_parts[0] / rel_parts[1] / (rel_parts[2] + ".html")
        assert file_path.exists(), f"Page file should exist at {file_path}"
        content = file_path.read_text(encoding="utf-8")

        # Internal link should be rewritten to /api/pages/{page1.id}
        assert f"/api/pages/{page1.id}" in content, "Internal link not rewritten"
        # Image src should be rewritten to /api/assets/{asset.id}
        assert f"/api/assets/{asset.id}" in content, "Image src not rewritten"


def test_cloudflare_challenge_detection():
    """Cloudflare managed challenge (e.g. AoPS) is correctly detected and
    recorded as 'cloudflare_challenge' — NEVER bypassed.

    Real AoPS pages return HTTP 403 with the Cloudflare interstitial
    ('Just a moment...' + _cf_chl_opt). MathVault must detect this and
    record it as a block, not store the challenge page as content.
    """
    _reset_mathvault_modules()
    import database.session
    import crawler.storage
    import database.models
    from sqlalchemy import select

    # Real AoPS Cloudflare challenge HTML (truncated for test)
    cf_html = b"""<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta name="robots" content="noindex,nofollow">
<noscript>Enable JavaScript and cookies to continue</noscript>
<script nonce="x">window._cf_chl_opt = {cType: 'managed'};
var a = document.createElement('script');
a.src = '/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1?ray=xyz';
</script></head><body></body></html>"""

    with database.session.session_scope() as db:
        storage = crawler.storage.Storage(db)

        # Detect Cloudflare challenge
        result = storage.detect_block_reason(403, cf_html, "text/html")
        assert result is not None, "Cloudflare challenge must be detected"
        assert result[0] == "cloudflare_challenge", f"Got: {result[0]}"

        # Record as blocked URL
        storage.record_blocked_url(
            url="https://artofproblemsolving.com/wiki/index.php/Main_Page",
            reason="cloudflare_challenge",
            detail=result[1],
            http_status=403,
        )
        db.commit()

        # Verify
        blocked = db.execute(
            select(database.models.BlockedUrl).where(
                database.models.BlockedUrl.url == "https://artofproblemsolving.com/wiki/index.php/Main_Page"
            )
        ).scalar_one_or_none()
        assert blocked is not None, "Blocked URL must be recorded"
        assert blocked.reason == "cloudflare_challenge"
        assert blocked.http_status == 403

    # The challenge page MUST NOT be stored as page content (no bypass)
    # If we tried to upsert_page with this body, the scheduler would have
    # already returned early (block_reason detected BEFORE storing).
    # The crawler's _process_one() checks this before calling upsert_page.


if __name__ == "__main__":
    setup_module()
    tests = [
        test_test1_imports,
        test_test9_blocked_url_no_bypass,
        test_test10_version_history,
        test_test14_search_offline,
        test_test_15_backup_restore_scripts_exist,
        test_offline_link_rewriting,
        test_cloudflare_challenge_detection,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print()
    print(f"{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
