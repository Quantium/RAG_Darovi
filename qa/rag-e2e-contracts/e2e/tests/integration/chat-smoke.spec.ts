import { test, expect } from "@playwright/test";

const realBase = process.env.E2E_REAL_BASE_URL;

test.describe("integration smoke", { tag: "@smoke" }, () => {
  test("chat shell loads against a running backend", async ({ browser }) => {
    test.skip(!realBase, "Set E2E_REAL_BASE_URL to run integration smoke tests (e.g. http://127.0.0.1:8000)");

    const context = await browser.newContext({ baseURL: realBase });
    const page = await context.newPage();
    await page.goto("/");
    await expect(page).toHaveTitle(/RAG Darovi/);
    await expect(page.locator("#messages .message.assistant").first()).toContainText(/Darovi/);
    await context.close();
  });
});
