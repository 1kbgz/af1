"""Shared fixtures for af1 tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from af1.config import Config
from af1.db import get_db


@pytest.fixture
def tmp_db_path(tmp_path):
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest_asyncio.fixture
async def db(tmp_db_path):
    """Create and return a temporary database connection."""
    conn = await get_db(tmp_db_path)
    yield conn
    await conn.close()


@pytest.fixture
def sample_config(tmp_db_path):
    """Return a test Config instance."""
    return Config(
        github_token="ghp_test_token_123",
        github_host="github.com",
        watched_authors=["testuser", "otheruser"],
        db_path=tmp_db_path,
        host="127.0.0.1",
        port=8510,
        sync_interval_seconds=60,
    )


def make_pr(
    *,
    id: int = 1001,
    node_id: str = "PR_node1",
    repo_owner: str = "testorg",
    repo_name: str = "testrepo",
    number: int = 42,
    title: str = "Fix the widget",
    body: str = "This PR fixes the widget.",
    state: str = "OPEN",
    author: str = "testuser",
    author_avatar: str = "https://avatars.example.com/u/1",
    draft: bool = False,
    mergeable: str = "MERGEABLE",
    head_ref: str = "fix-widget",
    head_sha: str = "abc123def456",
    base_ref: str = "main",
    base_sha: str = "000111222333",
    additions: int = 10,
    deletions: int = 3,
    changed_files: int = 2,
    review_decision: str = "APPROVED",
    ci_status: str = "SUCCESS",
    labels: list | None = None,
    created_at: str = "2025-01-15T10:00:00Z",
    updated_at: str = "2025-01-16T12:00:00Z",
    merged_at: str | None = None,
    closed_at: str | None = None,
    url: str = "https://github.com/testorg/testrepo/pull/42",
    commits: list | None = None,
    commits_complete: bool | None = None,
) -> dict:
    """Create a sample PR dict matching GitHubClient._normalize_pr output."""
    result = {
        "id": id,
        "node_id": node_id,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "author": author,
        "author_avatar": author_avatar,
        "draft": draft,
        "mergeable": mergeable,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "review_decision": review_decision,
        "ci_status": ci_status,
        "labels": labels or [{"name": "bug", "color": "d73a4a"}],
        "created_at": created_at,
        "updated_at": updated_at,
        "merged_at": merged_at,
        "closed_at": closed_at,
        "url": url,
    }
    if commits is not None:
        result["commits"] = commits
        result["commits_complete"] = commits_complete if commits_complete is not None else True
    return result


def make_commits():
    """Sample commit data."""
    return [
        {
            "sha": "abc123def456",
            "message": "Fix the widget\n\nDetailed description",
            "author": "testuser",
            "authored_date": "2025-01-15T10:30:00Z",
            "url": "https://github.com/testorg/testrepo/commit/abc123def456",
        },
        {
            "sha": "def789ghi012",
            "message": "Address review comments",
            "author": "testuser",
            "authored_date": "2025-01-16T11:00:00Z",
            "url": "https://github.com/testorg/testrepo/commit/def789ghi012",
        },
    ]


def make_files():
    """Sample file data."""
    return [
        {
            "filename": "src/widget.py",
            "status": "modified",
            "additions": 8,
            "deletions": 2,
            "patch": "@@ -10,5 +10,11 @@\n-old line\n+new line\n+another new line",
        },
        {
            "filename": "tests/test_widget.py",
            "status": "added",
            "additions": 2,
            "deletions": 1,
            "patch": "@@ -0,0 +1,2 @@\n+def test_widget():\n+    assert True",
        },
    ]


def make_checks():
    """Sample check run data."""
    return [
        {
            "name": "CI",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/testorg/testrepo/actions/runs/1",
        },
        {
            "name": "lint",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/testorg/testrepo/actions/runs/2",
        },
        {
            "name": "typecheck",
            "status": "completed",
            "conclusion": "failure",
            "url": "https://github.com/testorg/testrepo/actions/runs/3",
        },
    ]


def mock_github_client():
    """Create a mock GitHubClient with standard responses."""
    client = AsyncMock()
    client.fetch_open_prs_for_authors = AsyncMock(return_value=[make_pr()])
    client.fetch_review_requested_prs = AsyncMock(return_value=[])
    client.fetch_pr_commits = AsyncMock(return_value=make_commits())
    client.fetch_pr_files = AsyncMock(return_value=make_files())
    client.fetch_pr_check_runs = AsyncMock(return_value=make_checks())
    client.fetch_single_pr = AsyncMock(return_value=make_pr())
    client.fetch_open_issues_for_authors = AsyncMock(return_value=[make_issue()])
    client.fetch_assigned_issues = AsyncMock(return_value=[])
    client.get_authenticated_user = AsyncMock(
        return_value={"login": "testuser", "name": "Test User", "avatar_url": "https://avatars.example.com/u/1"}
    )
    client.merge_pull_request = AsyncMock(return_value={"success": True})
    client.close_pull_request = AsyncMock(return_value={"success": True})
    client.approve_pull_request = AsyncMock(return_value={"success": True})
    client.fetch_maintained_repos = AsyncMock(return_value=[])
    client.fetch_open_prs_for_repo = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


def make_repo(
    *,
    owner: str = "testorg",
    name: str = "testrepo",
    description: str | None = "A test repo",
    is_private: bool = False,
    is_archived: bool = False,
    default_branch: str = "main",
    viewer_permission: str = "ADMIN",
    pushed_at: str = "2025-01-16T12:00:00Z",
    url: str | None = None,
) -> dict:
    """Create a sample repo dict matching GitHubClient._normalize_repo output."""
    return {
        "name_with_owner": f"{owner}/{name}",
        "owner": owner,
        "name": name,
        "description": description,
        "is_private": is_private,
        "is_archived": is_archived,
        "default_branch": default_branch,
        "viewer_permission": viewer_permission,
        "pushed_at": pushed_at,
        "url": url or f"https://github.com/{owner}/{name}",
    }


def make_issue(
    *,
    id: int = 2001,
    node_id: str = "I_node1",
    repo_owner: str = "testorg",
    repo_name: str = "testrepo",
    number: int = 10,
    title: str = "Fix the widget bug",
    body: str = "The widget is broken.",
    state: str = "OPEN",
    author: str = "testuser",
    author_avatar: str = "https://avatars.example.com/u/1",
    labels: list | None = None,
    assignees: list | None = None,
    comment_count: int = 3,
    created_at: str = "2025-01-15T10:00:00Z",
    updated_at: str = "2025-01-16T12:00:00Z",
    closed_at: str | None = None,
    url: str = "https://github.com/testorg/testrepo/issues/10",
) -> dict:
    """Create a sample issue dict matching GitHubClient._normalize_issue output."""
    return {
        "id": id,
        "node_id": node_id,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "author": author,
        "author_avatar": author_avatar,
        "labels": labels or [{"name": "bug", "color": "d73a4a"}],
        "assignees": assignees or ["testuser"],
        "comment_count": comment_count,
        "created_at": created_at,
        "updated_at": updated_at,
        "closed_at": closed_at,
        "url": url,
    }
