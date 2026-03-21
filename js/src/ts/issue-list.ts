/** af1 — Issue list view with stats, filters, and table. */

import { getIssues, type Issue } from "./api.js";
import { esc, timeAgo, labelHTML } from "./render.js";
import { navigateTo } from "./router.js";

let allIssues: Issue[] = [];
let filterText = "";
let filterLabels: Set<string> = new Set();

type GroupByOption = "none" | "repo" | "author";
let groupBy: GroupByOption = "none";

type SortColumn = "number" | "author" | "created" | "updated";
let sortColumn: SortColumn = "updated";
let sortAsc = false;

let activeStatFilter: string | null = null;

function issueKey(issue: Issue): string {
  return `${issue.repo_owner}/${issue.repo_name}#${issue.number}`;
}

export async function renderIssueList(container: HTMLElement): Promise<void> {
  container.innerHTML = `<div class="loading">Loading issues&hellip;</div>`;

  try {
    allIssues = await getIssues();
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><h3>Failed to load issues</h3><p>${esc(String(e))}</p></div>`;
    return;
  }

  renderDashboard(container);
}

function renderDashboard(container?: HTMLElement): void {
  const root = container || document.getElementById("view-container");
  if (!root) return;

  const filtered = getFilteredIssues();

  // Stats
  const total = allIssues.length;
  const uniqueRepos = new Set(
    allIssues.map((i) => `${i.repo_owner}/${i.repo_name}`),
  ).size;
  const withComments = allIssues.filter((i) => i.comment_count > 0).length;
  const noAssignee = allIssues.filter(
    (i) => !i.assignees || i.assignees.length === 0,
  ).length;

  // Collect all labels
  const allLabels = new Set<string>();
  allIssues.forEach((i) =>
    (i.labels || []).forEach((l) => allLabels.add(l.name)),
  );
  const labelOptions = [...allLabels].sort();

  const labelDropdownHTML = labelOptions.length
    ? `<div class="multi-select" id="label-select">
        <button class="multi-select-btn" id="label-select-btn">Labels${filterLabels.size ? ` <span class="ms-count">(${filterLabels.size})</span>` : ""} <span class="ms-caret">&#x25BE;</span></button>
        <div class="multi-select-dropdown hidden" id="label-dropdown">
          ${labelOptions.map((l) => `<label class="ms-option"><input type="checkbox" value="${esc(l)}" ${filterLabels.has(l) ? "checked" : ""} /> ${esc(l)}</label>`).join("")}
        </div>
      </div>`
    : "";

  root.innerHTML = `
    <div class="dashboard-stats">
      <div class="stat-card stat-total${activeStatFilter === null ? " active" : ""}" data-filter="">
        <div class="stat-value">${total}</div>
        <div class="stat-label">Open</div>
      </div>
      <div class="stat-card stat-repos${activeStatFilter === "repos" ? " active" : ""}" data-filter="repos">
        <div class="stat-value">${uniqueRepos}</div>
        <div class="stat-label">Repos</div>
      </div>
      <div class="stat-card stat-comments${activeStatFilter === "comments" ? " active" : ""}" data-filter="comments">
        <div class="stat-value">${withComments}</div>
        <div class="stat-label">With Comments</div>
      </div>
      <div class="stat-card stat-unassigned${activeStatFilter === "unassigned" ? " active" : ""}" data-filter="unassigned">
        <div class="stat-value">${noAssignee}</div>
        <div class="stat-label">Unassigned</div>
      </div>
    </div>

    <div class="filter-bar">
      <input id="filter-input" type="text" placeholder="Filter issues&hellip;" value="${esc(filterText)}" />
      <select id="group-select">
        <option value="none"${groupBy === "none" ? " selected" : ""}>No grouping</option>
        <option value="repo"${groupBy === "repo" ? " selected" : ""}>Group by repo</option>
        <option value="author"${groupBy === "author" ? " selected" : ""}>Group by author</option>
      </select>
      ${labelDropdownHTML}
    </div>

    <div id="issue-list-container">
      ${filtered.length ? renderFilteredIssues(filtered) : `<div class="empty-state"><h3>No issues found</h3></div>`}
    </div>
  `;

  bindEvents(root);
}

function getFilteredIssues(): Issue[] {
  let issues = [...allIssues];

  // Stat filter
  if (activeStatFilter === "comments") {
    issues = issues.filter((i) => i.comment_count > 0);
  } else if (activeStatFilter === "unassigned") {
    issues = issues.filter((i) => !i.assignees || i.assignees.length === 0);
  }

  // Text filter
  if (filterText) {
    const lower = filterText.toLowerCase();
    issues = issues.filter(
      (i) =>
        i.title.toLowerCase().includes(lower) ||
        i.author.toLowerCase().includes(lower) ||
        `${i.repo_owner}/${i.repo_name}`.toLowerCase().includes(lower) ||
        `#${i.number}`.includes(lower),
    );
  }

  // Label filter
  if (filterLabels.size > 0) {
    issues = issues.filter((i) => {
      const names = (i.labels || []).map((l) => l.name);
      return [...filterLabels].every((fl) => names.includes(fl));
    });
  }

  // Sort
  issues.sort((a, b) => {
    let cmp = 0;
    switch (sortColumn) {
      case "number":
        cmp = a.number - b.number;
        break;
      case "author":
        cmp = a.author.localeCompare(b.author);
        break;
      case "created":
        cmp = a.created_at.localeCompare(b.created_at);
        break;
      case "updated":
        cmp = a.updated_at.localeCompare(b.updated_at);
        break;
    }
    return sortAsc ? cmp : -cmp;
  });

  return issues;
}

