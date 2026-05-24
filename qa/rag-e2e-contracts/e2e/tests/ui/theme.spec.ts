import { test, expect } from "../../fixtures/test";

test.describe("theme toggle", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem("rag_theme");
    });
  });

  test("toggles data-theme on body and persists to localStorage", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await expect(page.locator("body")).toHaveAttribute("data-theme", "dark");

    await page.locator("#theme-toggle").click();
    await expect(page.locator("body")).toHaveAttribute("data-theme", "light");

    await page.locator("#theme-toggle").click();
    await expect(page.locator("body")).toHaveAttribute("data-theme", "dark");

    const stored = await page.evaluate(() => localStorage.getItem("rag_theme"));
    expect(stored).toBe("dark");
  });
});
