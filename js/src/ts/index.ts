/** af1 — Main entry point. */

import { getMe, getConfig, triggerSync } from "./api.js";
import { renderIssueDetail } from "./issue-detail.js";
import { renderIssueList } from "./issue-list.js";
import { renderPRList } from "./pr-list.js";
import { renderPRDetail } from "./pr-detail.js";
import { registerRoute, handleRoute } from "./router.js";

// Register routes
registerRoute(/^\/$/, async (container) => {
  await renderPRList(container);
});

registerRoute(
  /^\/pr\/([^/]+)\/([^/]+)\/(\d+)$/,
  async (container, owner, repo, number) => {
    await renderPRDetail(container, owner, repo, parseInt(number, 10));
  },
);

registerRoute(/^\/issues$/, async (container) => {
  await renderIssueList(container);
});

registerRoute(
  /^\/issue\/([^/]+)\/([^/]+)\/(\d+)$/,
  async (container, owner, repo, number) => {
    await renderIssueDetail(container, owner, repo, parseInt(number, 10));
  },
);

function updateActiveNav(): void {
  const hash = window.location.hash.replace(/^#/, "") || "/";
  document.querySelectorAll<HTMLElement>(".nav-link").forEach((link) => {
    const view = link.dataset.view;
    const isActive =
      (view === "pr-list" && (hash === "/" || hash.startsWith("/pr/"))) ||
      (view === "issue-list" &&
        (hash === "/issues" || hash.startsWith("/issue/")));
    link.classList.toggle("active", isActive);
  });
}

// App initialization
async function init(): Promise<void> {
  const loading = document.getElementById("loading");

  // Load user info
  try {
    const user = await getMe();
    const userEl = document.getElementById("user-info");
    if (userEl) userEl.textContent = user.login;
  } catch {
    // Server may not be ready yet
  }

  // Sync button
  const syncBtn = document.getElementById("sync-btn");
  let syncing = false;

  async function doSync(): Promise<void> {
    if (syncing) return;
    syncing = true;
    syncBtn?.classList.add("syncing");
    try {
      await triggerSync();
      await handleRoute();
    } catch (e) {
      console.error("Sync failed:", e);
    } finally {
      syncing = false;
      syncBtn?.classList.remove("syncing");
    }
  }

  if (syncBtn) {
    syncBtn.addEventListener("click", doSync);
  }

  // Periodic background sync
  try {
    const config = await getConfig();
    const interval = config.sync_interval_seconds;
    if (interval && interval > 0) {
      setInterval(doSync, interval * 1000);
    }
  } catch {
    // Config unavailable — skip auto-sync
  }

  // Handle route changes
  window.addEventListener("hashchange", () => {
    updateActiveNav();
    handleRoute();
  });

  // Initial route
  if (loading) loading.classList.add("hidden");
  updateActiveNav();
  await handleRoute();
}

// Start
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
