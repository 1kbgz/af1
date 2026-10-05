"""Tests for af1.mcp_server — MCP tools over the local cache."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver.exceptions import ToolError
from starlette.applications import Starlette

from af1 import mcp_server as M
from af1.db import upsert_issue, upsert_pull_request, upsert_repo
from af1.mcp_server import (
    ListIssuesInput,
    ListPRsInput,
    MergeInput,
    Ref,
    SyncInput,
    TargetsInput,
    af1_approve_prs,
    af1_close_prs,
    af1_get_issue,
    af1_get_pr,
    af1_list_issues,
    af1_list_prs,
    af1_list_repos,
    af1_merge_prs,
    af1_sync,
)
from af1.tests.conftest import make_issue, make_pr, make_repo, mock_github_client

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest_asyncio.fixture
async def mcp_ctx(db, sample_config):
    """Wire the MCP module to a temp db + mock client, and reset global state after."""
    client = mock_github_client()
    M.set_context(db=db, client=client, config=sample_config)
    yield db, client, sample_config
    M._ctx.clear()


def _json(result: str) -> dict:
    return json.loads(result)


async def _seed_prs(db):
    await upsert_pull_request(
        db, make_pr(id=1, node_id="n1", repo_owner="acme", repo_name="widget", number=1, author="alice", ci_status="SUCCESS", draft=False)
    )
    await upsert_pull_request(
        db, make_pr(id=2, node_id="n2", repo_owner="acme", repo_name="widget", number=2, author="bob", ci_status="FAILURE", draft=False)
    )
    await upsert_pull_request(
        db, make_pr(id=3, node_id="n3", repo_owner="other", repo_name="thing", number=3, author="testuser", ci_status="SUCCESS", draft=True)
    )
    await db.commit()


class TestListPRs:
    async def test_all_scope_returns_everything(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await _seed_prs(db)
        out = _json(await af1_list_prs(ListPRsInput(scope="all")))
        assert out["total"] == 3
        assert {i["repo"] for i in out["items"]} == {"acme/widget", "other/thing"}

    async def test_mine_scope_filters_to_watched_authors(self, mcp_ctx):
        db, _, _config = mcp_ctx
        await _seed_prs(db)
        out = _json(await af1_list_prs(ListPRsInput(scope="mine")))
        assert out["total"] == 1
        assert out["items"][0]["author"] == "testuser"

    async def test_maintained_scope_filters_to_repo_table(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await _seed_prs(db)
        await upsert_repo(db, make_repo(owner="acme", name="widget"))
        await db.commit()
        out = _json(await af1_list_prs(ListPRsInput(scope="maintained")))
        assert {i["repo"] for i in out["items"]} == {"acme/widget"}
        assert out["total"] == 2

    async def test_ci_and_draft_filters(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await _seed_prs(db)
        out = _json(await af1_list_prs(ListPRsInput(scope="all", ci_status=["SUCCESS"], draft=False)))
        assert out["total"] == 1
        assert out["items"][0]["repo"] == "acme/widget"
        assert out["items"][0]["number"] == 1

    async def test_text_filter(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await upsert_pull_request(db, make_pr(id=10, node_id="x", number=10, title="Bump dependency"))
        await upsert_pull_request(db, make_pr(id=11, node_id="y", number=11, title="Refactor core"))
        await db.commit()
        out = _json(await af1_list_prs(ListPRsInput(scope="all", text="bump")))
        assert out["total"] == 1
        assert out["items"][0]["number"] == 10

    async def test_pagination(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await _seed_prs(db)
        out = _json(await af1_list_prs(ListPRsInput(scope="all", limit=2, offset=0)))
        assert out["count"] == 2
        assert out["has_more"] is True
        assert out["next_offset"] == 2

    async def test_markdown_format(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await _seed_prs(db)
        out = await af1_list_prs(ListPRsInput(scope="all", response_format="markdown"))
        assert out.startswith("# Pull Requests")
        assert "acme/widget#1" in out


class TestGetPR:
    async def test_returns_detail(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await upsert_pull_request(db, make_pr(id=1, node_id="n1", repo_owner="acme", repo_name="widget", number=5))
        await db.commit()
        out = _json(await af1_get_pr(Ref(owner="acme", repo="widget", number=5)))
        assert out["pr"]["number"] == 5
        assert "commits" in out and "files" in out and "checks" in out

    async def test_missing_pr_returns_actionable_error(self, mcp_ctx):
        out = _json(await af1_get_pr(Ref(owner="x", repo="y", number=99)))
        assert "error" in out
        assert "af1_sync" in out["error"]


class TestIssues:
    async def test_list_and_filter(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await upsert_issue(db, make_issue(id=1, node_id="i1", repo_owner="acme", repo_name="widget", number=1, author="alice"))
        await upsert_issue(db, make_issue(id=2, node_id="i2", repo_owner="acme", repo_name="widget", number=2, author="bob"))
        await db.commit()
        out = _json(await af1_list_issues(ListIssuesInput(authors=["alice"])))
        assert out["total"] == 1
        assert out["items"][0]["author"] == "alice"

    async def test_get_issue_missing(self, mcp_ctx):
        out = _json(await af1_get_issue(Ref(owner="x", repo="y", number=1)))
        assert "error" in out


class TestListRepos:
    async def test_lists_repos(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await upsert_repo(db, make_repo(owner="acme", name="widget"))
        await db.commit()
        out = _json(await af1_list_repos())
        assert out["count"] == 1
        assert out["repos"][0]["name_with_owner"] == "acme/widget"


class TestSync:
    async def test_no_token_errors(self, mcp_ctx):
        db, client, config = mcp_ctx
        M.set_context(db=db, client=client, config=replace(config, github_token=""))
        out = _json(await af1_sync(SyncInput()))
        assert "error" in out

    async def test_full_sync_runs(self, mcp_ctx):
        out = _json(await af1_sync(SyncInput()))
        assert out["status"] == "ok"
        assert out["scope"] == "full"

    async def test_single_pr_sync(self, mcp_ctx):
        _, client, _ = mcp_ctx
        out = _json(await af1_sync(SyncInput(pr=Ref(owner="acme", repo="widget", number=42))))
        assert out["scope"] == "single_pr"
        client.fetch_single_pr.assert_awaited()


class TestWriteActions:
    async def test_merge_updates_cache_state(self, mcp_ctx):
        db, client, _ = mcp_ctx
        await upsert_pull_request(db, make_pr(id=1, node_id="n1", repo_owner="acme", repo_name="widget", number=1))
        await db.commit()
        out = _json(await af1_merge_prs(MergeInput(targets=[Ref(owner="acme", repo="widget", number=1)])))
        assert out["results"][0]["success"] is True
        client.merge_pull_request.assert_awaited_with("acme", "widget", 1, "merge")
        from af1.db import get_pr

        pr = await get_pr(db, "acme", "widget", 1)
        assert pr["state"] == "MERGED"

    async def test_merge_method_passed_through(self, mcp_ctx):
        _, client, _ = mcp_ctx
        await af1_merge_prs(MergeInput(targets=[Ref(owner="o", repo="r", number=1)], merge_method="squash"))
        client.merge_pull_request.assert_awaited_with("o", "r", 1, "squash")

    async def test_approve(self, mcp_ctx):
        _, client, _ = mcp_ctx
        out = _json(await af1_approve_prs(TargetsInput(targets=[Ref(owner="o", repo="r", number=2)])))
        assert out["results"][0]["success"] is True
        client.approve_pull_request.assert_awaited_with("o", "r", 2)

    async def test_close_marks_closed(self, mcp_ctx):
        db, _client, _ = mcp_ctx
        await upsert_pull_request(db, make_pr(id=1, node_id="n1", repo_owner="o", repo_name="r", number=3))
        await db.commit()
        out = _json(await af1_close_prs(TargetsInput(targets=[Ref(owner="o", repo="r", number=3)])))
        assert out["results"][0]["success"] is True
        from af1.db import get_pr

        assert (await get_pr(db, "o", "r", 3))["state"] == "CLOSED"

    async def test_write_without_token_errors(self, mcp_ctx):
        db, client, config = mcp_ctx
        M.set_context(db=db, client=client, config=replace(config, github_token=""))
        out = _json(await af1_merge_prs(MergeInput(targets=[Ref(owner="o", repo="r", number=1)])))
        assert "error" in out
        client.merge_pull_request.assert_not_called()

    async def test_failed_action_does_not_update_state(self, mcp_ctx):
        db, client, _ = mcp_ctx
        client.merge_pull_request.return_value = {"success": False, "error": "not mergeable"}
        await upsert_pull_request(db, make_pr(id=1, node_id="n1", repo_owner="o", repo_name="r", number=4, state="OPEN"))
        await db.commit()
        out = _json(await af1_merge_prs(MergeInput(targets=[Ref(owner="o", repo="r", number=4)])))
        assert out["results"][0]["success"] is False
        from af1.db import get_pr

        assert (await get_pr(db, "o", "r", 4))["state"] == "OPEN"


class TestToolRegistration:
    async def test_all_tools_registered(self):
        names = {t.name for t in await M.mcp.list_tools()}
        assert names == {
            "af1_list_prs",
            "af1_get_pr",
            "af1_list_issues",
            "af1_get_issue",
            "af1_list_repos",
            "af1_sync",
            "af1_merge_prs",
            "af1_approve_prs",
            "af1_close_prs",
        }

    async def test_tool_annotations(self):
        tools = {t.name: t for t in await M.mcp.list_tools()}
        assert tools["af1_list_prs"].annotations.read_only_hint is True
        assert tools["af1_merge_prs"].annotations.destructive_hint is True

    async def test_call_tool_validates_and_dispatches(self, mcp_ctx):
        db, _, _ = mcp_ctx
        await _seed_prs(db)
        result = await M.mcp.call_tool("af1_list_prs", {"params": {"authors": ["alice"]}})
        assert result.is_error is False
        out = _json(result.content[0].text)
        assert out["total"] == 1
        assert out["items"][0]["author"] == "alice"

    async def test_call_tool_rejects_invalid_input(self, mcp_ctx):
        with pytest.raises(ToolError, match="params.limit"):
            await M.mcp.call_tool("af1_list_prs", {"params": {"limit": 0}})


class TestHTTPTransport:
    @pytest.mark.parametrize("host", ["localhost:8510", "127.0.0.1:8510"])
    async def test_mounted_tool_call(self, mcp_ctx, host):
        from af1.server import create_routes

        db, _, _ = mcp_ctx
        await _seed_prs(db)
        app = Starlette(routes=create_routes())
        async with M.mcp.session_manager.run(), AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{host}") as client:
            response = await client.post(
                "/mcp/",
                headers={"Accept": "application/json, text/event-stream", "Origin": f"http://{host}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "af1_list_prs", "arguments": {"params": {}}}},
            )
        assert response.status_code == 200
        assert "mcp-session-id" not in response.headers
        message = json.loads(next(line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")))
        assert message["result"]["isError"] is False
        assert _json(message["result"]["content"][0]["text"])["total"] == 3

    async def test_rejects_untrusted_host(self, mcp_ctx):
        from af1.server import create_routes

        app = Starlette(routes=create_routes())
        async with M.mcp.session_manager.run(), AsyncClient(transport=ASGITransport(app=app), base_url="http://untrusted.example") as client:
            response = await client.post(
                "/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        assert response.status_code == 421
