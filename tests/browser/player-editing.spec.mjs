import { expect, test } from "@playwright/test";

const POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "LC", "RC", "RF"];
const NEW_PLAYER = "Browser QA Player";
const NEW_PLAYER_POSITIONS = ["P", "C", "SS"];
const KEVIN_POSITIONS = ["2B", "3B", "SS", "LF", "LC", "RC"];

async function activate(locator, testInfo) {
  if (testInfo.project.name === "mobile-touch") {
    await locator.tap();
  } else {
    await locator.click();
  }
}

function playerNameInput(page) {
  return page.getByRole("textbox", { name: "Player name" });
}

function genderSelector(page) {
  return page.getByRole("combobox", { name: /Gender/ });
}

function positionButton(page, position) {
  return page.getByRole("button", { name: position, exact: true });
}

function playerCard(page, name) {
  return page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: `${name} ·` }),
  }).first();
}

async function openPlayerCard(page, name, testInfo) {
  const card = playerCard(page, name);
  await expect(card).toBeVisible();
  if (await card.getAttribute("open") === null) {
    await activate(card.locator("summary"), testInfo);
  }
  await expect(card).toHaveAttribute("open", "");
  return card;
}

async function editPlayer(page, name, testInfo) {
  const card = await openPlayerCard(page, name, testInfo);
  await activate(
    card.getByRole("button", { name: `Edit ${name}`, exact: true }),
    testInfo,
  );
  await expect(playerNameInput(page)).toBeVisible();
}

async function cancelEditor(page, testInfo) {
  await activate(page.getByRole("button", { name: "Cancel" }), testInfo);
  await expect(playerNameInput(page)).toBeHidden();
  await expect(page.getByRole("button", { name: "＋ Add player" })).toBeEnabled();
}

async function selectedGender(page) {
  const value = await genderSelector(page).inputValue();
  if (value === "Woman" || value === "Man") {
    return value;
  }
  const label = await genderSelector(page).getAttribute("aria-label");
  return label?.match(/^Selected (Woman|Man)\./)?.[1] ?? null;
}

async function chooseGender(page, gender, testInfo) {
  if (await selectedGender(page) === gender) {
    return;
  }
  const combobox = genderSelector(page);
  const openButton = combobox.locator("xpath=..").getByRole("button", {
    name: "Open",
    exact: true,
  });
  await activate(await openButton.count() ? openButton : combobox, testInfo);
  await activate(page.getByRole("option", { name: gender, exact: true }), testInfo);
  await expect.poll(() => selectedGender(page)).toBe(gender);
}

async function selectedPositions(page) {
  const selected = [];
  for (const position of POSITIONS) {
    const button = positionButton(page, position);
    const testId = await button.getAttribute("data-testid");
    const ariaPressed = await button.getAttribute("aria-pressed");
    const dataSelected = await button.getAttribute("data-selected");
    if (testId === "stBaseButton-pillsActive"
      || ariaPressed === "true"
      || dataSelected === "true") {
      selected.push(position);
    }
  }
  return selected;
}

async function expectEditorValues(page, { name, gender, positions }) {
  await expect(playerNameInput(page)).toHaveValue(name);
  await expect.poll(() => selectedGender(page)).toBe(gender);
  await expect.poll(() => selectedPositions(page)).toEqual(positions);
}

