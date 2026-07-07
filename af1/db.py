"""SQLite database for caching GitHub data."""

from __future__ import annotations

import json
import os
from pathlib import Path

import aiosqlite

DEFAULT_DB_PATH = Path(os.environ.get("AF1_DB_PATH", Path.home() / ".af1" / "af1.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS pull_requests (
    id INTEGER PRIMARY KEY,
    node_id TEXT UNIQUE NOT NULL,
    repo_owner TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    state TEXT NOT NULL,
    author TEXT NOT NULL,
    author_avatar TEXT,
    draft INTEGER NOT NULL DEFAULT 0,
    mergeable TEXT,
    head_ref TEXT,
    head_sha TEXT,
    base_ref TEXT,
    base_sha TEXT,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    changed_files INTEGER DEFAULT 0,
    review_decision TEXT,
    ci_status TEXT,
    labels TEXT,  -- JSON array
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    merged_at TEXT,
    closed_at TEXT,
    url TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo_owner, repo_name, number)
);

CREATE TABLE IF NOT EXISTS pr_commits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id INTEGER NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    message TEXT NOT NULL,
    author TEXT,
    authored_date TEXT,
    url TEXT,
    UNIQUE(pr_id, sha)
);

CREATE TABLE IF NOT EXISTS pr_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id INTEGER NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    status TEXT,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    patch TEXT,
    UNIQUE(pr_id, filename)
);

CREATE TABLE IF NOT EXISTS pr_check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id INTEGER NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT,
    conclusion TEXT,
    url TEXT,
    UNIQUE(pr_id, name)
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    node_id TEXT UNIQUE NOT NULL,
    repo_owner TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    state TEXT NOT NULL,
    author TEXT NOT NULL,
    author_avatar TEXT,
    labels TEXT,  -- JSON array
    assignees TEXT,  -- JSON array of logins
    comment_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    url TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo_owner, repo_name, number)
);

CREATE TABLE IF NOT EXISTS repos (
    name_with_owner TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    is_private INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    default_branch TEXT,
    viewer_permission TEXT,
    open_pr_count INTEGER NOT NULL DEFAULT 0,
    open_issue_count INTEGER NOT NULL DEFAULT 0,
    pushed_at TEXT,
    url TEXT,
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pr_repo ON pull_requests(repo_owner, repo_name);
CREATE INDEX IF NOT EXISTS idx_pr_author ON pull_requests(author);
CREATE INDEX IF NOT EXISTS idx_pr_state ON pull_requests(state);
CREATE INDEX IF NOT EXISTS idx_pr_updated ON pull_requests(updated_at);
CREATE INDEX IF NOT EXISTS idx_pr_commits_pr ON pr_commits(pr_id);
CREATE INDEX IF NOT EXISTS idx_pr_files_pr ON pr_files(pr_id);
CREATE INDEX IF NOT EXISTS idx_pr_checks_pr ON pr_check_runs(pr_id);
CREATE INDEX IF NOT EXISTS idx_issue_repo ON issues(repo_owner, repo_name);
CREATE INDEX IF NOT EXISTS idx_issue_author ON issues(author);
CREATE INDEX IF NOT EXISTS idx_issue_state ON issues(state);
CREATE INDEX IF NOT EXISTS idx_issue_updated ON issues(updated_at);
CREATE INDEX IF NOT EXISTS idx_repos_owner ON repos(owner);
"""


async def get_db(db_path: Path | None = None) -> aiosqlite.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.executescript(SCHEMA)
    await db.commit()
    return db


async def upsert_pull_request(db: aiosqlite.Connection, pr: dict) -> int:
    labels = json.dumps(pr.get("labels", []))
    await db.execute(
        """INSERT INTO pull_requests
           (id, node_id, repo_owner, repo_name, number, title, body, state, author, author_avatar,
            draft, mergeable, head_ref, head_sha, base_ref, base_sha,
            additions, deletions, changed_files, review_decision, ci_status,
            labels, created_at, updated_at, merged_at, closed_at, url, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(repo_owner, repo_name, number) DO UPDATE SET
             title=excluded.title, body=excluded.body, state=excluded.state,
             draft=excluded.draft, mergeable=excluded.mergeable,
             head_ref=excluded.head_ref, head_sha=excluded.head_sha,
             base_ref=excluded.base_ref, base_sha=excluded.base_sha,
             additions=excluded.additions, deletions=excluded.deletions,
             changed_files=excluded.changed_files, review_decision=excluded.review_decision,
             ci_status=excluded.ci_status, labels=excluded.labels,
             updated_at=excluded.updated_at, merged_at=excluded.merged_at,
             closed_at=excluded.closed_at, url=excluded.url, synced_at=datetime('now')""",
        (
            pr["id"],
            pr["node_id"],
            pr["repo_owner"],
            pr["repo_name"],
            pr["number"],
            pr["title"],
            pr.get("body"),
            pr["state"],
            pr["author"],
            pr.get("author_avatar"),
            int(pr.get("draft", False)),
            pr.get("mergeable"),
            pr.get("head_ref"),
            pr.get("head_sha"),
            pr.get("base_ref"),
            pr.get("base_sha"),
            pr.get("additions", 0),
            pr.get("deletions", 0),
            pr.get("changed_files", 0),
            pr.get("review_decision"),
            pr.get("ci_status"),
            labels,
            pr["created_at"],
            pr["updated_at"],
            pr.get("merged_at"),
            pr.get("closed_at"),
            pr["url"],
        ),
    )
    # Get the row id
    cursor = await db.execute(
        "SELECT id FROM pull_requests WHERE repo_owner=? AND repo_name=? AND number=?",
        (pr["repo_owner"], pr["repo_name"], pr["number"]),
    )
    row = await cursor.fetchone()
    return row["id"]


async def upsert_pr_commits(db: aiosqlite.Connection, pr_id: int, commits: list[dict]):
    for c in commits:
        await db.execute(
            """INSERT INTO pr_commits (pr_id, sha, message, author, authored_date, url)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(pr_id, sha) DO UPDATE SET
                 message=excluded.message, author=excluded.author,
                 authored_date=excluded.authored_date, url=excluded.url""",
            (pr_id, c["sha"], c["message"], c.get("author"), c.get("authored_date"), c.get("url")),
        )


async def upsert_pr_files(db: aiosqlite.Connection, pr_id: int, files: list[dict]):
    # Clear old files and re-insert (diff can change entirely)
    await db.execute("DELETE FROM pr_files WHERE pr_id=?", (pr_id,))
    for f in files:
        await db.execute(
            """INSERT INTO pr_files (pr_id, filename, status, additions, deletions, patch)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pr_id, f["filename"], f.get("status"), f.get("additions", 0), f.get("deletions", 0), f.get("patch")),
        )


