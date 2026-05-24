import { test as base, expect } from "@playwright/test";

/**
 * Resets mock server state before each test (last query + status overrides).
 */
export const test = base.extend({
  page: async ({ page, baseURL }, use) => {
    await page.request.post(`${baseURL}/__e2e/reset`);
    await use(page);
  },
});

export { expect };
