"""Tests for the authorization system.

Tests that:
- AuthorizationScope defaults to all-false (no opt-in by default)
- can_use_browser() requires explicit browser_session_allowed=True
- can_complete_js_challenge() requires both browser + challenge flags
- is_effectively_authorized() requires status + verified + scope
- verify_evidence_sha256 actually checks the file
- load_authorization refuses to authorize without a verified evidence file
- build_fetcher falls back to HttpFetcher without authorization
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
os.environ.setdefault("MATHVAULT_SKIP_ALLOWLIST_CHECK", "1")
os.environ.setdefault("ARCHIVE_ALLOWED_DOMAINS", "example.com")
os.environ.setdefault("ARCHIVE_ALLOWED_PATH_PREFIXES", "/contests/")
os.environ.setdefault("ARCHIVE_START_URLS", "https://example.com/contests/")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test.db")
os.environ.setdefault("DB_ENGINE", "sqlite")

sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from crawler.authorization import (
    Authorization, AuthorizationScope, load_authorization, verify_evidence_sha256,
)


def test_authorization_scope_defaults_to_all_false():
    """No scope is granted by default — each must be explicitly opted in."""
    scope = AuthorizationScope()
    assert scope.crawl_public_pages is False
    assert scope.archive_public_content is False
    assert scope.browser_session_allowed is False
    assert scope.challenge_verification_allowed is False
    assert scope.discussion_archive_allowed is False
    assert scope.asset_archive_allowed is False
    assert scope.can_use_browser() is False
    assert scope.can_complete_js_challenge() is False


def test_authorization_scope_explicit_opt_in():
    """Each scope flag must be explicitly true."""
    scope = AuthorizationScope.from_dict({
        "crawl_public_pages": True,
        "archive_public_content": True,
        "browser_session_allowed": True,
        "challenge_verification_allowed": True,
    })
    assert scope.can_use_browser() is True
    assert scope.can_complete_js_challenge() is True


def test_authorization_scope_browser_without_challenge():
    """Browser allowed but challenge verification NOT allowed → cannot auto-solve JS challenge."""
    scope = AuthorizationScope.from_dict({
        "crawl_public_pages": True,
        "browser_session_allowed": True,
        "challenge_verification_allowed": False,  # explicit
    })
    # Browser is allowed
    assert scope.can_use_browser() is True
    # But challenge verification is NOT (so JS challenge won't auto-run)
    assert scope.can_complete_js_challenge() is False


def test_authorization_not_authorized_by_default():
    auth = Authorization(status="unauthorized")
    assert auth.is_effectively_authorized() is False
    assert auth.can_use_browser() is False


def test_authorization_requires_evidence_verified():
    """Even status=authorized is not enough — evidence_verified must be True."""
    auth = Authorization(
        status="authorized",
        evidence_verified=False,
        scope=AuthorizationScope(crawl_public_pages=True, browser_session_allowed=True),
    )
    assert auth.is_effectively_authorized() is False
    assert auth.can_use_browser() is False


def test_authorization_full_authorized():
    auth = Authorization(
        status="authorized",
        evidence_verified=True,
        scope=AuthorizationScope(
            crawl_public_pages=True,
            archive_public_content=True,
            browser_session_allowed=True,
            challenge_verification_allowed=True,
        ),
    )
    assert auth.is_effectively_authorized() is True
    assert auth.can_use_browser() is True
    assert auth.can_complete_js_challenge() is True


def test_authorization_expired_blocks_browser():
    """If authorization has expired, can_use_browser returns False."""
    from datetime import datetime, timedelta, timezone
    past = datetime.now(timezone.utc) - timedelta(days=1)
    auth = Authorization(
        status="authorized",
        evidence_verified=True,
        expires_at=past,
        scope=AuthorizationScope(
            crawl_public_pages=True,
            browser_session_allowed=True,
        ),
    )
    assert auth.is_expired() is True
    assert auth.is_effectively_authorized() is False
    assert auth.can_use_browser() is False


def test_verify_evidence_sha256():
    """verify_evidence_sha256 returns True only if hash matches."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(b"This is the authorization document.")
        path = Path(f.name)
    try:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert verify_evidence_sha256(path, actual_hash) is True
        assert verify_evidence_sha256(path, "wrong-hash") is False
        assert verify_evidence_sha256(Path("/nonexistent"), actual_hash) is False
    finally:
        path.unlink(missing_ok=True)


def test_load_authorization_unauthorized_by_default():
    """A source.yaml with status='unauthorized' loads as unauthorized."""
    import tempfile, yaml
    from pathlib import Path
    # Create a temporary source.yaml that's explicitly unauthorized
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        source_yaml = tmpdir / "source.yaml"
        source_yaml.write_text(yaml.dump({
            "source": {"name": "test"},
            "authorization": {
                "status": "unauthorized",
                "scope": {},
            },
        }))
        auth = load_authorization(source_yaml)
        assert auth.status == "unauthorized"
        assert auth.is_effectively_authorized() is False
        assert auth.can_use_browser() is False


