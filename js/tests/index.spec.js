import { test, expect } from "@playwright/test";

// The test server is seeded with 5 PRs:
// PR #142: acme/frontend - "Add dark mode toggle" (alice, SUCCESS, MERGEABLE, APPROVED)
// PR #143: acme/frontend - "Fix responsive layout" (bob, FAILURE, CONFLICTING, CHANGES_REQUESTED)
// PR #77:  acme/backend  - "Upgrade database migration" (alice, PENDING, MERGEABLE, Draft)
// PR #78:  acme/backend  - "Add rate limiting" (charlie, SUCCESS, MERGEABLE, APPROVED)
// PR #31:  acme/infra    - "Terraform module for staging" (bob, null CI, UNKNOWN, REVIEW_REQUIRED)

// Helper: wait for the dashboard to fully load (default groups by repo → 3 tables)
async function waitForDashboard(page) {
  await expect(page.locator(".pr-row").first()).toBeVisible({ timeout: 10000 });
}

test.describe("API Health", () => {
  test("health endpoint returns ok", async ({ request }) => {
    const resp = await request.get("/api/health");
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.status).toBe("ok");
    expect(data.version).toBeDefined();
  });

  test("config endpoint returns watched authors", async ({ request }) => {
    const resp = await request.get("/api/config");
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.watched_authors.length).toBeGreaterThanOrEqual(1);
  });

  test("prs endpoint returns seeded PRs", async ({ request }) => {
    const resp = await request.get("/api/prs");
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.length).toBe(5);
  });

  test("prs endpoint filters by author", async ({ request }) => {
    const resp = await request.get("/api/prs?authors=alice");
    const data = await resp.json();
    expect(data.length).toBe(2);
    expect(data.every((pr) => pr.author === "alice")).toBeTruthy();
  });

  test("pr detail endpoint returns full data", async ({ request }) => {
    const resp = await request.get("/api/prs/acme/frontend/142");
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.title).toBe("Add dark mode toggle to settings page");
    expect(data.commits.length).toBe(3);
    expect(data.files.length).toBe(3);
    expect(data.checks.length).toBe(3);
  });

  test("pr detail 404 for nonexistent PR", async ({ request }) => {
    const resp = await request.get("/api/prs/nonexistent/repo/999");
    expect(resp.status()).toBe(404);
  });
});

test.describe("Dashboard Page Load", () => {
  test("loads and shows header", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toHaveText("af1");
    await expect(page.locator("#app-nav")).toBeVisible();
    await expect(page.locator("#sync-btn")).toBeVisible();
  });

  test("displays loading then PR list", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
  });

  test("shows all 5 PRs in the table", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    const rows = page.locator(".pr-row");
    await expect(rows).toHaveCount(5);
  });
});

test.describe("Dashboard Stats", () => {
  test("displays summary stat cards", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".dashboard-stats")).toBeVisible({
      timeout: 10000,
    });
    const statCards = page.locator(".stat-card");
    await expect(statCards).toHaveCount(9);
  });

  test("stat values are correct", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".dashboard-stats")).toBeVisible({
      timeout: 10000,
    });

    // 5 open PRs total
    const totalCard = page.locator(".stat-total .stat-value");
    await expect(totalCard).toHaveText("5");

    // 2 ready to merge (PR#142 and PR#78: SUCCESS + MERGEABLE + not draft)
    const readyCard = page.locator(".stat-ready .stat-value");
    await expect(readyCard).toHaveText("2");

    // 1 draft
    const draftsCard = page.locator(".stat-drafts .stat-value");
    await expect(draftsCard).toHaveText("1");
  });
});

