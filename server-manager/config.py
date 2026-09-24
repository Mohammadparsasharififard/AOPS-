"""Configuration for Personal Server Manager."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 7700
    app_debug: bool = True

    database_url: str = "sqlite:///./data/server-manager.db"
    master_password_hash: str = ""

    ssh_default_port: int = 22
    ssh_default_user: str = "root"
    ssh_connect_timeout: int = 15

    mathvault_frontend_url: str = "http://localhost:3000"
    mathvault_api_url: str = "http://localhost:8000"

    @property
    def data_path(self) -> Path:
        return Path("./data").resolve()

    @property
    def keypair_path(self) -> Path:
        return self.data_path / "keypair.json"

    @model_validator(mode="after")
    def _ensure_dirs(self) -> "Settings":
        self.data_path.mkdir(parents=True, exist_ok=True)
        (self.data_path / ".gitkeep").touch(exist_ok=True)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
