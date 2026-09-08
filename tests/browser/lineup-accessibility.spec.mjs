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

function lineupScrollRegion(page) {
  return page.getByRole("region", {
    name: "Scrollable seven-inning lineup",
  });
}

async function stickyMatrixGeometry(page) {
  const region = lineupScrollRegion(page);
  await region.evaluate((element) => {
    // Chromium reports pre-zoom scrollWidth/scrollHeight units under CSS zoom.
    // An intentionally oversized target reliably clamps to the true visual edge.
    element.scrollLeft = Number.MAX_SAFE_INTEGER;
    element.scrollTop = Number.MAX_SAFE_INTEGER;
  });
  await expect.poll(
    () => region.evaluate((element) => element.scrollLeft),
  ).toBeGreaterThan(0);
  await expect.poll(
    () => region.evaluate((element) => element.scrollTop),
  ).toBeGreaterThan(0);

  return region.evaluate((element) => {
    const rectangle = (target) => {
      const bounds = target.getBoundingClientRect();
      return {
        bottom: bounds.bottom,
        left: bounds.left,
        right: bounds.right,
        top: bounds.top,
      };
    };
    const table = element.querySelector("table");
    const corner = table.querySelector("thead th:first-child");
    const benchHeader = table.querySelector("thead th:last-child");
    const lastRow = table.querySelector("tbody tr:last-child");
    const inningHeader = lastRow.querySelector("th");
    const benchCell = lastRow.querySelector("td:last-child");
    const cornerStyle = getComputedStyle(corner);
    const columnStyle = getComputedStyle(benchHeader);
    const rowStyle = getComputedStyle(inningHeader);
    const isOpaque = (color) => color !== "transparent"
      && color !== "rgba(0, 0, 0, 0)";
    return {
      benchCell: rectangle(benchCell),
      benchHeader: rectangle(benchHeader),
      corner: rectangle(corner),
      inningHeader: rectangle(inningHeader),
      region: rectangle(element),
      styles: {
        columnBackgroundOpaque: isOpaque(columnStyle.backgroundColor),
        columnBorder: columnStyle.borderBottomStyle,
        columnPosition: columnStyle.position,
        columnZ: Number(columnStyle.zIndex),
        cornerBackgroundOpaque: isOpaque(cornerStyle.backgroundColor),
        cornerPosition: cornerStyle.position,
        cornerZ: Number(cornerStyle.zIndex),
        rowBackgroundOpaque: isOpaque(rowStyle.backgroundColor),
        rowBorder: rowStyle.borderRightStyle,
        rowPosition: rowStyle.position,
        rowZ: Number(rowStyle.zIndex),
      },
    };
  });
}

