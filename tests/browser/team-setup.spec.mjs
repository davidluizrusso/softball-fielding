import { expect, test } from "@playwright/test";

const NEUTRAL_URL = "http://127.0.0.1:8518";
const TEAM_RED_NAMES = [
  "David R",
  "Justin",
  "Andrew",
  "Kevin",
  "David",
  "Dung",
  "Heather",
  "Ryan",
  "Tristan",
  "Brad",
  "AP",
  "Chris",
  "Marty",
];

async function activate(locator, testInfo) {
  if (testInfo.project.name === "mobile-touch") {
    await locator.tap();
  } else {
    await locator.click();
  }
}

async function chooseSetup(page, setupName, testInfo) {
  const choice = page.getByRole("radio", {
    name: new RegExp(`^${setupName}`),
  });
  await activate(choice.locator("xpath=.."), testInfo);
  await expect(choice).toBeChecked();
  await activate(page.getByRole("button", { name: "Continue" }), testInfo);
  await expect(
    page.getByText(new RegExp(`Current setup:.*${setupName}`)),
  ).toBeVisible();
}

async function openPlayerEditor(page, playerName, testInfo) {
  const card = page.locator("details").filter({
    has: page.locator("summary").filter({ hasText: `${playerName} ·` }),
  }).first();
  const edit = card.getByRole("button", {
    name: `Edit ${playerName}`,
    exact: true,
  });
  if (!await edit.isVisible()) {
    await activate(card.locator("summary"), testInfo);
  }
  await activate(edit, testInfo);
  await expect(page.getByRole("textbox", { name: "Player name" })).toBeVisible();
}