async def upsert_pr_check_runs(db: aiosqlite.Connection, pr_id: int, checks: list[dict]):
    await db.execute("DELETE FROM pr_check_runs WHERE pr_id=?", (pr_id,))
    for ch in checks:
        await db.execute(
            """INSERT OR REPLACE INTO pr_check_runs (pr_id, name, status, conclusion, url)
               VALUES (?, ?, ?, ?, ?)""",
            (pr_id, ch["name"], ch.get("status"), ch.get("conclusion"), ch.get("url")),
        )


async def get_open_prs(db: aiosqlite.Connection, authors: list[str] | None = None) -> list[dict]:
    if authors:
        placeholders = ",".join("?" for _ in authors)
        cursor = await db.execute(
            f"SELECT * FROM pull_requests WHERE state='OPEN' AND author IN ({placeholders}) ORDER BY updated_at DESC",
            authors,
        )
    else:
        cursor = await db.execute("SELECT * FROM pull_requests WHERE state='OPEN' ORDER BY updated_at DESC")
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_pr(db: aiosqlite.Connection, owner: str, repo: str, number: int) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM pull_requests WHERE repo_owner=? AND repo_name=? AND number=?",
        (owner, repo, number),
    )
    row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def get_pr_commits(db: aiosqlite.Connection, pr_id: int) -> list[dict]:
    cursor = await db.execute("SELECT * FROM pr_commits WHERE pr_id=? ORDER BY authored_date ASC", (pr_id,))
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def get_pr_files(db: aiosqlite.Connection, pr_id: int) -> list[dict]:
    cursor = await db.execute("SELECT * FROM pr_files WHERE pr_id=? ORDER BY filename ASC", (pr_id,))
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def get_pr_checks(db: aiosqlite.Connection, pr_id: int) -> list[dict]:
    cursor = await db.execute("SELECT * FROM pr_check_runs WHERE pr_id=? ORDER BY name ASC", (pr_id,))
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def upsert_issue(db: aiosqlite.Connection, issue: dict) -> int:
    labels = json.dumps(issue.get("labels", []))
    assignees = json.dumps(issue.get("assignees", []))
    await db.execute(
        """INSERT INTO issues
           (id, node_id, repo_owner, repo_name, number, title, body, state, author, author_avatar,
            labels, assignees, comment_count, created_at, updated_at, closed_at, url, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(repo_owner, repo_name, number) DO UPDATE SET
             title=excluded.title, body=excluded.body, state=excluded.state,
             labels=excluded.labels, assignees=excluded.assignees,
             comment_count=excluded.comment_count,
             updated_at=excluded.updated_at, closed_at=excluded.closed_at,
             url=excluded.url, synced_at=datetime('now')""",
        (
            issue["id"],
            issue["node_id"],
            issue["repo_owner"],
            issue["repo_name"],
            issue["number"],
            issue["title"],
            issue.get("body"),
            issue["state"],
            issue["author"],
            issue.get("author_avatar"),
            labels,
            assignees,
            issue.get("comment_count", 0),
            issue["created_at"],
            issue["updated_at"],
            issue.get("closed_at"),
            issue["url"],
        ),
    )
    cursor = await db.execute(
        "SELECT id FROM issues WHERE repo_owner=? AND repo_name=? AND number=?",
        (issue["repo_owner"], issue["repo_name"], issue["number"]),
    )
    row = await cursor.fetchone()
    return row["id"]


