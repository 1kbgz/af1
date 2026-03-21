/** af1 — PR dashboard view with summary stats, table layout, and batch actions. */

import {
  getPullRequests,
  getConfig,
  mergePullRequests,
  closePullRequests,
  approvePullRequests,
  syncPR,
  syncRepo,
  type PullRequest,
  type AppConfig,
} from "./api.js";
import {
  esc,
  timeAgo,
  ciBadge,
  mergeableBadge,
  reviewBadge,
  labelHTML,
} from "./render.js";
import { navigateTo } from "./router.js";

let allPRs: PullRequest[] = [];
let config: AppConfig | null = null;
let filterText = "";
let filterAuthors: Set<string> = new Set();
let filterRepos: Set<string> = new Set();
let filterCIs: Set<string> = new Set();
let filterLabels: Set<string> = new Set();
let filterReviews: Set<string> = new Set();
let selectedPRs = new Set<string>(); // "owner/repo#number"
let groupBy: "none" | "repo" | "author" = "repo";
let sortColumn: "number" | "author" | "created" | "updated" = "number";
let sortAsc = false; // false = descending (newest first, matching GitHub)
let activeStat: string | null = null; // active stat-card filter key

function prKey(pr: PullRequest): string {
  return `${pr.repo_owner}/${pr.repo_name}#${pr.number}`;
}

// --- Multi-select dropdown helper ---
function createMultiSelect(
  id: string,
  label: string,
  options: string[],
  selected: Set<string>,
  onChange: () => void,
): string {
  return `<div class="multi-select" id="${id}-ms"><button class="multi-select-btn" id="${id}-btn">${label}<span class="ms-count" id="${id}-count"></span> <span class="ms-caret">&#x25BE;</span></button><div class="multi-select-dropdown hidden" id="${id}-dropdown"></div></div>`;
}

function initMultiSelect(
  id: string,
  options: string[],
  selected: Set<string>,
  labelFn: (v: string) => string,
  onChange: () => void,
): void {
  const btn = document.getElementById(`${id}-btn`)!;
  const dropdown = document.getElementById(`${id}-dropdown`)!;
  const countEl = document.getElementById(`${id}-count`)!;

  // Build dropdown items
  dropdown.innerHTML = options
    .map((opt) => {
      const checked = selected.has(opt) ? "checked" : "";
      return `<label class="ms-option"><input type="checkbox" value="${esc(opt)}" ${checked} /> ${esc(labelFn(opt))}</label>`;
    })
    .join("");

  const updateCount = () => {
    countEl.textContent = selected.size > 0 ? ` (${selected.size})` : "";
  };
  updateCount();

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    // Close all other dropdowns
    document.querySelectorAll(".multi-select-dropdown").forEach((d) => {
      if (d !== dropdown) d.classList.add("hidden");
    });
    dropdown.classList.toggle("hidden");
  });

  dropdown
    .querySelectorAll<HTMLInputElement>("input[type=checkbox]")
    .forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) selected.add(cb.value);
        else selected.delete(cb.value);
        updateCount();
        onChange();
      });
    });
}

// Close dropdowns on outside click
document.addEventListener("click", () => {
  document
    .querySelectorAll(".multi-select-dropdown")
    .forEach((d) => d.classList.add("hidden"));
});

