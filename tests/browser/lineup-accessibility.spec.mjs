import { expect, test } from "@playwright/test";
import { parse } from "csv-parse/sync";

const POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "LC", "RC", "RF"];
const LONG_PITCHER_NAME = "Dung Browser QA With A Very Long Pitcher Name";
const PLAYERS_TO_CLEAR = ["Brian", "David", "Jenn", "Evan", "Silas", "Ashley", "Matt"];

async function activate(locator, testInfo) {
  if (testInfo.project.name === "mobile-touch") {
    await locator.tap();
  } else {
    await locator.click();
  }
}

async function selectedChoice(combobox) {
  const value = await combobox.inputValue();
  if (value) {
    return value;
  }
  const label = await combobox.getAttribute("aria-label");
  return label?.match(/^Selected (.*?)\./)?.[1] ?? null;
}

async function choose(page, label, option, testInfo) {
  const combobox = page.getByRole("combobox", { name: new RegExp(label) });
  if (await selectedChoice(combobox) === option) {
    return;
  }
  if (testInfo.project.name === "mobile-touch") {
    await activate(combobox, testInfo);
  } else {
    await combobox.focus();
    await combobox.press("ArrowDown");
  }
  await activate(page.getByRole("option", { name: option, exact: true }), testInfo);
  await expect.poll(() => selectedChoice(combobox)).toBe(option);
}

function playerCard(page, name) {
  return page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: `${name} ·` }),
  }).first();
}

async function renamePitcher(page, testInfo) {
  const card = playerCard(page, "Dung");
  const editButton = card.getByRole("button", { name: "Edit Dung", exact: true });
  if (!await editButton.isVisible()) {
    await activate(card.locator("summary"), testInfo);
  }
  await activate(editButton, testInfo);
  await page.getByRole("textbox", { name: "Player name" }).fill(LONG_PITCHER_NAME);
  await activate(page.getByRole("button", { name: "Save changes" }), testInfo);
  await expect(playerCard(page, LONG_PITCHER_NAME)).toBeVisible();
}

async function downloadText(download) {
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function downloadLineup(page, testInfo) {
  const downloadPromise = page.waitForEvent("download");
  await activate(
    page.getByRole("button", { name: "Download full lineup CSV" }),
    testInfo,
  );
  const csv = await downloadText(await downloadPromise);
  return parse(csv, { columns: true, skip_empty_lines: true });
}

function lineupTable(page) {
  return page.getByRole("table", { name: /Inning \d+ assignments/ });
}

async function lineupPairs(page) {
  const rows = lineupTable(page).getByRole("row");
  const pairs = [];
  for (let index = 1; index < await rows.count(); index += 1) {
    const cells = rows.nth(index).getByRole("cell");
    pairs.push((await cells.allInnerTexts()).map((value) => value.trim()));
  }
  return pairs;
}

function namesFromList(value) {
  if (!value || value === "None") {
    return [];
  }
  return value.split(", ").map((name) => name.trim()).sort();
}

async function benchNames(page) {
  const text = await page.locator("[data-testid='stCaptionContainer']").filter({
    hasText: "Bench:",
  }).first().innerText();
  return namesFromList(text.replace(/^Bench:\s*/, ""));
}

async function assertSemanticInning(page, inning, csvRow) {
  await expect(
    page.getByRole("heading", { name: `Inning ${inning} assignments` }),
  ).toBeVisible();
  const table = lineupTable(page);
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveText(["Position", "Player"]);
  await expect(table.getByRole("row")).toHaveCount(11);
  await expect(table.getByRole("cell")).toHaveCount(20);

  const expectedPairs = POSITIONS.map((position) => [position, csvRow[position]]);
  await expect.poll(() => lineupPairs(page)).toEqual(expectedPairs);
  await expect.poll(() => benchNames(page)).toEqual(namesFromList(csvRow.Out));

  const activeNames = expectedPairs
    .map(([_position, name]) => name)
    .filter((name) => name !== "—");
  expect(activeNames.every((name) => Boolean(name.trim()))).toBe(true);
  expect(new Set(activeNames).size).toBe(activeNames.length);
}

test("the semantic inning lineup matches the full CSV and exposes reduced positions", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await renamePitcher(page, testInfo);

  await activate(
    page.getByRole("button", { name: "Optimize seven innings" }),
    testInfo,
  );
  await expect(
    page.getByRole("heading", { name: "Optimized lineup" }),
  ).toBeVisible({ timeout: 30_000 });

  const csvRows = await downloadLineup(page, testInfo);
  expect(csvRows.map((row) => Number(row.Inning))).toEqual([1, 2, 3, 4, 5, 6, 7]);

  for (const csvRow of csvRows) {
    const inning = Number(csvRow.Inning);
    await choose(page, "Inning", String(inning), testInfo);
    await assertSemanticInning(page, inning, csvRow);
    await expect(
      lineupTable(page).getByRole("cell", { name: LONG_PITCHER_NAME, exact: true }),
    ).toHaveCount(1);
  }

  if (testInfo.project.name === "mobile-touch") {
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
  }

  await choose(
    page,
    "League rules",
    "Open (no gender fielding minimums)",
    testInfo,
  );
  for (const name of PLAYERS_TO_CLEAR) {
    const checkbox = page.getByRole("checkbox", { name, exact: true });
    await activate(checkbox.locator("xpath=ancestor::label"), testInfo);
    await expect(checkbox).not.toBeChecked();
  }
  await activate(
    page.getByRole("button", { name: "Optimize seven innings" }),
    testInfo,
  );
  await expect(
    page.getByRole("heading", { name: "Optimized lineup" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Open \(no gender fielding minimums\) profile/)).toBeVisible();
  await choose(page, "Inning", "1", testInfo);
  await expect(
    page.getByRole("heading", { name: "Inning 1 assignments" }),
  ).toBeVisible();
  await expect.poll(() => lineupPairs(page)).toEqual(
    POSITIONS.map((position) => [
      position,
      ["C", "RF"].includes(position) ? "—" : expect.any(String),
    ]),
  );
  const reducedPairs = await lineupPairs(page);
  expect(reducedPairs.find(([position]) => position === "C")?.[1]).toBe("—");
  expect(reducedPairs.find(([position]) => position === "RF")?.[1]).toBe("—");
  const reducedActiveNames = reducedPairs
    .filter(([position]) => !["C", "RF"].includes(position))
    .map(([_position, name]) => name);
  expect(reducedActiveNames.every((name) => Boolean(name.trim()) && name !== "—")).toBe(true);
  expect(new Set(reducedActiveNames).size).toBe(8);

  if (testInfo.project.name === "mobile-touch") {
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
  }
});