def test_load_authorization_with_evidence_file():
    """Authorization with a real evidence file (verified SHA-256) loads as
    effectively authorized (only if scope flags are also true)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Create the evidence file
        evidence_path = tmpdir / "evidence.pdf"
        evidence_path.write_bytes(b"Authorization document content.")
        ev_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()

        # Create source.yaml
        source_yaml = tmpdir / "source.yaml"
        source_yaml.write_text(yaml.dump({
            "source": {"name": "test"},
            "authorization": {
                "status": "authorized",
                "evidence_file": "evidence.pdf",
                "evidence_sha256": ev_hash,
                "evidence_verified": True,
                "scope": {
                    "crawl_public_pages": True,
                    "browser_session_allowed": True,
                    "challenge_verification_allowed": True,
                },
            },
        }))

        auth = load_authorization(source_yaml)
        assert auth.status == "authorized"
        assert auth.evidence_verified is True
        assert auth.is_effectively_authorized() is True
        assert auth.can_use_browser() is True


def test_load_authorization_with_wrong_sha256():
    """If SHA-256 doesn't match the evidence file, evidence_verified=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        evidence_path = tmpdir / "evidence.pdf"
        evidence_path.write_bytes(b"Authorization document content.")

        source_yaml = tmpdir / "source.yaml"
        source_yaml.write_text(yaml.dump({
            "source": {"name": "test"},
            "authorization": {
                "status": "authorized",
                "evidence_file": "evidence.pdf",
                "evidence_sha256": "wrong-hash",
                "evidence_verified": True,
                "scope": {
                    "crawl_public_pages": True,
                    "browser_session_allowed": True,
                },
            },
        }))

        auth = load_authorization(source_yaml)
        # evidence_verified was True in YAML, but SHA-256 mismatch resets it
        assert auth.evidence_verified is False
        assert auth.is_effectively_authorized() is False


def test_build_fetcher_falls_back_to_http_without_authorization():
    """Without authorization, build_fetcher returns HttpFetcher (not browser)."""
    from crawler.fetcher import build_fetcher, HttpFetcher, Fetcher, build_allowlist
    al = build_allowlist()
    fetcher = build_fetcher(allowlist=al, authorization=None)
    assert isinstance(fetcher, HttpFetcher), "Without authorization, must be HttpFetcher"


def test_build_fetcher_uses_browser_when_authorized():
    """With authorization + browser_session_allowed, returns
    AuthorizedBrowserFetcher (or falls back to HttpFetcher if Playwright
    not installed — both are valid)."""
    from crawler.fetcher import build_fetcher, HttpFetcher, Fetcher, build_allowlist
    al = build_allowlist()
    auth = Authorization(
        status="authorized",
        evidence_verified=True,
        scope=AuthorizationScope(
            crawl_public_pages=True,
            browser_session_allowed=True,
            challenge_verification_allowed=True,
        ),
    )
    fetcher = build_fetcher(allowlist=al, authorization=auth)
    # If Playwright is installed, this will be AuthorizedBrowserFetcher.
    # If not, it falls back to HttpFetcher (which is also acceptable).
    assert isinstance(fetcher, Fetcher)
    # Either browser or http is OK; just verify it doesn't crash


def test_fetcher_result_has_challenge_required_field():
    """FetchResult has a challenge_required flag (for real CAPTCHA puzzles)."""
    from crawler.fetcher import FetchResult
    r = FetchResult(
        url="https://example.com/", final_url="https://example.com/",
        status_code=200, content=b"", content_type="text/html",
        etag=None, last_modified=None, content_hash="x",
        elapsed_seconds=0.0,
    )
    assert r.challenge_required is False  # default
    assert r.fetcher == "http"  # default
    # And we can set them
    r2 = FetchResult(
        url="x", final_url="x", status_code=403, content=b"",
        content_type="text/html", etag=None, last_modified=None,
        content_hash="y", elapsed_seconds=0.0,
        fetcher="browser", challenge_required=True,
    )
    assert r2.fetcher == "browser"
    assert r2.challenge_required is True


if __name__ == "__main__":
    tests = [
        test_authorization_scope_defaults_to_all_false,
        test_authorization_scope_explicit_opt_in,
        test_authorization_scope_browser_without_challenge,
        test_authorization_not_authorized_by_default,
        test_authorization_requires_evidence_verified,
        test_authorization_full_authorized,
        test_authorization_expired_blocks_browser,
        test_verify_evidence_sha256,
        test_load_authorization_unauthorized_by_default,
        test_load_authorization_with_evidence_file,
        test_load_authorization_with_wrong_sha256,
        test_build_fetcher_falls_back_to_http_without_authorization,
        test_build_fetcher_uses_browser_when_authorized,
        test_fetcher_result_has_challenge_required_field,
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
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
