import { test, expect } from "../../fixtures/test";

/** E2E suite: verifies tab switching shows the correct panels and that table sort and pagination work correctly. */
test.describe("table tabs visibility and controls", () => {
  test("hides dashboard when Document status tab is active", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });
    await expect(page.locator("#dashboard-panel")).toBeVisible();

    await page.getByRole("button", { name: "Document status" }).click();
    await expect(page.locator("#document-status-panel")).toBeVisible();
    await expect(page.locator("#dashboard-panel")).toBeHidden();
    await expect(page.locator("#raw-data-panel")).toBeHidden();
  });

  test("hides dashboard when RAW Data tab is active", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.getByRole("button", { name: "RAW Data" }).click();
    await expect(page.locator("#raw-data-panel")).toBeVisible();
    await expect(page.locator("#dashboard-panel")).toBeHidden();
  });

  test("sorts document status by name ascending and descending", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });
    await page.getByRole("button", { name: "Document status" }).click();
    await expect(page.locator("#document-status-table tbody tr")).toHaveCount(2);

    const docHeader = page.locator("#document-status-table .sortable-th[data-sort-key='name'] .th-sort-btn");
    await docHeader.click();
    await expect(page.locator("#document-status-table tbody tr").first()).toContainText("Contract-Draft.docx");

    await docHeader.click();
    await expect(page.locator("#document-status-table tbody tr").first()).toContainText("Invoice-April.pdf");
  });

  test("shows pagination info for document status", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });
    await page.getByRole("button", { name: "Document status" }).click();

    await expect(page.locator("#document-status-page-info")).toContainText(/Showing 1–2 of 2/i);
    await page.selectOption("#document-status-page-size", "10");
    await expect(page.locator("#document-status-page-info")).toContainText(/page 1 of 1/i);
  });
});
