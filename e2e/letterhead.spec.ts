/**
 * إعداد الترويسة — the official report letterhead.
 *
 * What matters to the agency, and therefore to this spec:
 *   1. the letterhead reads as written: four Arabic lines on the right, four English
 *      on the left, the logo in the centre;
 *   2. it appears where documents are read — the sign-in screen, the application
 *      shell, and every printed page;
 *   3. only the administrator can change it, and a change is visible immediately.
 */

import { join } from 'node:path';

import { bilingual, open, signInAs, withSignedInPage } from './lib/browser';
import { expect, test } from './lib/fixtures';

const LOGO = join(__dirname, 'fixtures', 'logo.webp');

const ARABIC_LAST = 'المختبر الوطني للرقابة الدوائية - عدن';
const ENGLISH_LAST = 'National Quality Control Laboratory - ADEN';

test('the sign-in screen carries the official letterhead', async ({ page }) => {
  await page.goto('/login');
  await page.waitForSelector('#username');
  const letterhead = page.locator('header.letterhead').first();
  await expect(letterhead).toBeVisible({ timeout: 30_000 });
  await expect(letterhead).toContainText('الجمهورية اليمنية');
  await expect(letterhead).toContainText('Republic of Yemen');
  await expect(letterhead).toContainText(ARABIC_LAST);
  await expect(letterhead).toContainText(ENGLISH_LAST);
});

test('the three blocks sit at the two edges and the centre, not around the logo', async ({
  page,
}) => {
  // The agency's requirement is geometric: Arabic flush with the right margin, the mark
  // exactly centred, English flush with the left margin. An earlier version satisfied the
  // words ("Arabic right, English left") while pushing both blocks *towards* the logo, so
  // the band read as three items huddled in the middle. Measuring the boxes is the only
  // assertion that catches that.
  await page.goto('/login');
  const band = page.locator('header.letterhead').first();
  await expect(band).toBeVisible({ timeout: 30_000 });

  const box = await band.boundingBox();
  expect(box).not.toBeNull();
  const bandBox = box!;

  const englishBlock = band.locator(':scope > div').nth(0);
  const logoCell = band.locator(':scope > div').nth(1);
  const arabicBlock = band.locator(':scope > div').nth(2);

  const english = await englishBlock.locator(':scope > div').first().boundingBox();
  const arabic = await arabicBlock.locator(':scope > div').first().boundingBox();
  const logo = await logoCell.boundingBox();
  expect(english && arabic && logo).toBeTruthy();

  const TOLERANCE = 16; // the band's own 2px padding, plus sub-pixel rounding
  // English touches the left edge …
  expect(Math.abs(english!.x - bandBox.x)).toBeLessThanOrEqual(TOLERANCE);
  // … Arabic touches the right edge …
  expect(
    Math.abs(arabic!.x + arabic!.width - (bandBox.x + bandBox.width)),
  ).toBeLessThanOrEqual(TOLERANCE);
  // … and there is real space between each block and the mark, not a shared cluster
  expect(logo!.x - (english!.x + english!.width)).toBeGreaterThanOrEqual(12);
  expect(arabic!.x - (logo!.x + logo!.width)).toBeGreaterThanOrEqual(12);
});

test('the administrator edits the letterhead and uploads the logo', async ({ browser, baseURL }) => {
  await withSignedInPage(browser, baseURL, 'admin', async (page) => {
    await open(page, '/settings');
    await expect(page.getByRole('heading', { name: 'إعداد الترويسة' })).toBeVisible({
      timeout: 30_000,
    });

    // ── the logo ────────────────────────────────────────────────────────────
    await page.setInputFiles('[data-testid="logo-input"]', LOGO);
    await expect(page.locator('body')).toContainText(
      bilingual('رُفع الشعار', 'Logo uploaded'),
      { timeout: 30_000 },
    );
    // WEBP cannot be embedded by the PDF engine, so the server converts it and says so
    await expect(page.locator('body')).toContainText(/PNG|SHA-256/);

    // the shell now shows the uploaded mark instead of the placeholder
    const shellLogo = page.locator('aside img[alt*="شعار"]').first();
    await expect(shellLogo).toBeVisible({ timeout: 30_000 });
    await expect(shellLogo).toHaveAttribute('src', /branding\/logo/);

    // ── the text ────────────────────────────────────────────────────────────
    const firstArabic = page.getByLabel('السطر العربي 1');
    await expect(firstArabic).toHaveValue('الجمهورية اليمنية');
    await firstArabic.fill('الجمهورية اليمنية — وزارة الصحة');
    await page.getByRole('button', { name: bilingual('حفظ الترويسة', 'Save letterhead') }).click();
    await expect(page.locator('body')).toContainText(/حُفظت الترويسة|Letterhead saved/, {
      timeout: 30_000,
    });
    await expect(firstArabic).toHaveValue('الجمهورية اليمنية — وزارة الصحة');

    // the letterhead is public, so a fresh visit to the sign-in screen shows the
    // edited line without a session
    const anonymous = await browser.newContext({ baseURL, locale: 'ar-YE' });
    try {
      const fresh = await anonymous.newPage();
      await fresh.goto('/login');
      await expect(fresh.locator('header.letterhead').first()).toContainText(
        'الجمهورية اليمنية — وزارة الصحة',
        { timeout: 30_000 },
      );
    } finally {
      await anonymous.close();
    }

    // ── restore, so the suite leaves the official wording behind ────────────
    await page.getByRole('button', { name: bilingual('استعادة الافتراضي', 'Restore defaults') }).click();
    await expect(page.locator('body')).toContainText(/استُعيدت الترويسة|official default/, {
      timeout: 30_000,
    });
    await expect(page.getByLabel('السطر العربي 1')).toHaveValue('الجمهورية اليمنية');
  });
});

test('a quality officer may read the screen but not change it', async ({ page }) => {
  await signInAs(page, 'qa');
  await open(page, '/settings');
  await expect(page.getByRole('heading', { name: 'إعداد الترويسة' })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.locator('body')).toContainText(/صلاحية|permission/i);
  await expect(
    page.getByRole('button', { name: bilingual('حفظ الترويسة', 'Save letterhead') }),
  ).toBeDisabled();
});

test('printing a page prints the letterhead, not the navigation', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/');
  const printed = page.locator('.print-only .letterhead').first();
  // hidden on screen…
  await expect(printed).toBeHidden();
  // …and part of the printed document
  await page.emulateMedia({ media: 'print' });
  await expect(printed).toBeVisible();
  await expect(printed).toContainText('الجمهورية اليمنية');
});