test.describe("Filtering", () => {
  test("search filter narrows results", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    const search = page.locator("#filter-search");
    await search.fill("dark mode");
    await expect(page.locator(".pr-row")).toHaveCount(1);
    await expect(page.locator(".pr-row").first()).toContainText(
      "dark mode toggle",
    );
  });

  test("search filter clears results", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    const search = page.locator("#filter-search");
    await search.fill("nonexistent");
    await expect(page.locator(".empty-state")).toBeVisible();

    await search.fill("");
    await expect(page.locator(".pr-row")).toHaveCount(5);
  });

  test("author multi-select filter works", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Open author dropdown
    await page.locator("#ms-author-btn").click();
    const dropdown = page.locator("#ms-author-dropdown");
    await expect(dropdown).toBeVisible();

    // Select "alice"
    const aliceCheckbox = dropdown.locator('input[value="alice"]');
    await aliceCheckbox.check();

    // Should show only alice's PRs (2)
    await expect(page.locator(".pr-row")).toHaveCount(2);
  });

  test("repo multi-select filter works", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#ms-repo-btn").click();
    const dropdown = page.locator("#ms-repo-dropdown");
    await expect(dropdown).toBeVisible();

    // Select "acme/backend"
    await dropdown.locator('input[value="acme/backend"]').check();

    // Should show 2 backend PRs
    await expect(page.locator(".pr-row")).toHaveCount(2);
  });

  test("CI status filter works", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#ms-ci-btn").click();
    const dropdown = page.locator("#ms-ci-dropdown");
    await expect(dropdown).toBeVisible();

    // Select "FAILURE"
    await dropdown.locator('input[value="FAILURE"]').check();

    // Only PR #143 has FAILURE status
    await expect(page.locator(".pr-row")).toHaveCount(1);
    await expect(page.locator(".pr-row").first()).toContainText(
      "responsive layout",
    );
  });

  test("dropdown closes on outside click", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#ms-author-btn").click();
    await expect(page.locator("#ms-author-dropdown")).toBeVisible();

    // Click outside
    await page.locator("body").click({ position: { x: 10, y: 10 } });
    await expect(page.locator("#ms-author-dropdown")).toBeHidden();
  });
});

test.describe("Grouping", () => {
  test("group by repo shows group headers", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Default is "group by repo"
    const headers = page.locator(".group-header");
    // 3 repos: acme/frontend, acme/backend, acme/infra
    await expect(headers).toHaveCount(3);
  });

  test("group by author shows author groups", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#group-by").selectOption("author");
    const headers = page.locator(".group-header");
    // 3 authors: alice, bob, charlie
    await expect(headers).toHaveCount(3);
  });

  test("no grouping shows single table", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator("#group-by").selectOption("none");
    const headers = page.locator(".group-header");
    await expect(headers).toHaveCount(0);
    await expect(page.locator(".pr-table")).toHaveCount(1);
  });
});

test.describe("Sorting", () => {
  test("clicking column header changes sort", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Switch to no grouping for easier testing
    await page.locator("#group-by").selectOption("none");

    // Click "Author" header to sort by author
    await page.locator('.sortable-th[data-sort="author"]').first().click();

    // First row should be alice (alphabetical ascending)
    const firstRow = page.locator(".pr-row").first();
    await expect(firstRow).toContainText("alice");
  });

  test("clicking same column toggles sort direction", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);
    await page.locator("#group-by").selectOption("none");

    // Click Author twice — first ascending, then descending
    const authorHeader = page
      .locator('.sortable-th[data-sort="author"]')
      .first();
    await authorHeader.click(); // ascending
    await authorHeader.click(); // descending

    const firstRow = page.locator(".pr-row").first();
    await expect(firstRow).toContainText("charlie");
  });
});

test.describe("Batch Selection", () => {
  test("selecting a PR shows batch bar", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Batch bar should be hidden initially
    await expect(page.locator("#batch-bar")).toBeHidden();

    // Check first PR checkbox
    const checkbox = page.locator(".pr-checkbox").first();
    await checkbox.check();

    // Batch bar should now be visible
    await expect(page.locator("#batch-bar")).toBeVisible();
    await expect(page.locator("#batch-count")).toContainText("1 selected");
  });

  test("clear selection hides batch bar", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    await page.locator(".pr-checkbox").first().check();
    await expect(page.locator("#batch-bar")).toBeVisible();

    await page.locator("#batch-clear").click();
    await expect(page.locator("#batch-bar")).toBeHidden();
  });

  test("group select-all checks all in group", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Click the first group's select-all checkbox
    const groupSelectAll = page.locator(".group-select-all").first();
    await groupSelectAll.check();

    // Should select all PRs in that group
    const batchCount = page.locator("#batch-count");
    const countText = await batchCount.textContent();
    expect(parseInt(countText)).toBeGreaterThan(0);
  });
});