export async function renderPRList(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div id="dashboard-stats" class="dashboard-stats"></div>
    <div class="filter-bar">
      <input id="filter-search" type="text" placeholder="Search PRs..." />
      <div id="ms-author-placeholder"></div>
      <div id="ms-repo-placeholder"></div>
      <div id="ms-ci-placeholder"></div>
      <div id="ms-label-placeholder"></div>
      <div id="ms-review-placeholder"></div>
      <select id="group-by">
        <option value="repo">Group by repo</option>
        <option value="author">Group by author</option>
        <option value="none">No grouping</option>
      </select>
    </div>
    <div id="batch-bar" class="batch-bar hidden">
      <span id="batch-count">0 selected</span>
      <button id="batch-merge" class="batch-btn batch-btn-merge" disabled>Merge selected</button>
      <button id="batch-approve" class="batch-btn batch-btn-approve">Approve selected</button>
      <button id="batch-close" class="batch-btn batch-btn-close">Close selected</button>
      <button id="batch-clear" class="batch-btn batch-btn-clear">Clear selection</button>
    </div>
    <div id="pr-table-container"></div>
  `;

  try {
    config = await getConfig();
    allPRs = await getPullRequests();
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><h3>Failed to load</h3><p>${esc(String(e))}</p></div>`;
    return;
  }

  if (allPRs.length === 0) {
    container.innerHTML = `<div class="empty-state"><h3>No open PRs</h3><p>Waiting for background sync to complete. Try clicking the sync button.</p></div>`;
    return;
  }

  // Build multi-select options
  const authors = [...new Set(allPRs.map((pr) => pr.author))].sort();
  const repos = [
    ...new Set(allPRs.map((pr) => `${pr.repo_owner}/${pr.repo_name}`)),
  ].sort();
  const ciOptions = ["SUCCESS", "FAILURE", "PENDING", "NONE"];
  const ciLabels: Record<string, string> = {
    SUCCESS: "CI passing",
    FAILURE: "CI failing",
    PENDING: "CI pending",
    NONE: "No CI",
  };
  const labels = [
    ...new Set(allPRs.flatMap((pr) => (pr.labels || []).map((l) => l.name))),
  ].sort();
  const reviewOptions = [
    "APPROVED",
    "CHANGES_REQUESTED",
    "REVIEW_REQUIRED",
    "NONE",
  ];
  const reviewLabels: Record<string, string> = {
    APPROVED: "Approved",
    CHANGES_REQUESTED: "Changes requested",
    REVIEW_REQUIRED: "Review required",
    NONE: "No review",
  };

  // Insert multi-selects
  document.getElementById("ms-author-placeholder")!.outerHTML =
    createMultiSelect(
      "ms-author",
      "Authors",
      authors,
      filterAuthors,
      renderDashboard,
    );
  document.getElementById("ms-repo-placeholder")!.outerHTML = createMultiSelect(
    "ms-repo",
    "Repos",
    repos,
    filterRepos,
    renderDashboard,
  );
  document.getElementById("ms-ci-placeholder")!.outerHTML = createMultiSelect(
    "ms-ci",
    "CI Status",
    ciOptions,
    filterCIs,
    renderDashboard,
  );
  document.getElementById("ms-label-placeholder")!.outerHTML =
    createMultiSelect(
      "ms-label",
      "Labels",
      labels,
      filterLabels,
      renderDashboard,
    );
  document.getElementById("ms-review-placeholder")!.outerHTML =
    createMultiSelect(
      "ms-review",
      "Review",
      reviewOptions,
      filterReviews,
      renderDashboard,
    );

  initMultiSelect(
    "ms-author",
    authors,
    filterAuthors,
    (v) => v,
    renderDashboard,
  );
  initMultiSelect("ms-repo", repos, filterRepos, (v) => v, renderDashboard);
  initMultiSelect(
    "ms-ci",
    ciOptions,
    filterCIs,
    (v) => ciLabels[v] || v,
    renderDashboard,
  );
  initMultiSelect("ms-label", labels, filterLabels, (v) => v, renderDashboard);
  initMultiSelect(
    "ms-review",
    reviewOptions,
    filterReviews,
    (v) => reviewLabels[v] || v,
    renderDashboard,
  );

  // Event handlers
  const searchInput = document.getElementById(
    "filter-search",
  ) as HTMLInputElement;
  searchInput.addEventListener("input", () => {
    filterText = searchInput.value.toLowerCase();
    renderDashboard();
  });
  (document.getElementById("group-by") as HTMLSelectElement).addEventListener(
    "change",
    (e) => {
      groupBy = (e.target as HTMLSelectElement).value as typeof groupBy;
      renderDashboard();
    },
  );

  // Batch action handlers
  document
    .getElementById("batch-merge")!
    .addEventListener("click", handleBatchMerge);
  document
    .getElementById("batch-approve")!
    .addEventListener("click", handleBatchApprove);
  document
    .getElementById("batch-close")!
    .addEventListener("click", handleBatchClose);
  document.getElementById("batch-clear")!.addEventListener("click", () => {
    selectedPRs.clear();
    renderDashboard();
  });

  selectedPRs.clear();
  renderDashboard();
}

