/** af1 — Repo list view: maintained repos across orgs with inline counts. */

import { getRepos, type Repo } from "./api.js";
import { esc, timeAgo } from "./render.js";

let allRepos: Repo[] = [];
let filterText = "";
let filterOrgs: Set<string> = new Set();

type SortColumn = "name" | "open_prs" | "open_issues" | "failing_ci" | "pushed";
let sortColumn: SortColumn = "pushed";
let sortAsc = false;

let activeStatFilter: string | null = null;

export async function renderRepoList(container: HTMLElement): Promise<void> {
  container.innerHTML = `<div class="loading">Loading repos&hellip;</div>`;

  try {
    allRepos = await getRepos();
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><h3>Failed to load repos</h3><p>${esc(String(e))}</p></div>`;
    return;
  }

  renderDashboard(container);
}

function renderDashboard(container?: HTMLElement): void {
  const root = container || document.getElementById("view-container");
  if (!root) return;

  const filtered = getFilteredRepos();

  const total = allRepos.length;
  const orgs = new Set(allRepos.map((r) => r.owner));
  const totalOpenPRs = allRepos.reduce((n, r) => n + (r.open_pr_count || 0), 0);
  const withFailingCI = allRepos.filter(
    (r) => (r.failing_ci_count || 0) > 0,
  ).length;

  const orgOptions = [...orgs].sort();
  const orgDropdownHTML = orgOptions.length
    ? `<div class="multi-select" id="org-select">
        <button class="multi-select-btn" id="org-select-btn">Orgs${filterOrgs.size ? ` <span class="ms-count">(${filterOrgs.size})</span>` : ""} <span class="ms-caret">&#x25BE;</span></button>
        <div class="multi-select-dropdown hidden" id="org-dropdown">
          ${orgOptions.map((o) => `<label class="ms-option"><input type="checkbox" value="${esc(o)}" ${filterOrgs.has(o) ? "checked" : ""} /> ${esc(o)}</label>`).join("")}
        </div>
      </div>`
    : "";

  root.innerHTML = `
    <div class="dashboard-stats">
      <div class="stat-card stat-total${activeStatFilter === null ? " active" : ""}" data-filter="">
        <div class="stat-value">${total}</div>
        <div class="stat-label">Repos</div>
      </div>
      <div class="stat-card stat-repos" data-filter="">
        <div class="stat-value">${orgs.size}</div>
        <div class="stat-label">Orgs</div>
      </div>
      <div class="stat-card stat-comments" data-filter="">
        <div class="stat-value">${totalOpenPRs}</div>
        <div class="stat-label">Open PRs</div>
      </div>
      <div class="stat-card stat-failing${activeStatFilter === "failing" ? " active" : ""}" data-filter="failing">
        <div class="stat-value">${withFailingCI}</div>
        <div class="stat-label">Failing CI</div>
      </div>
    </div>

    <div class="filter-bar">
      <input id="filter-input" type="text" placeholder="Filter repos&hellip;" value="${esc(filterText)}" />
      ${orgDropdownHTML}
    </div>

    <div id="repo-list-container">
      ${filtered.length ? renderTable(filtered) : `<div class="empty-state"><h3>No repos found</h3><p>Set AF1_WATCHED_USERS / AF1_WATCHED_ORGS / AF1_WATCHED_REPOS, then sync.</p></div>`}
    </div>
  `;

  bindEvents(root);
}

function getFilteredRepos(): Repo[] {
  let repos = [...allRepos];

  if (activeStatFilter === "failing") {
    repos = repos.filter((r) => (r.failing_ci_count || 0) > 0);
  }

  if (filterOrgs.size > 0) {
    repos = repos.filter((r) => filterOrgs.has(r.owner));
  }

  if (filterText) {
    const lower = filterText.toLowerCase();
    repos = repos.filter(
      (r) =>
        r.name_with_owner.toLowerCase().includes(lower) ||
        (r.description || "").toLowerCase().includes(lower),
    );
  }

  repos.sort((a, b) => {
    let cmp = 0;
    switch (sortColumn) {
      case "name":
        cmp = a.name_with_owner.localeCompare(b.name_with_owner);
        break;
      case "open_prs":
        cmp = a.open_pr_count - b.open_pr_count;
        break;
      case "open_issues":
        cmp = a.open_issue_count - b.open_issue_count;
        break;
      case "failing_ci":
        cmp = a.failing_ci_count - b.failing_ci_count;
        break;
      case "pushed":
        cmp = (a.pushed_at || "").localeCompare(b.pushed_at || "");
        break;
    }
    return sortAsc ? cmp : -cmp;
  });

  return repos;
}

function sortIndicator(col: SortColumn): string {
  if (sortColumn !== col) return "";
  return sortAsc ? " &#x25B4;" : " &#x25BE;";
}

function permissionBadge(permission: string | null): string {
  if (!permission) return "";
  const p = permission.toUpperCase();
  const cls =
    p === "ADMIN" || p === "MAINTAIN" ? "badge-success" : "badge-review";
  return `<span class="badge ${cls}">${esc(p.toLowerCase())}</span>`;
}

function countCell(n: number, kind: "" | "failing" = ""): string {
  if (!n) return `<span class="text-muted">—</span>`;
  const cls = kind === "failing" ? "count-failing" : "";
  return `<span class="repo-count ${cls}">${n}</span>`;
}

function renderTable(repos: Repo[]): string {
  const rows = repos
    .map((repo) => {
      return `<tr class="repo-row">
      <td class="td-title">
        <a class="repo-row-link" href="${esc(repo.url || "#")}" target="_blank" rel="noopener">${esc(repo.name_with_owner)}</a>
        ${repo.is_private ? `<span class="badge badge-pending">private</span>` : ""}
        ${repo.is_archived ? `<span class="badge badge-failure">archived</span>` : ""}
        ${permissionBadge(repo.viewer_permission)}
        ${repo.description ? `<span class="repo-row-desc">${esc(repo.description)}</span>` : ""}
      </td>
      <td class="td-count">${countCell(repo.open_pr_count)}</td>
      <td class="td-count">${countCell(repo.open_issue_count)}</td>
      <td class="td-count">${countCell(repo.failing_ci_count, "failing")}</td>
      <td class="td-time" title="${esc(repo.pushed_at || "")}">${repo.pushed_at ? timeAgo(repo.pushed_at) : "—"}</td>
      <td class="td-actions"><a class="external-link" href="${esc(repo.url || "#")}" target="_blank" rel="noopener">&#x2197;</a></td>
    </tr>`;
    })
    .join("");

  return `
    <table class="repo-table">
      <thead>
        <tr>
          <th class="th-title sortable-th" data-sort="name">Repository${sortIndicator("name")}</th>
          <th class="th-count sortable-th" data-sort="open_prs">Open PRs${sortIndicator("open_prs")}</th>
          <th class="th-count sortable-th" data-sort="open_issues">Open Issues${sortIndicator("open_issues")}</th>
          <th class="th-count sortable-th" data-sort="failing_ci">Failing CI${sortIndicator("failing_ci")}</th>
          <th class="th-time sortable-th" data-sort="pushed">Pushed${sortIndicator("pushed")}</th>
          <th class="th-actions"></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function bindEvents(container: HTMLElement): void {
  const filterInput =
    container.querySelector<HTMLInputElement>("#filter-input");
  if (filterInput) {
    filterInput.addEventListener("input", () => {
      filterText = filterInput.value;
      renderDashboard();
    });
  }

  container.querySelectorAll<HTMLElement>(".stat-card").forEach((card) => {
    card.addEventListener("click", () => {
      const f = card.dataset.filter ?? null;
      activeStatFilter = activeStatFilter === f ? null : f || null;
      renderDashboard();
    });
  });

  container.querySelectorAll<HTMLElement>(".sortable-th").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort as SortColumn;
      if (sortColumn === col) {
        sortAsc = !sortAsc;
      } else {
        sortColumn = col;
        sortAsc = false;
      }
      renderDashboard();
    });
  });

  const orgBtn = container.querySelector("#org-select-btn");
  const orgDrop = container.querySelector("#org-dropdown");
  if (orgBtn && orgDrop) {
    orgBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      orgDrop.classList.toggle("hidden");
    });
    orgDrop
      .querySelectorAll<HTMLInputElement>("input[type=checkbox]")
      .forEach((cb) => {
        cb.addEventListener("change", () => {
          if (cb.checked) filterOrgs.add(cb.value);
          else filterOrgs.delete(cb.value);
          renderDashboard();
        });
      });
    document.addEventListener("click", () => orgDrop.classList.add("hidden"));
  }
}
