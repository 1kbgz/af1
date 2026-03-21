"""GitHub API client using GraphQL and REST."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# GraphQL query: fetch open PRs for a search query (authored or review-requested)
SEARCH_PRS_QUERY = """
query($query: String!, $cursor: String) {
  search(query: $query, type: ISSUE, first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        id
        databaseId
        number
        title
        body
        state
        isDraft
        mergeable
        additions
        deletions
        changedFiles
        headRefName
        headRefOid
        baseRefName
        baseRefOid
        createdAt
        updatedAt
        mergedAt
        closedAt
        url
        author { login avatarUrl }
        repository { owner { login } name }
        labels(first: 20) { nodes { name color } }
        reviewDecision
        commits(last: 1) {
          nodes {
            commit {
              statusCheckRollup {
                state
              }
            }
          }
        }
      }
    }
  }
}
"""

PR_COMMITS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      commits(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          commit {
            oid
            message
            author { name user { login } }
            authoredDate
            url
          }
        }
      }
    }
  }
}
"""

SEARCH_ISSUES_QUERY = """
query($query: String!, $cursor: String) {
  search(query: $query, type: ISSUE, first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Issue {
        id
        databaseId
        number
        title
        body
        state
        createdAt
        updatedAt
        closedAt
        url
        author { login avatarUrl }
        repository { owner { login } name }
        labels(first: 20) { nodes { name color } }
        assignees(first: 20) { nodes { login } }
        comments { totalCount }
      }
    }
  }
}
"""