function matchesStat(pr: PullRequest, stat: string): boolean {
  switch (stat) {
    case "total":
      return true;
    case "ready":
      return (
        pr.ci_status?.toUpperCase() === "SUCCESS" &&
        pr.mergeable?.toUpperCase() === "MERGEABLE" &&
        !pr.draft
      );
    case "pass":
      return pr.ci_status?.toUpperCase() === "SUCCESS";
    case "fail":
      return (
        pr.ci_status?.toUpperCase() === "FAILURE" ||
        pr.ci_status?.toUpperCase() === "ERROR"
      );
    case "pending":
      return (
        pr.ci_status?.toUpperCase() === "PENDING" ||
        pr.ci_status?.toUpperCase() === "EXPECTED"
      );
    case "mergeable":
      return pr.mergeable?.toUpperCase() === "MERGEABLE";
    case "conflicts":
      return pr.mergeable?.toUpperCase() === "CONFLICTING";
    case "approved":
      return pr.review_decision?.toUpperCase() === "APPROVED";
    case "drafts":
      return !!pr.draft;
    default:
      return true;
  }
}

function getFiltered(): PullRequest[] {
  let filtered = allPRs;
  if (activeStat && activeStat !== "total") {
    filtered = filtered.filter((pr) => matchesStat(pr, activeStat!));
  }
  if (filterText) {
    filtered = filtered.filter(
      (pr) =>
        pr.title.toLowerCase().includes(filterText) ||
        `${pr.repo_owner}/${pr.repo_name}`.toLowerCase().includes(filterText) ||
        pr.author.toLowerCase().includes(filterText),
    );
  }
  if (filterAuthors.size > 0)
    filtered = filtered.filter((pr) => filterAuthors.has(pr.author));
  if (filterRepos.size > 0)
    filtered = filtered.filter((pr) =>
      filterRepos.has(`${pr.repo_owner}/${pr.repo_name}`),
    );
  if (filterCIs.size > 0) {
    filtered = filtered.filter((pr) => {
      const status = pr.ci_status?.toUpperCase() || "NONE";
      for (const ci of filterCIs) {
        if (ci === "NONE" && !pr.ci_status) return true;
        if (status === ci) return true;
      }
      return false;
    });
  }
  if (filterLabels.size > 0) {
    filtered = filtered.filter((pr) =>
      (pr.labels || []).some((l) => filterLabels.has(l.name)),
    );
  }
  if (filterReviews.size > 0) {
    filtered = filtered.filter((pr) => {
      const review = pr.review_decision?.toUpperCase() || "NONE";
      for (const r of filterReviews) {
        if (r === "NONE" && !pr.review_decision) return true;
        if (review === r) return true;
      }
      return false;
    });
  }
  return filtered;
}

