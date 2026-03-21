"""Seed a test database and start the af1 server for Playwright tests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure the af1 package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from af1.config import Config
from af1.db import get_db, upsert_pr_check_runs, upsert_pr_commits, upsert_pr_files, upsert_pull_request


SAMPLE_PRS = [
    {
        "id": 1001,
        "node_id": "PR_node1",
        "repo_owner": "acme",
        "repo_name": "frontend",
        "number": 142,
        "title": "Add dark mode toggle to settings page",
        "body": "Implements a dark mode toggle.\n\nCloses #100",
        "state": "OPEN",
        "author": "alice",
        "author_avatar": None,
        "draft": False,
        "mergeable": "MERGEABLE",
        "head_ref": "feature/dark-mode",
        "head_sha": "abc123def456789012345678901234567890abcd",
        "base_ref": "main",
        "base_sha": "000111222333444555666777888999aaabbbcccdd",
        "additions": 85,
        "deletions": 12,
        "changed_files": 5,
        "review_decision": "APPROVED",
        "ci_status": "SUCCESS",
        "labels": [{"name": "enhancement", "color": "a2eeef"}, {"name": "frontend", "color": "7057ff"}],
        "created_at": "2025-03-10T09:00:00Z",
        "updated_at": "2025-03-18T14:30:00Z",
        "merged_at": None,
        "closed_at": None,
        "url": "https://github.com/acme/frontend/pull/142",
    },
    {
        "id": 1002,
        "node_id": "PR_node2",
        "repo_owner": "acme",
        "repo_name": "frontend",
        "number": 143,
        "title": "Fix responsive layout on mobile devices",
        "body": "Fixes a CSS issue with the responsive layout on small screens.",
        "state": "OPEN",
        "author": "bob",
        "author_avatar": None,
        "draft": False,
        "mergeable": "CONFLICTING",
        "head_ref": "fix/responsive-layout",
        "head_sha": "def456789012345678901234567890abcdef1234",
        "base_ref": "main",
        "base_sha": "000111222333444555666777888999aaabbbcccdd",
        "additions": 23,
        "deletions": 8,
        "changed_files": 2,
        "review_decision": "CHANGES_REQUESTED",
        "ci_status": "FAILURE",
        "labels": [{"name": "bug", "color": "d73a4a"}],
        "created_at": "2025-03-12T11:00:00Z",
        "updated_at": "2025-03-17T16:45:00Z",
        "merged_at": None,
        "closed_at": None,
        "url": "https://github.com/acme/frontend/pull/143",
    },
    {
        "id": 1003,
        "node_id": "PR_node3",
        "repo_owner": "acme",
        "repo_name": "backend",
        "number": 77,
        "title": "Upgrade database migration framework",
        "body": "Upgrades alembic from 1.12 to 1.14 and adds new migration scripts.",
        "state": "OPEN",
        "author": "alice",
        "author_avatar": None,
        "draft": True,
        "mergeable": "MERGEABLE",
        "head_ref": "chore/upgrade-alembic",
        "head_sha": "789012345678901234567890abcdef1234567890",
        "base_ref": "main",
        "base_sha": "aaa111bbb222ccc333ddd444eee555fff666777",
        "additions": 200,
        "deletions": 150,
        "changed_files": 8,
        "review_decision": None,
        "ci_status": "PENDING",
        "labels": [{"name": "dependencies", "color": "0075ca"}],
        "created_at": "2025-03-14T08:00:00Z",
        "updated_at": "2025-03-19T10:00:00Z",
        "merged_at": None,
        "closed_at": None,
        "url": "https://github.com/acme/backend/pull/77",
    },
    {
        "id": 1004,
        "node_id": "PR_node4",
        "repo_owner": "acme",
        "repo_name": "backend",
        "number": 78,
        "title": "Add rate limiting to API endpoints",
        "body": "Adds rate limiting middleware to prevent abuse.",
        "state": "OPEN",
        "author": "charlie",
        "author_avatar": None,
        "draft": False,
        "mergeable": "MERGEABLE",
        "head_ref": "feature/rate-limiting",
        "head_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "base_ref": "main",
        "base_sha": "aaa111bbb222ccc333ddd444eee555fff666777",
        "additions": 120,
        "deletions": 5,
        "changed_files": 4,
        "review_decision": "APPROVED",
        "ci_status": "SUCCESS",
        "labels": [{"name": "security", "color": "e4e669"}, {"name": "enhancement", "color": "a2eeef"}],
        "created_at": "2025-03-15T13:00:00Z",
        "updated_at": "2025-03-19T09:15:00Z",
        "merged_at": None,
        "closed_at": None,
        "url": "https://github.com/acme/backend/pull/78",
    },
    {
        "id": 1005,
        "node_id": "PR_node5",
        "repo_owner": "acme",
        "repo_name": "infra",
        "number": 31,
        "title": "Terraform module for new staging environment",
        "body": "Creates a new staging environment with Terraform.",
        "state": "OPEN",
        "author": "bob",
        "author_avatar": None,
        "draft": False,
        "mergeable": "UNKNOWN",
        "head_ref": "infra/staging-env",
        "head_sha": "1234567890abcdef1234567890abcdef12345678",
        "base_ref": "main",
        "base_sha": "bbb222ccc333ddd444eee555fff666777888aaa",
        "additions": 340,
        "deletions": 0,
        "changed_files": 12,
        "review_decision": "REVIEW_REQUIRED",
        "ci_status": None,
        "labels": [],
        "created_at": "2025-03-16T07:30:00Z",
        "updated_at": "2025-03-18T19:00:00Z",
        "merged_at": None,
        "closed_at": None,
        "url": "https://github.com/acme/infra/pull/31",
    },
]

SAMPLE_COMMITS = {
    1001: [
        {"sha": "aaa111", "message": "Initial dark mode implementation", "author": "alice", "authored_date": "2025-03-10T09:30:00Z", "url": "https://github.com/acme/frontend/commit/aaa111"},
        {"sha": "aaa222", "message": "Add toggle switch component", "author": "alice", "authored_date": "2025-03-11T10:00:00Z", "url": "https://github.com/acme/frontend/commit/aaa222"},
        {"sha": "aaa333", "message": "Store preference in localStorage", "author": "alice", "authored_date": "2025-03-12T14:00:00Z", "url": "https://github.com/acme/frontend/commit/aaa333"},
    ],
    1002: [
        {"sha": "bbb111", "message": "Fix media query breakpoints", "author": "bob", "authored_date": "2025-03-12T11:30:00Z", "url": "https://github.com/acme/frontend/commit/bbb111"},
    ],
    1003: [
        {"sha": "ccc111", "message": "Bump alembic to 1.14", "author": "alice", "authored_date": "2025-03-14T08:30:00Z", "url": "https://github.com/acme/backend/commit/ccc111"},
        {"sha": "ccc222", "message": "Update migration scripts", "author": "alice", "authored_date": "2025-03-15T09:00:00Z", "url": "https://github.com/acme/backend/commit/ccc222"},
    ],
    1004: [
        {"sha": "ddd111", "message": "Add rate limiter middleware", "author": "charlie", "authored_date": "2025-03-15T13:30:00Z", "url": "https://github.com/acme/backend/commit/ddd111"},
        {"sha": "ddd222", "message": "Add rate limit tests", "author": "charlie", "authored_date": "2025-03-16T10:00:00Z", "url": "https://github.com/acme/backend/commit/ddd222"},
    ],
    1005: [
        {"sha": "eee111", "message": "Add Terraform module for staging", "author": "bob", "authored_date": "2025-03-16T07:45:00Z", "url": "https://github.com/acme/infra/commit/eee111"},
    ],
}

SAMPLE_FILES = {
    1001: [
        {"filename": "src/components/Settings.tsx", "status": "modified", "additions": 40, "deletions": 5, "patch": "@@ -10,5 +10,45 @@\n-// TODO: dark mode\n+import { DarkModeToggle } from './DarkModeToggle';\n+\n+export function Settings() {\n+  return <DarkModeToggle />\n+}"},
        {"filename": "src/components/DarkModeToggle.tsx", "status": "added", "additions": 30, "deletions": 0, "patch": "@@ -0,0 +1,30 @@\n+export function DarkModeToggle() {\n+  // toggle implementation\n+}"},
        {"filename": "src/styles/theme.css", "status": "modified", "additions": 15, "deletions": 7, "patch": "@@ -1,7 +1,15 @@\n-:root { --bg: #fff; }\n+:root { --bg: #fff; }\n+.dark { --bg: #1a1a2e; }"},
    ],
    1002: [
        {"filename": "src/styles/responsive.css", "status": "modified", "additions": 20, "deletions": 8, "patch": "@@ -5,8 +5,20 @@\n-@media (max-width: 768px) {\n+@media (max-width: 768px) {\n+  .container { padding: 8px; }"},
        {"filename": "src/layouts/MainLayout.tsx", "status": "modified", "additions": 3, "deletions": 0, "patch": "@@ -15,0 +16,3 @@\n+  className={`layout ${isMobile ? 'mobile' : ''}`}"},
    ],
}

SAMPLE_CHECKS = {
    1001: [
        {"name": "build", "status": "completed", "conclusion": "success", "url": "https://github.com/acme/frontend/actions/runs/1"},
        {"name": "test", "status": "completed", "conclusion": "success", "url": "https://github.com/acme/frontend/actions/runs/2"},
        {"name": "lint", "status": "completed", "conclusion": "success", "url": "https://github.com/acme/frontend/actions/runs/3"},
    ],
    1002: [
        {"name": "build", "status": "completed", "conclusion": "success", "url": None},
        {"name": "test", "status": "completed", "conclusion": "failure", "url": None},
    ],
    1003: [
        {"name": "build", "status": "in_progress", "conclusion": None, "url": None},
        {"name": "test", "status": "queued", "conclusion": None, "url": None},
    ],
    1004: [
        {"name": "build", "status": "completed", "conclusion": "success", "url": None},
        {"name": "test", "status": "completed", "conclusion": "success", "url": None},
        {"name": "security-scan", "status": "completed", "conclusion": "success", "url": None},
    ],
}


async def seed_database(db_path: Path):
    """Seed the test database with sample data."""
    db = await get_db(db_path)
    for pr in SAMPLE_PRS:
        pr_id = await upsert_pull_request(db, pr)
        if pr_id in SAMPLE_COMMITS:
            await upsert_pr_commits(db, pr_id, SAMPLE_COMMITS[pr_id])
        if pr_id in SAMPLE_FILES:
            await upsert_pr_files(db, pr_id, SAMPLE_FILES[pr_id])
        if pr_id in SAMPLE_CHECKS:
            await upsert_pr_check_runs(db, pr_id, SAMPLE_CHECKS[pr_id])
    await db.commit()
    await db.close()
    print(f"Seeded {len(SAMPLE_PRS)} PRs into {db_path}")


def main():
    """Seed database and start af1 server for testing."""
    import uvicorn

    from af1.server import create_app

    # Use a temp directory for the test database
    test_dir = Path(tempfile.mkdtemp(prefix="af1_test_"))
    db_path = test_dir / "test.db"

    # Seed the database
    asyncio.run(seed_database(db_path))

    # Create config — use a dummy token; sync is disabled by using a very long interval
    config = Config(
        github_token="ghp_test_placeholder_token",
        github_host="github.com",
        watched_authors=["alice", "bob", "charlie"],
        db_path=db_path,
        host="127.0.0.1",
        port=8510,
        sync_interval_seconds=999999,
    )

    app = create_app(config)
    print(f"Starting test server on {config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")


if __name__ == "__main__":
    main()
