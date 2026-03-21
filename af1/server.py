"""af1 ASGI server: serves frontend assets and exposes API endpoints."""

from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .config import Config
from .db import get_db, get_issue, get_open_issues, get_open_prs, get_pr, get_pr_checks, get_pr_commits, get_pr_files, update_pr_state
from .github_client import GitHubClient
from .sync import sync_all_issues, sync_all_prs, sync_loop, sync_repo_prs, sync_single_pr

logger = logging.getLogger(__name__)

EXTENSION_DIR = Path(__file__).parent / "extension"


# --- API handlers ---


async def api_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


async def api_me(request: Request) -> JSONResponse:
    client: GitHubClient = request.app.state.github_client
    try:
        user = await client.get_authenticated_user()
        return JSONResponse({"login": user["login"], "name": user.get("name"), "avatar_url": user.get("avatar_url")})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_config(request: Request) -> JSONResponse:
    config: Config = request.app.state.config
    return JSONResponse(
        {
            "watched_authors": config.watched_authors,
            "sync_interval_seconds": config.sync_interval_seconds,
        }
    )


async def api_pull_requests(request: Request) -> JSONResponse:
    db = request.app.state.db
    authors_param = request.query_params.get("authors")
    authors = [a.strip() for a in authors_param.split(",") if a.strip()] if authors_param else None
    prs = await get_open_prs(db, authors)
    return JSONResponse(prs)


async def api_pr_detail(request: Request) -> JSONResponse:
    db = request.app.state.db
    owner = request.path_params["owner"]
    repo = request.path_params["repo"]
    number = int(request.path_params["number"])
    pr = await get_pr(db, owner, repo, number)
    if not pr:
        return JSONResponse({"error": "PR not found"}, status_code=404)
    commits = await get_pr_commits(db, pr["id"])
    files = await get_pr_files(db, pr["id"])
    checks = await get_pr_checks(db, pr["id"])
    return JSONResponse({**pr, "commits": commits, "files": files, "checks": checks})


