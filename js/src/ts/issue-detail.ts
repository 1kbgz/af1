import { getIssueDetail, type Issue } from "./api.js";
import { esc, timeAgo, labelHTML } from "./render.js";
import { navigateTo } from "./router.js";

export async function renderIssueDetail(
  container: HTMLElement,
  owner: string,
  repo: string,
  number: number,
): Promise<void> {
  container.innerHTML = `<div class="loading">Loading issue&hellip;</div>`;

  let issue: Issue;
  try {
    issue = await getIssueDetail(owner, repo, number);
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><h3>Failed to load issue</h3><p>${esc(String(e))}</p></div>`;
    return;
  }

  const labelsHTML = (issue.labels || []).map(labelHTML).join(" ");
  const assigneesHTML =
    (issue.assignees || []).map((a) => esc(a)).join(", ") || "Unassigned";

  container.innerHTML = `
    <button class="pr-detail-back" id="back-btn">&larr; All Issues</button>

    <div class="pr-detail-header">
      <div class="pr-detail-title">${esc(issue.title)}</div>
      <div class="pr-detail-subtitle">
        ${esc(owner)}/${esc(repo)}#${number}
        &middot; <span class="pr-author">
          ${issue.author_avatar ? `<img src="${esc(issue.author_avatar)}&s=32" alt="" />` : ""}
          ${esc(issue.author)}
        </span>
        &middot; updated ${timeAgo(issue.updated_at)}
        &middot; <a class="external-link" href="${esc(issue.url)}" target="_blank" rel="noopener">View on GitHub &nearr;</a>
      </div>
      <div class="pr-detail-badges">
        ${labelsHTML}
      </div>
      <div class="pr-stats" style="margin-top:8px">
        <span>Assignees: ${assigneesHTML}</span>
        &middot;
        <span>&#x1F4AC; ${issue.comment_count} comment${issue.comment_count !== 1 ? "s" : ""}</span>
      </div>
    </div>

    ${issue.body ? `<div class="section"><h3>Description</h3><div class="issue-body">${esc(issue.body)}</div></div>` : ""}
  `;

  document
    .getElementById("back-btn")
    ?.addEventListener("click", () => navigateTo("/issues"));
}