class GitHubClient:
    def __init__(self, token: str, github_host: str = "github.com"):
        self._token = token
        self._github_host = github_host
        if github_host == "github.com":
            self._api_base = "https://api.github.com"
            self._graphql_url = "https://api.github.com/graphql"
        else:
            self._api_base = f"https://{github_host}/api/v3"
            self._graphql_url = f"https://{github_host}/api/graphql"
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        resp = await self._client.post(
            self._graphql_url,
            json={"query": query, "variables": variables or {}},
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            logger.error("GraphQL errors: %s", data["errors"])
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]

    async def fetch_open_prs_for_authors(self, authors: list[str]) -> list[dict]:
        """Fetch all open PRs authored by the given users across all repos."""
        all_prs = []
        for author in authors:
            query_str = f"is:pr is:open author:{author}"
            cursor = None
            while True:
                data = await self._graphql(SEARCH_PRS_QUERY, {"query": query_str, "cursor": cursor})
                search = data["search"]
                for node in search["nodes"]:
                    if node is None:
                        continue
                    all_prs.append(self._normalize_pr(node))
                if not search["pageInfo"]["hasNextPage"]:
                    break
                cursor = search["pageInfo"]["endCursor"]
        # Deduplicate by (owner, repo, number)
        seen = set()
        deduped = []
        for pr in all_prs:
            key = (pr["repo_owner"], pr["repo_name"], pr["number"])
            if key not in seen:
                seen.add(key)
                deduped.append(pr)
        return deduped

    async def fetch_review_requested_prs(self, username: str) -> list[dict]:
        """Fetch open PRs where review is requested from the user."""
        query_str = f"is:pr is:open review-requested:{username}"
        all_prs = []
        cursor = None
        while True:
            data = await self._graphql(SEARCH_PRS_QUERY, {"query": query_str, "cursor": cursor})
            search = data["search"]
            for node in search["nodes"]:
                if node is None:
                    continue
                all_prs.append(self._normalize_pr(node))
            if not search["pageInfo"]["hasNextPage"]:
                break
            cursor = search["pageInfo"]["endCursor"]
        return all_prs

    async def fetch_open_issues_for_authors(self, authors: list[str]) -> list[dict]:
        all_issues = []
        for author in authors:
            query_str = f"is:issue is:open author:{author}"
            cursor = None
            while True:
                data = await self._graphql(SEARCH_ISSUES_QUERY, {"query": query_str, "cursor": cursor})
                search = data["search"]
                for node in search["nodes"]:
                    if node is None:
                        continue
                    all_issues.append(self._normalize_issue(node))
                if not search["pageInfo"]["hasNextPage"]:
                    break
                cursor = search["pageInfo"]["endCursor"]
        seen = set()
        deduped = []
        for issue in all_issues:
            key = (issue["repo_owner"], issue["repo_name"], issue["number"])
            if key not in seen:
                seen.add(key)
                deduped.append(issue)
        return deduped

    async def fetch_assigned_issues(self, username: str) -> list[dict]:
        query_str = f"is:issue is:open assignee:{username}"
        all_issues = []
        cursor = None
        while True:
            data = await self._graphql(SEARCH_ISSUES_QUERY, {"query": query_str, "cursor": cursor})
            search = data["search"]
            for node in search["nodes"]:
                if node is None:
                    continue
                all_issues.append(self._normalize_issue(node))
            if not search["pageInfo"]["hasNextPage"]:
                break
            cursor = search["pageInfo"]["endCursor"]
        return all_issues

    def _normalize_pr(self, node: dict) -> dict:
        """Convert GraphQL PR node to flat dict for the database."""
        author = node.get("author") or {}
        repo = node.get("repository") or {}
        owner = repo.get("owner", {})
        labels = [{"name": lbl["name"], "color": lbl["color"]} for lbl in (node.get("labels", {}).get("nodes") or [])]

        # CI status from statusCheckRollup
        ci_status = None
        commits_nodes = (node.get("commits") or {}).get("nodes") or []
        if commits_nodes:
            rollup = (commits_nodes[-1].get("commit") or {}).get("statusCheckRollup")
            if rollup:
                ci_status = rollup.get("state")  # SUCCESS, FAILURE, PENDING, ERROR

        return {
            "id": node["databaseId"],
            "node_id": node["id"],
            "repo_owner": owner.get("login", ""),
            "repo_name": repo.get("name", ""),
            "number": node["number"],
            "title": node["title"],
            "body": node.get("body"),
            "state": node["state"],
            "author": author.get("login", "ghost"),
            "author_avatar": author.get("avatarUrl"),
            "draft": node.get("isDraft", False),
            "mergeable": node.get("mergeable"),
            "head_ref": node.get("headRefName"),
            "head_sha": node.get("headRefOid"),
            "base_ref": node.get("baseRefName"),
            "base_sha": node.get("baseRefOid"),
            "additions": node.get("additions", 0),
            "deletions": node.get("deletions", 0),
            "changed_files": node.get("changedFiles", 0),
            "review_decision": node.get("reviewDecision"),
            "ci_status": ci_status,
            "labels": labels,
            "created_at": node["createdAt"],
            "updated_at": node["updatedAt"],
            "merged_at": node.get("mergedAt"),
            "closed_at": node.get("closedAt"),
            "url": node["url"],
        }

    def _normalize_issue(self, node: dict) -> dict:
        """Convert GraphQL Issue node to flat dict for the database."""
        author = node.get("author") or {}
        repo = node.get("repository") or {}
        owner = repo.get("owner", {})
        labels = [{"name": lbl["name"], "color": lbl["color"]} for lbl in (node.get("labels", {}).get("nodes") or [])]
        assignees = [a["login"] for a in (node.get("assignees", {}).get("nodes") or [])]
        comments = node.get("comments") or {}

        return {
            "id": node["databaseId"],
            "node_id": node["id"],
            "repo_owner": owner.get("login", ""),
            "repo_name": repo.get("name", ""),
            "number": node["number"],
            "title": node["title"],
            "body": node.get("body"),
            "state": node["state"],
            "author": author.get("login", "ghost"),
            "author_avatar": author.get("avatarUrl"),
            "labels": labels,
            "assignees": assignees,
            "comment_count": comments.get("totalCount", 0),
            "created_at": node["createdAt"],
            "updated_at": node["updatedAt"],
            "closed_at": node.get("closedAt"),
            "url": node["url"],
        }

    async def fetch_pr_commits(self, owner: str, repo: str, number: int) -> list[dict]:
        """Fetch commits for a PR via GraphQL."""
        commits = []
        cursor = None
        while True:
            data = await self._graphql(
                PR_COMMITS_QUERY,
                {
                    "owner": owner,
                    "repo": repo,
                    "number": number,
                    "cursor": cursor,
                },
            )
            pr_data = data["repository"]["pullRequest"]["commits"]
            for node in pr_data["nodes"]:
                c = node["commit"]
                author_name = None
                if c.get("author"):
                    author_name = (c["author"].get("user") or {}).get("login") or c["author"].get("name")
                commits.append(
                    {
                        "sha": c["oid"],
                        "message": c["message"],
                        "author": author_name,
                        "authored_date": c.get("authoredDate"),
                        "url": c.get("url"),
                    }
                )
            if not pr_data["pageInfo"]["hasNextPage"]:
                break
            cursor = pr_data["pageInfo"]["endCursor"]
        return commits

    async def fetch_pr_files(self, owner: str, repo: str, number: int) -> list[dict]:
        """Fetch changed files for a PR via REST API (not available in GraphQL)."""
        files = []
        page = 1
        while True:
            resp = await self._client.get(
                f"{self._api_base}/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for f in batch:
                files.append(
                    {
                        "filename": f["filename"],
                        "status": f.get("status"),
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "patch": f.get("patch"),
                    }
                )
            if len(batch) < 100:
                break
            page += 1
        return files

    async def fetch_pr_check_runs(self, owner: str, repo: str, ref: str) -> list[dict]:
        """Fetch check runs for a commit ref via REST API."""
        checks = []
        page = 1
        while True:
            resp = await self._client.get(
                f"{self._api_base}/repos/{owner}/{repo}/commits/{ref}/check-runs",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            for cr in data.get("check_runs", []):
                checks.append(
                    {
                        "name": cr["name"],
                        "status": cr.get("status"),
                        "conclusion": cr.get("conclusion"),
                        "url": cr.get("html_url"),
                    }
                )
            if len(data.get("check_runs", [])) < 100:
                break
            page += 1
        return checks

    async def get_authenticated_user(self) -> dict:
        resp = await self._client.get(f"{self._api_base}/user")
        resp.raise_for_status()
        return resp.json()

    async def merge_pull_request(self, owner: str, repo: str, number: int, merge_method: str = "merge") -> dict:
        """Merge a PR via REST API. merge_method: merge, squash, or rebase."""
        resp = await self._client.put(
            f"{self._api_base}/repos/{owner}/{repo}/pulls/{number}/merge",
            json={"merge_method": merge_method},
        )
        if resp.status_code == 200:
            return {"success": True}
        data = resp.json()
        return {"success": False, "error": data.get("message", f"HTTP {resp.status_code}")}

    async def close_pull_request(self, owner: str, repo: str, number: int) -> dict:
        """Close a PR via REST API (update state to closed)."""
        resp = await self._client.patch(
            f"{self._api_base}/repos/{owner}/{repo}/pulls/{number}",
            json={"state": "closed"},
        )
        if resp.status_code == 200:
            return {"success": True}
        data = resp.json()
        return {"success": False, "error": data.get("message", f"HTTP {resp.status_code}")}

    async def approve_pull_request(self, owner: str, repo: str, number: int) -> dict:
        """Approve a PR by submitting an APPROVE review via REST API."""
        resp = await self._client.post(
            f"{self._api_base}/repos/{owner}/{repo}/pulls/{number}/reviews",
            json={"event": "APPROVE"},
        )
        if resp.status_code == 200:
            return {"success": True}
        data = resp.json()
        return {"success": False, "error": data.get("message", f"HTTP {resp.status_code}")}
