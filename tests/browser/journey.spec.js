const { test, expect } = require("@playwright/test");
const fs = require("node:fs/promises");
for (const scenario of ["healthy", "duplicate", "lost_ack", "disconnected"]) {
  test(`visitor can inspect ${scenario}`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await page.locator(`[data-scenario="${scenario}"]`).click();
    await page.getByRole("button", { name: "Request release" }).click();
    if (scenario === "lost_ack" && process.env.CAPTURE_DEMO) {
      await expect(page.locator("#service-state")).toHaveText("UNCERTAIN");
      await page
        .locator(".evidence-grid")
        .screenshot({ path: "docs/demo-uncertain.png" });
    }
    if (scenario === "disconnected") {
      await expect(page.locator("#service-state")).toHaveText("UNCERTAIN");
      await expect(page.locator("#pulses")).toHaveText("0");
      await page
        .getByRole("button", { name: "Reconnect device", exact: true })
        .click();
    }
    await expect(page.locator("#service-state")).toHaveText("COMPLETED", {
      timeout: 15000,
    });
    await expect(page.locator("#pulses")).toHaveText("1");
    await expect(
      page.locator('[data-kind="PHYSICAL_ACTION_PERFORMED"]'),
    ).toHaveCount(1);
    if (scenario === "duplicate")
      await expect(
        page.locator('[data-kind="DUPLICATE_SUPPRESSED"]'),
      ).toHaveCount(1);
    if (scenario === "lost_ack") {
      await expect(page.locator('[data-kind="OUTCOME_UNCERTAIN"]')).toHaveCount(
        1,
      );
      await expect(page.locator('[data-kind="RECONCILED"]')).toHaveCount(1);
      if (process.env.CAPTURE_DEMO)
        await page.screenshot({
          path: "docs/demo-lost-ack.png",
          fullPage: true,
        });
    }
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export evidence JSON" }).click();
    const file = await download;
    const evidence = JSON.parse(await fs.readFile(await file.path(), "utf8"));
    expect(file.suggestedFilename()).toBe(`recovery-${evidence.id}.json`);
    expect(evidence.state).toBe("COMPLETED");
    await page.reload();
    await expect(page.locator("#service-state")).toHaveText("COMPLETED");
    expect(errors).toEqual([]);
  });
}
test("narrow viewport has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Duplicate command" }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "Duplicate command" }),
  ).toHaveAttribute("aria-pressed", "true");
});
for (const [scenario, pulses] of [
  ["crash_before", "0"],
  ["crash_after", "1"],
]) {
  test(`actual process ${scenario} requires inspection without retry`, async ({
    page,
  }) => {
    await page.goto("/");
    await page.locator(`[data-scenario="${scenario}"]`).click();
    await page.getByRole("button", { name: "Request release" }).click();
    await expect(page.locator("#service-state")).toHaveText(
      "NEEDS INSPECTION",
      { timeout: 15000 },
    );
    await expect(page.locator("#pulses")).toHaveText(pulses);
    await expect(page.locator("#sends")).toHaveText("1");
    await expect(page.locator("#resume")).toBeHidden();
    await expect(
      page.locator('[data-kind="CONTROLLER_RESTARTED"]'),
    ).toHaveCount(1);
    const wait = page.waitForEvent("download");
    await page.locator("#export").click();
    const file = await wait;
    const evidence = JSON.parse(await fs.readFile(await file.path(), "utf8"));
    expect(evidence.state).toBe("NEEDS_INSPECTION");
    expect(evidence.device.pulses).toBe(Number(pulses));
    const resume = await page.request.post(`/api/runs/${evidence.id}/resume`, {
      data: {},
    });
    expect(resume.status()).toBe(409);
    await page.reload();
    await expect(page.locator("#service-state")).toHaveText("NEEDS INSPECTION");
    await expect(page.locator("#pulses")).toHaveText(pulses);
    await expect(page.locator("#sends")).toHaveText("1");
  });
}
test("changing runs disables export until matching evidence arrives", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Request release" }).click();
  await expect(page.locator("#service-state")).toHaveText("COMPLETED");
  const first = await page.locator("#history").inputValue();
  await page.getByRole("button", { name: "Request release" }).click();
  await expect(page.locator("#service-state")).toHaveText("COMPLETED");
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/runs/${first}`, async (route) => {
    await gate;
    await route.continue();
  });
  await page.locator("#history").selectOption(first);
  await expect(
    page.getByRole("button", { name: "Export evidence JSON" }),
  ).toBeDisabled();
  release();
  await expect(
    page.getByRole("button", { name: "Export evidence JSON" }),
  ).toBeEnabled();
  const wait = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export evidence JSON" }).click();
  const file = await wait;
  const evidence = JSON.parse(await fs.readFile(await file.path(), "utf8"));
  expect(evidence.id).toBe(first);
  expect(file.suggestedFilename()).toBe(`recovery-${first}.json`);
});
