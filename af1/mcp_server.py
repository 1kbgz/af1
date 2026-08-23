"""af1 MCP server — exposes the local GitHub cache and actions to agents.

Reads are served from the same SQLite cache the af1 web server maintains, so they
are instant and work offline. Writes (merge/approve/close) and sync go straight to
GitHub via the shared GitHubClient, then re-sync the affected rows.

Two transports share the same tool definitions:
  - stdio:  ``af1-mcp`` / ``python -m af1.mcp_server`` (default). Builds its own
            cache connection + client lazily on first use.
  - HTTP:   mounted on the af1 Starlette app at ``/mcp`` (see server.py), reusing the
            server's live db connection, client, and background sync.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field

from .config import Config
from .db import (
    get_db,
    get_issue,
    get_open_issues,
    get_open_prs,
    get_pr,
    get_pr_checks,
    get_pr_commits,
    get_pr_files,
    get_repos,
    update_pr_state,
)
from .github_client import GitHubClient
from .sync import run_full_sync, sync_single_pr

logger = logging.getLogger(__name__)

INSTRUCTIONS = """af1 is a local GitHub command center. These tools read from a local
cache of pull requests, issues, and maintained repos, and can act on PRs (merge, approve,
close) across all your organizations.

Typical flow: call af1_sync first if you need fresh data, then af1_list_prs / af1_list_issues
with filters. Use scope='maintained' to limit to repos you maintain (configured via
AF1_WATCHED_USERS / AF1_WATCHED_ORGS / AF1_WATCHED_REPOS). PR list items expose the signals
needed to decide if a PR is actionable: draft, ci_status, mergeable, and review_decision."""

# af1 binds to localhost only; keep DNS-rebinding protection on but allow the local host.
_LOCAL_HOSTS = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]
_TRANSPORT_SECURITY = TransportSecuritySettings(
    allowed_hosts=_LOCAL_HOSTS,
    allowed_origins=[f"http://{h}" for h in _LOCAL_HOSTS],
)

mcp = FastMCP(
    "af1_mcp",
    instructions=INSTRUCTIONS,
    stateless_http=True,
    streamable_http_path="/",
    transport_security=_TRANSPORT_SECURITY,
)


_ctx: dict[str, Any] = {}
_ctx_lock = asyncio.Lock()


def set_context(*, db, client: GitHubClient, config: Config) -> None:
    """Inject already-initialized resources (used when mounted on the af1 server)."""
    _ctx["db"] = db
    _ctx["client"] = client
    _ctx["config"] = config


async def _require_ctx():
    """Return (db, client, config), lazily building them for the stdio transport."""
    async with _ctx_lock:
        if "db" not in _ctx:
            config = Config.load()
            _ctx["config"] = config
            _ctx["client"] = GitHubClient(config.github_token, config.github_host)
            _ctx["db"] = await get_db(config.db_path)
        return _ctx["db"], _ctx["client"], _ctx["config"]


class ResponseFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def _full_name(owner: str, name: str) -> str:
    return f"{owner}/{name}"


def _pr_summary(pr: dict) -> dict:
    """Compact PR view with the signals an agent needs to triage / act."""
    return {
        "repo": _full_name(pr["repo_owner"], pr["repo_name"]),
        "number": pr["number"],
        "title": pr["title"],
        "author": pr["author"],
        "draft": bool(pr.get("draft")),
        "ci_status": pr.get("ci_status"),
        "mergeable": pr.get("mergeable"),
        "review_decision": pr.get("review_decision"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changed_files"),
        "labels": [lbl.get("name") for lbl in pr.get("labels", []) if isinstance(lbl, dict)],
        "updated_at": pr.get("updated_at"),
        "url": pr.get("url"),
    }


def _issue_summary(issue: dict) -> dict:
    return {
        "repo": _full_name(issue["repo_owner"], issue["repo_name"]),
        "number": issue["number"],
        "title": issue["title"],
        "author": issue["author"],
        "assignees": issue.get("assignees", []),
        "comment_count": issue.get("comment_count"),
        "labels": [lbl.get("name") for lbl in issue.get("labels", []) if isinstance(lbl, dict)],
        "updated_at": issue.get("updated_at"),
        "url": issue.get("url"),
    }


def _matches(value, allowed: list[str] | None) -> bool:
    """Case-insensitive membership test; True when no filter is given."""
    if not allowed:
        return True
    if value is None:
        return False
    return str(value).upper() in {a.upper() for a in allowed}


def _paginate(items: list, limit: int, offset: int) -> dict:
    window = items[offset : offset + limit]
    total = len(items)
    return {
        "total": total,
        "count": len(window),
        "offset": offset,
        "has_more": offset + len(window) < total,
        "next_offset": offset + len(window) if offset + len(window) < total else None,
        "items": window,
    }


def _render(payload: dict, fmt: ResponseFormat, *, kind: str) -> str:
    if fmt == ResponseFormat.JSON:
        return _dumps(payload)
    lines = [f"# {kind} — {payload['count']} of {payload['total']} (offset {payload['offset']})", ""]
    for it in payload["items"]:
        repo = it.get("repo", "")
        num = it.get("number", "")
        lines.append(f"## {repo}#{num} — {it.get('title', '')}")
        for key, val in it.items():
            if key in ("repo", "number", "title") or val in (None, [], ""):
                continue
            lines.append(f"- **{key}**: {val}")
        lines.append("")
    if payload["has_more"]:
        lines.append(f"_More available — call again with offset={payload['next_offset']}._")
    return "\n".join(lines)


class PRScope(str, Enum):
    ALL = "all"
    MINE = "mine"
    MAINTAINED = "maintained"


class ListPRsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    scope: PRScope = Field(
        default=PRScope.ALL,
        description="'mine' = authored by watched authors; 'maintained' = on repos you maintain; 'all' = everything cached",
    )
    authors: list[str] | None = Field(default=None, description="Filter to these PR author logins")
    repos: list[str] | None = Field(default=None, description="Filter to these repos in 'owner/name' form")
    ci_status: list[str] | None = Field(default=None, description="Filter by CI rollup: SUCCESS, FAILURE, PENDING, ERROR")
    review_decision: list[str] | None = Field(default=None, description="Filter by review decision: APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED")
    mergeable: list[str] | None = Field(default=None, description="Filter by mergeable: MERGEABLE, CONFLICTING, UNKNOWN")
    draft: bool | None = Field(default=None, description="Filter by draft flag; omit for both")
    text: str | None = Field(default=None, description="Case-insensitive substring match on PR title")
    limit: int = Field(default=30, ge=1, le=100, description="Max results to return")
    offset: int = Field(default=0, ge=0, description="Results to skip for pagination")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="'json' or 'markdown'")


class ListIssuesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    authors: list[str] | None = Field(default=None, description="Filter to these issue author logins")
    repos: list[str] | None = Field(default=None, description="Filter to these repos in 'owner/name' form")
    assignee: str | None = Field(default=None, description="Filter to issues assigned to this login")
    text: str | None = Field(default=None, description="Case-insensitive substring match on issue title")
    limit: int = Field(default=30, ge=1, le=100, description="Max results to return")
    offset: int = Field(default=0, ge=0, description="Results to skip for pagination")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="'json' or 'markdown'")


class Ref(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    owner: str = Field(..., description="Repository owner", min_length=1)
    repo: str = Field(..., description="Repository name", min_length=1)
    number: int = Field(..., description="PR or issue number", ge=1)


class TargetsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[Ref] = Field(..., description="PRs to act on", min_length=1, max_length=50)


class MergeInput(TargetsInput):
    merge_method: str = Field(default="merge", description="Merge strategy: merge, squash, or rebase", pattern="^(merge|squash|rebase)$")


class SyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pr: Ref | None = Field(default=None, description="Sync only this single PR (full detail). Omit for a full sync of everything.")


@mcp.tool(
    name="af1_list_prs",
    annotations={"title": "List Pull Requests", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def af1_list_prs(params: ListPRsInput) -> str:
    """List open pull requests from the local cache, with filters for triage.

    Reads cached PRs (no GitHub call). Combine ``scope`` with the other filters to answer
    questions like "open PRs on repos I maintain that are mergeable with passing CI".
    Call af1_sync first if you need fresh data.

    Returns (json): {"total", "count", "offset", "has_more", "next_offset", "items": [
      {"repo": "owner/name", "number", "title", "author", "draft", "ci_status",
       "mergeable", "review_decision", "additions", "deletions", "changed_files",
       "labels": [str], "updated_at", "url"}]}
    """
    db, _, config = await _require_ctx()
    prs = await get_open_prs(db)

    repo_filter = {r.upper() for r in params.repos} if params.repos else None
    if params.scope == PRScope.MAINTAINED:
        maintained = {r["name_with_owner"].upper() for r in await get_repos(db)}
        repo_filter = maintained if repo_filter is None else (repo_filter & maintained)
    author_filter = params.authors or (config.watched_authors if params.scope == PRScope.MINE else None)

    out = []
    for pr in prs:
        full = _full_name(pr["repo_owner"], pr["repo_name"])
        if repo_filter is not None and full.upper() not in repo_filter:
            continue
        if not _matches(pr["author"], author_filter):
            continue
        if not _matches(pr.get("ci_status"), params.ci_status):
            continue
        if not _matches(pr.get("review_decision"), params.review_decision):
            continue
        if not _matches(pr.get("mergeable"), params.mergeable):
            continue
        if params.draft is not None and bool(pr.get("draft")) != params.draft:
            continue
        if params.text and params.text.lower() not in (pr.get("title") or "").lower():
            continue
        out.append(_pr_summary(pr))

    payload = _paginate(out, params.limit, params.offset)
    return _render(payload, params.response_format, kind="Pull Requests")


@mcp.tool(
    name="af1_get_pr",
    annotations={"title": "Get Pull Request Detail", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def af1_get_pr(params: Ref) -> str:
    """Get full cached detail for one PR: metadata, commits, file diffs, and CI checks.

    Reads from cache. If the PR isn't cached, returns an error suggesting af1_sync with a
    pr target. Returns (json): {"pr": {...full row...}, "commits": [...], "files": [...],
    "checks": [...]}.
    """
    db, _, _ = await _require_ctx()
    pr = await get_pr(db, params.owner, params.repo, params.number)
    if not pr:
        return _dumps(
            {"error": f"PR {params.owner}/{params.repo}#{params.number} not in cache. Call af1_sync with pr={{owner,repo,number}} to fetch it."}
        )
    pr_id = pr["id"]
    return _dumps(
        {
            "pr": pr,
            "commits": await get_pr_commits(db, pr_id),
            "files": await get_pr_files(db, pr_id),
            "checks": await get_pr_checks(db, pr_id),
        }
    )


@mcp.tool(
    name="af1_list_issues",
    annotations={"title": "List Issues", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def af1_list_issues(params: ListIssuesInput) -> str:
    """List open issues from the local cache, with author/repo/assignee/text filters.

    Reads cached issues (no GitHub call). Returns (json): {"total", "count", "offset",
    "has_more", "next_offset", "items": [{"repo", "number", "title", "author",
    "assignees": [str], "comment_count", "labels": [str], "updated_at", "url"}]}.
    """
    db, _, _ = await _require_ctx()
    issues = await get_open_issues(db, params.authors)

    repo_filter = {r.upper() for r in params.repos} if params.repos else None
    out = []
    for issue in issues:
        full = _full_name(issue["repo_owner"], issue["repo_name"])
        if repo_filter is not None and full.upper() not in repo_filter:
            continue
        if params.assignee and params.assignee not in (issue.get("assignees") or []):
            continue
        if params.text and params.text.lower() not in (issue.get("title") or "").lower():
            continue
        out.append(_issue_summary(issue))

    payload = _paginate(out, params.limit, params.offset)
    return _render(payload, params.response_format, kind="Issues")


@mcp.tool(
    name="af1_get_issue",
    annotations={"title": "Get Issue Detail", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def af1_get_issue(params: Ref) -> str:
    """Get full cached detail for one issue (body, labels, assignees, comment count).

    Returns (json): the issue row, or {"error": ...} if not cached.
    """
    db, _, _ = await _require_ctx()
    issue = await get_issue(db, params.owner, params.repo, params.number)
    if not issue:
        return _dumps({"error": f"Issue {params.owner}/{params.repo}#{params.number} not in cache."})
    return _dumps(issue)


@mcp.tool(
    name="af1_list_repos",
    annotations={"title": "List Maintained Repos", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def af1_list_repos() -> str:
    """List the repos af1 tracks as maintained (where your token has write/maintain/admin).

    Populated from AF1_WATCHED_USERS / AF1_WATCHED_ORGS / AF1_WATCHED_REPOS by af1_sync.
    Returns (json): {"count", "repos": [{"name_with_owner", "owner", "name", "description",
    "is_private", "is_archived", "default_branch", "viewer_permission", "pushed_at", "url"}]}.
    """
    db, _, _ = await _require_ctx()
    repos = await get_repos(db)
    return _dumps({"count": len(repos), "repos": repos})


@mcp.tool(
    name="af1_sync",
    annotations={"title": "Sync from GitHub", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def af1_sync(params: SyncInput) -> str:
    """Refresh the local cache from GitHub before querying.

    With no arguments, runs a full sync: maintained repos + their open PRs, PRs authored by /
    review-requested for watched authors, and open issues. Pass ``pr`` to refresh just one PR
    (including its commits, files, and checks) — much faster. Requires a configured token.

    Returns (json): {"status": "ok", "scope": "full"|"single_pr"} or {"error": ...}.
    """
    db, client, config = await _require_ctx()
    if not config.github_token:
        return _dumps({"error": "No GitHub token configured. Set AF1_GITHUB_TOKEN or GITHUB_TOKEN."})
    try:
        if params.pr:
            await sync_single_pr(db, client, params.pr.owner, params.pr.repo, params.pr.number)
            return _dumps({"status": "ok", "scope": "single_pr", "pr": f"{params.pr.owner}/{params.pr.repo}#{params.pr.number}"})
        await run_full_sync(db, client, config)
        return _dumps({"status": "ok", "scope": "full"})
    except Exception as e:
        logger.exception("af1_sync failed")
        return _dumps({"error": f"Sync failed: {e}"})


async def _act_on_prs(targets: list[Ref], action, *, post_state: str | None) -> str:
    """Run a write action over a list of PRs, updating cached state on success."""
    db, client, config = await _require_ctx()
    if not config.github_token:
        return _dumps({"error": "No GitHub token configured. Set AF1_GITHUB_TOKEN or GITHUB_TOKEN."})
    results = []
    for t in targets:
        try:
            result = await action(client, t)
        except Exception as e:
            logger.exception("PR action failed for %s/%s#%d", t.owner, t.repo, t.number)
            result = {"success": False, "error": str(e)}
        if result.get("success") and post_state:
            await update_pr_state(db, t.owner, t.repo, t.number, post_state)
        results.append({"repo": _full_name(t.owner, t.repo), "number": t.number, **result})
    return _dumps({"results": results})


@mcp.tool(
    name="af1_merge_prs",
    annotations={"title": "Merge Pull Requests", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
)
async def af1_merge_prs(params: MergeInput) -> str:
    """Merge one or more PRs on GitHub, then mark them MERGED in the cache.

    GitHub enforces branch protection / mergeability; a PR that can't merge returns
    success=false with the GitHub message. Inspect ci_status and mergeable via af1_list_prs
    first. Returns (json): {"results": [{"repo", "number", "success", "error"?}]}.
    """
    return await _act_on_prs(
        params.targets,
        lambda client, t: client.merge_pull_request(t.owner, t.repo, t.number, params.merge_method),
        post_state="MERGED",
    )


@mcp.tool(
    name="af1_approve_prs",
    annotations={"title": "Approve Pull Requests", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def af1_approve_prs(params: TargetsInput) -> str:
    """Submit an APPROVE review on one or more PRs.

    Returns (json): {"results": [{"repo", "number", "success", "error"?}]}.
    """
    return await _act_on_prs(
        params.targets,
        lambda client, t: client.approve_pull_request(t.owner, t.repo, t.number),
        post_state=None,
    )


@mcp.tool(
    name="af1_close_prs",
    annotations={"title": "Close Pull Requests", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
)
async def af1_close_prs(params: TargetsInput) -> str:
    """Close one or more PRs without merging, then mark them CLOSED in the cache.

    Returns (json): {"results": [{"repo", "number", "success", "error"?}]}.
    """
    return await _act_on_prs(
        params.targets,
        lambda client, t: client.close_pull_request(t.owner, t.repo, t.number),
        post_state="CLOSED",
    )


def main() -> None:
    """Entry point for the stdio transport (``af1-mcp``)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