test("issue #8 saves every individual edit and Cancel discards a draft", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "🥎 Softball Fielding Optimizer" }),
  ).toBeVisible();

  await test.step("exercise every position control and save the intended three", async () => {
    await activate(page.getByRole("button", { name: "＋ Add player" }), testInfo);
    await expect(playerNameInput(page)).toBeVisible();
    await playerNameInput(page).fill(NEW_PLAYER);

    for (const position of POSITIONS) {
      await activate(positionButton(page, position), testInfo);
      await expect.poll(
        async () => (await selectedPositions(page)).includes(position),
      ).toBe(true);
    }
    await expect.poll(() => selectedPositions(page)).toEqual(POSITIONS);
    for (const position of POSITIONS.filter(
      (candidate) => !NEW_PLAYER_POSITIONS.includes(candidate),
    )) {
      await activate(positionButton(page, position), testInfo);
      await expect.poll(
        async () => (await selectedPositions(page)).includes(position),
      ).toBe(false);
    }
    await expect.poll(() => selectedPositions(page)).toEqual(NEW_PLAYER_POSITIONS);

    await chooseGender(page, "Man", testInfo);
    await expectEditorValues(page, {
      name: NEW_PLAYER,
      gender: "Man",
      positions: NEW_PLAYER_POSITIONS,
    });

    await activate(page.getByRole("button", { name: "Save changes" }), testInfo);
    const savedCard = playerCard(page, NEW_PLAYER);
    await expect(savedCard).toBeVisible();
    await expect(savedCard.locator("summary")).toContainText(
      `${NEW_PLAYER} · Man · Available · P, C, SS`,
    );
    await expect(playerNameInput(page)).toBeHidden();
  });

  await test.step("reopen the saved player and verify the persisted record", async () => {
    await editPlayer(page, NEW_PLAYER, testInfo);
    await expectEditorValues(page, {
      name: NEW_PLAYER,
      gender: "Man",
      positions: NEW_PLAYER_POSITIONS,
    });
    await cancelEditor(page, testInfo);
  });

  await test.step("optimization and an uncommitted Add/Cancel preserve the saved record and result", async () => {
    const optimize = page.getByRole("button", { name: "Optimize seven innings" });
    await activate(optimize, testInfo);
    const resultHeading = page.getByRole("heading", { name: "Optimized lineup" });
    await expect(resultHeading).toBeVisible({ timeout: 30_000 });

    await editPlayer(page, NEW_PLAYER, testInfo);
    await expectEditorValues(page, {
      name: NEW_PLAYER,
      gender: "Man",
      positions: NEW_PLAYER_POSITIONS,
    });
    await cancelEditor(page, testInfo);
    await expect(resultHeading).toBeVisible();

    await activate(page.getByRole("button", { name: "＋ Add player" }), testInfo);
    await expect(playerNameInput(page)).toBeVisible();
    await cancelEditor(page, testInfo);
    await expect(resultHeading).toBeVisible();
    await expect(page.getByText("Inputs changed — optimize again.")).toBeHidden();
  });

  await test.step("Cancel discards acknowledged edits to an existing player", async () => {
    await editPlayer(page, "Kevin", testInfo);
    await expectEditorValues(page, {
      name: "Kevin",
      gender: "Man",
      positions: KEVIN_POSITIONS,
    });

    await playerNameInput(page).fill("Cancelled Kevin");
    await chooseGender(page, "Woman", testInfo);
    await activate(positionButton(page, "P"), testInfo);
    await expectEditorValues(page, {
      name: "Cancelled Kevin",
      gender: "Woman",
      positions: ["P", ...KEVIN_POSITIONS],
    });

    await cancelEditor(page, testInfo);
    await expect(playerCard(page, "Kevin")).toBeVisible();
    await expect(page.getByText("Cancelled Kevin", { exact: true })).toHaveCount(0);

    await editPlayer(page, "Kevin", testInfo);
    await expectEditorValues(page, {
      name: "Kevin",
      gender: "Man",
      positions: KEVIN_POSITIONS,
    });
    await cancelEditor(page, testInfo);
  });

  await test.step("availability survives moving the saved player between gender groups", async () => {
    await editPlayer(page, NEW_PLAYER, testInfo);
    await chooseGender(page, "Woman", testInfo);
    await activate(page.getByRole("button", { name: "Save changes" }), testInfo);
    await expect(playerCard(page, NEW_PLAYER).locator("summary")).toContainText(
      `${NEW_PLAYER} · Woman · Available · P, C, SS`,
    );
    await expect(page.getByRole("checkbox", { name: NEW_PLAYER, exact: true })).toBeChecked();

    await editPlayer(page, NEW_PLAYER, testInfo);
    await chooseGender(page, "Man", testInfo);
    await activate(page.getByRole("button", { name: "Save changes" }), testInfo);
    await expect(playerCard(page, NEW_PLAYER).locator("summary")).toContainText(
      `${NEW_PLAYER} · Man · Available · P, C, SS`,
    );
    await expect(page.getByRole("checkbox", { name: NEW_PLAYER, exact: true })).toBeChecked();
  });

  await test.step("issue #7 persists several individual availability presses", async () => {
    const status = page.getByText(/available players.*available women/);
    await expect(status).toContainText("16 available players");

    for (const [index, name] of ["Andrew", "Luis", "Matt"].entries()) {
      const checkbox = page.getByRole("checkbox", { name, exact: true });
      await expect(checkbox).toBeChecked();
      const targetLabel = checkbox.locator("xpath=ancestor::label");
      await activate(targetLabel, testInfo);
      await expect(checkbox).not.toBeChecked();
      await expect(status).toContainText(`${15 - index} available players`);
      const target = await targetLabel.boundingBox();
      expect(target?.height).toBeGreaterThanOrEqual(44);
    }

    await editPlayer(page, "Kevin", testInfo);
    await cancelEditor(page, testInfo);
    await expect(status).toContainText("13 available players");
    for (const name of ["Andrew", "Luis", "Matt"]) {
      await expect(page.getByRole("checkbox", { name, exact: true })).not.toBeChecked();
    }

    await activate(page.getByRole("button", { name: "Optimize seven innings" }), testInfo);
    await expect(page.getByRole("heading", { name: "Optimized lineup" })).toBeVisible({
      timeout: 30_000,
    });
    for (const name of ["Andrew", "Luis", "Matt"]) {
      await expect(page.getByRole("checkbox", { name, exact: true })).not.toBeChecked();
    }

    await editPlayer(page, NEW_PLAYER, testInfo);
    await expectEditorValues(page, {
      name: NEW_PLAYER,
      gender: "Man",
      positions: NEW_PLAYER_POSITIONS,
    });
    await cancelEditor(page, testInfo);
    await expect(page.getByRole("heading", { name: "Optimized lineup" })).toBeVisible();
  });

  await test.step("issue #7 bulk availability actions update every woman", async () => {
    const women = ["Arielle", "Ashley", "Jenn", "Mia", "Taylor"];
    const status = page.getByText(/available players.*available women/);
    await activate(
      page.getByRole("button", { name: "Clear all women", exact: true }),
      testInfo,
    );
    await expect(status).toContainText("8 available players");
    for (const name of women) {
      await expect(page.getByRole("checkbox", { name, exact: true })).not.toBeChecked();
    }

    await activate(
      page.getByRole("button", { name: "Select all women", exact: true }),
      testInfo,
    );
    await expect(status).toContainText("13 available players");
    for (const name of women) {
      await expect(page.getByRole("checkbox", { name, exact: true })).toBeChecked();
    }
  });
});
