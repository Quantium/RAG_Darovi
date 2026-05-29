import { test, expect } from "../../fixtures/test";

/** E2E suite: verifies that source reference cards are rendered after the assistant's done message. */
test.describe("sources", () => {
  test("renders source cards after done message", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator("#query-input").fill("Show me sources");
    await page.locator("#send-btn").click();

    await expect(page.locator(".sources .source-card")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".source-card")).toContainText("Sample.pdf");
    await expect(page.locator(".source-card")).toContainText("91%");
  });
});