function expectStickyContext(geometry) {
  const tolerance = 3;
  expect(Math.abs(geometry.corner.top - geometry.region.top)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(geometry.corner.left - geometry.region.left)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(geometry.benchHeader.top - geometry.region.top)).toBeLessThanOrEqual(tolerance);
  expect(Math.abs(geometry.inningHeader.left - geometry.region.left)).toBeLessThanOrEqual(tolerance);
  expect(geometry.benchHeader.left).toBeLessThan(geometry.region.right);
  expect(geometry.benchHeader.right).toBeLessThanOrEqual(geometry.region.right + tolerance);
  expect(geometry.benchCell.left).toBeLessThan(geometry.region.right);
  expect(geometry.benchCell.right).toBeLessThanOrEqual(geometry.region.right + tolerance);
  expect(geometry.inningHeader.top).toBeLessThan(geometry.region.bottom);
  expect(geometry.inningHeader.bottom).toBeLessThanOrEqual(geometry.region.bottom + tolerance);
  expect(geometry.styles.columnPosition).toBe("sticky");
  expect(geometry.styles.rowPosition).toBe("sticky");
  expect(geometry.styles.cornerPosition).toBe("sticky");
  expect(geometry.styles.columnBackgroundOpaque).toBe(true);
  expect(geometry.styles.rowBackgroundOpaque).toBe(true);
  expect(geometry.styles.cornerBackgroundOpaque).toBe(true);
  expect(geometry.styles.columnBorder).not.toBe("none");
  expect(geometry.styles.rowBorder).not.toBe("none");
  expect(geometry.styles.cornerZ).toBeGreaterThan(geometry.styles.columnZ);
  expect(geometry.styles.columnZ).toBeGreaterThan(geometry.styles.rowZ);
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
  await expect(table.locator("caption")).toHaveText("Seven-inning lineup");
  await expect(table.getByRole("columnheader")).toHaveText([
    "Inning", ...POSITIONS, "Bench",
  ]);
  await expect(table.locator('thead th[scope="col"]')).toHaveCount(12);
  await expect(table.getByRole("row")).toHaveCount(8);
  await expect(table.getByRole("rowheader")).toHaveText([
    "1", "2", "3", "4", "5", "6", "7",
  ]);
  await expect(table.locator('tbody th[scope="row"]')).toHaveCount(7);

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

test("issues #19 and #23 show one sticky semantic lineup matching the full CSV", async ({ page }, testInfo) => {
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
    const scrollRegion = lineupScrollRegion(page);
    await expect(scrollRegion).toHaveAttribute("tabindex", "0");
    expect(await scrollRegion.evaluate(
      (region) => region.scrollWidth > region.clientWidth,
    )).toBe(true);
    expect(await scrollRegion.evaluate(
      (region) => region.scrollHeight > region.clientHeight,
    )).toBe(true);
    await scrollRegion.evaluate((region) => {
      region.scrollLeft = 0;
      region.scrollTop = 0;
    });
    await scrollRegion.focus();
    await expect(scrollRegion).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect.poll(
      () => scrollRegion.evaluate((region) => region.scrollLeft),
    ).toBeGreaterThan(0);
    await page.keyboard.press("ArrowDown");
    await expect.poll(
      () => scrollRegion.evaluate((region) => region.scrollTop),
    ).toBeGreaterThan(0);
    expectStickyContext(await stickyMatrixGeometry(page));
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
    // A 195-CSS-pixel viewport is the effective layout width of this
    // 390-pixel mobile viewport at 200% browser zoom. CSS `zoom` is not a
    // browser-zoom emulation and gives Chromium incorrect scroll extents.
    await page.setViewportSize({ width: 195, height: 422 });
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
    expect(await scrollRegion.evaluate(
      (region) => region.getBoundingClientRect().right <= window.innerWidth + 1,
    )).toBe(true);
    expectStickyContext(await stickyMatrixGeometry(page));
    await expect(lineupTable(page).getByRole("row")).toHaveCount(8);
    await page.setViewportSize({ width: 390, height: 844 });
  } else {
    const scrollRegion = lineupScrollRegion(page);
    expect(await scrollRegion.evaluate(
      (region) => region.scrollHeight === region.clientHeight,
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
    const scrollRegion = lineupScrollRegion(page);
    await scrollRegion.evaluate((region) => {
      region.scrollLeft = region.scrollWidth;
    });
    await expect.poll(
      () => scrollRegion.evaluate((region) => region.scrollLeft),
    ).toBeGreaterThan(0);
    const horizontalContext = await scrollRegion.evaluate((region) => {
      const regionBounds = region.getBoundingClientRect();
      const lastRow = region.querySelector("tbody tr:last-child");
      const inningBounds = lastRow.querySelector("th").getBoundingClientRect();
      const benchBounds = lastRow.querySelector("td:last-child").getBoundingClientRect();
      return {
        benchLeft: benchBounds.left,
        benchRight: benchBounds.right,
        inningLeft: inningBounds.left,
        regionLeft: regionBounds.left,
        regionRight: regionBounds.right,
      };
    });
    expect(Math.abs(
      horizontalContext.inningLeft - horizontalContext.regionLeft,
    )).toBeLessThanOrEqual(3);
    expect(horizontalContext.benchLeft).toBeLessThan(horizontalContext.regionRight);
    expect(horizontalContext.benchRight).toBeLessThanOrEqual(
      horizontalContext.regionRight + 3,
    );
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    )).toBe(true);
  }
});
