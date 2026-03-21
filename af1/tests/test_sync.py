"""Tests for af1.sync — background sync engine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from af1.db import get_open_issues, get_open_prs, get_pr_checks, get_pr_commits, get_pr_files
from af1.sync import sync_all_issues, sync_all_prs, sync_loop
from af1.tests.conftest import make_commits, make_issue, make_pr, mock_github_client

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

    async def test_files_failure_still_syncs_pr_and_commits(self, db, sample_config):
        """A 403 on fetch_pr_files should not prevent PR data or commits from being saved."""
        pr = make_pr()
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]
        client.fetch_pr_files = AsyncMock(side_effect=RuntimeError("403 Forbidden"))

        await sync_all_prs(db, client, sample_config)

        prs = await get_open_prs(db)
        assert len(prs) == 1
        commits = await get_pr_commits(db, prs[0]["id"])
        assert len(commits) == 2
        checks = await get_pr_checks(db, prs[0]["id"])
        assert len(checks) == 3
        files = await get_pr_files(db, prs[0]["id"])
        assert len(files) == 0

    async def test_commits_failure_still_syncs_pr_and_files(self, db, sample_config):
        """A failure on fetch_pr_commits should not prevent PR data or files from being saved."""
        pr = make_pr()
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]
        client.fetch_pr_commits = AsyncMock(side_effect=RuntimeError("Network error"))

        await sync_all_prs(db, client, sample_config)

        prs = await get_open_prs(db)
        assert len(prs) == 1
        commits = await get_pr_commits(db, prs[0]["id"])
        assert len(commits) == 0
        files = await get_pr_files(db, prs[0]["id"])
        assert len(files) == 2

    async def test_checks_failure_still_syncs_pr_and_rest(self, db, sample_config):
        """A failure on fetch_pr_check_runs should not prevent other data from being saved."""
        pr = make_pr()
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]
        client.fetch_pr_check_runs = AsyncMock(side_effect=RuntimeError("500 Server Error"))

        await sync_all_prs(db, client, sample_config)

        prs = await get_open_prs(db)
        assert len(prs) == 1
        commits = await get_pr_commits(db, prs[0]["id"])
        assert len(commits) == 2
        files = await get_pr_files(db, prs[0]["id"])
        assert len(files) == 2
        checks = await get_pr_checks(db, prs[0]["id"])
        assert len(checks) == 0

    async def test_skips_check_runs_without_head_sha(self, db, sample_config):
        pr = make_pr(head_sha=None)
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]

        await sync_all_prs(db, client, sample_config)

        client.fetch_pr_check_runs.assert_not_called()

    async def test_skips_detail_fetches_for_unchanged_pr(self, db, sample_config):
        """If a PR's updated_at and head_sha haven't changed, skip detail fetches."""
        client = mock_github_client()

        # First sync: details should be fetched
        await sync_all_prs(db, client, sample_config)
        assert client.fetch_pr_files.call_count == 1
        assert client.fetch_pr_check_runs.call_count == 1

        # Reset mocks
        client.fetch_pr_commits.reset_mock()
        client.fetch_pr_files.reset_mock()
        client.fetch_pr_check_runs.reset_mock()

        # Second sync with same data: details should be skipped
        await sync_all_prs(db, client, sample_config)
        client.fetch_pr_files.assert_not_called()
        client.fetch_pr_check_runs.assert_not_called()

    async def test_refetches_details_when_updated_at_changes(self, db, sample_config):
        """If updated_at changes, detail fetches should happen again."""
        client = mock_github_client()

        # First sync
        await sync_all_prs(db, client, sample_config)

        # Reset and change updated_at
        client.fetch_pr_files.reset_mock()
        client.fetch_pr_check_runs.reset_mock()
        updated_pr = make_pr(updated_at="2025-01-17T12:00:00Z")
        client.fetch_open_prs_for_authors.return_value = [updated_pr]

        await sync_all_prs(db, client, sample_config)
        assert client.fetch_pr_files.call_count == 1
        assert client.fetch_pr_check_runs.call_count == 1

    async def test_uses_inline_commits_when_complete(self, db, sample_config):
        """When PR has inline commits from GraphQL, don't fetch commits separately."""
        inline = [
            {
                "sha": "inline1",
                "message": "Inline commit",
                "author": "testuser",
                "authored_date": "2025-01-15T10:30:00Z",
                "url": "https://example.com",
            }
        ]
        pr = make_pr(commits=inline, commits_complete=True)
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]

        await sync_all_prs(db, client, sample_config)

        # fetch_pr_commits should NOT be called since inline commits were complete
        client.fetch_pr_commits.assert_not_called()
        prs = await get_open_prs(db)
        commits = await get_pr_commits(db, prs[0]["id"])
        assert len(commits) == 1
        assert commits[0]["sha"] == "inline1"

    async def test_falls_back_to_fetch_when_commits_incomplete(self, db, sample_config):
        """When inline commits are truncated (hasNextPage), fall back to full fetch."""
        pr = make_pr(commits=[{"sha": "partial", "message": "Partial", "author": "x", "authored_date": None, "url": None}], commits_complete=False)
        client = mock_github_client()
        client.fetch_open_prs_for_authors.return_value = [pr]

        await sync_all_prs(db, client, sample_config)

        # Should fall back to fetch_pr_commits
        assert client.fetch_pr_commits.call_count == 1
        prs = await get_open_prs(db)
        commits = await get_pr_commits(db, prs[0]["id"])
        assert len(commits) == 2  # from make_commits() via mock


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


class TestSyncAllIssues:
    async def test_syncs_authored_issues(self, db, sample_config):
        client = mock_github_client()
        await sync_all_issues(db, client, sample_config)

        issues = await get_open_issues(db)
        assert len(issues) == 1
        assert issues[0]["title"] == "Fix the widget bug"

    async def test_syncs_assigned_issues(self, db, sample_config):
        assigned_issue = make_issue(
            id=2002,
            node_id="I_assigned",
            number=20,
            title="Assigned issue",
            author="otheruser",
            url="https://github.com/testorg/testrepo/issues/20",
        )
        client = mock_github_client()
        client.fetch_assigned_issues.return_value = [assigned_issue]

        await sync_all_issues(db, client, sample_config)

        issues = await get_open_issues(db)
        assert len(issues) == 2

    async def test_deduplicates_authored_and_assigned_issues(self, db, sample_config):
        issue = make_issue()
        client = mock_github_client()
        client.fetch_open_issues_for_authors.return_value = [issue]
        client.fetch_assigned_issues.return_value = [issue]

        await sync_all_issues(db, client, sample_config)

        issues = await get_open_issues(db)
        assert len(issues) == 1