test("neutral setup chooser isolates teams and switches only after confirmation", async ({ browser, page }, testInfo) => {
  test.setTimeout(180_000);
  await page.goto(NEUTRAL_URL);

  await test.step("first load reveals no team roster or league controls", async () => {
    await expect(
      page.getByRole("heading", { name: "Choose a starting setup" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
    await expect(page.getByRole("checkbox")).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "League rules" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Optimize seven innings" })).toHaveCount(0);
    await expect(page.getByText("Dung", { exact: true })).toHaveCount(0);

    if (testInfo.project.name === "mobile-touch") {
      for (const setupName of ["Here For The Beer", "Team Red", "Start blank"]) {
        const target = await page.getByRole("radio", {
          name: new RegExp(`^${setupName}`),
        }).locator("xpath=..").boundingBox();
        expect(target?.height).toBeGreaterThanOrEqual(44);
      }
      expect(await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      )).toBe(true);
    }
  });

  await test.step("Team Red loads exact names, locked Open rules, and no gender UI", async () => {
    await chooseSetup(page, "Team Red", testInfo);
    await expect(page.getByText(/League rules:.*Open/)).toBeVisible();
    await expect(page.getByRole("combobox", { name: "League rules" })).toHaveCount(0);
    await expect(page.getByText("Unspecified", { exact: false })).toHaveCount(0);
    const checkboxes = page.getByRole("checkbox");
    await expect(checkboxes).toHaveCount(TEAM_RED_NAMES.length);
    for (const name of TEAM_RED_NAMES) {
      await expect(page.getByRole("checkbox", { name, exact: true })).toBeChecked();
    }

    await openPlayerEditor(page, "David R", testInfo);
    await expect(page.getByRole("combobox", { name: "Gender" })).toHaveCount(0);
    await activate(page.getByRole("button", { name: "Cancel" }), testInfo);

    const dungAvailability = page.getByRole("checkbox", {
      name: "Dung",
      exact: true,
    });
    await activate(dungAvailability.locator("xpath=ancestor::label"), testInfo);
    await expect(dungAvailability).not.toBeChecked();
    await expect(page.getByText(
      /No available player is eligible for the following required position\(s\): P\./,
    )).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Optimize seven innings" }),
    ).toBeDisabled();
    await expect(page.getByText(/Ready for 10 fielders/)).toHaveCount(0);

    await activate(dungAvailability.locator("xpath=ancestor::label"), testInfo);
    await expect(dungAvailability).toBeChecked();
    await expect(page.getByText(
      /No available player is eligible for the following required position\(s\): P\./,
    )).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Optimize seven innings" }),
    ).toBeEnabled();
    await expect(page.getByText(/Ready for 10 fielders/)).toBeVisible();

    await activate(
      page.getByRole("button", { name: "Optimize seven innings" }),
      testInfo,
    );
    await expect(page.getByRole("heading", { name: "Optimized lineup" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("combobox", { name: /Lineup view/ })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: /^Inning$/ })).toHaveCount(0);
    await expect(
      page.getByRole("table", { name: "Seven-inning lineup" }).getByRole("row"),
    ).toHaveCount(8);
    await expect(page.getByText(
      /^(Optimal|Feasible): Legal, authoritative lineup for the current inputs\./,
    )).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await activate(
      page.getByRole("button", { name: "Download full lineup CSV" }),
      testInfo,
    );
    expect((await downloadPromise).suggestedFilename()).toMatch(
      /^team-red_open_\d{8}T\d{6}Z_[a-f0-9]{8}\.csv$/,
    );
  });

  await test.step("a second browser session starts clean and can choose blank", async () => {
    const isolatedContext = await browser.newContext({
      viewport: testInfo.project.use.viewport,
      hasTouch: testInfo.project.use.hasTouch,
      isMobile: testInfo.project.use.isMobile,
    });
    const isolatedPage = await isolatedContext.newPage();
    await isolatedPage.goto(NEUTRAL_URL);
    await expect(
      isolatedPage.getByRole("heading", { name: "Choose a starting setup" }),
    ).toBeVisible();
    await expect(isolatedPage.getByRole("checkbox")).toHaveCount(0);
    await chooseSetup(isolatedPage, "Start blank", testInfo);
    await expect(isolatedPage.getByText(/Roster is empty/)).toBeVisible();
    await expect(
      isolatedPage.getByRole("button", { name: "＋ Add first player" }),
    ).toBeVisible();
    await activate(
      isolatedPage.getByRole("button", { name: "＋ Add first player" }),
      testInfo,
    );
    await isolatedPage.getByRole("textbox", { name: "Player name" }).fill(
      "Isolated QA Player",
    );
    await activate(
      isolatedPage.getByRole("button", { name: "P", exact: true }),
      testInfo,
    );
    await activate(
      isolatedPage.getByRole("button", { name: "Save changes" }),
      testInfo,
    );
    await expect(
      isolatedPage.getByRole("checkbox", {
        name: "Isolated QA Player",
        exact: true,
      }),
    ).toBeChecked();
    await expect(
      page.getByText(/Current setup:.*Team Red/),
    ).toBeVisible();
    await expect(page.getByText("Isolated QA Player", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("checkbox")).toHaveCount(TEAM_RED_NAMES.length);
    await isolatedContext.close();
  });

  await test.step("cancel preserves Team Red and confirm atomically loads HFTB", async () => {
    const result = page.getByRole("heading", { name: "Optimized lineup" });
    await activate(page.getByRole("button", { name: "Change roster setup" }), testInfo);
    await expect(page.getByRole("checkbox")).toHaveCount(0);
    await activate(page.getByRole("radio", {
      name: "Here For The Beer",
      exact: true,
    }).locator("xpath=.."), testInfo);
    await expect(page.getByText(/Switch to Here For The Beer\?/)).toBeVisible();
    await activate(page.getByRole("button", { name: "Keep Team Red" }), testInfo);
    await expect(result).toBeVisible();
    await expect(page.getByRole("checkbox")).toHaveCount(TEAM_RED_NAMES.length);

    await activate(page.getByRole("button", { name: "Change roster setup" }), testInfo);
    await activate(page.getByRole("radio", {
      name: "Here For The Beer",
      exact: true,
    }).locator("xpath=.."), testInfo);
    await activate(
      page.getByRole("button", {
        name: "Discard changes and switch to Here For The Beer",
      }),
      testInfo,
    );
    await expect(page.getByText(/Current setup:.*Here For The Beer/)).toBeVisible();
    await expect(result).toHaveCount(0);
    await expect(page.getByRole("checkbox")).toHaveCount(15);
    await expect(page.getByRole("combobox", { name: "League rules" })).toBeVisible();
    await expect(page.getByText("Women", { exact: true })).toBeVisible();
    await expect(page.getByText("Men", { exact: true })).toBeVisible();
  });
});
