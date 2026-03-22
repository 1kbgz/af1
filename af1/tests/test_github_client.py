"""Tests for af1.github_client — GitHub API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import httpx
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
            "lastCommit": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
            "allCommits": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {
                        "commit": {
                            "oid": "abc123",
                            "message": "Fix",
                            "author": {"name": "Test", "user": {"login": "testuser"}},
                            "authoredDate": "2025-01-01T00:00:00Z",
                            "url": "https://github.com/org/repo/commit/abc123",
                        }
                    }
                ],
            },
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
        assert result["commits"] == [
            {
                "sha": "abc123",
                "message": "Fix",
                "author": "testuser",
                "authored_date": "2025-01-01T00:00:00Z",
                "url": "https://github.com/org/repo/commit/abc123",
            }
        ]
        assert result["commits_complete"] is True

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
            "lastCommit": {"nodes": []},
            "allCommits": {"pageInfo": {"hasNextPage": False}, "nodes": []},
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
            "lastCommit": {"nodes": [{"commit": {"statusCheckRollup": None}}]},
            "allCommits": {"pageInfo": {"hasNextPage": False}, "nodes": []},
        }
        result = client._normalize_pr(node)
        assert result["ci_status"] is None

    def test_commits_complete_false_when_has_next_page(self):
        client = GitHubClient("token")
        node = {
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
            "lastCommit": {"nodes": []},
            "allCommits": {
                "pageInfo": {"hasNextPage": True},
                "nodes": [
                    {"commit": {"oid": "a1", "message": "First", "author": None, "authoredDate": None, "url": None}},
                ],
            },
        }
        result = client._normalize_pr(node)
        assert result["commits_complete"] is False
        assert len(result["commits"]) == 1


class TestRestPacing:
    async def test_rest_get_paces_requests(self, monkeypatch):
        """_rest_get sleeps for _rest_delay before each request."""
        import af1.github_client as gc

        mock_sleep = AsyncMock()
        monkeypatch.setattr(gc.asyncio, "sleep", mock_sleep)

        client = GitHubClient("token")
        client._rest_delay = 0.05
        ok = Mock()
        ok.status_code = 200
        ok.raise_for_status = lambda: None
        client._client.get = AsyncMock(return_value=ok)

        await client._rest_get("https://api.github.com/test")
        mock_sleep.assert_awaited_once_with(0.05)

    async def test_rest_get_skips_pacing_when_delay_zero(self, monkeypatch):
        """_rest_get skips sleep when _rest_delay is 0."""
        import af1.github_client as gc

        mock_sleep = AsyncMock()
        monkeypatch.setattr(gc.asyncio, "sleep", mock_sleep)

        client = GitHubClient("token")
        client._rest_delay = 0
        ok = Mock()
        ok.status_code = 200
        ok.raise_for_status = lambda: None
        client._client.get = AsyncMock(return_value=ok)

        await client._rest_get("https://api.github.com/test")
        mock_sleep.assert_not_awaited()


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
            "lastCommit": {"nodes": []},
            "allCommits": {"pageInfo": {"hasNextPage": False}, "nodes": []},
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

    async def test_approve_pull_request_success(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.status_code = 200
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client.approve_pull_request("org", "repo", 1)
        assert result == {"success": True}

    async def test_approve_pull_request_failure(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.status_code = 422
        mock_resp.json.return_value = {"message": "Cannot approve own PR"}
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client.approve_pull_request("org", "repo", 1)
        assert result["success"] is False
        assert "Cannot approve own PR" in result["error"]

    async def test_get_authenticated_user(self):
        client = GitHubClient("token")
        mock_resp = Mock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json.return_value = {"login": "user1", "name": "User One"}
        client._client.get = AsyncMock(return_value=mock_resp)

        result = await client.get_authenticated_user()
        assert result["login"] == "user1"


class TestRestGetRetry:
    async def test_retries_on_403_with_retry_after(self, monkeypatch):
        """_rest_get retries on 403 and succeeds on next attempt."""
        import af1.github_client as gc

        monkeypatch.setattr(gc.asyncio, "sleep", AsyncMock())

        client = GitHubClient("token")
        client._rest_delay = 0
        forbidden = Mock()
        forbidden.status_code = 403
        forbidden.headers = {"retry-after": "1"}
        ok = Mock()
        ok.status_code = 200
        ok.raise_for_status = lambda: None
        client._client.get = AsyncMock(side_effect=[forbidden, ok])

        resp = await client._rest_get("https://api.github.com/test")
        assert resp.status_code == 200
        assert client._client.get.call_count == 2

    async def test_retries_on_403_with_ratelimit_reset(self, monkeypatch):
        """_rest_get uses x-ratelimit-reset header for wait time."""
        import af1.github_client as gc

        monkeypatch.setattr(gc.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(gc.time, "time", lambda: 1000)

        client = GitHubClient("token")
        client._rest_delay = 0
        forbidden = Mock()
        forbidden.status_code = 403
        forbidden.headers = {"x-ratelimit-reset": "1002"}
        ok = Mock()
        ok.status_code = 200
        ok.raise_for_status = lambda: None
        client._client.get = AsyncMock(side_effect=[forbidden, ok])

        resp = await client._rest_get("https://api.github.com/test")
        assert resp.status_code == 200
        gc.asyncio.sleep.assert_awaited_once_with(2)

    async def test_retries_on_403_with_exponential_backoff(self, monkeypatch):
        """_rest_get uses exponential backoff when no rate-limit headers."""
        import af1.github_client as gc

        monkeypatch.setattr(gc.asyncio, "sleep", AsyncMock())

        client = GitHubClient("token")
        client._rest_delay = 0
        forbidden = Mock()
        forbidden.status_code = 403
        forbidden.headers = {}
        ok = Mock()
        ok.status_code = 200
        ok.raise_for_status = lambda: None
        client._client.get = AsyncMock(side_effect=[forbidden, forbidden, ok])

        resp = await client._rest_get("https://api.github.com/test")
        assert resp.status_code == 200
        assert client._client.get.call_count == 3
        # backoff: 2^0=1, 2^1=2
        assert gc.asyncio.sleep.await_count == 2

    async def test_raises_after_max_retries(self, monkeypatch):
        """_rest_get raises after exhausting retries on persistent 403."""
        import af1.github_client as gc

        monkeypatch.setattr(gc.asyncio, "sleep", AsyncMock())

        client = GitHubClient("token")
        client._rest_delay = 0
        forbidden = Mock()
        forbidden.status_code = 403
        forbidden.headers = {}
        forbidden.raise_for_status = Mock(side_effect=httpx.HTTPStatusError("403", request=Mock(), response=forbidden))
        client._client.get = AsyncMock(return_value=forbidden)

        with pytest.raises(httpx.HTTPStatusError):
            await client._rest_get("https://api.github.com/test")
        assert client._client.get.call_count == 3

    async def test_no_retry_on_non_403(self):
        """_rest_get does not retry on non-403 errors."""
        client = GitHubClient("token")
        client._rest_delay = 0
        not_found = Mock()
        not_found.status_code = 404
        not_found.raise_for_status = Mock(side_effect=httpx.HTTPStatusError("404", request=Mock(), response=not_found))
        client._client.get = AsyncMock(return_value=not_found)

        with pytest.raises(httpx.HTTPStatusError):
            await client._rest_get("https://api.github.com/test")
        assert client._client.get.call_count == 1
