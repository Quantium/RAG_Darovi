import { test, expect } from "../../fixtures/test";

test.describe("dashboard tab", () => {
  test("switches to Dashboard and shows RAW card metrics", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Dashboard" }).click();
    await expect(page.locator("#dash-card-raw h2")).toContainText("RAW");
    await expect(page.locator("#dash-metrics-raw")).toContainText(/MinIO RAW objects/i, {
      timeout: 15_000,
    });
  });
});