function renderFilteredIssues(issues: Issue[]): string {
  if (groupBy === "none") {
    return renderTable(issues, null);
  }

  const groups = new Map<string, Issue[]>();
  for (const issue of issues) {
    const key =
      groupBy === "repo"
        ? `${issue.repo_owner}/${issue.repo_name}`
        : issue.author;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(issue);
  }

  return [...groups.entries()]
    .map(([label, items]) => renderTable(items, label))
    .join("");
}

function sortIndicator(col: typeof sortColumn): string {
  if (sortColumn !== col) return "";
  return sortAsc ? " &#x25B4;" : " &#x25BE;";
}

function renderTable(issues: Issue[], groupLabel: string | null): string {
  const header = groupLabel
    ? `<div class="group-header">
        <span class="group-name">${esc(groupLabel)}</span>
        <span class="group-count">${issues.length}</span>
       </div>`
    : "";

  const rows = issues
    .map((issue) => {
      const labelsHTML = (issue.labels || []).map(labelHTML).join(" ");
      const assigneesHTML = (issue.assignees || [])
        .map((a) => esc(a))
        .join(", ");

      return `<tr class="issue-row">
      <td class="td-title">
        <span class="issue-row-link" data-owner="${esc(issue.repo_owner)}" data-repo="${esc(issue.repo_name)}" data-number="${issue.number}">
          ${esc(issue.title)}
        </span>
        <span class="issue-row-ref">${groupBy !== "repo" ? esc(`${issue.repo_owner}/${issue.repo_name}`) + " " : ""}#${issue.number}</span>
        ${labelsHTML ? `<span class="issue-row-labels">${labelsHTML}</span>` : ""}
      </td>
      <td class="td-author">
        ${issue.author_avatar ? `<img class="avatar-sm" src="${esc(issue.author_avatar)}&s=32" alt="" />` : ""}
        ${esc(issue.author)}
      </td>
      <td class="td-assignees">${assigneesHTML || `<span class="text-muted">—</span>`}</td>
      <td class="td-comments">${issue.comment_count > 0 ? `&#x1F4AC; ${issue.comment_count}` : ""}</td>
      <td class="td-time" title="${esc(issue.created_at)}">${timeAgo(issue.created_at)}</td>
      <td class="td-time" title="${esc(issue.updated_at)}">${timeAgo(issue.updated_at)}</td>
      <td class="td-actions"><a class="external-link" href="${esc(issue.url)}" target="_blank" rel="noopener">&#x2197;</a></td>
    </tr>`;
    })
    .join("");

  return `
    ${header}
    <table class="issue-table">
      <thead>
        <tr>
          <th class="th-title sortable-th" data-sort="number">Issue${sortIndicator("number")}</th>
          <th class="th-author sortable-th" data-sort="author">Author${sortIndicator("author")}</th>
          <th class="th-assignees">Assignees</th>
          <th class="th-comments">Comments</th>
          <th class="th-time sortable-th" data-sort="created">Created${sortIndicator("created")}</th>
          <th class="th-time sortable-th" data-sort="updated">Updated${sortIndicator("updated")}</th>
          <th class="th-actions"></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function bindEvents(container: HTMLElement): void {
  // Filter input
  const filterInput =
    container.querySelector<HTMLInputElement>("#filter-input");
  if (filterInput) {
    filterInput.addEventListener("input", () => {
      filterText = filterInput.value;
      renderDashboard();
    });
  }

  // Group select
  const groupSelect =
    container.querySelector<HTMLSelectElement>("#group-select");
  if (groupSelect) {
    groupSelect.addEventListener("change", () => {
      groupBy = groupSelect.value as GroupByOption;
      renderDashboard();
    });
  }

  // Stat card filters
  container.querySelectorAll<HTMLElement>(".stat-card").forEach((card) => {
    card.addEventListener("click", () => {
      const f = card.dataset.filter ?? null;
      activeStatFilter = activeStatFilter === f ? null : f || null;
      renderDashboard();
    });
  });

  // Sortable headers
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

  // Label multi-select
  const labelBtn = container.querySelector("#label-select-btn");
  const labelDrop = container.querySelector("#label-dropdown");
  if (labelBtn && labelDrop) {
    labelBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      labelDrop.classList.toggle("hidden");
    });
    labelDrop
      .querySelectorAll<HTMLInputElement>("input[type=checkbox]")
      .forEach((cb) => {
        cb.addEventListener("change", () => {
          if (cb.checked) filterLabels.add(cb.value);
          else filterLabels.delete(cb.value);
          renderDashboard();
        });
      });
    document.addEventListener("click", () => labelDrop.classList.add("hidden"));
  }

  // Issue row click → open GitHub URL
  container.querySelectorAll<HTMLElement>(".issue-row-link").forEach((link) => {
    link.addEventListener("click", () => {
      const { owner, repo, number } = link.dataset;
      navigateTo(`/issue/${owner}/${repo}/${number}`);
    });
  });
}
