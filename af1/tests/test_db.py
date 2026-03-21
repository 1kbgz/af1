"""Tests for af1.db — SQLite schema, upserts, and queries."""

from __future__ import annotations

import pytest

from af1.db import (
    get_db,
    get_open_prs,
    get_pr,
    get_pr_checks,
    get_pr_commits,
    get_pr_files,
    upsert_pr_check_runs,
    upsert_pr_commits,
    upsert_pr_files,
    upsert_pull_request,
)
from af1.tests.conftest import make_checks, make_commits, make_files, make_pr

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestGetDb:
    async def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "sub" / "test.db"
        conn = await get_db(db_path)
        try:
            assert db_path.exists()
        finally:
            await conn.close()

    async def test_schema_tables_created(self, db):
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in await cursor.fetchall()]
        assert "pull_requests" in tables
        assert "pr_commits" in tables
        assert "pr_files" in tables
        assert "pr_check_runs" in tables
        assert "sync_state" in tables

    async def test_wal_mode_enabled(self, db):
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row[0] == "wal"

    async def test_foreign_keys_enabled(self, db):
        cursor = await db.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row[0] == 1


class TestUpsertPullRequest:
    async def test_insert_new_pr(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        await db.commit()
        assert pr_id == pr["id"]

        row = await get_pr(db, "testorg", "testrepo", 42)
        assert row is not None
        assert row["title"] == "Fix the widget"
        assert row["author"] == "testuser"
        assert row["state"] == "OPEN"
        assert row["additions"] == 10
        assert row["deletions"] == 3

    async def test_upsert_updates_existing_pr(self, db):
        pr = make_pr()
        await upsert_pull_request(db, pr)
        await db.commit()

        pr["title"] = "Updated title"
        pr["additions"] = 20
        await upsert_pull_request(db, pr)
        await db.commit()

        row = await get_pr(db, "testorg", "testrepo", 42)
        assert row["title"] == "Updated title"
        assert row["additions"] == 20

    async def test_labels_stored_as_json(self, db):
        pr = make_pr(labels=[{"name": "bug", "color": "d73a4a"}, {"name": "urgent", "color": "ff0000"}])
        await upsert_pull_request(db, pr)
        await db.commit()

        row = await get_pr(db, "testorg", "testrepo", 42)
        assert isinstance(row["labels"], list)
        assert len(row["labels"]) == 2
        assert row["labels"][0]["name"] == "bug"

    async def test_multiple_prs_different_repos(self, db):
        pr1 = make_pr(id=1, node_id="PR_1", repo_name="repo1", number=1, url="https://github.com/testorg/repo1/pull/1")
        pr2 = make_pr(id=2, node_id="PR_2", repo_name="repo2", number=1, url="https://github.com/testorg/repo2/pull/1")
        await upsert_pull_request(db, pr1)
        await upsert_pull_request(db, pr2)
        await db.commit()

        prs = await get_open_prs(db)
        assert len(prs) == 2


class TestUpsertPrCommits:
    async def test_insert_commits(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        await db.commit()

        commits = make_commits()
        await upsert_pr_commits(db, pr_id, commits)
        await db.commit()

        result = await get_pr_commits(db, pr_id)
        assert len(result) == 2
        assert result[0]["sha"] == "abc123def456"
        assert result[1]["sha"] == "def789ghi012"

    async def test_upsert_commits_updates(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        commits = make_commits()
        await upsert_pr_commits(db, pr_id, commits)
        await db.commit()

        # Update message on existing commit
        commits[0]["message"] = "Updated commit message"
        await upsert_pr_commits(db, pr_id, commits)
        await db.commit()

        result = await get_pr_commits(db, pr_id)
        assert len(result) == 2
        assert result[0]["message"] == "Updated commit message"


class TestUpsertPrFiles:
    async def test_insert_files(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        await db.commit()

        files = make_files()
        await upsert_pr_files(db, pr_id, files)
        await db.commit()

        result = await get_pr_files(db, pr_id)
        assert len(result) == 2
        # Sorted by filename
        assert result[0]["filename"] == "src/widget.py"
        assert result[1]["filename"] == "tests/test_widget.py"

    async def test_upsert_files_replaces(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        files = make_files()
        await upsert_pr_files(db, pr_id, files)
        await db.commit()

        # Replace with different files
        new_files = [{"filename": "new_file.py", "status": "added", "additions": 5, "deletions": 0, "patch": None}]
        await upsert_pr_files(db, pr_id, new_files)
        await db.commit()

        result = await get_pr_files(db, pr_id)
        assert len(result) == 1
        assert result[0]["filename"] == "new_file.py"


class TestUpsertPrCheckRuns:
    async def test_insert_checks(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        await db.commit()

        checks = make_checks()
        await upsert_pr_check_runs(db, pr_id, checks)
        await db.commit()

        result = await get_pr_checks(db, pr_id)
        assert len(result) == 3

    async def test_replace_checks(self, db):
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        checks = make_checks()
        await upsert_pr_check_runs(db, pr_id, checks)
        await db.commit()

        # Replace with updated checks
        new_checks = [{"name": "CI", "status": "completed", "conclusion": "failure", "url": None}]
        await upsert_pr_check_runs(db, pr_id, new_checks)
        await db.commit()

        result = await get_pr_checks(db, pr_id)
        assert len(result) == 1
        assert result[0]["conclusion"] == "failure"

    async def test_duplicate_check_names_handled(self, db):
        """Regression: GitHub can return duplicate check run names (re-runs)."""
        pr = make_pr()
        pr_id = await upsert_pull_request(db, pr)
        await db.commit()

        # Simulate duplicate names in a single batch
        checks = [
            {"name": "CI", "status": "completed", "conclusion": "failure", "url": None},
            {"name": "CI", "status": "completed", "conclusion": "success", "url": None},
        ]
        await upsert_pr_check_runs(db, pr_id, checks)
        await db.commit()

        result = await get_pr_checks(db, pr_id)
        assert len(result) == 1
        # Last one wins with INSERT OR REPLACE
        assert result[0]["conclusion"] == "success"


class TestQueries:
    async def test_get_open_prs_empty(self, db):
        prs = await get_open_prs(db)
        assert prs == []

    async def test_get_open_prs_filters_by_state(self, db):
        open_pr = make_pr(id=1, node_id="PR_1", number=1, state="OPEN", url="https://github.com/testorg/testrepo/pull/1")
        closed_pr = make_pr(id=2, node_id="PR_2", number=2, state="CLOSED", url="https://github.com/testorg/testrepo/pull/2")
        await upsert_pull_request(db, open_pr)
        await upsert_pull_request(db, closed_pr)
        await db.commit()

        prs = await get_open_prs(db)
        assert len(prs) == 1
        assert prs[0]["state"] == "OPEN"

    async def test_get_open_prs_filters_by_authors(self, db):
        pr1 = make_pr(id=1, node_id="PR_1", number=1, author="alice", url="https://github.com/testorg/testrepo/pull/1")
        pr2 = make_pr(id=2, node_id="PR_2", number=2, author="bob", url="https://github.com/testorg/testrepo/pull/2")
        await upsert_pull_request(db, pr1)
        await upsert_pull_request(db, pr2)
        await db.commit()

        prs = await get_open_prs(db, authors=["alice"])
        assert len(prs) == 1
        assert prs[0]["author"] == "alice"

    async def test_get_pr_not_found(self, db):
        result = await get_pr(db, "no", "such", 999)
        assert result is None

    async def test_get_pr_found(self, db):
        pr = make_pr()
        await upsert_pull_request(db, pr)
        await db.commit()

        result = await get_pr(db, "testorg", "testrepo", 42)
        assert result is not None
        assert result["number"] == 42

    async def test_get_pr_commits_empty(self, db):
        result = await get_pr_commits(db, 9999)
        assert result == []

    async def test_get_pr_files_empty(self, db):
        result = await get_pr_files(db, 9999)
        assert result == []

    async def test_get_pr_checks_empty(self, db):
        result = await get_pr_checks(db, 9999)
        assert result == []
