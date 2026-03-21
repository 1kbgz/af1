"""Configuration loading for af1."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    github_token: str = ""
    github_host: str = "github.com"
    watched_authors: list[str] = field(default_factory=lambda: ["timkpaine", "painebot"])
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("AF1_DB_PATH", Path.home() / ".af1" / "af1.db")))
    host: str = "127.0.0.1"
    port: int = 8510
    sync_interval_seconds: int = 120

    @classmethod
    def load(cls, **overrides: object) -> "Config":
        """Load config from env vars, with optional keyword overrides (e.g. from CLI)."""
        token = os.environ.get("AF1_GITHUB_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
        github_host = os.environ.get("AF1_GITHUB_HOST", "github.com")
        authors_env = os.environ.get("AF1_WATCHED_AUTHORS", "")
        authors = [a.strip() for a in authors_env.split(",") if a.strip()] if authors_env else ["timkpaine", "painebot"]
        db_path = Path(os.environ.get("AF1_DB_PATH", Path.home() / ".af1" / "af1.db"))
        host = os.environ.get("AF1_HOST", "127.0.0.1")
        port = int(os.environ.get("AF1_PORT", "8510"))
        sync_interval = int(os.environ.get("AF1_SYNC_INTERVAL", "120"))

        # CLI overrides take precedence over env vars
        if "github_token" in overrides and overrides["github_token"]:
            token = str(overrides["github_token"])
        if "github_host" in overrides and overrides["github_host"]:
            github_host = str(overrides["github_host"])
        if "watched_authors" in overrides and overrides["watched_authors"]:
            raw = str(overrides["watched_authors"])
            authors = [a.strip() for a in raw.split(",") if a.strip()]

        return cls(
            github_token=token,
            github_host=github_host,
            watched_authors=authors,
            db_path=db_path,
            host=host,
            port=port,
            sync_interval_seconds=sync_interval,
        )
