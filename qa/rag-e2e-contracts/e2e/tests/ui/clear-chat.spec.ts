import { test, expect } from "../../fixtures/test";

/** E2E suite: verifies clearing the chat history resets the message list and allows subsequent messages. */
test.describe("clear chat", () => {
  test("resets messages and shows greeting; allows new messages", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator("#query-input").fill("First question");
    await page.locator("#send-btn").click();
    await expect(page.locator("#messages .message.user")).toHaveCount(1);

    await page.locator("#clear-chat").click();

    await expect(page.locator("#messages .message.assistant")).toHaveCount(1);
    await expect(page.locator("#messages .message.assistant").first()).toContainText(/History cleared/);

    await page.locator("#query-input").fill("After clear");
    await page.locator("#send-btn").click();
    await expect(page.locator("#messages .message.user")).toContainText("After clear");
  });
});
