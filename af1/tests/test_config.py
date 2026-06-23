"""Tests for af1.config."""

from __future__ import annotations

import os
from pathlib import Path

from af1.config import Config


class TestConfigDefaults:
    def test_default_values(self):
        c = Config()
        assert c.github_token == ""
        assert c.github_host == "github.com"
        assert c.watched_authors == ["timkpaine", "painebot"]
        assert c.host == "127.0.0.1"
        assert c.port == 8510
        assert c.sync_interval_seconds == 120

    def test_db_path_default(self):
        c = Config()
        assert c.db_path == Path(os.environ.get("AF1_DB_PATH", Path.home() / ".af1" / "af1.db"))

    def test_maintained_repo_defaults_empty(self):
        c = Config()
        assert c.watched_users == []
        assert c.watched_orgs == []
        assert c.watched_repos == []


class TestConfigLoad:
    def test_load_from_env(self, monkeypatch):
        monkeypatch.setenv("AF1_GITHUB_TOKEN", "env_token")
        monkeypatch.setenv("AF1_GITHUB_HOST", "ghe.corp.com")
        monkeypatch.setenv("AF1_WATCHED_AUTHORS", "alice,bob")
        monkeypatch.setenv("AF1_HOST", "0.0.0.0")
        monkeypatch.setenv("AF1_PORT", "9000")
        monkeypatch.setenv("AF1_SYNC_INTERVAL", "300")
        c = Config.load()
        assert c.github_token == "env_token"
        assert c.github_host == "ghe.corp.com"
        assert c.watched_authors == ["alice", "bob"]
        assert c.host == "0.0.0.0"
        assert c.port == 9000
        assert c.sync_interval_seconds == 300

    def test_load_fallback_to_github_token(self, monkeypatch):
        monkeypatch.delenv("AF1_GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "fallback_token")
        c = Config.load()
        assert c.github_token == "fallback_token"

    def test_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("AF1_GITHUB_TOKEN", "env_token")
        monkeypatch.setenv("AF1_GITHUB_HOST", "ghe.corp.com")
        monkeypatch.setenv("AF1_WATCHED_AUTHORS", "alice")
        c = Config.load(
            github_token="cli_token",
            github_host="custom.github.com",
            watched_authors="dave,eve",
        )
        assert c.github_token == "cli_token"
        assert c.github_host == "custom.github.com"
        assert c.watched_authors == ["dave", "eve"]

    def test_cli_none_does_not_override(self, monkeypatch):
        monkeypatch.setenv("AF1_GITHUB_TOKEN", "env_token")
        c = Config.load(github_token=None)
        assert c.github_token == "env_token"

    def test_cli_empty_string_does_not_override(self, monkeypatch):
        monkeypatch.setenv("AF1_GITHUB_TOKEN", "env_token")
        c = Config.load(github_token="")
        assert c.github_token == "env_token"

    def test_load_with_no_env(self, monkeypatch):
        monkeypatch.delenv("AF1_GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("AF1_GITHUB_HOST", raising=False)
        monkeypatch.delenv("AF1_WATCHED_AUTHORS", raising=False)
        c = Config.load()
        assert c.github_token == ""
        assert c.github_host == "github.com"
        assert c.watched_authors == ["timkpaine", "painebot"]

    def test_watched_authors_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("AF1_WATCHED_AUTHORS", " alice , bob , ")
        c = Config.load()
        assert c.watched_authors == ["alice", "bob"]

    def test_db_path_from_env(self, monkeypatch, tmp_path):
        custom_path = str(tmp_path / "custom.db")
        monkeypatch.setenv("AF1_DB_PATH", custom_path)
        c = Config.load()
        assert c.db_path == Path(custom_path)

    def test_maintained_repos_from_env(self, monkeypatch):
        monkeypatch.setenv("AF1_WATCHED_USERS", " alice , bob ")
        monkeypatch.setenv("AF1_WATCHED_ORGS", "acme,globex")
        monkeypatch.setenv("AF1_WATCHED_REPOS", "acme/widget, acme/gadget")
        c = Config.load()
        assert c.watched_users == ["alice", "bob"]
        assert c.watched_orgs == ["acme", "globex"]
        assert c.watched_repos == ["acme/widget", "acme/gadget"]

    def test_maintained_repos_cli_override(self, monkeypatch):
        monkeypatch.setenv("AF1_WATCHED_ORGS", "envorg")
        c = Config.load(watched_orgs="cliorg1,cliorg2")
        assert c.watched_orgs == ["cliorg1", "cliorg2"]
