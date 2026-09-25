"""Centralized, type-safe configuration for MathVault.

All runtime configuration is loaded once at process start and validated via
pydantic-settings. The configuration is the SOLE source of truth for the
crawler allowlist — no hardcoded URLs exist anywhere in the codebase.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MathVault settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Archive allowlist ---------------------------------------------------
    archive_allowed_domains: str = ""
    archive_allowed_path_prefixes: str = ""
    archive_start_urls: str = ""

    # --- Crawl behavior ------------------------------------------------------
    crawl_max_depth: int = 5
    crawl_max_pages: int = 1000
    crawl_delay_seconds: float = 2.0
    crawl_concurrency: int = 1
    crawl_timeout_seconds: int = 30
    crawl_max_retries: int = 3
    crawl_user_agent: str = "MathVault-Archiver/1.0"
    crawl_respect_robots: bool = True
    # Per-page asset download limit — how many images/PDFs/etc to fetch
    # per single page (prevents downloading 100s of small icons on a
    # complex page). Default: 50 (was hardcoded 20 in scheduler).
    crawl_max_assets_per_page: int = 50

    # --- Sync ----------------------------------------------------------------
    sync_interval_hours: int = 2

    # --- Database ------------------------------------------------------------
    database_url: str = "sqlite:///./data/mathvault.db"
    db_engine: str = "sqlite"

    # --- Security ------------------------------------------------------------
    secret_key: str = "dev-only-CHANGE-ME"
    admin_username: str = "admin"
    admin_password_hash: str = ""

    # --- Storage -------------------------------------------------------------
    archive_dir: str = "./archive"
    data_dir: str = "./data"
    log_dir: str = "./logs"

    # --- API -----------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2
    trusted_proxies: str = "127.0.0.1"

    # --- Frontend ------------------------------------------------------------
    next_public_api_base: str = "http://localhost:8000"

    # --- Computed helpers ----------------------------------------------------
    @property
    def allowed_domains(self) -> List[str]:
        return [d.strip().lower() for d in self.archive_allowed_domains.split(",") if d.strip()]

    @property
    def allowed_path_prefixes(self) -> List[str]:
        return [p.strip() for p in self.archive_allowed_path_prefixes.split(",") if p.strip()]

    @property
    def start_urls(self) -> List[str]:
        return [u.strip() for u in self.archive_start_urls.split(",") if u.strip()]

    @property
    def trusted_proxies_list(self) -> List[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def archive_path(self) -> Path:
        return Path(self.archive_dir).resolve()

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def log_path(self) -> Path:
        return Path(self.log_dir).resolve()

    @model_validator(mode="after")
    def _ensure_dirs(self) -> "Settings":
        """Create directories on import so the app never fails on missing dir."""
        for p in (self.archive_path, self.data_path, self.log_path):
            p.mkdir(parents=True, exist_ok=True)
            (p / ".gitkeep").touch(exist_ok=True)
        return self

    @field_validator("crawl_max_depth", "crawl_max_pages", "crawl_max_retries")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("crawl_delay_seconds")
    @classmethod
    def _delay_floor(cls, v: float) -> float:
        # Minimum delay to enforce politeness — even if user sets 0.
        return max(v, 0.5)

    @model_validator(mode="after")
    def _validate_allowlist(self) -> "Settings":
        if not self.allowed_domains:
            # Don't raise in test env; warn loudly.
            if os.environ.get("MATHVAULT_SKIP_ALLOWLIST_CHECK") != "1":
                raise ValueError(
                    "ARCHIVE_ALLOWED_DOMAINS is empty. Refusing to start — "
                    "the crawler would have no allowlist and could fetch anything."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings singleton.

    The cache ensures all components share the same settings object. Tests
    can call `get_settings.cache_clear()` to reset.
    """
    return Settings()
