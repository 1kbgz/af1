"""Background sync engine: fetches GitHub data and stores in SQLite."""

from __future__ import annotations

import asyncio
import logging

import aiosqlite

from .config import Config
from .db import (
    upsert_pr_check_runs,
    upsert_pr_commits,
    upsert_pr_files,
    upsert_pull_request,
)
from .github_client import GitHubClient

logger = logging.getLogger(__name__)


async def sync_all_prs(db: aiosqlite.Connection, client: GitHubClient, config: Config):
    """Full sync: fetch open PRs for all watched authors, plus review-requested PRs."""
    logger.info("Starting PR sync for authors: %s", config.watched_authors)

    # Fetch PRs authored by watched users
    prs = await client.fetch_open_prs_for_authors(config.watched_authors)
    logger.info("Fetched %d open PRs from watched authors", len(prs))

    # Also fetch PRs where the primary user has review requested
    if config.watched_authors:
        review_prs = await client.fetch_review_requested_prs(config.watched_authors[0])
        logger.info("Fetched %d review-requested PRs", len(review_prs))
        # Merge, dedup
        seen = {(p["repo_owner"], p["repo_name"], p["number"]) for p in prs}
        for pr in review_prs:
            key = (pr["repo_owner"], pr["repo_name"], pr["number"])
            if key not in seen:
                prs.append(pr)
                seen.add(key)

    # Upsert each PR and fetch details
    for pr in prs:
        try:
            pr_id = await upsert_pull_request(db, pr)

            # Fetch commits
            commits = await client.fetch_pr_commits(pr["repo_owner"], pr["repo_name"], pr["number"])
            await upsert_pr_commits(db, pr_id, commits)

            # Fetch files/diffs
            files = await client.fetch_pr_files(pr["repo_owner"], pr["repo_name"], pr["number"])
            await upsert_pr_files(db, pr_id, files)

            # Fetch check runs
            if pr.get("head_sha"):
                checks = await client.fetch_pr_check_runs(pr["repo_owner"], pr["repo_name"], pr["head_sha"])
                await upsert_pr_check_runs(db, pr_id, checks)

            await db.commit()
            logger.debug("Synced PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])
        except Exception:
            logger.exception("Failed to sync PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

    logger.info("PR sync complete: %d PRs processed", len(prs))


async def sync_loop(db: aiosqlite.Connection, client: GitHubClient, config: Config, stop_event: asyncio.Event):
    """Run sync_all_prs on a recurring schedule."""
    while not stop_event.is_set():
        try:
            await sync_all_prs(db, client, config)
        except Exception:
            logger.exception("Sync loop error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.sync_interval_seconds)
        except asyncio.TimeoutError:
            pass
