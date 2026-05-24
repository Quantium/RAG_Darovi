import { test, expect } from "../../fixtures/test";

test.describe("app load", () => {
  test("shows title and initial assistant greeting", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/RAG Darovi/);
    await expect(page.locator("#messages .message.assistant").first()).toContainText(/Darovi/);
  });

  test("status becomes online after WebSocket connects", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });
  });

  test("status shows pipeline warning when failed count is non-zero", async ({ page, baseURL }) => {
    await page.request.post(`${baseURL}/__e2e/status-failed`, {
      data: JSON.stringify({ failed: 2 }),
      headers: { "Content-Type": "application/json" },
    });
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/2 failed/i, { timeout: 15_000 });
  });
});