function sortPRs(prs: PullRequest[]): PullRequest[] {
  const cmp = (a: PullRequest, b: PullRequest): number => {
    switch (sortColumn) {
      case "number":
        return a.number - b.number;
      case "author":
        return a.author.localeCompare(b.author);
      case "created":
        return (
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
      case "updated":
        return (
          new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime()
        );
      default:
        return 0;
    }
  };
  const sorted = [...prs].sort(cmp);
  return sortAsc ? sorted : sorted.reverse();
}

function renderStats(): void {
  const container = document.getElementById("dashboard-stats");
  if (!container) return;

  // Always compute counts from allPRs so cards stay meaningful as toggle buttons
  const stats: Array<{ key: string; cls: string; label: string }> = [
    { key: "total", cls: "stat-total", label: "Open PRs" },
    { key: "ready", cls: "stat-ready", label: "Ready to merge" },
    { key: "pass", cls: "stat-pass", label: "CI passing" },
    { key: "fail", cls: "stat-fail", label: "CI failing" },
    { key: "pending", cls: "stat-pending-stat", label: "CI pending" },
    { key: "mergeable", cls: "stat-mergeable", label: "No conflicts" },
    { key: "conflicts", cls: "stat-conflicts", label: "Conflicts" },
    { key: "approved", cls: "stat-approved", label: "Approved" },
    { key: "drafts", cls: "stat-drafts", label: "Drafts" },
  ];

  container.innerHTML = stats
    .map((s) => {
      const count = allPRs.filter((p) => matchesStat(p, s.key)).length;
      const active = activeStat === s.key ? " active" : "";
      return `<div class="stat-card ${s.cls}${active}" data-stat="${s.key}"><div class="stat-value">${count}</div><div class="stat-label">${s.label}</div></div>`;
    })
    .join("");

  container.querySelectorAll<HTMLElement>(".stat-card").forEach((card) => {
    card.addEventListener("click", () => {
      const key = card.dataset.stat!;
      activeStat = activeStat === key ? null : key;
      renderDashboard();
    });
  });
}

function renderDashboard(): void {
  const filtered = getFiltered();
  renderStats();
  updateBatchBar();

  const container = document.getElementById("pr-table-container");
  if (!container) return;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state"><p>No PRs match the current filters.</p></div>`;
    return;
  }

  if (groupBy === "none") {
    container.innerHTML = renderTable(sortPRs(filtered), null);
  } else {
    const groups = new Map<string, PullRequest[]>();
    for (const pr of filtered) {
      const key =
        groupBy === "repo" ? `${pr.repo_owner}/${pr.repo_name}` : pr.author;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(pr);
    }
    const sorted = [...groups.entries()].sort(
      (a, b) => b[1].length - a[1].length,
    );
    container.innerHTML = sorted
      .map(([label, prs]) => renderTable(sortPRs(prs), label))
      .join("");
  }

  // Attach event listeners
  container.querySelectorAll<HTMLInputElement>(".pr-checkbox").forEach((cb) => {
    cb.checked = selectedPRs.has(cb.value);
    cb.addEventListener("change", () => {
      if (cb.checked) selectedPRs.add(cb.value);
      else selectedPRs.delete(cb.value);
      updateBatchBar();
      // Update the group select-all checkboxes
      updateGroupCheckboxes(container);
    });
  });

  container
    .querySelectorAll<HTMLInputElement>(".group-select-all")
    .forEach((cb) => {
      cb.addEventListener("change", () => {
        const group = cb.getAttribute("data-group")!;
        const checkboxes = container.querySelectorAll<HTMLInputElement>(
          `.pr-checkbox[data-group="${group}"]`,
        );
        checkboxes.forEach((box) => {
          box.checked = cb.checked;
          if (cb.checked) selectedPRs.add(box.value);
          else selectedPRs.delete(box.value);
        });
        updateBatchBar();
      });
    });

  container.querySelectorAll<HTMLElement>(".pr-row-link").forEach((el) => {
    el.addEventListener("click", () => {
      navigateTo(
        `/pr/${el.dataset.owner}/${el.dataset.repo}/${el.dataset.number}`,
      );
    });
  });

  // Sort column handlers
  container.querySelectorAll<HTMLElement>(".sortable-th").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort as typeof sortColumn;
      if (sortColumn === col) {
        sortAsc = !sortAsc;
      } else {
        sortColumn = col;
        sortAsc = col === "author"; // alpha ascending by default, numbers descending
      }
      renderDashboard();
    });
  });

  // Inline quick action handlers
  container.querySelectorAll<HTMLElement>(".inline-merge").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const { owner, repo, number } = btn.dataset;
      btn.classList.add("working");
      try {
        const results = await mergePullRequests([
          { owner: owner!, repo: repo!, number: parseInt(number!) },
        ]);
        if (results[0] && !results[0].success)
          alert(`Merge failed: ${results[0].error}`);
        allPRs = await getPullRequests();
        renderDashboard();
      } catch (err) {
        alert(`Merge failed: ${err}`);
      }
    });
  });
  container.querySelectorAll<HTMLElement>(".inline-approve").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const { owner, repo, number } = btn.dataset;
      btn.classList.add("working");
      try {
        const results = await approvePullRequests([
          { owner: owner!, repo: repo!, number: parseInt(number!) },
        ]);
        if (results[0] && !results[0].success)
          alert(`Approve failed: ${results[0].error}`);
        allPRs = await getPullRequests();
        renderDashboard();
      } catch (err) {
        alert(`Approve failed: ${err}`);
      }
    });
  });
  container.querySelectorAll<HTMLElement>(".inline-close").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const { owner, repo, number } = btn.dataset;
      btn.classList.add("working");
      try {
        const results = await closePullRequests([
          { owner: owner!, repo: repo!, number: parseInt(number!) },
        ]);
        if (results[0] && !results[0].success)
          alert(`Close failed: ${results[0].error}`);
        allPRs = await getPullRequests();
        renderDashboard();
      } catch (err) {
        alert(`Close failed: ${err}`);
      }
    });
  });
  container.querySelectorAll<HTMLElement>(".inline-sync").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const { owner, repo, number } = btn.dataset;
      btn.classList.add("working");
      try {
        await syncPR(owner!, repo!, parseInt(number!));
        allPRs = await getPullRequests();
        renderDashboard();
      } catch (err) {
        alert(`Sync failed: ${err}`);
      }
    });
  });
  container.querySelectorAll<HTMLElement>(".group-sync-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const label = btn.dataset.groupLabel!;
      const slash = label.indexOf("/");
      const owner = label.substring(0, slash);
      const repo = label.substring(slash + 1);
      btn.classList.add("working");
      try {
        await syncRepo(owner, repo);
        allPRs = await getPullRequests();
        renderDashboard();
      } catch (err) {
        alert(`Repo sync failed: ${err}`);
      }
    });
  });
}

