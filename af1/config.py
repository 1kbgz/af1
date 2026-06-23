"""Configuration loading for af1."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _csv(raw: str) -> list[str]:
    """Parse a comma-separated string into a list of trimmed, non-empty values."""
    return [v.strip() for v in raw.split(",") if v.strip()]


@dataclass
class Config:
    github_token: str = ""
    github_host: str = "github.com"
    watched_authors: list[str] = field(default_factory=lambda: ["timkpaine", "painebot"])
    # Repos to treat as "maintained" for cross-org PR sync. All optional; if all three
    # are empty, maintained-repo sync is skipped entirely.
    watched_users: list[str] = field(default_factory=list)  # discover repos these users own that the token can write to
    watched_orgs: list[str] = field(default_factory=list)  # discover repos in these orgs that the token can write to
    watched_repos: list[str] = field(default_factory=list)  # explicit "owner/repo" entries to always include
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
        users = _csv(os.environ.get("AF1_WATCHED_USERS", ""))
        orgs = _csv(os.environ.get("AF1_WATCHED_ORGS", ""))
        repos = _csv(os.environ.get("AF1_WATCHED_REPOS", ""))
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
        if "watched_users" in overrides and overrides["watched_users"]:
            users = _csv(str(overrides["watched_users"]))
        if "watched_orgs" in overrides and overrides["watched_orgs"]:
            orgs = _csv(str(overrides["watched_orgs"]))
        if "watched_repos" in overrides and overrides["watched_repos"]:
            repos = _csv(str(overrides["watched_repos"]))

        return cls(
            github_token=token,
            github_host=github_host,
            watched_authors=authors,
            watched_users=users,
            watched_orgs=orgs,
            watched_repos=repos,
            db_path=db_path,
            host=host,
            port=port,
            sync_interval_seconds=sync_interval,
        )
