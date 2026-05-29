import { test, expect } from "../../fixtures/test";

/** E2E suite: verifies that selecting a document-type filter sends the correct document_type in the WebSocket payload. */
test.describe("document type filters", () => {
  test("sends selected document_type with the WebSocket payload", async ({ page, baseURL }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator('.filter-btn[data-type="pdf"]').click();
    await expect(page.locator('.filter-btn[data-type="pdf"]')).toHaveClass(/active/);

    await page.locator("#query-input").fill("Filtered question");
    await page.locator("#send-btn").click();

    await expect(page.locator("#messages .message.user")).toContainText("Filtered question");

    const res = await page.request.get(`${baseURL}/__e2e/last-query`);
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as { last: { document_type?: string } | null };
    expect(body.last?.document_type).toBe("pdf");
  });

  test('All filter sends empty document_type', async ({ page, baseURL }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator('.filter-btn[data-type="sheet"]').click();
    await page.locator('.filter-btn[data-type=""]').click();
    await expect(page.locator('.filter-btn[data-type=""]')).toHaveClass(/active/);

    await page.locator("#query-input").fill("No filter");
    await page.locator("#send-btn").click();

    const res = await page.request.get(`${baseURL}/__e2e/last-query`);
    const body = (await res.json()) as { last: { document_type?: string } | null };
    // Empty filter is sent as undefined and omitted from JSON.stringify in the app.
    expect(body.last?.document_type).toBeUndefined();
  });
});
