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
  await activate(combobox, testInfo);
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

test("issues #1, #3, and #6 keep the game-day outcome visible and current", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await page.goto("/");
  const optimize = page.getByRole("button", { name: "Optimize seven innings" });
  await expect(optimize).toBeEnabled();
  await activate(optimize, testInfo);

  const resultHeading = page.getByRole("heading", { name: "Optimized lineup" });
  await expect(resultHeading).toBeVisible({ timeout: 30_000 });
  const detailsHeading = page.getByRole("heading", {
    name: "Player details & preferences",
  });
  await expect(detailsHeading).toBeVisible();
  expect(await resultHeading.evaluate((result, details) => Boolean(
    result.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING
  ), await detailsHeading.elementHandle())).toBe(true);

  const lineupView = page.getByRole("combobox", { name: /Lineup view/ });
  await expect.poll(async () => selectedChoice(lineupView)).toBe("By inning");
  await expect(page.locator("[data-testid='stDataFrame']").first()).toBeVisible();
  await expect(page.getByText(/Bench:/)).toBeVisible();
  if (testInfo.project.name === "mobile-touch") {
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
  }

  for (const inning of [2, 3, 4, 5, 6, 7, 1]) {
    await choose(page, "Inning", String(inning), testInfo);
    await expect(page.locator("[data-testid='stDataFrame']").first()).toBeVisible();
  }

  await choose(page, "Lineup view", "Full matrix", testInfo);
  await expect(page.getByRole("combobox", { name: /Inning/ })).toBeHidden();
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
  await expect(optimize).toBeEnabled();
  await activate(optimize, testInfo);
  await expect(resultHeading).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Open \(no gender fielding minimums\) profile/)).toBeVisible();
});
