/**
 * Registering an instrument — through the administrator's own browser session.
 *
 * The specs that touch the bench sign in as the analyst inside the test, which is fine
 * for a session without a second factor. The administrator demands a one-time code, and
 * a code may be spent once: global setup has already spent one for the administrator and
 * saved the resulting session. This spec therefore *reuses* that saved session instead of
 * minting a second code, which is both honest about the account's protection and stable
 * across runs.
 */

import { expect, test } from "@playwright/test";

import { storageStatePath } from "./lib/state";

test.describe("instrument registration", () => {
  test.use({ storageState: storageStatePath("admin") });

  test("the administrator registers a unit, numbered from two", async ({
    page,
  }) => {
    await page.goto("/lab/units");

    const add = page
      .getByRole("button", { name: /إضافة جهاز HPLC|Add HPLC unit/ })
      .first();
    await expect(add).toBeVisible({ timeout: 20_000 });
    await add.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // the number the unit will carry is shown before it is saved
    await expect(dialog.getByText("2", { exact: true })).toBeVisible();

    // the Arabic and English names are pre-filled with the number the server will
    // issue; the model and the serial number are the two the seeder demands
    await dialog.locator("input").nth(4).fill("LC-2050C");
    await dialog.locator("input").nth(5).fill("E2E-UNIT-SERIAL-2");
    await dialog.getByRole("button", { name: /حفظ|Save/ }).click();

    // the new tile appears with its own circled number
    await expect(page.getByText("HPLC (2)").first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
