const { test, expect } = require("@playwright/test");

test("captured uncertainty and every recovery path remain inspectable", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator("#state")).toHaveText("UNCERTAIN");
  await expect(page.locator("#physical")).toHaveText("Open");
  await expect(page.locator("#pulses")).toHaveText("1");
  await expect(page.locator(".notice")).toContainText("does not execute");
  for (const scenario of ["healthy", "duplicate", "lost_ack", "disconnected"]) {
    await page.locator(`[data-scenario="${scenario}"]`).click();
    await page.locator("#frame").focus();
    await page.keyboard.press("End");
    await expect(page.locator("#state")).toHaveText("COMPLETED");
    await expect(page.locator("#pulses")).toHaveText("1");
    const expected = {
      healthy: "COMPLETION_CONFIRMED",
      duplicate: "DUPLICATE_SUPPRESSED",
      lost_ack: "RECONCILED",
      disconnected: "JOURNAL_ABSENT",
    }[scenario];
    await expect(page.locator(`[data-kind="${expected}"]`)).toHaveCount(1);
  }
  await page.locator('[data-scenario="lost_ack"]').click();
  if (process.env.CAPTURE_DEMO)
    await page.screenshot({ path: "docs/recorded-viewer.png", fullPage: true });
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Pause capture");
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Play capture");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