async def get_open_issues(db: aiosqlite.Connection, authors: list[str] | None = None) -> list[dict]:
    if authors:
        placeholders = ",".join("?" for _ in authors)
        cursor = await db.execute(
            f"SELECT * FROM issues WHERE state='OPEN' AND author IN ({placeholders}) ORDER BY updated_at DESC",
            authors,
        )
    else:
        cursor = await db.execute("SELECT * FROM issues WHERE state='OPEN' ORDER BY updated_at DESC")
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_issue(db: aiosqlite.Connection, owner: str, repo: str, number: int) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM issues WHERE repo_owner=? AND repo_name=? AND number=?",
        (owner, repo, number),
    )
    row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def upsert_repo(db: aiosqlite.Connection, repo: dict) -> None:
    await db.execute(
        """INSERT INTO repos
           (name_with_owner, owner, name, description, is_private, is_archived,
            default_branch, viewer_permission, open_pr_count, open_issue_count, pushed_at, url, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(name_with_owner) DO UPDATE SET
             owner=excluded.owner, name=excluded.name, description=excluded.description,
             is_private=excluded.is_private, is_archived=excluded.is_archived,
             default_branch=excluded.default_branch, viewer_permission=excluded.viewer_permission,
             open_pr_count=excluded.open_pr_count, open_issue_count=excluded.open_issue_count,
             pushed_at=excluded.pushed_at, url=excluded.url, synced_at=datetime('now')""",
        (
            repo["name_with_owner"],
            repo["owner"],
            repo["name"],
            repo.get("description"),
            int(repo.get("is_private", False)),
            int(repo.get("is_archived", False)),
            repo.get("default_branch"),
            repo.get("viewer_permission"),
            int(repo.get("open_pr_count", 0)),
            int(repo.get("open_issue_count", 0)),
            repo.get("pushed_at"),
            repo.get("url"),
        ),
    )


async def get_repos(db: aiosqlite.Connection) -> list[dict]:
    # failing_ci_count is derived from cached open PRs for the repo (maintained-repo
    # sync caches every open PR per repo, so this tracks the repo's failing-CI PRs).
    cursor = await db.execute(
        """SELECT r.*,
                  (SELECT COUNT(*) FROM pull_requests p
                   WHERE p.repo_owner = r.owner AND p.repo_name = r.name
                     AND p.state = 'OPEN' AND p.ci_status IN ('FAILURE', 'ERROR')) AS failing_ci_count
           FROM repos r ORDER BY r.pushed_at DESC"""
    )
    return [_row_to_dict(r) for r in await cursor.fetchall()]


async def get_pr_updated_state(db: aiosqlite.Connection, owner: str, repo: str, number: int) -> tuple[str, str | None] | None:
    """Return (updated_at, head_sha) for a PR, or None if not in DB."""
    cursor = await db.execute(
        "SELECT updated_at, head_sha FROM pull_requests WHERE repo_owner=? AND repo_name=? AND number=?",
        (owner, repo, number),
    )
    row = await cursor.fetchone()
    if row:
        return (row["updated_at"], row["head_sha"])
    return None


async def update_pr_state(
    db: aiosqlite.Connection, owner: str, repo: str, number: int, state: str, merged_at: str | None = None, closed_at: str | None = None
):
    """Update the state of a PR in the local DB (e.g. after merge/close)."""
    await db.execute(
        "UPDATE pull_requests SET state=?, merged_at=COALESCE(?, merged_at), closed_at=COALESCE(?, closed_at), synced_at=datetime('now') WHERE repo_owner=? AND repo_name=? AND number=?",
        (state, merged_at, closed_at, owner, repo, number),
    )
    await db.commit()


async def mark_stale_prs_closed(db: aiosqlite.Connection, still_open: set[tuple[str, str, int]]):
    """Mark DB-open PRs as CLOSED if they weren't returned in the latest GitHub fetch."""
    cursor = await db.execute("SELECT repo_owner, repo_name, number FROM pull_requests WHERE state='OPEN'")
    rows = await cursor.fetchall()
    for row in rows:
        key = (row["repo_owner"], row["repo_name"], row["number"])
        if key not in still_open:
            await db.execute(
                "UPDATE pull_requests SET state='CLOSED', synced_at=datetime('now') WHERE repo_owner=? AND repo_name=? AND number=?",
                key,
            )
    await db.commit()


async def mark_stale_issues_closed(db: aiosqlite.Connection, still_open: set[tuple[str, str, int]]):
    """Mark DB-open issues as CLOSED if they weren't returned in the latest GitHub fetch."""
    cursor = await db.execute("SELECT repo_owner, repo_name, number FROM issues WHERE state='OPEN'")
    rows = await cursor.fetchall()
    for row in rows:
        key = (row["repo_owner"], row["repo_name"], row["number"])
        if key not in still_open:
            await db.execute(
                "UPDATE issues SET state='CLOSED', synced_at=datetime('now') WHERE repo_owner=? AND repo_name=? AND number=?",
                key,
            )
    await db.commit()


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    # Parse JSON fields
    for field in ("labels", "assignees"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d
