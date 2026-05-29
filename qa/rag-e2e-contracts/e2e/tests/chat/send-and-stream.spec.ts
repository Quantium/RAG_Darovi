import { test, expect } from "../../fixtures/test";

/** E2E suite: verifies WebSocket streaming — query submission, token streaming, and send-button state. */
test.describe("send and stream", () => {
  test("submits a query, streams assistant tokens, re-enables send", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator("#query-input").fill("What is in the docs?");
    await page.locator("#send-btn").click();

    await expect(page.locator("#messages .message.user")).toContainText("What is in the docs?");
    await expect(page.locator("#query-input")).toHaveValue("");

    await expect(page.locator("#messages .message.assistant").last().locator(".bubble")).toContainText(
      "Hello Darovi",
      { timeout: 10_000 },
    );

    await expect(page.locator("#send-btn")).toBeEnabled();
  });

  test("disables send button while streaming", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#status-text")).toContainText(/Online/i, { timeout: 15_000 });

    await page.locator("#query-input").fill("__SLOW_TOKENS__");
    await page.locator("#send-btn").click();

    await expect(page.locator("#chat-input-status")).not.toHaveAttribute("hidden");
    await expect(page.locator("#chat-input-status")).toContainText("Thinking...");

    await expect(page.locator("#send-btn")).toBeDisabled();
    await expect(page.locator("#messages .message.assistant").last().locator(".bubble")).toContainText(
      "One Two Three",
      { timeout: 15_000 },
    );
    await expect(page.locator("#send-btn")).toBeEnabled();
    await expect(page.locator("#chat-input-status")).toBeHidden();
  });
});
