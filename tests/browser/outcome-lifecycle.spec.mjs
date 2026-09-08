import { expect, test } from "@playwright/test";

const CHANGED_MESSAGE = "Inputs changed — optimize again.";
const UNCOVERED_P_ERROR =
  "No available player is eligible for the following required position(s): P.";

async function activate(locator, testInfo) {
  if (testInfo.project.name === "mobile-touch") {
    await locator.tap();
  } else {
    await locator.click();
  }
}

function playerCard(page, name) {
  return page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: `${name} ·` }),
  }).first();
}

async function editPlayer(page, name, testInfo) {
  const card = playerCard(page, name);
  await expect(card).toBeVisible();
  const editButton = card.getByRole("button", {
    name: `Edit ${name}`,
    exact: true,
  });
  if (!await editButton.isVisible()) {
    await activate(card.locator("summary"), testInfo);
  }
  await expect(editButton).toBeVisible();
  await activate(editButton, testInfo);
  await expect(page.getByRole("textbox", { name: "Player name" })).toBeVisible();
}

async function selectedGender(page) {
  const combobox = page.getByRole("combobox", { name: /Gender/ });
  const value = await combobox.inputValue();
  if (value === "Woman" || value === "Man") {
    return value;
  }
  const label = await combobox.getAttribute("aria-label");
  return label?.match(/^Selected (Woman|Man)\./)?.[1] ?? null;
}

async function chooseGender(page, gender, testInfo) {
  if (await selectedGender(page) === gender) {
    return;
  }
  const combobox = page.getByRole("combobox", { name: /Gender/ });
  if (testInfo.project.name === "mobile-touch") {
    await activate(combobox, testInfo);
  } else {
    await combobox.focus();
    await combobox.press("ArrowDown");
  }
  await activate(page.getByRole("option", { name: gender, exact: true }), testInfo);
  await expect.poll(() => selectedGender(page)).toBe(gender);
}

async function positionIsSelected(button) {
  const testId = await button.getAttribute("data-testid");
  const ariaPressed = await button.getAttribute("aria-pressed");
  const dataSelected = await button.getAttribute("data-selected");
  return testId === "stBaseButton-pillsActive"
    || ariaPressed === "true"
    || dataSelected === "true";
}

async function setPosition(page, position, selected, testInfo) {
  const button = page.getByRole("button", { name: position, exact: true });
  if (await positionIsSelected(button) !== selected) {
    await activate(button, testInfo);
  }
  await expect.poll(() => positionIsSelected(button)).toBe(selected);
}

async function savePlayer(page, testInfo) {
  await activate(page.getByRole("button", { name: "Save changes" }), testInfo);
  await expect(page.getByRole("textbox", { name: "Player name" })).toBeHidden();
}

async function optimizeSuccessfully(page, testInfo) {
  await activate(
    page.getByRole("button", { name: "Optimize seven innings" }),
    testInfo,
  );
  await expect(
    page.getByRole("heading", { name: "Optimized lineup" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(CHANGED_MESSAGE, { exact: true })).toBeHidden();
}

async function expectCurrentResultInvalidated(page) {
  await expect(
    page.getByRole("heading", { name: "Optimized lineup" }),
  ).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Download full lineup CSV" }),
  ).toBeHidden();
  await expect(page.getByText(CHANGED_MESSAGE, { exact: true })).toBeVisible();
}

test("optimization error appears before roster details and recovers after an input correction", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto("/");

  await editPlayer(page, "Dung", testInfo);
  await setPosition(page, "C", true, testInfo);
  await setPosition(page, "P", false, testInfo);
  await savePlayer(page, testInfo);

  await activate(
    page.getByRole("button", { name: "Optimize seven innings" }),
    testInfo,
  );
  const optimizationError = page.locator("[data-testid='stAlert']").filter({
    hasText: UNCOVERED_P_ERROR,
  }).first();
  await expect(optimizationError).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Optimized lineup" }),
  ).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Download full lineup CSV" }),
  ).toBeHidden();

  const detailsHeading = page.getByRole("heading", {
    name: "Player details & preferences",
  });
  await expect(detailsHeading).toBeVisible();
  expect(await optimizationError.evaluate((error, details) => Boolean(
    error.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING
  ), await detailsHeading.elementHandle())).toBe(true);

  await editPlayer(page, "Dung", testInfo);
  await setPosition(page, "P", true, testInfo);
  await savePlayer(page, testInfo);
  await expect(optimizationError).toBeHidden();
  await expect(page.getByText(CHANGED_MESSAGE, { exact: true })).toBeVisible();

  await optimizeSuccessfully(page, testInfo);
  await expect(optimizationError).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Download full lineup CSV" }),
  ).toBeEnabled();

  const resultHeading = page.getByRole("heading", { name: "Optimized lineup" });
  expect(await resultHeading.evaluate((result, details) => Boolean(
    result.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING
  ), await detailsHeading.elementHandle())).toBe(true);
});

test("name, gender, and preference commits each invalidate only the current result", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await optimizeSuccessfully(page, testInfo);

  await test.step("name fingerprint field", async () => {
    await editPlayer(page, "Kevin", testInfo);
    await page.getByRole("textbox", { name: "Player name" }).fill("Kevin Browser QA");
    await savePlayer(page, testInfo);
    await expect(playerCard(page, "Kevin Browser QA")).toBeVisible();
    await expectCurrentResultInvalidated(page);
    await optimizeSuccessfully(page, testInfo);
  });

  await test.step("gender fingerprint field", async () => {
    await editPlayer(page, "Kevin Browser QA", testInfo);
    await chooseGender(page, "Woman", testInfo);
    await savePlayer(page, testInfo);
    await expect(playerCard(page, "Kevin Browser QA").locator("summary")).toContainText(
      "Kevin Browser QA · Woman · Available",
    );
    await expectCurrentResultInvalidated(page);
    await optimizeSuccessfully(page, testInfo);
  });

  await test.step("preferences fingerprint field", async () => {
    await editPlayer(page, "Kevin Browser QA", testInfo);
    await setPosition(page, "P", true, testInfo);
    await savePlayer(page, testInfo);
    await expect(playerCard(page, "Kevin Browser QA").locator("summary")).toContainText(
      "P, 2B, 3B, SS, LF, LC, RC",
    );
    await expectCurrentResultInvalidated(page);
    await optimizeSuccessfully(page, testInfo);
  });
});
