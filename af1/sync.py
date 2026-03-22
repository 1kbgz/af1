"""Background sync engine: fetches GitHub data and stores in SQLite."""

from __future__ import annotations

import asyncio
import logging

import aiosqlite

from .config import Config
from .db import (
    get_pr_updated_state,
    mark_stale_issues_closed,
    mark_stale_prs_closed,
    upsert_issue,
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
            # Check if PR is unchanged since last sync
            prior = await get_pr_updated_state(db, pr["repo_owner"], pr["repo_name"], pr["number"])
            changed = prior is None or prior[0] != pr["updated_at"] or prior[1] != pr.get("head_sha")

            pr_id = await upsert_pull_request(db, pr)
            await db.commit()
        except Exception:
            logger.exception("Failed to upsert PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])
            continue

        if not changed:
            logger.debug("Skipping details for unchanged PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])
            continue

        # Fetch details individually so one failure doesn't block the others

        # Use inline commits from bulk query when available and complete
        inline_commits = pr.get("commits")
        if inline_commits is not None and pr.get("commits_complete", False):
            try:
                await upsert_pr_commits(db, pr_id, inline_commits)
                await db.commit()
            except Exception:
                logger.exception("Failed to upsert inline commits for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])
        else:
            try:
                commits = await client.fetch_pr_commits(pr["repo_owner"], pr["repo_name"], pr["number"])
                await upsert_pr_commits(db, pr_id, commits)
                await db.commit()
            except Exception:
                logger.exception("Failed to sync commits for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

        try:
            files = await client.fetch_pr_files(pr["repo_owner"], pr["repo_name"], pr["number"])
            await upsert_pr_files(db, pr_id, files)
            await db.commit()
        except Exception:
            logger.exception("Failed to sync files for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

        try:
            if pr.get("head_sha"):
                checks = await client.fetch_pr_check_runs(pr["repo_owner"], pr["repo_name"], pr["head_sha"])
                await upsert_pr_check_runs(db, pr_id, checks)
                await db.commit()
        except Exception:
            logger.exception("Failed to sync checks for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

        logger.debug("Synced PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

    # Mark PRs that are OPEN in the DB but no longer returned by GitHub
    still_open = {(p["repo_owner"], p["repo_name"], p["number"]) for p in prs}
    await mark_stale_prs_closed(db, still_open)

    logger.info("PR sync complete: %d PRs processed", len(prs))


async def sync_single_pr(db: aiosqlite.Connection, client: GitHubClient, owner: str, repo: str, number: int):
    """Sync a single PR: fetch latest data from GitHub and update the local DB."""
    logger.info("Syncing single PR %s/%s#%d", owner, repo, number)
    pr = await client.fetch_single_pr(owner, repo, number)
    pr_id = await upsert_pull_request(db, pr)
    await db.commit()

    # Use inline commits when available and complete
    inline_commits = pr.get("commits")
    if inline_commits is not None and pr.get("commits_complete", False):
        await upsert_pr_commits(db, pr_id, inline_commits)
        await db.commit()
    else:
        commits = await client.fetch_pr_commits(owner, repo, number)
        await upsert_pr_commits(db, pr_id, commits)
        await db.commit()

    files = await client.fetch_pr_files(owner, repo, number)
    await upsert_pr_files(db, pr_id, files)
    await db.commit()

    if pr.get("head_sha"):
        checks = await client.fetch_pr_check_runs(owner, repo, pr["head_sha"])
        await upsert_pr_check_runs(db, pr_id, checks)
        await db.commit()

    logger.info("Single PR sync complete: %s/%s#%d", owner, repo, number)


async def sync_repo_prs(db: aiosqlite.Connection, client: GitHubClient, owner: str, repo: str, config: Config):
    """Sync all open PRs for a specific repo that belong to watched authors."""
    logger.info("Syncing PRs for repo %s/%s", owner, repo)

    # Fetch open PRs from watched authors, filter to this repo
    all_prs = await client.fetch_open_prs_for_authors(config.watched_authors)
    repo_prs = [p for p in all_prs if p["repo_owner"] == owner and p["repo_name"] == repo]

    # Also include review-requested PRs for this repo
    if config.watched_authors:
        review_prs = await client.fetch_review_requested_prs(config.watched_authors[0])
        seen = {(p["repo_owner"], p["repo_name"], p["number"]) for p in repo_prs}
        for pr in review_prs:
            if pr["repo_owner"] == owner and pr["repo_name"] == repo:
                key = (pr["repo_owner"], pr["repo_name"], pr["number"])
                if key not in seen:
                    repo_prs.append(pr)
                    seen.add(key)

    for pr in repo_prs:
        try:
            pr_id = await upsert_pull_request(db, pr)
            await db.commit()
        except Exception:
            logger.exception("Failed to upsert PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])
            continue

        # Use inline commits when available and complete
        inline_commits = pr.get("commits")
        if inline_commits is not None and pr.get("commits_complete", False):
            try:
                await upsert_pr_commits(db, pr_id, inline_commits)
                await db.commit()
            except Exception:
                logger.exception("Failed to upsert inline commits for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])
        else:
            try:
                commits = await client.fetch_pr_commits(pr["repo_owner"], pr["repo_name"], pr["number"])
                await upsert_pr_commits(db, pr_id, commits)
                await db.commit()
            except Exception:
                logger.exception("Failed to sync commits for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

        try:
            files = await client.fetch_pr_files(pr["repo_owner"], pr["repo_name"], pr["number"])
            await upsert_pr_files(db, pr_id, files)
            await db.commit()
        except Exception:
            logger.exception("Failed to sync files for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

        try:
            if pr.get("head_sha"):
                checks = await client.fetch_pr_check_runs(pr["repo_owner"], pr["repo_name"], pr["head_sha"])
                await upsert_pr_check_runs(db, pr_id, checks)
                await db.commit()
        except Exception:
            logger.exception("Failed to sync checks for PR %s/%s#%d", pr["repo_owner"], pr["repo_name"], pr["number"])

    logger.info("Repo PR sync complete: %s/%s — %d PRs processed", owner, repo, len(repo_prs))


async def sync_all_issues(db: aiosqlite.Connection, client: GitHubClient, config: Config):
    """Full sync: fetch open issues for all watched authors, plus assigned issues."""
    logger.info("Starting issue sync for authors: %s", config.watched_authors)

    issues = await client.fetch_open_issues_for_authors(config.watched_authors)
    logger.info("Fetched %d open issues from watched authors", len(issues))

    # Also fetch issues assigned to the primary user
    if config.watched_authors:
        assigned = await client.fetch_assigned_issues(config.watched_authors[0])
        logger.info("Fetched %d assigned issues", len(assigned))
        seen = {(i["repo_owner"], i["repo_name"], i["number"]) for i in issues}
        for issue in assigned:
            key = (issue["repo_owner"], issue["repo_name"], issue["number"])
            if key not in seen:
                issues.append(issue)
                seen.add(key)

    for issue in issues:
        try:
            await upsert_issue(db, issue)
            await db.commit()
            logger.debug("Synced issue %s/%s#%d", issue["repo_owner"], issue["repo_name"], issue["number"])
        except Exception:
            logger.exception("Failed to sync issue %s/%s#%d", issue["repo_owner"], issue["repo_name"], issue["number"])

    # Mark issues that are OPEN in the DB but no longer returned by GitHub
    still_open_issues = {(i["repo_owner"], i["repo_name"], i["number"]) for i in issues}
    await mark_stale_issues_closed(db, still_open_issues)

    logger.info("Issue sync complete: %d issues processed", len(issues))


async def sync_loop(db: aiosqlite.Connection, client: GitHubClient, config: Config, stop_event: asyncio.Event):
    """Run sync_all_prs on a recurring schedule."""
    while not stop_event.is_set():
        try:
            await sync_all_prs(db, client, config)
            await sync_all_issues(db, client, config)
        except Exception:
            logger.exception("Sync loop error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.sync_interval_seconds)
        except asyncio.TimeoutError:
            pass
