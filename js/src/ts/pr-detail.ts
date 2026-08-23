import {
  getPRDetail,
  type PRDetail,
  type PRCheck,
  type PRCommit,
  type PRFile,
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

export async function renderPRDetail(
  container: HTMLElement,
  owner: string,
  repo: string,
  number: number,
): Promise<void> {
  container.innerHTML = `<div class="loading">Loading PR&hellip;</div>`;

  let pr: PRDetail;
  try {
    pr = await getPRDetail(owner, repo, number);
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><h3>Failed to load PR</h3><p>${esc(String(e))}</p></div>`;
    return;
  }

  const badges: string[] = [];
  if (pr.draft) badges.push(`<span class="badge badge-draft">Draft</span>`);
  badges.push(ciBadge(pr.ci_status));
  badges.push(mergeableBadge(pr.mergeable));
  badges.push(reviewBadge(pr.review_decision));

  const labelsHTML = (pr.labels || []).map(labelHTML).join(" ");

  container.innerHTML = `
    <button class="pr-detail-back" id="back-btn">&larr; All PRs</button>

    <div class="pr-detail-header">
      <div class="pr-detail-title">${esc(pr.title)}</div>
      <div class="pr-detail-subtitle">
        ${esc(owner)}/${esc(repo)}#${number}
        &middot; ${esc(pr.head_ref || "")} &rarr; ${esc(pr.base_ref || "")}
        &middot; <span class="pr-author">
          ${pr.author_avatar ? `<img src="${esc(pr.author_avatar)}&s=32" alt="" />` : ""}
          ${esc(pr.author)}
        </span>
        &middot; updated ${timeAgo(pr.updated_at)}
        &middot; <a class="external-link" href="${esc(pr.url)}" target="_blank" rel="noopener">View on GitHub &nearr;</a>
      </div>
      <div class="pr-detail-badges">
        ${badges.filter(Boolean).join(" ")} ${labelsHTML}
      </div>
      <div class="pr-stats" style="margin-top:8px">
        <span class="stat-add">+${pr.additions}</span>
        <span class="stat-del">-${pr.deletions}</span>
        <span class="stat-files">${pr.changed_files} file${pr.changed_files !== 1 ? "s" : ""}</span>
      </div>
    </div>

    ${renderChecksSection(pr.checks)}
    ${renderCommitsSection(pr.commits)}
    ${renderFilesSection(pr.files)}
  `;

  document
    .getElementById("back-btn")
    ?.addEventListener("click", () => navigateTo("/"));

  container.querySelectorAll(".file-header").forEach((header) => {
    header.addEventListener("click", () => {
      const patch = header.nextElementSibling as HTMLElement;
      if (patch) patch.classList.toggle("open");
    });
  });
}

function renderChecksSection(checks: PRCheck[]): string {
  if (!checks.length) return "";

  const passed = checks.filter((c) => c.conclusion === "success").length;
  const failed = checks.filter(
    (c) => c.conclusion === "failure" || c.conclusion === "action_required",
  ).length;
  const pending = checks.filter(
    (c) =>
      !c.conclusion ||
      c.conclusion === "neutral" ||
      c.status === "in_progress" ||
      c.status === "queued",
  ).length;

  return `
    <div class="section">
      <h3>Checks (${passed} passed, ${failed} failed, ${pending} pending)</h3>
      <div class="check-list">
        ${checks
          .map((c) => {
            let icon = "pending";
            let symbol = "&#x25cf;";
            if (c.conclusion === "success") {
              icon = "success";
              symbol = "&#x2713;";
            } else if (
              c.conclusion === "failure" ||
              c.conclusion === "action_required"
            ) {
              icon = "failure";
              symbol = "&#x2717;";
            }
            return `
            <div class="check-item">
              <span class="check-icon ${icon}">${symbol}</span>
              <span class="check-name">${esc(c.name)}</span>
              ${c.url ? `<a class="external-link" href="${esc(c.url)}" target="_blank" rel="noopener">&nearr;</a>` : ""}
            </div>
          `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function renderCommitsSection(commits: PRCommit[]): string {
  if (!commits.length) return "";
  return `
    <div class="section">
      <h3>Commits (${commits.length})</h3>
      <div class="commit-list">
        ${commits
          .map((c) => {
            const shortSha = c.sha.substring(0, 7);
            const firstLine = c.message.split("\n")[0];
            return `
            <div class="commit-item">
              <span class="commit-sha">${c.url ? `<a class="external-link" href="${esc(c.url)}" target="_blank" rel="noopener">${shortSha}</a>` : shortSha}</span>
              <span class="commit-msg">${esc(firstLine)}</span>
              ${c.author ? `<span class="commit-author">${esc(c.author)}</span>` : ""}
            </div>
          `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function renderFilesSection(files: PRFile[]): string {
  if (!files.length) return "";
  return `
    <div class="section">
      <h3>Files changed (${files.length})</h3>
      <div class="file-list">
        ${files
          .map((f) => {
            const statusClass = f.status ? `file-status-${f.status}` : "";
            const patchHTML = f.patch
              ? renderPatch(f.patch)
              : "<pre>(no diff available)</pre>";
            return `
            <div class="file-item">
              <div class="file-header">
                <span class="file-status ${statusClass}">${esc(f.status || "")}</span>
                <span class="file-name">${esc(f.filename)}</span>
                <span class="file-stats">
                  <span class="stat-add">+${f.additions}</span>
                  <span class="stat-del">-${f.deletions}</span>
                </span>
              </div>
              <div class="file-patch">${patchHTML}</div>
            </div>
          `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function renderPatch(patch: string): string {
  const lines = patch.split("\n");
  const htmlLines = lines.map((line) => {
    const escaped = esc(line);
    if (line.startsWith("@@"))
      return `<span class="diff-hunk">${escaped}</span>`;
    if (line.startsWith("+")) return `<span class="diff-add">${escaped}</span>`;
    if (line.startsWith("-")) return `<span class="diff-del">${escaped}</span>`;
    return escaped;
  });
  return `<pre>${htmlLines.join("\n")}</pre>`;
}
