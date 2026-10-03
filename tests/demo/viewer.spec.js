const { test, expect } = require("@playwright/test");

test("the opening explains the disagreement and shows recovery without another action", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator("main #hero-title")).toContainText(
    "Device recovery is",
  );
  await expect(page.locator("#case-title")).toHaveText(
    "The door opened. The reply didn’t.",
  );
  await expect(page.locator("#decision-title")).toHaveText(
    "Check before repeating.",
  );
  await expect(page.locator("#guided-result")).toHaveText(
    "Unconfirmed · 1 action",
  );
  for (const viewport of [
    { width: 1366, height: 900 },
    { width: 1366, height: 768 },
    { width: 1280, height: 720 },
    { width: 821, height: 870 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
    { width: 375, height: 812 },
  ]) {
    await page.setViewportSize(viewport);
    const action = await page.locator("#resolve").boundingBox();
    const physical = await page.locator("#physical").boundingBox();
    await expect(page.locator(".instrument-caption")).toBeVisible();
    expect(action.y + action.height).toBeLessThanOrEqual(viewport.height);
    expect(physical.y + physical.height).toBeLessThanOrEqual(viewport.height);
  }
  await page.locator("#resolve").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#state")).toHaveText("COMPLETED", {
    timeout: 12000,
  });
  await expect(page.locator("#guided-result")).toHaveText(
    "Confirmed · 1 action",
  );
  await expect(page.locator("#sends")).toHaveText("1");
  await expect(page.locator("#pulses")).toHaveText("1");
  await expect(page.locator("#decision-title")).toHaveText(
    "Confirmed. No second action.",
  );
  await expect(page.locator("#decision-evidence")).toHaveText(
    "Controller completion evidence received",
  );
  await page.locator('.scenarios [data-scenario="crash_after"]').click();
  await expect(page.locator("#case-title")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#resolve")).toBeFocused();
  await expect(page.locator("#guided-result")).toHaveText(
    "Inspection required · 1 action",
  );
  await expect(page.locator("#resolve")).toContainText("See why it stops");
  await expect(page.locator("#decision-title")).toHaveText(
    "The service must stop.",
  );
  await expect(page.locator("#hero-title")).toContainText("Device recovery is");
});

test("captured uncertainty and every recovery path remain inspectable", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator("#state")).toHaveText("UNCERTAIN");
  await expect(page.locator("#physical")).toHaveText("Open");
  await expect(page.locator("#pulses")).toHaveText("1");
  await expect(page.locator("#apparatus")).toHaveClass(/is-open/);
  await expect(page.locator("#decision-evidence")).toHaveText(
    "Completion has not been established",
  );
  await expect(page.locator(".notice")).toContainText("does not execute");
  await expect(page.locator('[data-pulses="crash_before"]')).toHaveText("0");
  await expect(page.locator('[data-pulses="crash_after"]')).toHaveText("1");
  for (const [scenario, pulses] of [
    ["crash_before", "0"],
    ["crash_after", "1"],
  ]) {
    await page.locator(`.scenarios [data-scenario="${scenario}"]`).click();
    await expect(page.locator("#state")).toHaveText("NEEDS INSPECTION");
    await expect(page.locator("#pulses")).toHaveText(pulses);
    await expect(
      page.locator('[data-kind="PHYSICAL_OUTCOME_UNRESOLVED"]'),
    ).toHaveCount(1);
  }
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
  if (process.env.CAPTURE_DEMO) {
    await page.evaluate(() => document.fonts.ready);
    await page
      .locator("#experiment")
      .screenshot({ path: "docs/experiment-workbench.png" });
    await page.screenshot({ path: "docs/recorded-viewer.png", fullPage: true });
    await page
      .locator("#boundary")
      .screenshot({ path: "docs/crash-boundary.png" });
  }
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Pause capture");
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("Play capture");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.scenarios [data-scenario="crash_after"]').click();
  await expect(page.locator("#state")).toHaveText("NEEDS INSPECTION");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("every workload pair is inspectable, including the slower four-worker run", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const report = require("../../demo/workload.json");
  await page.goto("/#workload");
  await expect(page.locator("#measurement-strip strong")).toHaveCount(3);
  for (const workload of ["clean", "mixed"]) {
    await page.locator("#workload-kind").selectOption(workload);
    for (const seed of [7, 23, 99]) {
      await page.locator("#workload-seed").selectOption(String(seed));
      for (let repetition = 0; repetition < 3; repetition++) {
        await page
          .locator("#workload-repetition")
          .selectOption({ value: String(repetition) });
        const pair = [1, 4].map((workers) =>
          report.trials.find(
            (t) =>
              t.workload === workload &&
              t.seed === seed &&
              t.repetition === repetition &&
              t.workers === workers,
          ),
        );
        await expect(
          page.locator("#measurement-strip strong").first(),
        ).toHaveText(
          pair.map((t) => t.batch_seconds.toFixed(3) + " s").join(" / "),
        );
        await expect(page.locator("#plot-caption")).toContainText(
          `Seed ${seed}, repetition ${repetition + 1}`,
        );
        await expect(page.locator("#workload-chart path")).toHaveCount(2);
      }
    }
  }
  await page.locator("#inspect-outlier").click();
  await expect(page.locator("#measurement-strip strong").first()).toHaveText(
    "5.857 s / 8.009 s",
  );
  await expect(page.locator("#workload-chart")).toHaveAttribute(
    "aria-label",
    /one worker 5.857 s; four workers 8.009 s/,
  );
  expect(errors).toEqual([]);
});

test("keyboard navigation and evidence remain usable at narrow and enlarged layouts", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip")).toBeFocused();
  await page.keyboard.press("Enter");
  await page.locator('.scenarios [data-scenario="healthy"]').focus();
  await page.keyboard.press("Enter");
  await page.locator("#frame").focus();
  await page.keyboard.press("Home");
  await expect(page.locator("#pulses")).toHaveText("0");
  await expect(page.locator("#apparatus")).not.toHaveClass(/is-open/);
  await page.keyboard.press("End");
  await expect(page.locator("#physical")).toHaveText("Open");
  // 720 CSS pixels also checks the reflow width of a 1440px window at 200% zoom.
  for (const width of [1440, 768, 720, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("#measurement-strip strong")).toHaveCount(3);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect
      .poll(
        async () =>
          (await page.locator("#workload-chart text").first().boundingBox())
            ?.height ?? 0,
      )
      .toBeGreaterThanOrEqual(10);
  }
});
