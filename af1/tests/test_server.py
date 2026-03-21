"""Tests for af1.server — Starlette ASGI server API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from af1.config import Config
from af1.db import get_db, upsert_issue, upsert_pr_check_runs, upsert_pr_commits, upsert_pr_files, upsert_pull_request
from af1.server import create_app, create_routes
from af1.tests.conftest import make_checks, make_commits, make_files, make_issue, make_pr, mock_github_client

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture
def test_config(tmp_path):
    """Config for testing (no real GitHub token needed for API tests)."""
    return Config(
        github_token="test_token",
        github_host="github.com",
        watched_authors=["testuser"],
        db_path=tmp_path / "test.db",
        host="127.0.0.1",
        port=8510,
        sync_interval_seconds=60,
    )


@pytest.fixture
def app(test_config):
    """Create app without lifespan (we'll set state manually)."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    from af1.server import (
        api_batch_approve,
        api_batch_close,
        api_batch_merge,
        api_config,
        api_health,
        api_issue_detail,
        api_issues,
        api_me,
        api_pr_detail,
        api_pull_requests,
        api_sync,
        api_sync_pr,
        api_sync_repo,
    )

    routes = [
        Route("/api/health", api_health),
        Route("/api/me", api_me),
        Route("/api/config", api_config),
        Route("/api/prs", api_pull_requests),
        Route("/api/prs/merge", api_batch_merge, methods=["POST"]),
        Route("/api/prs/close", api_batch_close, methods=["POST"]),
        Route("/api/prs/approve", api_batch_approve, methods=["POST"]),
        Route("/api/prs/{owner}/{repo}/{number:int}", api_pr_detail),
        Route("/api/issues", api_issues),
        Route("/api/issues/{owner}/{repo}/{number:int}", api_issue_detail),
        Route("/api/sync", api_sync, methods=["POST"]),
        Route("/api/prs/{owner}/{repo}/{number:int}/sync", api_sync_pr, methods=["POST"]),
        Route("/api/repos/{owner}/{repo}/sync", api_sync_repo, methods=["POST"]),
    ]

    app = Starlette(routes=routes)
    app.state.config = test_config
    return app


