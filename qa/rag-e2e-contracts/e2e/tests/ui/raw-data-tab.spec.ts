import { test, expect } from "../../fixtures/test";

test.describe("raw data tab", () => {
  test("shows extracted document data", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.getByRole("button", { name: "RAW Data" }).click();

    await expect(page.locator("#raw-data-panel")).toBeVisible();
    await expect(page.locator("#raw-data-table tbody tr")).toHaveCount(2);

    const rows = page.locator("#raw-data-table tbody tr");
    await expect(rows.nth(0)).toContainText("Invoice-April.pdf");
    await expect(rows.nth(0)).toContainText("Extracted invoice text from OCR");
    await expect(rows.nth(1)).toContainText("Contract-Draft.docx");
    await expect(rows.nth(1)).toContainText("No extracted text available yet.");
  });

  test("expands and collapses long extracted text", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.getByRole("button", { name: "RAW Data" }).click();
    await expect(page.locator("#raw-data-panel")).toBeVisible();

    const toggle = page.locator("#raw-data-table tbody tr").first().locator(".raw-data-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveText("Show more");

    const preview = page.locator("#raw-data-table tbody tr").first().locator(".raw-data-preview");
    await expect(preview).toHaveClass(/is-collapsed/);

    await toggle.click();
    await expect(toggle).toHaveText("Show less");
    await expect(preview).toHaveClass(/is-expanded/);

    await toggle.click();
    await expect(toggle).toHaveText("Show more");
    await expect(preview).toHaveClass(/is-collapsed/);
  });
});
