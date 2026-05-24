import { test, expect } from "../../fixtures/test";

test.describe("document status tab", () => {
  test("shows extracted documents and extraction status", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.getByRole("button", { name: "Document status" }).click();

    await expect(page.locator("#document-status-panel")).toBeVisible();
    await expect(page.locator("#document-status-table tbody tr")).toHaveCount(2);

    const rows = page.locator("#document-status-table tbody tr");
    await expect(rows.nth(0)).toContainText("Invoice-April.pdf");
    await expect(rows.nth(0)).toContainText("embedded");
    await expect(rows.nth(0)).toContainText("Yes");
    await expect(rows.nth(1)).toContainText("Contract-Draft.docx");
    await expect(rows.nth(1)).toContainText("failed");
    await expect(rows.nth(1)).toContainText("No");
    await expect(rows.nth(1)).toContainText("Extracted text object not found in storage.");
  });

  test("filters rows by missing raw text availability", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.getByRole("button", { name: "Document status" }).click();
    await expect(page.locator("#document-status-panel")).toBeVisible();
    await expect(page.locator("#document-status-table tbody tr")).toHaveCount(2);

    const statusFilters = page.getByRole("group", { name: "Document status filters" });
    await statusFilters.getByRole("button", { name: "Raw text missing" }).click();
    await expect(page.locator("#document-status-table tbody tr")).toHaveCount(1);
    await expect(page.locator("#document-status-table tbody tr").first()).toContainText("Contract-Draft.docx");
    await expect(page.locator("#document-status-table tbody tr").first()).toContainText("No");

    await statusFilters.getByRole("button", { name: "All" }).click();
    await expect(page.locator("#document-status-table tbody tr")).toHaveCount(2);
  });
});
