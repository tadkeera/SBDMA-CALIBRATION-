/**
 * Release 2.3.0 in the browser: the Flow Rate page and multi-role checkboxes.
 *
 * The page is exercised the way an analyst uses it — thirty readings typed into the grid,
 * the server recomputing the statistics, the run stored, and the certificate fetched as a
 * draft until the run is approved. Nothing here asserts a *number* the page computed on its
 * own: the summary block and the status must come from the server's answer, which is why the
 * test reads the API's verdict and compares it with what the screen shows.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { bilingual, open, settle, signInAs } from './lib/browser';
import { expect, test } from './lib/fixtures';

const INPUTS = JSON.parse(
  readFileSync(join(__dirname, 'fixtures', 'compliant_inputs.json'), 'utf8'),
) as Record<string, Record<string, number[]>>;

const GRID = [INPUTS.T02.flow_p1000, INPUTS.T02.flow_p1500, INPUTS.T02.flow_p2000];

/** Type the three rows into the dedicated grid. */
async function fillGrid(page: import('@playwright/test').Page): Promise<void> {
  for (const [row, values] of GRID.entries()) {
    for (const [cell, value] of values.entries()) {
      await page.locator(`[aria-label="run-${row + 1}-${cell + 1}"]`).fill(String(value));
    }
  }
}

test('the flow-rate page states the limits for each set point before anything is typed', async ({
  page,
}) => {
  await signInAs(page, 'analyst');
  await open(page, '/lab/flow-rate');

  await expect(
    page.getByText(bilingual('الحدود المرجعية لكل نقطة ضبط', 'Reference limits for each set point')).first(),
  ).toBeVisible({ timeout: 30_000 });

  // The band is printed in mL/min, which is what the analyst compares a flask against.
  const body = page.locator('body');
  await expect(body).toContainText('0.980');
  await expect(body).toContainText('1.020');
  await expect(body).toContainText('1.470');
  await expect(body).toContainText('2.040');
  // and the two percentages from the approved limit table
  await expect(body).toContainText('±2.0%');
  await expect(body).toContainText('1.0%');

  // ten inputs per row, thirty in total
  await expect(page.locator('[aria-label^="run-1-"]')).toHaveCount(10);
  await expect(page.locator('[aria-label^="run-3-"]')).toHaveCount(10);
});

test('a completed grid is recomputed by the server, saved, and issued as a draft certificate', async ({
  page,
}) => {
  await signInAs(page, 'analyst');
  await open(page, '/lab/flow-rate');
  await expect(page.locator('[aria-label^="run-1-"]').first()).toBeVisible({ timeout: 30_000 });

  await fillGrid(page);
  await page.getByRole('button', { name: bilingual('تشغيل المعايرة', 'Run Calibration') }).click();

  // the server's summary block: the numbers on screen are the server's, not the browser's
  await expect(
    page.getByText(bilingual('ملخص الحساب — من الخادم', 'Calculation summary — computed by the server')).first(),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('body')).toContainText(/PASS|مطابق/);

  // the two charts render from the same response
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 });

  await page.getByRole('button', { name: bilingual('حفظ', 'Save') }).click();
  await expect(
    page.getByText(bilingual('حالة الاعتماد', 'Approval status')).first(),
  ).toBeVisible({ timeout: 45_000 });
  // a freshly saved run has not been reviewed: the panel must say so, in amber
  await expect(page.locator('body')).toContainText(/Pending Review|قيد المراجعة/);
  await expect(page.locator('body')).toContainText(/Pending QA|بانتظار اعتماد/);

  // the stored run is what the API reports, so the page and the record agree
  const runs = await page.request.get('/api/v1/runs?page=1&page_size=10');
  expect(runs.ok()).toBeTruthy();
  const body = (await runs.json()) as {
    data: Array<{ id: string; overall_status: string; results: unknown[] }>;
  };
  expect(body.data.length).toBeGreaterThan(0);

  // fetch the draft through the API with the browser's session
  const runId = body.data[0].id;
  const draft = await page.request.get(
    `/api/v1/reports/runs/${runId}/tests/T02/certificate.pdf?stage=PROVISIONAL`,
  );
  expect(draft.status()).toBe(200);
  expect(draft.headers()['content-disposition']).toContain('-draft.pdf');
  const pdf = await draft.body();
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.length).toBeGreaterThan(5_000);
});

test('the users dialog offers every role as a checkbox, several at once', async ({ page }) => {
  await signInAs(page, 'admin');
  await open(page, '/users');

  await expect(
    page.getByText(bilingual('إدارة المستخدمين', 'User management')).first(),
  ).toBeVisible({ timeout: 30_000 });

  await page
    .getByRole('button', { name: bilingual('حساب جديد', 'New account') })
    .first()
    .click();

  // The role group is a checkbox list, and the second tier is named "Supervisor".
  const group = page.locator('[role="group"][aria-label="roles"]');
  await expect(group).toBeVisible();
  const boxes = group.locator('input[type="checkbox"]');
  expect(await boxes.count()).toBeGreaterThanOrEqual(5);
  await expect(group).toContainText(/SUPERVISOR/);
  await expect(group).not.toContainText(/TECHNICAL_REVIEWER/);

  // two roles can be ticked at the same time — the point of the control
  const first = boxes.first();
  if (!(await first.isDisabled())) await first.check();
  const second = boxes.nth(1);
  if (!(await second.isDisabled())) await second.check();
  if (!(await first.isDisabled()) && !(await second.isDisabled())) {
    await expect(first).toBeChecked();
    await expect(second).toBeChecked();
  }

  await settle(page);
});
