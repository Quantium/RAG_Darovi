import { test, expect } from "../../fixtures/test";

test.describe("websocket error", () => {
  test("shows error text in assistant bubble", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator("#query-input").fill("__WS_ERROR__");
    await page.locator("#send-btn").click();

    await expect(page.locator("#chat-input-status")).toContainText("Error");
    await expect(page.locator("#chat-input-status")).toContainText("Mock WebSocket failure");

    await expect(page.locator("#messages .message.assistant").last().locator(".bubble")).toContainText(
      /Error:\s*Mock WebSocket failure/,
      { timeout: 10_000 },
    );
  });
});
