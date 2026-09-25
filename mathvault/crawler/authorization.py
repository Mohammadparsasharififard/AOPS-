"""Authorization loader — verifies an evidence file before granting any
elevated access to a source.

CRITICAL DESIGN:
- Without an evidence file + verified SHA-256 + explicit scope flags,
  the system falls back to HTTP-only mode (no browser, no challenge
  solving).
- Even WITH authorization, the system NEVER uses:
  - CAPTCHA-solving services
  - Stolen cf_clearance cookies
  - Third-party challenge-bypass libraries
  - User-agent spoofing
- The authorization may grant the right to use a real browser (Playwright)
  that lets Cloudflare's JS challenge run naturally (same as a human in
  Chrome). This is NOT a bypass.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AuthorizationScope:
    """What the authorization explicitly allows. Each flag must be opted-in."""
    crawl_public_pages: bool = False
    archive_public_content: bool = False
    browser_session_allowed: bool = False
    challenge_verification_allowed: bool = False
    discussion_archive_allowed: bool = False
    asset_archive_allowed: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "AuthorizationScope":
        return cls(
            crawl_public_pages=bool(d.get("crawl_public_pages", False)),
            archive_public_content=bool(d.get("archive_public_content", False)),
            browser_session_allowed=bool(d.get("browser_session_allowed", False)),
            challenge_verification_allowed=bool(d.get("challenge_verification_allowed", False)),
            discussion_archive_allowed=bool(d.get("discussion_archive_allowed", False)),
            asset_archive_allowed=bool(d.get("asset_archive_allowed", False)),
        )

    def can_use_browser(self) -> bool:
        """True only if browser session is explicitly allowed."""
        return self.browser_session_allowed

    def can_complete_js_challenge(self) -> bool:
        """True only if both browser session AND challenge verification are
        explicitly allowed. Even then, real CAPTCHA puzzles are NEVER
        solved programmatically — the system pauses and waits for human
        verification.
        """
        return self.browser_session_allowed and self.challenge_verification_allowed


@dataclass
class Authorization:
    """A loaded authorization record for a source."""
    status: str  # unauthorized | authorized | pending | expired
    evidence_file: Optional[Path] = None
    evidence_sha256: Optional[str] = None
    evidence_verified: bool = False
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    scope: AuthorizationScope = field(default_factory=AuthorizationScope)
    expires_at: Optional[datetime] = None
    contact: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Authorization":
        expires_at = None
        if d.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(d["expires_at"])
            except Exception:
                pass
        verified_at = None
        if d.get("verified_at"):
            try:
                verified_at = datetime.fromisoformat(d["verified_at"])
            except Exception:
                pass
        return cls(
            status=d.get("status", "unauthorized"),
            evidence_file=Path(d["evidence_file"]) if d.get("evidence_file") else None,
            evidence_sha256=d.get("evidence_sha256"),
            evidence_verified=bool(d.get("evidence_verified", False)),
            verified_at=verified_at,
            verified_by=d.get("verified_by"),
            scope=AuthorizationScope.from_dict(d.get("scope", {})),
            expires_at=expires_at,
            contact=d.get("contact"),
        )

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def is_effectively_authorized(self) -> bool:
        """True only if all conditions are met:
        - status == 'authorized'
        - evidence_verified == True
        - not expired
        - at least crawl_public_pages scope
        """
        if self.status != "authorized":
            return False
        if not self.evidence_verified:
            return False
        if self.is_expired():
            return False
        if not self.scope.crawl_public_pages:
            return False
        return True

    def can_use_browser(self) -> bool:
        """True only if explicitly authorized AND scope allows."""
        return self.is_effectively_authorized() and self.scope.can_use_browser()

    def can_complete_js_challenge(self) -> bool:
        """True only if explicitly authorized AND scope allows.

        NOTE: Even when this is True, the system NEVER solves real CAPTCHA
        puzzles programmatically — it only lets Cloudflare's JS challenge
        run naturally in the browser. Real CAPTCHAs pause for human input.
        """
        return self.is_effectively_authorized() and self.scope.can_complete_js_challenge()


def verify_evidence_sha256(evidence_path: Path, expected_sha256: str) -> bool:
    """Compute SHA-256 of the evidence file and compare to expected."""
    if not evidence_path.is_file():
        return False
    h = hashlib.sha256()
    with open(evidence_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest() == expected_sha256


def load_authorization(source_yaml_path: Path) -> Authorization:
    """Load authorization from a source.yaml file.

    Performs verification:
    - If status == 'authorized' but evidence file is missing → status becomes 'unauthorized'
    - If evidence_sha256 doesn't match the file → evidence_verified = False
    - If authorization is expired → status becomes 'expired'
    """
    with open(source_yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    auth_dict = config.get("authorization", {})
    auth = Authorization.from_dict(auth_dict)

    # Verify
    if auth.status == "authorized":
        if auth.evidence_file and auth.evidence_sha256:
            ev_path = source_yaml_path.parent / auth.evidence_file
            if verify_evidence_sha256(ev_path, auth.evidence_sha256):
                logger.info("Evidence file verified: %s", ev_path)
            else:
                logger.warning(
                    "Evidence file SHA-256 mismatch — authorization NOT verified"
                )
                auth.evidence_verified = False
        else:
            logger.warning(
                "Authorization status='authorized' but no evidence file/sha256 — treating as unauthorized"
            )
            auth.status = "unauthorized"
            auth.evidence_verified = False

    if auth.is_expired():
        logger.warning("Authorization expired — status='expired'")
        auth.status = "expired"

    return auth
