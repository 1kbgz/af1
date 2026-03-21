"""Tests for af1.github_client — GitHub API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from af1.github_client import GitHubClient

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestGitHubClientInit:
    def test_github_com_urls(self):
        client = GitHubClient("token123", "github.com")
        assert client._api_base == "https://api.github.com"
        assert client._graphql_url == "https://api.github.com/graphql"

    def test_ghe_urls(self):
        client = GitHubClient("token123", "ghe.corp.com")
        assert client._api_base == "https://ghe.corp.com/api/v3"
        assert client._graphql_url == "https://ghe.corp.com/api/graphql"

    def test_default_host(self):
        client = GitHubClient("token123")
        assert client._api_base == "https://api.github.com"


class TestNormalizePr:
    def test_normalizes_full_pr_node(self):
        client = GitHubClient("token")
        node = {
            "databaseId": 1001,
            "id": "MDExOlB1bGxSZXF1ZXN0MQ==",
            "number": 42,
            "title": "Add feature",
            "body": "PR body",
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "additions": 10,
            "deletions": 3,
            "changedFiles": 2,
            "headRefName": "feature",
            "headRefOid": "abc123",
            "baseRefName": "main",
            "baseRefOid": "def456",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-02T00:00:00Z",
            "mergedAt": None,
            "closedAt": None,
            "url": "https://github.com/org/repo/pull/42",
            "author": {"login": "testuser", "avatarUrl": "https://avatars.example.com/1"},
            "repository": {"owner": {"login": "org"}, "name": "repo"},
            "labels": {"nodes": [{"name": "bug", "color": "d73a4a"}]},
            "reviewDecision": "APPROVED",
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        }
        result = client._normalize_pr(node)
        assert result["id"] == 1001
        assert result["repo_owner"] == "org"
        assert result["repo_name"] == "repo"
        assert result["number"] == 42
        assert result["author"] == "testuser"
        assert result["ci_status"] == "SUCCESS"
        assert result["labels"] == [{"name": "bug", "color": "d73a4a"}]
        assert result["review_decision"] == "APPROVED"

    def test_normalizes_pr_with_missing_author(self):
        client = GitHubClient("token")
        node = {
            "databaseId": 1,
            "id": "node1",
            "number": 1,
            "title": "PR title",
            "state": "OPEN",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
            "url": "https://github.com/org/repo/pull/1",
            "author": None,
            "repository": {"owner": {"login": "org"}, "name": "repo"},
            "labels": {"nodes": []},
            "commits": {"nodes": []},
        }
        result = client._normalize_pr(node)
        assert result["author"] == "ghost"
        assert result["ci_status"] is None

    def test_normalizes_pr_with_no_status_rollup(self):
        client = GitHubClient("token")
        node = {
            "databaseId": 1,
            "id": "node1",
            "number": 1,
            "title": "PR title",
            "state": "OPEN",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
            "url": "https://github.com/org/repo/pull/1",
            "author": {"login": "user1", "avatarUrl": None},
            "repository": {"owner": {"login": "org"}, "name": "repo"},
            "labels": {"nodes": []},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]},
        }
        result = client._normalize_pr(node)
        assert result["ci_status"] is None


class TestGraphQL:
    async def test_graphql_raises_on_errors(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {"errors": [{"message": "Bad request"}]}
        client._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(RuntimeError, match="GraphQL errors"):
            await client._graphql("query { viewer { login } }")

    async def test_graphql_returns_data(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {"data": {"viewer": {"login": "user1"}}}
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client._graphql("query { viewer { login } }")
        assert result == {"viewer": {"login": "user1"}}


class TestFetchOpenPrs:
    async def test_deduplicates_prs(self):
        client = GitHubClient("token")
        pr_node = {
            "databaseId": 1,
            "id": "node1",
            "number": 1,
            "title": "PR",
            "state": "OPEN",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
            "url": "https://github.com/org/repo/pull/1",
            "author": {"login": "user1", "avatarUrl": None},
            "repository": {"owner": {"login": "org"}, "name": "repo"},
            "labels": {"nodes": []},
            "commits": {"nodes": []},
        }

        # Return same PR for two different authors
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {
            "data": {
                "search": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [pr_node],
                }
            }
        }
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client.fetch_open_prs_for_authors(["user1", "user2"])
        # Same PR returned for both, but should be deduped
        assert len(result) == 1

    async def test_skips_none_nodes(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {
            "data": {
                "search": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [None],
                }
            }
        }
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client.fetch_open_prs_for_authors(["user1"])
        assert result == []


class TestRestEndpoints:
    async def test_fetch_pr_files(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = [{"filename": "a.py", "status": "modified", "additions": 5, "deletions": 2, "patch": "@@ -1 +1 @@\n-old\n+new"}]
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.fetch_pr_files("org", "repo", 1)
        assert len(result) == 1
        assert result[0]["filename"] == "a.py"

    async def test_fetch_pr_check_runs(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {
            "check_runs": [{"name": "CI", "status": "completed", "conclusion": "success", "html_url": "https://example.com"}]
        }
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.fetch_pr_check_runs("org", "repo", "abc123")
        assert len(result) == 1
        assert result[0]["name"] == "CI"
        assert result[0]["url"] == "https://example.com"

    async def test_merge_pull_request_success(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.status_code = 200
        client._client.put = AsyncMock(return_value=mock_resp)

        result = await client.merge_pull_request("org", "repo", 1)
        assert result == {"success": True}

    async def test_merge_pull_request_failure(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.status_code = 405
        mock_resp.json.return_value = {"message": "Pull Request is not mergeable"}
        client._client.put = AsyncMock(return_value=mock_resp)

        result = await client.merge_pull_request("org", "repo", 1)
        assert result["success"] is False
        assert "not mergeable" in result["error"]

    async def test_close_pull_request_success(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.status_code = 200
        client._client.patch = AsyncMock(return_value=mock_resp)

        result = await client.close_pull_request("org", "repo", 1)
        assert result == {"success": True}

    async def test_close_pull_request_failure(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.status_code = 422
        mock_resp.json.return_value = {"message": "Validation failed"}
        client._client.patch = AsyncMock(return_value=mock_resp)

        result = await client.close_pull_request("org", "repo", 1)
        assert result["success"] is False

    async def test_get_authenticated_user(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {"login": "user1", "name": "User One"}
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.get_authenticated_user()
        assert result["login"] == "user1"
