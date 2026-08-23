import { test, expect } from "@playwright/test";

// Visual regression tests using Playwright's screenshot comparison.
// Run `pnpm test --update-snapshots` to generate/update baseline images.

async function waitForDashboard(page) {
  await expect(page.locator(".pr-row").first()).toBeVisible({ timeout: 10000 });
}

test.describe("Visual — Dashboard", () => {
  test("full dashboard with all PRs", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    await expect(page.locator(".dashboard-stats .stat-card")).toHaveCount(9);
    await page.waitForTimeout(300); // settle animations
    await expect(page).toHaveScreenshot("dashboard-full.png", {
      fullPage: true,
    });
  });

  test("dashboard stat cards", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    await expect(page.locator(".dashboard-stats .stat-card")).toHaveCount(9);
    await expect(page.locator(".dashboard-stats")).toHaveScreenshot(
      "stat-cards.png",
    );
  });

  test("filter bar area", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    await expect(page.locator(".filter-bar")).toHaveScreenshot(
      "filter-bar.png",
    );
  });

  test("PR table rows", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    await expect(page.locator(".pr-table").first()).toHaveScreenshot(
      "pr-table-first-group.png",
    );
  });

  test("group headers", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    await expect(page.locator(".group-header").first()).toHaveScreenshot(
      "group-header.png",
    );
  });
});

test.describe("Visual — PR Detail", () => {
  test("PR detail page — passing PR", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 10000,
    });
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("pr-detail-passing.png", {
      fullPage: true,
    });
  });

  test("PR detail page — failing PR with conflicts", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/143");
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 10000,
    });
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("pr-detail-failing.png", {
      fullPage: true,
    });
  });

  test("PR detail page — draft PR", async ({ page }) => {
    await page.goto("/#/pr/acme/backend/77");
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 10000,
    });
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("pr-detail-draft.png", {
      fullPage: true,
    });
  });

  test("PR detail badges area", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".pr-detail-badges")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator(".pr-detail-badges")).toHaveScreenshot(
      "pr-detail-badges-passing.png",
    );
  });

  test("checks section", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".check-list")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".check-list")).toHaveScreenshot(
      "check-list.png",
    );
  });

  test("commits section", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".commit-list")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".commit-list")).toHaveScreenshot(
      "commit-list.png",
    );
  });

  test("files section collapsed", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".file-list")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".file-list")).toHaveScreenshot(
      "file-list-collapsed.png",
    );
  });

  test("file diff expanded", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".file-list")).toBeVisible({ timeout: 10000 });

    await page.locator(".file-header").first().click();
    await expect(page.locator(".file-patch.open")).toBeVisible();

    await expect(page.locator(".file-item").first()).toHaveScreenshot(
      "file-diff-expanded.png",
    );
  });
});

test.describe("Visual — Filter States", () => {
  test("author dropdown open", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#ms-author-btn").click();
    await expect(page.locator("#ms-author-dropdown")).toBeVisible();

    await expect(page.locator("#ms-author-ms")).toHaveScreenshot(
      "author-dropdown-open.png",
    );
  });

  test("filtered results with search", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#filter-search").fill("dark mode");
    await expect(page.locator(".pr-row")).toHaveCount(1);
    await page.waitForTimeout(200);

    await expect(page.locator("#pr-table-container")).toHaveScreenshot(
      "filtered-search-results.png",
    );
  });

  test("empty state when no results", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#filter-search").fill("nonexistent query xyz");
    await expect(page.locator(".empty-state")).toBeVisible();

    await expect(page.locator("#pr-table-container")).toHaveScreenshot(
      "empty-state-no-results.png",
    );
  });

  test("grouped by author", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#group-by").selectOption("author");
    await page.waitForTimeout(200);

    await expect(page).toHaveScreenshot("grouped-by-author.png", {
      fullPage: true,
    });
  });

  test("no grouping flat view", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#group-by").selectOption("none");
    await page.waitForTimeout(200);

    await expect(page).toHaveScreenshot("no-grouping-flat.png", {
      fullPage: true,
    });
  });
});

test.describe("Visual — Batch Bar", () => {
  test("batch bar visible with selections", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator(".pr-checkbox").first().check();
    await expect(page.locator("#batch-bar")).toBeVisible();

    await expect(page.locator("#batch-bar")).toHaveScreenshot(
      "batch-bar-visible.png",
    );
  });
});

test.describe("Visual — Header", () => {
  test("application header", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#app-header")).toBeVisible();
    await expect(page.locator("#app-header")).toHaveScreenshot(
      "app-header.png",
    );
  });
});
