/**
 * The registers a quality manager actually opens: deviations, due-date notices, the
 * instrument register, and the immutable audit trail — including the server-side
 * chain verification, which must still be intact after the approvals this suite
 * performed.
 *
 * The audit trail needs `audit.view`, which belongs to QA_APPROVER and the admins,
 * not to an analyst; that test therefore runs in the QA session from global setup.
 */

import { bilingual, open, settle, signInAs, withSignedInPage } from './lib/browser';
import { expect, test } from './lib/fixtures';

test('deviations register renders with the OOS controls', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/deviations');
  await expect(
    page.getByText(bilingual('سجل الانحرافات خارج المواصفة (OOS)', 'Out-of-specification deviations')).first(),
  ).toBeVisible({ timeout: 30_000 });
  // An empty state and a populated table are both valid; a blank page is not.
  await expect(page.locator('body')).toContainText(/انحراف|deviation/i);
});

test('due-date notices and the scheduler status render', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/notifications');
  await expect(page.getByText(bilingual('إشعارات الانتهاء والمعايرة', 'Due-date notices')).first()).toBeVisible({
    timeout: 30_000,
  });
  // The delivery provider is stated honestly: no mail transport is configured in
  // this stack, so notices stay in-app rather than pretending to be sent.
  await expect(page.locator('body')).toContainText(/داخل التطبيق|in-app/i);
  await expect(page.locator('body')).toContainText(/لا توجد إشعارات|No notices|إشعار/);
});

test('the instrument register lists the seeded instruments', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/control');
  await expect(page.getByText(bilingual('سجل الأجهزة', 'Instrument register')).first()).toBeVisible({
    timeout: 30_000,
  });
  // The register is the authoritative list of agency instruments, each with its
  // calibration interval and due date.
  await expect(page.locator('body')).toContainText('SBDMA-CHEM-HPLC-001');
  await expect(page.locator('body')).toContainText(/LC-2050C/);
  await expect(page.locator('body')).toContainText(/\d{3}d/);
});

test('the audit trail lists chained records and verifies intact', async ({ browser, baseURL }) => {
  await withSignedInPage(browser, baseURL, 'qa', async (page) => {
    await open(page, '/audit');
    await expect(
      page.getByText(bilingual('سجل التدقيق غير القابل للتعديل', 'Immutable audit trail')).first(),
    ).toBeVisible({ timeout: 30_000 });

    await page.getByRole('button', { name: bilingual('التحقق من السلسلة', 'Verify chain') }).click();

    // The server recomputes every SHA-256 link from the stored rows; a single
    // mutated record surfaces here as a broken chain.
    await expect(page.getByText(bilingual('سلسلة التدقيق سليمة', 'Audit chain intact')).first()).toBeVisible({
      timeout: 60_000,
    });
    await settle(page);
  });
});

test('every page an analyst needs is reachable without a redirect to login', async ({ page }) => {
  await signInAs(page, 'analyst');
  for (const path of ['/', '/lab', '/qa', '/engineering', '/control', '/deviations', '/notifications']) {
    await open(page, path);
    await expect(page, `${path} bounced a signed-in analyst to /login`).not.toHaveURL(/\/login/);
    await expect(page.locator('body')).not.toBeEmpty();
  }
});
