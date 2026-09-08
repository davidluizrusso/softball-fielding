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
  return page.getByRole("table", { name: "Seven-inning lineup" });
}

async function lineupRows(page) {
  const rows = lineupTable(page).getByRole("row");
  const values = [];
  for (let index = 1; index < await rows.count(); index += 1) {
    const row = rows.nth(index);
    const inning = (await row.getByRole("rowheader").innerText()).trim();
    const cells = (await row.getByRole("cell").allInnerTexts()).map(
      (value) => value.trim(),
    );
    values.push([inning, ...cells]);
  }
  return values;
}

function namesFromList(value) {
  if (!value || value === "None") {
    return [];
  }
  return value.split(", ").map((name) => name.trim()).sort();
}

async function assertSemanticSchedule(page, csvRows) {
  const table = lineupTable(page);
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveText([
    "Inning", ...POSITIONS, "Bench",
  ]);
  await expect(table.getByRole("row")).toHaveCount(8);
  await expect(table.getByRole("rowheader")).toHaveText([
    "1", "2", "3", "4", "5", "6", "7",
  ]);

  const visibleRows = await lineupRows(page);
  expect(visibleRows).toHaveLength(csvRows.length);
  for (const [index, csvRow] of csvRows.entries()) {
    const visibleRow = visibleRows[index];
    expect(visibleRow[0]).toBe(String(csvRow.Inning));
    expect(visibleRow.slice(1, 11)).toEqual(
      POSITIONS.map((position) => csvRow[position]),
    );
    expect(namesFromList(visibleRow[11])).toEqual(namesFromList(csvRow.Out));

    const activeNames = visibleRow
      .slice(1, 11)
      .filter((name) => name !== "—");
    expect(activeNames.every((name) => Boolean(name.trim()))).toBe(true);
    expect(new Set(activeNames).size).toBe(activeNames.length);
  }
}

test("issue #19 shows one semantic seven-inning lineup matching the full CSV", async ({ page }, testInfo) => {
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
  await assertSemanticSchedule(page, csvRows);
  await expect(page.getByRole("combobox", { name: /Lineup view/ })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: /^Inning$/ })).toHaveCount(0);
  await expect(
    lineupTable(page).getByRole("cell", { name: LONG_PITCHER_NAME, exact: true }),
  ).not.toHaveCount(0);

  if (testInfo.project.name === "mobile-touch") {
    const scrollRegion = page.getByRole("region", {
      name: "Scrollable seven-inning lineup",
    });
    await expect(scrollRegion).toHaveAttribute("tabindex", "0");
    expect(await scrollRegion.evaluate(
      (region) => region.scrollWidth > region.clientWidth,
    )).toBe(true);
    await scrollRegion.focus();
    await expect(scrollRegion).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect.poll(
      () => scrollRegion.evaluate((region) => region.scrollLeft),
    ).toBeGreaterThan(0);
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
    await page.evaluate(() => {
      document.documentElement.style.zoom = "200%";
    });
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
    await expect(lineupTable(page).getByRole("row")).toHaveCount(8);
    await page.evaluate(() => {
      document.documentElement.style.zoom = "";
    });
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
  const reducedCsvRows = await downloadLineup(page, testInfo);
  await assertSemanticSchedule(page, reducedCsvRows);
  const reducedRows = await lineupRows(page);
  const cIndex = POSITIONS.indexOf("C") + 1;
  const rfIndex = POSITIONS.indexOf("RF") + 1;
  for (const row of reducedRows) {
    expect(row[cIndex]).toBe("—");
    expect(row[rfIndex]).toBe("—");
    const activeNames = row
      .slice(1, 11)
      .filter((name) => name !== "—");
    expect(activeNames).toHaveLength(8);
    expect(new Set(activeNames).size).toBe(8);
  }

  if (testInfo.project.name === "mobile-touch") {
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
  }
});
