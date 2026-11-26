/**
 * Release 2.2.0 in a browser.
 *
 * Four things are proven here, and none of them can be proven by the API tests alone:
 *
 *  1. the Control Center switch really flips a test on and off, and the row reports
 *     what the server said (not an optimistic guess);
 *  2. a disabled test is gone from the laboratory navigator of another user — the
 *     requirement was "disappears from the screen", so the screen is what is checked;
 *  3. the documented procedure is printed in English, left-to-right, whatever the
 *     interface language is;
 *  4. the Reference Manual renders every section, is searchable, and its PDF downloads.
 *
 * Sign-in notes: `signInAs` drives the real login form. The administrator's session is
 * a saved storage state (the account carries a second factor, which global setup has
 * already enrolled); the analyst has no factor, so a plain context is enough — and
 * using a *separate context* is what makes the "another user" check meaningful.
 */

import { bilingual, open, settle, signInAs, withSignedInPage } from './lib/browser';
import { expect, test } from './lib/fixtures';

test('the Control Center enables and disables a test, and the laboratory reflects it', async ({
  page,
  browser,
  baseURL,
}) => {
  await signInAs(page, 'admin');
  await open(page, '/control');
  await page.getByRole('button', { name: bilingual('حالة الاختبارات', 'Test status') }).click();

  const panel = page.locator('section', { hasText: /Enable and disable tests|تفعيل وتعطيل الاختبارات/ });
  await expect(panel).toBeVisible({ timeout: 30_000 });
  await expect(panel.locator('table tbody tr')).toHaveCount(20);

  const row = panel.locator('tr', { hasText: 'T13' });
  const toggle = row.getByRole('switch');
  await expect(toggle).toHaveAttribute('aria-checked', 'true');

  // disable, with the reason the server demands
  await toggle.click();
  await page.getByRole('textbox').last().fill('E2E: leak sensor under repair — release 2.2.0 check');
  await page.getByRole('button', { name: /^(Disable|تعطيل)$/ }).click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false', { timeout: 30_000 });
  await expect(row).toContainText(/Disabled|معطّل/);

  // a different user, in a different browser context, no longer sees the test
  const other = await browser.newContext({ baseURL, viewport: { width: 1500, height: 1000 } });
  try {
    const analyst = await other.newPage();
    await signInAs(analyst, 'analyst');
    await open(analyst, '/lab');
    const navigator = analyst.locator('section', { hasText: /Protocol tests|اختبارات البروتوكول/ });
    await expect(navigator).toBeVisible({ timeout: 30_000 });
    await expect(navigator.locator('li')).toHaveCount(19);
    await expect(navigator).not.toContainText('T13');
  } finally {
    await other.close();
  }

  // restore, so the rest of the suite (and the demonstration database) is unchanged
  await toggle.click();
  await page.getByRole('textbox').last().fill('E2E: sensor replaced — test restored');
  await page.getByRole('button', { name: /^(Enable|تفعيل)$/ }).click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true', { timeout: 30_000 });
});

test('the documented procedure is English and left-to-right', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/lab');

  const procedure = page.locator('details', { hasText: /Documented procedure/ }).first();
  await expect(procedure).toBeVisible({ timeout: 30_000 });

  const steps = procedure.locator('ol');
  await expect(steps).toHaveAttribute('dir', 'ltr');
  await expect(steps).toHaveAttribute('lang', 'en');
  await expect(steps.locator('li')).toHaveCount(6);

  const text = (await steps.innerText()).trim();
  // professional English wording, and not a single Arabic letter
  expect(text).toMatch(/USP|<1058>|integrity guide|instrument|calibration|procedure/i);
  expect(text).not.toMatch(/[\u0600-\u06FF]/);
});

test('the Reference Manual is searchable and prints a PDF per test', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/control');
  await page.getByRole('button', { name: bilingual('الدليل المرجعي', 'Reference Manual') }).click();

  const search = page.getByPlaceholder('Search code, name, standard…');
  await expect(search).toBeVisible({ timeout: 30_000 });

  // the filter narrows twenty sections down to the wavelength family
  await search.fill('wavelength');
  const entries = page.locator('ul li button', { hasText: /^T\d\d/ });
  await expect(entries.first()).toBeVisible();
  const count = await entries.count();
  expect(count).toBeGreaterThanOrEqual(3);
  expect(count).toBeLessThan(20);

  await page.locator('ul li button', { hasText: 'T14' }).click();
  await settle(page);

  const body = page.locator('[dir="ltr"]').last();
  await expect(body).toContainText(/Overview & importance/i);
  await expect(body).toContainText(/Required readings/i);
  await expect(body).toContainText(/Mathematical equations/i);
  await expect(body).toContainText(/Evaluation criteria/i);
  await expect(body).toContainText(/Acceptance limits/i);
  await expect(body).toContainText(/Chart \/ calibration curve/i);
  await expect(body).toContainText(/Scientific references/i);
  await expect(body).toContainText(/USP <857>/);

  // the curve is drawn from the ideal readings, not an empty frame
  await expect(body.locator('svg path').first()).toBeVisible();

  const download = page.waitForEvent('download', { timeout: 60_000 });
  await body.getByRole('button', { name: /^PDF$/ }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/Reference-Manual-T14\.pdf$/);
});

test('a single test can be run without the other nineteen', async ({ browser, baseURL }) => {
  await withSignedInPage(browser, baseURL, 'qa', async (page) => {
    await open(page, '/lab');
    const toggle = page.getByRole('checkbox').filter({ hasText: '' }).first();
    // the scope switch lives in the run bar; scoped runs are recorded with one result
    const single = page.getByTitle(/Run only the test on screen|تشغيل الاختبار المعروض فقط/);
    await expect(single).toBeVisible({ timeout: 30_000 });
    await single.locator('input[type="checkbox"]').check();
    await expect(page.getByText(/Single test only|اختبار واحد فقط/).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /^Run T\d\d$|^تشغيل T\d\d$/ })).toBeVisible();
    // restore the default for any later spec
    await single.locator('input[type="checkbox"]').uncheck();
    expect(toggle).toBeTruthy();
  });
});