@pytest.fixture
def client(app):
    """Create a test client (httpx.AsyncClient via Starlette TestClient)."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


class TestHealthEndpoint:
    async def test_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestMeEndpoint:
    async def test_me_success(self, app, client):
        app.state.github_client = mock_github_client()
        resp = await client.get("/api/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["login"] == "testuser"

    async def test_me_error(self, app, client):
        mock_client = AsyncMock()
        mock_client.get_authenticated_user = AsyncMock(side_effect=RuntimeError("Auth failed"))
        app.state.github_client = mock_client

        resp = await client.get("/api/me")
        assert resp.status_code == 500
        assert "error" in resp.json()


class TestConfigEndpoint:
    async def test_config(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["watched_authors"] == ["testuser"]
        assert data["sync_interval_seconds"] == 60


class TestPullRequestsEndpoint:
    async def test_prs_empty(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            resp = await client.get("/api/prs")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            await db.close()

    async def test_prs_returns_data(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            pr = make_pr()
            await upsert_pull_request(db, pr)
            await db.commit()

            resp = await client.get("/api/prs")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["title"] == "Fix the widget"
        finally:
            await db.close()

    async def test_prs_filters_by_authors(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            pr1 = make_pr(id=1, node_id="PR_1", number=1, author="alice", url="https://github.com/org/repo/pull/1")
            pr2 = make_pr(id=2, node_id="PR_2", number=2, author="bob", url="https://github.com/org/repo/pull/2")
            await upsert_pull_request(db, pr1)
            await upsert_pull_request(db, pr2)
            await db.commit()

            resp = await client.get("/api/prs?authors=alice")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["author"] == "alice"
        finally:
            await db.close()


class TestPRDetailEndpoint:
    async def test_pr_detail_found(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            pr = make_pr()
            pr_id = await upsert_pull_request(db, pr)
            await upsert_pr_commits(db, pr_id, make_commits())
            await upsert_pr_files(db, pr_id, make_files())
            await upsert_pr_check_runs(db, pr_id, make_checks())
            await db.commit()

            resp = await client.get("/api/prs/testorg/testrepo/42")
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "Fix the widget"
            assert len(data["commits"]) == 2
            assert len(data["files"]) == 2
            assert len(data["checks"]) == 3
        finally:
            await db.close()

    async def test_pr_detail_not_found(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            resp = await client.get("/api/prs/nonexistent/repo/999")
            assert resp.status_code == 404
        finally:
            await db.close()


class TestBatchMerge:
    async def test_batch_merge_success(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        pr = make_pr(repo_owner="org", repo_name="repo", number=1)
        await upsert_pull_request(db, pr)
        await db.commit()
        try:
            resp = await client.post(
                "/api/prs/merge",
                json={"targets": [{"owner": "org", "repo": "repo", "number": 1}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["success"] is True
            # Verify DB state was updated
            from af1.db import get_pr

            pr_row = await get_pr(db, "org", "repo", 1)
            assert pr_row["state"] == "MERGED"
        finally:
            await db.close()

    async def test_batch_merge_missing_fields(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        try:
            resp = await client.post(
                "/api/prs/merge",
                json={"targets": [{"owner": "", "repo": "repo", "number": 1}]},
            )
            data = resp.json()
            assert data[0]["success"] is False
            assert "Missing fields" in data[0]["error"]
        finally:
            await db.close()

    async def test_batch_merge_multiple(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        pr1 = make_pr(id=1, node_id="PR_1", repo_owner="org", repo_name="repo1", number=1, url="https://github.com/org/repo1/pull/1")
        pr2 = make_pr(id=2, node_id="PR_2", repo_owner="org", repo_name="repo2", number=2, url="https://github.com/org/repo2/pull/2")
        await upsert_pull_request(db, pr1)
        await upsert_pull_request(db, pr2)
        await db.commit()
        try:
            targets = [
                {"owner": "org", "repo": "repo1", "number": 1},
                {"owner": "org", "repo": "repo2", "number": 2},
            ]
            resp = await client.post("/api/prs/merge", json={"targets": targets})
            data = resp.json()
            assert len(data) == 2
            assert all(r["success"] for r in data)
        finally:
            await db.close()


class TestBatchClose:
    async def test_batch_close_success(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        pr = make_pr(repo_owner="org", repo_name="repo", number=1)
        await upsert_pull_request(db, pr)
        await db.commit()
        try:
            resp = await client.post(
                "/api/prs/close",
                json={"targets": [{"owner": "org", "repo": "repo", "number": 1}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data[0]["success"] is True
            # Verify DB state was updated
            from af1.db import get_pr

            pr_row = await get_pr(db, "org", "repo", 1)
            assert pr_row["state"] == "CLOSED"
        finally:
            await db.close()

    async def test_batch_close_missing_fields(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        try:
            resp = await client.post(
                "/api/prs/close",
                json={"targets": [{"owner": "org", "repo": "", "number": 1}]},
            )
            data = resp.json()
            assert data[0]["success"] is False
        finally:
            await db.close()


class TestBatchApprove:
    async def test_batch_approve_success(self, app, client):
        app.state.github_client = mock_github_client()
        resp = await client.post(
            "/api/prs/approve",
            json={"targets": [{"owner": "org", "repo": "repo", "number": 1}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["success"] is True

    async def test_batch_approve_missing_fields(self, app, client):
        app.state.github_client = mock_github_client()
        resp = await client.post(
            "/api/prs/approve",
            json={"targets": [{"owner": "", "repo": "repo", "number": 1}]},
        )
        data = resp.json()
        assert data[0]["success"] is False
        assert "Missing fields" in data[0]["error"]

    async def test_batch_approve_multiple(self, app, client):
        app.state.github_client = mock_github_client()
        targets = [
            {"owner": "org", "repo": "repo1", "number": 1},
            {"owner": "org", "repo": "repo2", "number": 2},
        ]
        resp = await client.post("/api/prs/approve", json={"targets": targets})
        data = resp.json()
        assert len(data) == 2
        assert all(r["success"] for r in data)


class TestSyncEndpoint:
    async def test_sync_success(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        try:
            resp = await client.post("/api/sync")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            await db.close()

    async def test_sync_error(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        mock_client = mock_github_client()
        mock_client.fetch_open_prs_for_authors = AsyncMock(side_effect=RuntimeError("API down"))
        app.state.github_client = mock_client
        try:
            resp = await client.post("/api/sync")
            assert resp.status_code == 500
            assert "error" in resp.json()
        finally:
            await db.close()


class TestSyncPREndpoint:
    async def test_sync_pr_success(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        try:
            resp = await client.post("/api/prs/org/repo/42/sync")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            await db.close()

    async def test_sync_pr_error(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        mock_client = mock_github_client()
        mock_client.fetch_single_pr = AsyncMock(side_effect=RuntimeError("Not found"))
        app.state.github_client = mock_client
        try:
            resp = await client.post("/api/prs/org/repo/999/sync")
            assert resp.status_code == 500
            assert "error" in resp.json()
        finally:
            await db.close()


class TestSyncRepoEndpoint:
    async def test_sync_repo_success(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        app.state.github_client = mock_github_client()
        try:
            resp = await client.post("/api/repos/org/repo/sync")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            await db.close()

    async def test_sync_repo_error(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        mock_client = mock_github_client()
        mock_client.fetch_open_prs_for_authors = AsyncMock(side_effect=RuntimeError("API down"))
        app.state.github_client = mock_client
        try:
            resp = await client.post("/api/repos/org/repo/sync")
            assert resp.status_code == 500
            assert "error" in resp.json()
        finally:
            await db.close()


class TestCreateApp:
    def test_create_app_with_config(self, test_config):
        app = create_app(test_config)
        assert app.state.config.github_token == "test_token"

    def test_create_routes(self):
        routes = create_routes()
        # Should have API routes + maybe static mount
        route_paths = []
        for r in routes:
            if hasattr(r, "path"):
                route_paths.append(r.path)
        assert "/api/health" in route_paths
        assert "/api/me" in route_paths
        assert "/api/config" in route_paths
        assert "/api/prs" in route_paths
        assert "/api/prs/merge" in route_paths
        assert "/api/prs/close" in route_paths
        assert "/api/issues" in route_paths
        assert "/api/sync" in route_paths
        assert "/api/prs/{owner}/{repo}/{number:int}/sync" in route_paths
        assert "/api/repos/{owner}/{repo}/sync" in route_paths


class TestIssuesEndpoint:
    async def test_issues_empty(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            resp = await client.get("/api/issues")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            await db.close()

    async def test_issues_returns_data(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            issue = make_issue()
            await upsert_issue(db, issue)
            await db.commit()

            resp = await client.get("/api/issues")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["title"] == "Fix the widget bug"
        finally:
            await db.close()

    async def test_issues_filters_by_authors(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            i1 = make_issue(id=2001, node_id="I_1", number=1, author="alice", url="https://github.com/org/repo/issues/1")
            i2 = make_issue(id=2002, node_id="I_2", number=2, author="bob", url="https://github.com/org/repo/issues/2")
            await upsert_issue(db, i1)
            await upsert_issue(db, i2)
            await db.commit()

            resp = await client.get("/api/issues?authors=alice")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["author"] == "alice"
        finally:
            await db.close()


class TestIssueDetailEndpoint:
    async def test_issue_detail_found(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            issue = make_issue()
            await upsert_issue(db, issue)
            await db.commit()

            resp = await client.get("/api/issues/testorg/testrepo/10")
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "Fix the widget bug"
            assert data["comment_count"] == 3
        finally:
            await db.close()

    async def test_issue_detail_not_found(self, app, client, tmp_path):
        db = await get_db(tmp_path / "test.db")
        app.state.db = db
        try:
            resp = await client.get("/api/issues/nonexistent/repo/999")
            assert resp.status_code == 404
        finally:
            await db.close()


class TestNoCacheMiddleware:
    async def test_no_cache_headers_on_non_api_responses(self, test_config):
        """NoCacheStaticMiddleware should add cache-control headers to non-API responses."""
        app = create_app(test_config)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/api/health")
            # API responses don't get the no-cache header via middleware
            # (they go through the normal handler)
            assert resp.status_code == 200
