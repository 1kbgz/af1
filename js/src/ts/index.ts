/** af1 — Main entry point. */

import { getMe, getConfig, triggerSync } from "./api.js";
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
    handleRoute();
  });

  // Initial route
  if (loading) loading.classList.add("hidden");
  await handleRoute();
}

// Start
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