async def api_sync(request: Request) -> JSONResponse:
    """Trigger an immediate sync."""
    db = request.app.state.db
    client: GitHubClient = request.app.state.github_client
    config: Config = request.app.state.config
    try:
        await sync_all_prs(db, client, config)
        await sync_all_issues(db, client, config)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.exception("Manual sync failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_sync_pr(request: Request) -> JSONResponse:
    """Sync a single PR by owner/repo/number."""
    db = request.app.state.db
    client: GitHubClient = request.app.state.github_client
    owner = request.path_params["owner"]
    repo = request.path_params["repo"]
    number = int(request.path_params["number"])
    try:
        await sync_single_pr(db, client, owner, repo, number)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.exception("Single PR sync failed for %s/%s#%d", owner, repo, number)
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_sync_repo(request: Request) -> JSONResponse:
    """Sync all PRs for a specific repo."""
    db = request.app.state.db
    client: GitHubClient = request.app.state.github_client
    config: Config = request.app.state.config
    owner = request.path_params["owner"]
    repo = request.path_params["repo"]
    try:
        await sync_repo_prs(db, client, owner, repo, config)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.exception("Repo sync failed for %s/%s", owner, repo)
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_batch_merge(request: Request) -> JSONResponse:
    """Batch merge PRs. Expects JSON body: {"targets": [{"owner", "repo", "number"}, ...]}."""
    client: GitHubClient = request.app.state.github_client
    db = request.app.state.db
    body = await request.json()
    targets = body.get("targets", [])
    results = []
    for t in targets:
        owner = t.get("owner", "")
        repo = t.get("repo", "")
        number = t.get("number", 0)
        if not owner or not repo or not number:
            results.append({"owner": owner, "repo": repo, "number": number, "success": False, "error": "Missing fields"})
            continue
        result = await client.merge_pull_request(owner, repo, int(number))
        if result.get("success"):
            await update_pr_state(db, owner, repo, int(number), "MERGED")
        results.append({"owner": owner, "repo": repo, "number": number, **result})
    return JSONResponse(results)


async def api_batch_close(request: Request) -> JSONResponse:
    """Batch close PRs. Expects JSON body: {"targets": [{"owner", "repo", "number"}, ...]}."""
    client: GitHubClient = request.app.state.github_client
    db = request.app.state.db
    body = await request.json()
    targets = body.get("targets", [])
    results = []
    for t in targets:
        owner = t.get("owner", "")
        repo = t.get("repo", "")
        number = t.get("number", 0)
        if not owner or not repo or not number:
            results.append({"owner": owner, "repo": repo, "number": number, "success": False, "error": "Missing fields"})
            continue
        result = await client.close_pull_request(owner, repo, int(number))
        if result.get("success"):
            await update_pr_state(db, owner, repo, int(number), "CLOSED")
        results.append({"owner": owner, "repo": repo, "number": number, **result})
    return JSONResponse(results)


async def api_batch_approve(request: Request) -> JSONResponse:
    """Batch approve PRs. Expects JSON body: {"targets": [{"owner", "repo", "number"}, ...]}."""
    client: GitHubClient = request.app.state.github_client
    body = await request.json()
    targets = body.get("targets", [])
    results = []
    for t in targets:
        owner = t.get("owner", "")
        repo = t.get("repo", "")
        number = t.get("number", 0)
        if not owner or not repo or not number:
            results.append({"owner": owner, "repo": repo, "number": number, "success": False, "error": "Missing fields"})
            continue
        result = await client.approve_pull_request(owner, repo, int(number))
        results.append({"owner": owner, "repo": repo, "number": number, **result})
    return JSONResponse(results)


async def api_issues(request: Request) -> JSONResponse:
    db = request.app.state.db
    authors_param = request.query_params.get("authors")
    authors = [a.strip() for a in authors_param.split(",") if a.strip()] if authors_param else None
    issues = await get_open_issues(db, authors)
    return JSONResponse(issues)


async def api_issue_detail(request: Request) -> JSONResponse:
    db = request.app.state.db
    owner = request.path_params["owner"]
    repo = request.path_params["repo"]
    number = int(request.path_params["number"])
    issue = await get_issue(db, owner, repo, number)
    if not issue:
        return JSONResponse({"error": "Issue not found"}, status_code=404)
    return JSONResponse(issue)


# --- App lifecycle ---


@asynccontextmanager
async def lifespan(app: Starlette):
    config = app.state.config
    if not config.github_token:
        logger.error(
            "No GitHub token configured. Set AF1_GITHUB_TOKEN or GITHUB_TOKEN environment variable, or pass --token. See SETUP.md for instructions."
        )
        raise SystemExit(1)

    app.state.db = await get_db(config.db_path)
    app.state.github_client = GitHubClient(config.github_token, config.github_host)
    app.state.stop_event = asyncio.Event()

    # Start background sync
    sync_task = asyncio.create_task(sync_loop(app.state.db, app.state.github_client, config, app.state.stop_event))
    logger.info("af1 server started on %s:%d", config.host, config.port)

    yield

    # Shutdown
    app.state.stop_event.set()
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    await app.state.github_client.close()
    await app.state.db.close()
    logger.info("af1 server shut down")


def create_routes() -> list:
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

    # Serve frontend static files if the extension directory exists
    if EXTENSION_DIR.exists():
        routes.append(Mount("/", app=StaticFiles(directory=str(EXTENSION_DIR), html=True)))

    return routes


class NoCacheStaticMiddleware:
    """Add no-cache headers to static file responses to prevent stale assets during development."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_with_no_cache(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_no_cache)


def create_app(config: Config | None = None) -> Starlette:
    app = Starlette(
        routes=create_routes(),
        lifespan=lifespan,
        middleware=[
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
            Middleware(NoCacheStaticMiddleware),
        ],
    )
    app.state.config = config or Config.load()
    return app


def main():
    parser = argparse.ArgumentParser(prog="af1", description="af1 — local GitHub command center")
    parser.add_argument("--token", default=None, help="GitHub personal access token (overrides AF1_GITHUB_TOKEN / GITHUB_TOKEN env vars)")
    parser.add_argument("--authors", default=None, help="Comma-separated list of GitHub usernames to watch (overrides AF1_WATCHED_AUTHORS)")
    parser.add_argument(
        "--github-host", default=None, help="GitHub hostname, e.g. github.mycompany.com (default: github.com, overrides AF1_GITHUB_HOST)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    config = Config.load(
        github_token=args.token,
        watched_authors=args.authors,
        github_host=args.github_host,
    )
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