function sortIndicator(col: typeof sortColumn): string {
  if (sortColumn !== col) return "";
  return sortAsc ? " &#x25B4;" : " &#x25BE;";
}

function renderTable(prs: PullRequest[], groupLabel: string | null): string {
  const groupId = groupLabel ? groupLabel.replace(/[^a-zA-Z0-9]/g, "_") : "all";
  const header = groupLabel
    ? `<div class="group-header">
        <label class="group-select-label"><input type="checkbox" class="group-select-all" data-group="${esc(groupId)}" /> </label>
        <span class="group-name">${esc(groupLabel)}</span>
        <span class="group-count">${prs.length}</span>
        ${groupBy === "repo" ? `<button class="inline-btn group-sync-btn" data-group-label="${esc(groupLabel)}" title="Sync repo">&#x21bb;</button>` : ""}
       </div>`
    : "";

  const rows = prs
    .map((pr) => {
      const key = prKey(pr);
      const checked = selectedPRs.has(key) ? "checked" : "";
      const badges: string[] = [];
      if (pr.draft) badges.push(`<span class="badge badge-draft">Draft</span>`);
      badges.push(ciBadge(pr.ci_status));
      badges.push(mergeableBadge(pr.mergeable));
      badges.push(reviewBadge(pr.review_decision));
      const labelsHTML = (pr.labels || []).map(labelHTML).join(" ");
      const canMerge =
        pr.ci_status?.toUpperCase() === "SUCCESS" &&
        pr.mergeable?.toUpperCase() === "MERGEABLE" &&
        !pr.draft;
      const actions = `<span class="inline-actions"><button class="inline-btn inline-sync" data-owner="${esc(pr.repo_owner)}" data-repo="${esc(pr.repo_name)}" data-number="${pr.number}" title="Sync">&#x21bb;</button>${canMerge ? `<button class="inline-btn inline-merge" data-owner="${esc(pr.repo_owner)}" data-repo="${esc(pr.repo_name)}" data-number="${pr.number}" title="Merge">&#x2714;</button>` : ""}<button class="inline-btn inline-approve" data-owner="${esc(pr.repo_owner)}" data-repo="${esc(pr.repo_name)}" data-number="${pr.number}" title="Approve">&#x1F44D;</button><button class="inline-btn inline-close" data-owner="${esc(pr.repo_owner)}" data-repo="${esc(pr.repo_name)}" data-number="${pr.number}" title="Close">&#x2716;</button></span>`;

      return `<tr class="pr-row ${canMerge ? "pr-row-ready" : ""}">
      <td class="td-check"><input type="checkbox" class="pr-checkbox" value="${esc(key)}" data-group="${esc(groupId)}" data-owner="${esc(pr.repo_owner)}" data-repo="${esc(pr.repo_name)}" data-number="${pr.number}" ${checked} /></td>
      <td class="td-status">${badges.filter(Boolean).join(" ")}</td>
      <td class="td-title">
        <span class="pr-row-link" data-owner="${esc(pr.repo_owner)}" data-repo="${esc(pr.repo_name)}" data-number="${pr.number}">
          ${esc(pr.title)}
        </span>
        <span class="pr-row-ref">${groupBy !== "repo" ? esc(`${pr.repo_owner}/${pr.repo_name}`) + " " : ""}#${pr.number} ${esc(pr.head_ref || "")} &rarr; ${esc(pr.base_ref || "")}</span>
        ${labelsHTML ? `<span class="pr-row-labels">${labelsHTML}</span>` : ""}
      </td>
      <td class="td-author">
        ${pr.author_avatar ? `<img class="avatar-sm" src="${esc(pr.author_avatar)}&s=32" alt="" />` : ""}
        ${esc(pr.author)}
      </td>
      <td class="td-stats"><span class="stat-add">+${pr.additions}</span> <span class="stat-del">-${pr.deletions}</span></td>
      <td class="td-time" title="${esc(pr.created_at)}">${timeAgo(pr.created_at)}</td>
      <td class="td-time" title="${esc(pr.updated_at)}">${timeAgo(pr.updated_at)}</td>
      <td class="td-actions">${actions}</td>
    </tr>`;
    })
    .join("");

  return `
    ${header}
    <table class="pr-table">
      <thead>
        <tr>
          <th class="th-check"></th>
          <th class="th-status">Status</th>
          <th class="th-title sortable-th" data-sort="number">PR${sortIndicator("number")}</th>
          <th class="th-author sortable-th" data-sort="author">Author${sortIndicator("author")}</th>
          <th class="th-stats">Changes</th>
          <th class="th-time sortable-th" data-sort="created">Created${sortIndicator("created")}</th>
          <th class="th-time sortable-th" data-sort="updated">Updated${sortIndicator("updated")}</th>
          <th class="th-actions">Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function updateBatchBar(): void {
  const bar = document.getElementById("batch-bar");
  const countEl = document.getElementById("batch-count");
  if (!bar || !countEl) return;

  if (selectedPRs.size > 0) {
    bar.classList.remove("hidden");
    countEl.textContent = `${selectedPRs.size} selected`;

    // Enable merge only if all selected PRs are merge-ready
    const mergeBtn = document.getElementById(
      "batch-merge",
    ) as HTMLButtonElement;
    const allMergeable = getSelectedPRs().every(
      (pr) =>
        pr.ci_status?.toUpperCase() === "SUCCESS" &&
        pr.mergeable?.toUpperCase() === "MERGEABLE" &&
        !pr.draft,
    );
    mergeBtn.disabled = !allMergeable;
    mergeBtn.title = allMergeable
      ? "Merge all selected PRs"
      : "Some selected PRs have failing CI, conflicts, or are drafts";
  } else {
    bar.classList.add("hidden");
  }
}

function updateGroupCheckboxes(container: HTMLElement): void {
  container
    .querySelectorAll<HTMLInputElement>(".group-select-all")
    .forEach((cb) => {
      const group = cb.getAttribute("data-group")!;
      const boxes = container.querySelectorAll<HTMLInputElement>(
        `.pr-checkbox[data-group="${group}"]`,
      );
      const allChecked = boxes.length > 0 && [...boxes].every((b) => b.checked);
      cb.checked = allChecked;
      cb.indeterminate = !allChecked && [...boxes].some((b) => b.checked);
    });
}

function getSelectedPRs(): PullRequest[] {
  return allPRs.filter((pr) => selectedPRs.has(prKey(pr)));
}

async function handleBatchMerge(): Promise<void> {
  const selected = getSelectedPRs();
  const nonReady = selected.filter(
    (pr) =>
      pr.ci_status?.toUpperCase() !== "SUCCESS" ||
      pr.mergeable?.toUpperCase() !== "MERGEABLE" ||
      pr.draft,
  );
  if (nonReady.length > 0) return; // guard

  const targets = selected.map((pr) => ({
    owner: pr.repo_owner,
    repo: pr.repo_name,
    number: pr.number,
  }));
  const bar = document.getElementById("batch-bar")!;
  bar.classList.add("batch-working");
  try {
    const results = await mergePullRequests(targets);
    const failed = results.filter((r) => !r.success);
    if (failed.length > 0) {
      alert(
        `Merged ${results.length - failed.length} PRs. ${failed.length} failed:\n${failed.map((f) => f.error || "Unknown error").join("\n")}`,
      );
    }
    selectedPRs.clear();
    // Re-fetch PRs
    allPRs = await getPullRequests();
    renderDashboard();
  } catch (e) {
    alert(`Batch merge failed: ${e}`);
  } finally {
    bar.classList.remove("batch-working");
  }
}

async function handleBatchApprove(): Promise<void> {
  const selected = getSelectedPRs();
  const targets = selected.map((pr) => ({
    owner: pr.repo_owner,
    repo: pr.repo_name,
    number: pr.number,
  }));
  const bar = document.getElementById("batch-bar")!;
  bar.classList.add("batch-working");
  try {
    const results = await approvePullRequests(targets);
    const failed = results.filter((r) => !r.success);
    if (failed.length > 0) {
      alert(
        `Approved ${results.length - failed.length} PRs. ${failed.length} failed:\n${failed.map((f) => f.error || "Unknown error").join("\n")}`,
      );
    }
    selectedPRs.clear();
    allPRs = await getPullRequests();
    renderDashboard();
  } catch (e) {
    alert(`Batch approve failed: ${e}`);
  } finally {
    bar.classList.remove("batch-working");
  }
}

async function handleBatchClose(): Promise<void> {
  const selected = getSelectedPRs();
  const targets = selected.map((pr) => ({
    owner: pr.repo_owner,
    repo: pr.repo_name,
    number: pr.number,
  }));
  const bar = document.getElementById("batch-bar")!;
  bar.classList.add("batch-working");
  try {
    const results = await closePullRequests(targets);
    const failed = results.filter((r) => !r.success);
    if (failed.length > 0) {
      alert(
        `Closed ${results.length - failed.length} PRs. ${failed.length} failed:\n${failed.map((f) => f.error || "Unknown error").join("\n")}`,
      );
    }
    selectedPRs.clear();
    allPRs = await getPullRequests();
    renderDashboard();
  } catch (e) {
    alert(`Batch close failed: ${e}`);
  } finally {
    bar.classList.remove("batch-working");
  }
}
