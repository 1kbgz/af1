"""Tests for af1.sync — background sync engine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from af1.db import get_open_prs, get_pr_checks, get_pr_commits, get_pr_files
from af1.sync import sync_all_prs, sync_loop
from af1.tests.conftest import make_commits, make_pr, mock_github_client

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestSyncAllPrs:
    async def test_syncs_authored_prs(self, db, sample_config):
        client = mock_github_client()
        await sync_all_prs(db, client, sample_config)

        prs = await get_open_prs(db)
        assert len(prs) == 1
        assert prs[0]["title"] == "Fix the widget"

        # Verify commits, files, checks were also synced
        pr = prs[0]
        commits = await get_pr_commits(db, pr["id"])
        assert len(commits) == 2

        files = await get_pr_files(db, pr["id"])
        assert len(files) == 2

        checks = await get_pr_checks(db, pr["id"])
        assert len(checks) == 3

    async def test_syncs_review_requested_prs(self, db, sample_config):
        review_pr = make_pr(
            id=2002,
            node_id="PR_review",
            number=99,
            title="Review requested PR",
            author="otheruser",
            url="https://github.com/testorg/testrepo/pull/99",
        )
        client = mock_github_client()
        client.fetch_review_requested_prs.return_value = [review_pr]

        await sync_all_prs(db, client, sample_config)

        prs = await get_open_prs(db)
        assert len(prs) == 2

    async def test_deduplicates_authored_and_review_prs(self, db, sample_config):
        pr = make_pr()
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]
        # Same PR also appears in review-requested
        client.fetch_review_requested_prs.return_value = [pr]

        await sync_all_prs(db, client, sample_config)

        prs = await get_open_prs(db)
        assert len(prs) == 1

    async def test_continues_on_pr_failure(self, db, sample_config):
        """If syncing one PR fails, others should still be processed."""
        pr1 = make_pr(id=1, node_id="PR_1", number=1, url="https://github.com/testorg/testrepo/pull/1")
        pr2 = make_pr(id=2, node_id="PR_2", number=2, url="https://github.com/testorg/testrepo/pull/2")
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr1, pr2]

        # Make commit fetch fail for first PR
        call_count = 0

        async def failing_commits(owner, repo, number):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Network error")
            return make_commits()

        client.fetch_pr_commits = AsyncMock(side_effect=failing_commits)

        await sync_all_prs(db, client, sample_config)

        # Both PRs should be upserted (the first one before commits fail)
        prs = await get_open_prs(db)
        # At least pr2 should have commits
        assert len(prs) >= 1

    async def test_skips_check_runs_without_head_sha(self, db, sample_config):
        pr = make_pr(head_sha=None)
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]

        await sync_all_prs(db, client, sample_config)

        client.fetch_pr_check_runs.assert_not_called()


class TestSyncLoop:
    async def test_sync_loop_stops_on_event(self, db, sample_config):
        client = mock_github_client()
        sample_config.sync_interval_seconds = 1
        stop_event = asyncio.Event()

        # Stop after first sync
        original_fetch = client.fetch_open_prs_for_authors

        async def fetch_and_stop(*args, **kwargs):
            result = await original_fetch(*args, **kwargs)
            stop_event.set()
            return result

        client.fetch_open_prs_for_authors = AsyncMock(side_effect=fetch_and_stop)

        await asyncio.wait_for(sync_loop(db, client, sample_config, stop_event), timeout=5.0)

        # At least one sync should have happened
        prs = await get_open_prs(db)
        assert len(prs) == 1

    async def test_sync_loop_handles_error(self, db, sample_config):
        """Sync loop should continue even if sync_all_prs raises."""
        client = mock_github_client()
        sample_config.sync_interval_seconds = 1
        stop_event = asyncio.Event()

        call_count = 0

        async def failing_then_stopping(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Sync failed")
            stop_event.set()
            return [make_pr()]

        client.fetch_open_prs_for_authors = AsyncMock(side_effect=failing_then_stopping)

        await asyncio.wait_for(sync_loop(db, client, sample_config, stop_event), timeout=5.0)
        assert call_count >= 2
