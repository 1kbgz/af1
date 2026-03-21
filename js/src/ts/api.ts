/** af1 — API client for communicating with the Python backend. */

const API_BASE = window.location.origin;

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API ${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

export interface PullRequest {
  id: number;
  node_id: string;
  repo_owner: string;
  repo_name: string;
  number: number;
  title: string;
  body: string | null;
  state: string;
  author: string;
  author_avatar: string | null;
  draft: number;
  mergeable: string | null;
  head_ref: string | null;
  head_sha: string | null;
  base_ref: string | null;
  base_sha: string | null;
  additions: number;
  deletions: number;
  changed_files: number;
  review_decision: string | null;
  ci_status: string | null;
  labels: Array<{ name: string; color: string }>;
  created_at: string;
  updated_at: string;
  merged_at: string | null;
  closed_at: string | null;
  url: string;
}

export interface PRCommit {
  sha: string;
  message: string;
  author: string | null;
  authored_date: string | null;
  url: string | null;
}

export interface PRFile {
  filename: string;
  status: string | null;
  additions: number;
  deletions: number;
  patch: string | null;
}

export interface PRCheck {
  name: string;
  status: string | null;
  conclusion: string | null;
  url: string | null;
}

export interface PRDetail extends PullRequest {
  commits: PRCommit[];
  files: PRFile[];
  checks: PRCheck[];
}

export interface UserInfo {
  login: string;
  name: string | null;
  avatar_url: string | null;
}

export interface AppConfig {
  watched_authors: string[];
  sync_interval_seconds: number;
}

export async function getMe(): Promise<UserInfo> {
  return fetchJSON<UserInfo>("/api/me");
}

export async function getConfig(): Promise<AppConfig> {
  return fetchJSON<AppConfig>("/api/config");
}

export async function getPullRequests(
  authors?: string[],
): Promise<PullRequest[]> {
  const params = authors?.length
    ? `?authors=${encodeURIComponent(authors.join(","))}`
    : "";
  return fetchJSON<PullRequest[]>(`/api/prs${params}`);
}

export async function getPRDetail(
  owner: string,
  repo: string,
  number: number,
): Promise<PRDetail> {
  return fetchJSON<PRDetail>(
    `/api/prs/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${number}`,
  );
}

export async function triggerSync(): Promise<void> {
  await fetchJSON<{ status: string }>("/api/sync", { method: "POST" });
}

export async function syncPR(
  owner: string,
  repo: string,
  number: number,
): Promise<void> {
  await fetchJSON<{ status: string }>(
    `/api/prs/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${number}/sync`,
    { method: "POST" },
  );
}

export async function syncRepo(owner: string, repo: string): Promise<void> {
  await fetchJSON<{ status: string }>(
    `/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/sync`,
    { method: "POST" },
  );
}

export interface BatchTarget {
  owner: string;
  repo: string;
  number: number;
}

export interface BatchResult {
  owner: string;
  repo: string;
  number: number;
  success: boolean;
  error?: string;
}

export async function mergePullRequests(
  targets: BatchTarget[],
): Promise<BatchResult[]> {
  return fetchJSON<BatchResult[]>("/api/prs/merge", {
    method: "POST",
    body: JSON.stringify({ targets }),
  });
}

export async function closePullRequests(
  targets: BatchTarget[],
): Promise<BatchResult[]> {
  return fetchJSON<BatchResult[]>("/api/prs/close", {
    method: "POST",
    body: JSON.stringify({ targets }),
  });
}

export async function approvePullRequests(
  targets: BatchTarget[],
): Promise<BatchResult[]> {
  return fetchJSON<BatchResult[]>("/api/prs/approve", {
    method: "POST",
    body: JSON.stringify({ targets }),
  });
}

export interface Issue {
  id: number;
  node_id: string;
  repo_owner: string;
  repo_name: string;
  number: number;
  title: string;
  body: string | null;
  state: string;
  author: string;
  author_avatar: string | null;
  labels: Array<{ name: string; color: string }>;
  assignees: string[];
  comment_count: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  url: string;
}

export async function getIssues(authors?: string[]): Promise<Issue[]> {
  const params = authors?.length
    ? `?authors=${encodeURIComponent(authors.join(","))}`
    : "";
  return fetchJSON<Issue[]>(`/api/issues${params}`);
}

export async function getIssueDetail(
  owner: string,
  repo: string,
  number: number,
): Promise<Issue> {
  return fetchJSON<Issue>(
    `/api/issues/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${number}`,
  );
}