test.describe("PR Detail Navigation", () => {
  test("clicking a PR title navigates to detail view", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Click the first PR row link
    await page.locator(".pr-row-link").first().click();

    // Should navigate to PR detail
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 5000,
    });
  });

  test("PR detail shows title and metadata", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator(".pr-detail-title")).toContainText(
      "dark mode toggle",
    );
    await expect(page.locator(".pr-detail-subtitle")).toContainText(
      "acme/frontend#142",
    );
  });

  test("PR detail shows commits", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".commit-list")).toBeVisible({ timeout: 10000 });
    const commits = page.locator(".commit-item");
    await expect(commits).toHaveCount(3);
  });

  test("PR detail shows files", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".file-list")).toBeVisible({ timeout: 10000 });
    const files = page.locator(".file-item");
    await expect(files).toHaveCount(3);
  });

  test("PR detail shows checks", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".check-list")).toBeVisible({ timeout: 10000 });
    const checks = page.locator(".check-item");
    await expect(checks).toHaveCount(3);
  });

  test("PR detail shows badges", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".pr-detail-badges")).toBeVisible({
      timeout: 10000,
    });
    // Should have CI passed, No conflicts, Approved badges
    await expect(page.locator(".badge-success")).toHaveCount(2); // CI + review
    await expect(page.locator(".badge-mergeable")).toHaveCount(1);
  });

  test("PR detail shows labels", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".pr-detail-badges")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator(".label-tag")).toHaveCount(2);
  });

  test("back button returns to PR list", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 10000,
    });

    await page.locator("#back-btn").click();
    await waitForDashboard(page);
  });

  test("PR detail for PR with failing CI shows failure badges", async ({
    page,
  }) => {
    await page.goto("/#/pr/acme/frontend/143");
    await expect(page.locator(".pr-detail-badges")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator(".badge-failure")).toHaveCount(2); // CI + changes requested
    await expect(page.locator(".badge-conflict")).toHaveCount(1);
  });

  test("PR detail for draft shows draft badge", async ({ page }) => {
    await page.goto("/#/pr/acme/backend/77");
    await expect(page.locator(".pr-detail-badges")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator(".badge-draft")).toHaveCount(1);
  });

  test("file diff expand/collapse works", async ({ page }) => {
    await page.goto("/#/pr/acme/frontend/142");
    await expect(page.locator(".file-list")).toBeVisible({ timeout: 10000 });

    const firstHeader = page.locator(".file-header").first();
    const firstPatch = page.locator(".file-patch").first();

    // Click to toggle
    await firstHeader.click();
    const hasOpenClass = await firstPatch.evaluate((el) =>
      el.classList.contains("open"),
    );
    expect(hasOpenClass).toBeTruthy();

    // Click again to collapse
    await firstHeader.click();
    const stillOpen = await firstPatch.evaluate((el) =>
      el.classList.contains("open"),
    );
    expect(stillOpen).toBeFalsy();
  });
});

test.describe("Hash Routing", () => {
  test("navigating directly to PR detail via hash", async ({ page }) => {
    await page.goto("/#/pr/acme/backend/78");
    await expect(page.locator(".pr-detail-title")).toContainText(
      "rate limiting",
      { timeout: 10000 },
    );
  });

  test("navigating to root shows PR list", async ({ page }) => {
    await page.goto("/#/");
    await waitForDashboard(page);
  });

  test("hash change triggers route update", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Navigate via hash
    await page.evaluate(() => (window.location.hash = "/pr/acme/frontend/142"));
    await expect(page.locator(".pr-detail-header")).toBeVisible({
      timeout: 5000,
    });
  });
});

test.describe("PR Table Content", () => {
  test("PR rows show badges correctly", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // CI badges should be present in rows
    await expect(page.locator(".pr-row .badge-success").first()).toBeVisible();
    await expect(page.locator(".pr-row .badge-failure").first()).toBeVisible();
  });

  test("PR rows show additions and deletions", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Should have stat-add and stat-del spans in rows
    await expect(page.locator(".pr-row .stat-add").first()).toBeVisible();
    await expect(page.locator(".pr-row .stat-del").first()).toBeVisible();
  });

  test("PR rows show time ago", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // Time cells should contain some time-ago text
    const timeCells = page.locator(".td-time");
    const count = await timeCells.count();
    expect(count).toBeGreaterThan(0);
  });

  test("labels are displayed in PR rows", async ({ page }) => {
    await page.goto("/");
    await waitForDashboard(page);

    // At least some rows should have labels
    const labels = page.locator(".pr-row .label-tag");
    const count = await labels.count();
    expect(count).toBeGreaterThan(0);
  });
});
