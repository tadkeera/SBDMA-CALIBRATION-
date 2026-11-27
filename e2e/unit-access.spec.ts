/**
 * Opening a unit must not throw the reader out of the laboratory.
 *
 * The defect this spec is written for: on 2.4.0, clicking the HPLC (1) tile as QA or as an
 * administrator landed on the dashboard — the guard in `Shell` treated "not an operator"
 * as "not welcome anywhere under /lab". The twenty tiles exist to be read by the office
 * that reviews and approves them, so the shelf below a unit is now open to anyone who may
 * view instruments and review results; only the readings stay with the bench.
 */

import { expect, test } from "@playwright/test";

import { signInAs } from "./lib/browser";
import type { AccountKey } from "./lib/accounts";

const UNIT_TILE = 'main a[href^="/lab/"][href*="-"]';
const TEST_TILE = 'a[href*="/T"]';

async function openFirstUnit(page: import("@playwright/test").Page) {
  await page.goto("/lab/units");
  const tile = page.locator(UNIT_TILE).first();
  await tile.waitFor({ timeout: 30_000 });
  await tile.click();
  await expect(page).toHaveURL(/\/lab\/[0-9a-f-]{36}$/, { timeout: 20_000 });
  return page.url();
}

for (const role of ["analyst", "qa", "admin"] as AccountKey[]) {
  test(`opening a unit keeps ${role} on the unit's tests`, async ({ page }) => {
    await signInAs(page, role);
    const url = await openFirstUnit(page);

    // the twenty tiles are the destination, not the dashboard
    await expect(page.locator(TEST_TILE).first()).toBeVisible({ timeout: 30_000 });
    expect(await page.locator(TEST_TILE).count()).toBeGreaterThanOrEqual(19);
    await expect(page.getByText("T01", { exact: true }).first()).toBeVisible();
    // and the page is still the unit's, five seconds later: a client-side guard that
    // fires late would still have thrown the reader out by now
    await page.waitForTimeout(5_000);
    expect(page.url()).toBe(url);
  });
}

test("the shelf stays open to a read-only viewer", async ({ page }) => {
  // The register is department-scoped, so a viewer whose department holds no unit sees an
  // empty shelf — but it is *the shelf*, not the dashboard: reading the register is the
  // viewer's whole job.
  await signInAs(page, "viewer");
  await page.goto("/lab/units");
  await expect(page).toHaveURL(/\/lab\/units$/, { timeout: 20_000 });
  await expect(
    page.getByText(/لا يوجد جهاز في نطاقك|No unit in your scope/).first(),
  ).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(4_000);
  await expect(page).toHaveURL(/\/lab\/units$/);
});

test("QA reads a unit without being offered the bench's buttons", async ({ page }) => {
  await signInAs(page, "qa");
  await openFirstUnit(page);
  await page.locator(TEST_TILE).first().waitFor({ timeout: 30_000 });

  // the read-only notice is shown, and the work is refused on the test page
  await expect(
    page.getByText(/للقراءة فقط|read-only/i).first(),
  ).toBeVisible({ timeout: 20_000 });

  await page.locator('a[href*="/T02"]').first().click();
  await expect(page).toHaveURL(/\/T02$/, { timeout: 20_000 });
  await expect(
    page.getByRole("button", { name: /Run Calibration|تشغيل المعايرة/ }),
  ).toBeDisabled({ timeout: 30_000 });
});

test("the analyst still works on the unit it opened", async ({ page }) => {
  await signInAs(page, "analyst");
  await openFirstUnit(page);
  await page.locator('a[href*="/T02"]').first().click();
  await expect(page).toHaveURL(/\/T02$/, { timeout: 20_000 });
  await expect(
    page.getByRole("button", { name: /Run Calibration|تشغيل المعايرة/ }),
  ).toBeEnabled({ timeout: 30_000 });
});
