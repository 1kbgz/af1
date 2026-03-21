/** af1 — Render helper utilities. */

/** Escape HTML special characters. */
export function esc(s: string): string {
  const el = document.createElement("span");
  el.textContent = s;
  return el.innerHTML;
}

/** Format a relative time string, e.g. "3 hours ago". */
export function timeAgo(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

/** CI status to badge HTML. */
export function ciBadge(status: string | null): string {
  if (!status) return "";
  const s = status.toUpperCase();
  if (s === "SUCCESS")
    return `<span class="badge badge-success">&#x2713; CI passed</span>`;
  if (s === "FAILURE" || s === "ERROR")
    return `<span class="badge badge-failure">&#x2717; CI failed</span>`;
  if (s === "PENDING" || s === "EXPECTED")
    return `<span class="badge badge-pending">&#x25cf; CI pending</span>`;
  return `<span class="badge badge-pending">${esc(status)}</span>`;
}

/** Mergeable status to badge. */
export function mergeableBadge(mergeable: string | null): string {
  if (!mergeable) return "";
  const m = mergeable.toUpperCase();
  if (m === "MERGEABLE")
    return `<span class="badge badge-mergeable">&#x2713; No conflicts</span>`;
  if (m === "CONFLICTING")
    return `<span class="badge badge-conflict">&#x2717; Conflicts</span>`;
  if (m === "UNKNOWN")
    return `<span class="badge badge-pending">? Merge status unknown</span>`;
  return "";
}

/** Review decision to badge. */
export function reviewBadge(decision: string | null): string {
  if (!decision) return "";
  const d = decision.toUpperCase();
  if (d === "APPROVED")
    return `<span class="badge badge-success">&#x2713; Approved</span>`;
  if (d === "CHANGES_REQUESTED")
    return `<span class="badge badge-failure">&#x270e; Changes requested</span>`;
  if (d === "REVIEW_REQUIRED")
    return `<span class="badge badge-review">&#x25cb; Review required</span>`;
  return "";
}

/** Render a label. */
export function labelHTML(label: { name: string; color: string }): string {
  const bg = `#${label.color}`;
  // Compute text color based on luminance
  const r = parseInt(label.color.substring(0, 2), 16);
  const g = parseInt(label.color.substring(2, 4), 16);
  const b = parseInt(label.color.substring(4, 6), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  const fg = lum > 0.5 ? "#000" : "#fff";
  return `<span class="label-tag" style="background:${bg};color:${fg}">${esc(label.name)}</span>`;
}
