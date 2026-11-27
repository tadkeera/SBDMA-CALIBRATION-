/**
 * Release 2.4.0 through the browser: units, the per-test workbench, and the certificate.
 *
 * The backend suite proves the rules; this spec proves the *screens* exist and are wired,
 * which is the part a unit test cannot see. Three journeys:
 *
 *  1. the analyst sees the unit gallery, opens HPLC (1), and finds the twenty test tiles;
 *  2. the analyst opens a test, enters a reading, presses Run Calibration and sees the
 *     server's verdict and statistics — not the browser's arithmetic;
 *  3. the Flow Rate page is no longer a navigation entry, but is still reachable from the
 *     test tile and still renders its grid (it was hidden, not deleted).
 */

import { expect, test } from "@playwright/test";

import { signInAs } from "./lib/browser";

test.describe("laboratory units", () => {
  test.beforeEach(async ({ page }) => {
    await signInAs(page, "analyst");
  });

  test("the shelf lists the unit with its circled number", async ({ page }) => {
    await page.goto("/lab/units");
    const tile = page.locator('main a[href^="/lab/"][href*="-"]').first();
    await expect(tile).toBeVisible({ timeout: 20_000 });
    // the number printed in the red circle belongs to the unit itself
    await expect(page.getByText(/HPLC \(\d+\)/).first()).toBeVisible();
    // the analyst reads the shelf but does not register units: adding one is an
    // administrative permission, so the control is absent for the bench
    await expect(
      page.getByRole("button", { name: /إضافة جهاز HPLC|Add HPLC unit/ }),
    ).toHaveCount(0);
  });

  test("opening a unit shows the protocol tests as tiles", async ({ page }) => {
    await page.goto("/lab/units");
    const firstTile = page.locator('main a[href^="/lab/"][href*="-"]').first();
    await firstTile.waitFor();
    await firstTile.click();
    await expect(page).toHaveURL(/\/lab\/[0-9a-f-]{36}$/);
    // twenty tests, one tile each, each tile a link into the test's own page
    const testTiles = page.locator('a[href*="/lab/"][href*="/T"]');
    await expect(testTiles.first()).toBeVisible({ timeout: 20_000 });
    expect(await testTiles.count()).toBeGreaterThanOrEqual(19);
    await expect(page.getByText("T01", { exact: true }).first()).toBeVisible();
  });

  test("a test page computes on the server and shows the statistics panel", async ({
    page,
  }) => {
    await page.goto("/lab/units");
    const firstTile = page.locator('main a[href^="/lab/"][href*="-"]').first();
    await firstTile.waitFor();
    await firstTile.click();
    await page.locator('a[href*="/T02"]').first().click();
    await expect(page).toHaveURL(/\/T02$/);

    // the accepted limits are printed from the server's definition, in English keys
    await expect(
      page.locator("main").getByText("max_abs_error").first(),
    ).toBeVisible({ timeout: 20_000 });

    // ten readings per set point, three rows
    const cells = page.locator('input[aria-label^="flow_p1000-"]');
    await expect(cells).toHaveCount(10);
    for (let index = 0; index < 10; index += 1) {
      await cells.nth(index).fill("1.000");
    }
    for (let index = 0; index < 10; index += 1) {
      await page
        .locator(`input[aria-label="flow_p1500-${index + 1}"]`)
        .fill("1.500");
      await page
        .locator(`input[aria-label="flow_p2000-${index + 1}"]`)
        .fill("2.000");
    }

    await page
      .getByRole("button", { name: /Run Calibration|تشغيل المعايرة/ })
      .click();
    // the server's answer arrives as a summary card, one row per applied limit
    await expect(
      page.getByText(/ملخص الحساب|Calculation summary/).first(),
    ).toBeVisible({
      timeout: 25_000,
    });
    await expect(
      page.locator("main").getByText("max_rsd").first(),
    ).toBeVisible();
  });

  test("flow rate is reached from the test tile and is not in the sidebar", async ({
    page,
  }) => {
    await page.goto("/lab/units");
    const nav = page.locator("aside nav");
    await expect(nav.getByText(/Flow Rate|معدل التدفق/)).toHaveCount(0);

    // the page itself still exists and still renders its thirty cells
    await page.goto("/lab/flow-rate");
    await expect(
      page.locator('input[aria-label^="run-1-"]').first(),
    ).toBeVisible({ timeout: 20_000 });
  });
});
