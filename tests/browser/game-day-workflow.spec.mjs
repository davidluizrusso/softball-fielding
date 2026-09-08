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

  const dancer = page.locator(".optimization-dancer");
  await expect(dancer).toBeVisible({ timeout: 10_000 });
  await expect(dancer).toContainText("Tiny coach is dancing");
  expect(await dancer.locator(".optimization-dancer__figure").evaluate(
    (figure) => getComputedStyle(figure).animationName,
  )).toBe("softball-stick-figure-dance");

  const resultHeading = page.getByRole("heading", { name: "Optimized lineup" });
  await expect(resultHeading).toBeVisible({ timeout: 30_000 });
  await expect(dancer).toBeHidden();
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
  expect(download.suggestedFilename()).toBe("softball_lineup.csv");
  expect(await download.failure()).toBeNull();
  const csv = await downloadText(download);
  const csvLines = csv.trim().split(/\r?\n/);
  expect(csvLines).toHaveLength(8);
  expect(csvLines[0]).toBe("Inning,P,C,1B,2B,3B,SS,LF,LC,RC,RF,Out");

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
