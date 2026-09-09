import { expect, test } from "@playwright/test";

async function activate(locator, testInfo) {
  if (testInfo.project.name === "mobile-touch") {
    await locator.tap();
  } else {
    await locator.click();
  }
}

async function choose(page, label, option, testInfo) {
  const combobox = page.getByRole("combobox", { name: new RegExp(label) });
  if (testInfo.project.name === "mobile-touch") {
    await activate(combobox, testInfo);
  } else {
    await combobox.focus();
    await combobox.press("ArrowDown");
  }
  await activate(page.getByRole("option", { name: option, exact: true }), testInfo);
  await expect.poll(async () => selectedChoice(combobox)).toBe(option);
}

async function selectedChoice(combobox) {
  const value = await combobox.inputValue();
  if (value) {
    return value;
  }
  const label = await combobox.getAttribute("aria-label");
  return label?.match(/^Selected (.*?)\./)?.[1] ?? null;
}

async function downloadText(download) {
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

test("issues #1, #3, and #19 keep the complete game-day outcome visible and current", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await page.goto("/");
  const optimize = page.getByRole("button", { name: "Optimize seven innings" });
  await expect(optimize).toBeEnabled();
  await activate(optimize, testInfo);

  const status = page.locator('.optimization-status[role="status"]');
  const dancer = page.locator(".optimization-dancer");
  await expect(dancer).toBeVisible({ timeout: 10_000 });
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status).toHaveAttribute("aria-atomic", "true");
  await expect(status).toHaveText(/\S/);
  await expect(dancer).toHaveAttribute("aria-hidden", "true");
  await expect(dancer).toHaveAttribute("data-facing", "right");
  await expect(dancer).toHaveAttribute("data-motion", "moon-dance");
  await expect(dancer.locator("svg")).toHaveAttribute("focusable", "false");
  expect(await status.evaluate((statusElement, dancerElement) => Boolean(
    statusElement.compareDocumentPosition(dancerElement)
      & Node.DOCUMENT_POSITION_FOLLOWING
  ), await dancer.elementHandle())).toBe(true);
  const statusBox = await status.boundingBox();
  const dancerBox = await dancer.boundingBox();
  expect(dancerBox.y).toBeGreaterThanOrEqual(statusBox.y + statusBox.height);
  expect(await dancer.locator(".optimization-dancer__figure").evaluate(
    (figure) => getComputedStyle(figure).animationName,
  )).toBe("none");
  expect(await dancer.locator(".optimization-dancer__body").evaluate(
    (body) => getComputedStyle(body).animationName,
  )).toBe("softball-moon-body");
  expect(await dancer.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      height: style.height,
      overflow: style.overflow,
      width: style.width,
    };
  })).toEqual({ height: "84px", overflow: "hidden", width: "128px" });
  const footCycles = await dancer.locator(
    ".optimization-dancer__foot--front, .optimization-dancer__foot--rear",
  ).evaluateAll((feet) => feet.map((foot) => ({
    animationName: getComputedStyle(foot).animationName,
    keyframes: foot.getAnimations()[0].effect.getKeyframes(),
  })));
  expect(footCycles.map((cycle) => cycle.animationName)).toEqual([
    "softball-moon-foot-rear",
    "softball-moon-foot-front",
  ]);
  for (const cycle of footCycles) {
    expect(cycle.keyframes).toHaveLength(5);
    expect(new Set(cycle.keyframes.map((frame) => frame.transform)).size).toBeGreaterThan(2);
    expect(cycle.keyframes.every(
      (frame) => /matrix|translateX/.test(frame.transform),
    )).toBe(true);
  }
  expect(footCycles[0].keyframes[0].transform).not.toBe(
    footCycles[1].keyframes[0].transform,
  );

  const resultHeading = page.getByRole("heading", { name: "Optimized lineup" });
  await expect(resultHeading).toBeVisible({ timeout: 30_000 });
  await expect(dancer).toBeHidden();
  await expect(status).toBeHidden();
  await expect(page.getByText(
    /^(Optimal|Feasible): Legal, authoritative lineup for the current inputs\./,
  )).toBeVisible();
  const identityText = await page.getByText(
    /Here For The Beer.*Created.*Snapshot [a-f0-9]{8}/,
  ).textContent();
  const snapshotId = identityText.match(/Snapshot ([a-f0-9]{8})/)[1];
  const detailsHeading = page.getByRole("heading", {
    name: "Player details & preferences",
  });
  await expect(detailsHeading).toBeVisible();
  expect(await resultHeading.evaluate((result, details) => Boolean(
    result.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING
  ), await detailsHeading.elementHandle())).toBe(true);

  await expect(page.getByRole("combobox", { name: /Lineup view/ })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: /^Inning$/ })).toHaveCount(0);
  const lineup = page.getByRole("table", { name: "Seven-inning lineup" });
  await expect(lineup).toBeVisible();
  await expect(lineup.getByRole("row")).toHaveCount(8);
  await expect(lineup.getByRole("columnheader")).toHaveText([
    "Inning", "P", "C", "1B", "2B", "3B", "SS", "LF", "LC", "RC", "RF", "Bench",
  ]);
  if (testInfo.project.name === "mobile-touch") {
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
  }

  const downloadPromise = page.waitForEvent("download");
  await activate(
    page.getByRole("button", { name: "Download full lineup CSV" }),
    testInfo,
  );
  const download = await downloadPromise;
  const filename = download.suggestedFilename();
  expect(filename).toMatch(
    /^here-for-the-beer_coed_\d{8}T\d{6}Z_[a-f0-9]{8}\.csv$/,
  );
  expect(filename).toContain(snapshotId);
  expect(await download.failure()).toBeNull();
  const csv = await downloadText(download);
  const csvLines = csv.trim().split(/\r?\n/);
  expect(csvLines).toHaveLength(8);
  expect(csvLines[0]).toBe("Inning,P,C,1B,2B,3B,SS,LF,LC,RC,RF,Out");
  const repeatedDownloadPromise = page.waitForEvent("download");
  await activate(
    page.getByRole("button", { name: "Download full lineup CSV" }),
    testInfo,
  );
  const repeatedDownload = await repeatedDownloadPromise;
  expect(repeatedDownload.suggestedFilename()).toBe(filename);
  expect(await downloadText(repeatedDownload)).toBe(csv);

  const andrew = page.getByRole("checkbox", { name: "Andrew", exact: true });
  await activate(andrew.locator("xpath=ancestor::label"), testInfo);
  await expect(andrew).not.toBeChecked();
  await expect(resultHeading).toBeHidden();
  await expect(page.getByText("Inputs changed — optimize again.")).toBeVisible();

  await activate(
    page.getByRole("button", { name: "Clear all women", exact: true }),
    testInfo,
  );
  await expect(optimize).toBeDisabled();
  await expect(page.getByText(/At least 3 available women are required/)).toBeVisible();

  await choose(
    page,
    "League rules",
    "Open (no gender fielding minimums)",
    testInfo,
  );
  await expect(page.getByText(/Active profile:.*Open/)).toBeVisible();
  await expect(page.getByText(/At least 3 available women are required/)).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Clear all women", exact: true }),
  ).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Select all men", exact: true }),
  ).toBeHidden();
  const clearAllPlayers = page.getByRole("button", {
    name: "Clear all players",
    exact: true,
  });
  const selectAllPlayers = page.getByRole("button", {
    name: "Select all players",
    exact: true,
  });
  await expect(clearAllPlayers).toBeVisible();
  await expect(selectAllPlayers).toBeVisible();
  expect((await clearAllPlayers.boundingBox()).height).toBeGreaterThanOrEqual(44);
  expect((await selectAllPlayers.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await expect(andrew).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Ashley", exact: true }),
  ).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Brian", exact: true }),
  ).toBeChecked();

  await choose(page, "League rules", "Co-ed", testInfo);
  await expect(andrew).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Ashley", exact: true }),
  ).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Brian", exact: true }),
  ).toBeChecked();
  await choose(
    page,
    "League rules",
    "Open (no gender fielding minimums)",
    testInfo,
  );

  await activate(clearAllPlayers, testInfo);
  await expect(
    page.getByText("0 available players", { exact: true }),
  ).toBeVisible();
  await expect(andrew).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Ashley", exact: true }),
  ).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Brian", exact: true }),
  ).not.toBeChecked();
  await expect(optimize).toBeDisabled();
  await expect(page.getByText(/At least 8 available players are required/)).toBeVisible();
  await expect(page.getByText(/available women are required/)).toBeHidden();

  await activate(selectAllPlayers, testInfo);
  await expect(
    page.getByText("15 available players", { exact: true }),
  ).toBeVisible();
  await expect(andrew).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Ashley", exact: true }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Brian", exact: true }),
  ).toBeChecked();
  await expect(optimize).toBeEnabled();
  await activate(optimize, testInfo);
  await expect(resultHeading).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Open \(no gender fielding minimums\) profile/)).toBeVisible();
});

test("issues #21 and #25 keep the moon dancer static for reduced motion", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await activate(
    page.getByRole("button", { name: "Optimize seven innings" }),
    testInfo,
  );

  const status = page.locator('.optimization-status[role="status"]');
  const dancer = page.locator(".optimization-dancer");
  await expect(dancer).toBeVisible({ timeout: 10_000 });
  await expect(status).toBeVisible();
  for (const animatedPart of await dancer.locator(
    ".optimization-dancer__body, .optimization-dancer__arm, "
      + ".optimization-dancer__leg, .optimization-dancer__foot",
  ).all()) {
    expect(await animatedPart.evaluate(
      (element) => getComputedStyle(element).animationName,
    )).toBe("none");
  }

  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  )).toBe(true);
  expect(await dancer.evaluate(
    (element) => element.getBoundingClientRect().right <= window.innerWidth + 1,
  )).toBe(true);

  await expect(page.getByRole("heading", { name: "Optimized lineup" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(dancer).toBeHidden();
  await expect(status).toBeHidden();
});
