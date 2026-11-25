/**
 * The whole governed workflow, in the browser, against the real server:
 *
 *   analyst fills the 13 tests → engine verdict PASS → run is stored
 *   → reviewer signs the technical review → QA approves and locks it
 *   → certificate PDF and Excel export download as real files.
 *
 * Serial by construction: each step depends on the state the previous one produced,
 * which is exactly the property being tested — segregation of duties across three
 * different humans. The run created here is identified by diffing the API list
 * against the ids recorded in global setup, never by trusting queue order.
 *
 * The analyst signs in through the form here; the reviewer and QA reuse the UI
 * sessions global setup established (see the note there about single-use codes).
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import type { APIRequestContext } from '@playwright/test';

import { ACCOUNTS } from './lib/accounts';
import {
  bilingual,
  fillLabForm,
  open,
  settle,
  signInAs,
  withSignedInPage,
  type FieldValue,
} from './lib/browser';
import { expect, test } from './lib/fixtures';
import { readState } from './lib/state';

const INPUTS = JSON.parse(
  readFileSync(join(__dirname, 'fixtures', 'compliant_inputs.json'), 'utf8'),
) as Record<string, FieldValue>;

test.describe.configure({ mode: 'serial' });

let runId = '';
let runCode = '';

/** Poll the run list until a run that did not exist at setup appears. */
async function waitForNewRun(
  request: APIRequestContext,
  timeoutMs = 45_000,
): Promise<{ id: string; execution_code: string; overall_status: string }> {
  const baseline = new Set(readState().baselineRunIds);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await request.get('/api/v1/runs?page=1&page_size=20');
    if (response.ok()) {
      const body = (await response.json()) as {
        data: Array<{ id: string; execution_code: string; overall_status: string }>;
      };
      // The panel creates the run and then executes it; only the executed run has a
      // verdict. Waiting for a non-INCOMPLETE new run means the assertion below is
      // about the stored result, not about a half-written row.
      const fresh = body.data.find(
        (run) => !baseline.has(run.id) && run.overall_status !== 'INCOMPLETE',
      );
      if (fresh) return fresh;
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error('the submitted run never appeared in /api/v1/runs');
}

test('the analyst completes the 13 tests and submits a PASS run', async ({ page }) => {
  await signInAs(page, 'analyst');
  await open(page, '/lab');

  // the seeded instrument must be the target before anything is typed (it lives in
  // the instrument picker, so it is an <option>, not visible text)
  await expect(page.locator('select', { hasText: 'LC-2050C' }).first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.locator('[data-field]').first()).toBeVisible();

  await fillLabForm(page, INPUTS);
  await page.getByRole('button', { name: 'Run Calibration' }).click();

  const save = page.getByRole('button', {
    name: bilingual('حفظ وإرسال للمراجعة الفنية', 'Save & submit for review'),
  });
  await expect(save).toBeVisible({ timeout: 30_000 });

  // The preview must agree with the reference dataset before the run is stored: all
  // thirteen protocol tests pass, nothing left under review. (Labels are bilingual,
  // so the count is matched in either language; the stored run is checked below.)
  const dialog = page.locator('[role="dialog"]').last();
  await expect(dialog).toContainText(/(?:مطابق|Pass)\s*13/);
  await expect(dialog).toContainText(/(?:قيد المراجعة|Review)\s*0/);

  // Saving is two server calls by design: create the governed record, then execute
  // the protocol against the stored limits. The second one carries the verdict.
  const executed = page.waitForResponse(
    (response) =>
      /\/api\/v1\/runs\/[0-9a-f-]+\/execute$/.test(response.url()) &&
      response.request().method() === 'POST',
    { timeout: 90_000 },
  );
  await save.click();
  const response = await executed;
  expect(response.status(), 'the server refused the run').toBeLessThan(300);
  const executedBody = (await response.json()) as {
    data: { run: { overall_status: string } };
  };
  expect(executedBody.data.run.overall_status).toBe('PASS');

  const run = await waitForNewRun(page.request);
  runId = run.id;
  runCode = run.execution_code;
  expect(run.overall_status).toBe('PASS');

  // The stored run, not just the preview: thirteen results, every one of them PASS.
  const detail = await page.request.get(`/api/v1/runs/${runId}`);
  const envelope = (await detail.json()) as {
    data: { results: Array<{ test_code: string; status: string }> };
  };
  expect(envelope.data.results).toHaveLength(13);
  expect(envelope.data.results.map((result) => result.status)).toEqual(
    Array.from({ length: 13 }, () => 'PASS'),
  );
});

test('the reviewer signs the technical review', async ({ browser, baseURL }) => {
  expect(runId, 'the analyst step must run first').not.toBe('');

  await withSignedInPage(browser, baseURL, 'reviewer', async (page) => {
    await open(page, '/qa');

    const item = page.locator('li', { hasText: runCode }).locator('button').first();
    await expect(item).toBeVisible({ timeout: 30_000 });
    await item.click();

    // every protocol test is on screen with its own limit comparison
    for (const code of Object.keys(INPUTS)) {
      await expect(page.locator('body')).toContainText(code);
    }

    await page
      .getByRole('button', { name: bilingual('توقيع المراجعة الفنية', 'Sign technical review') })
      .first()
      .click();
    await page.locator('input[type="password"]').fill(ACCOUNTS.reviewer.password);
    await page
      .locator('textarea')
      .first()
      .fill('مراجعة فنية: القراءات مطابقة لبروتوكول المعايرة المعتمد، والانحرافات داخل الحدود');
    await page.getByRole('button', { name: bilingual('توقيع واعتماد', 'Sign and approve') }).click();
    await settle(page);

    const detail = await page.request.get(`/api/v1/runs/${runId}`);
    expect(detail.ok()).toBeTruthy();
    const envelope = (await detail.json()) as {
      data: { reviewer_id: string | null; reviewed_at: string | null };
    };
    expect(envelope.data.reviewer_id, 'the review signature was not recorded').toBeTruthy();
    expect(envelope.data.reviewed_at, 'the review timestamp was not recorded').toBeTruthy();
  });
});

test('QA approves and locks the run', async ({ browser, baseURL }) => {
  expect(runId, 'the analyst step must run first').not.toBe('');

  await withSignedInPage(browser, baseURL, 'qa', async (page) => {
    await open(page, '/qa');

    const item = page.locator('li', { hasText: runCode }).locator('button').first();
    await expect(item).toBeVisible({ timeout: 30_000 });
    await item.click();

    await page
      .getByRole('button', { name: bilingual('اعتماد ضمان الجودة النهائي', 'Final QA approval') })
      .first()
      .click();
    await page.locator('input[type="password"]').fill(ACCOUNTS.qa.password);
    await page
      .locator('textarea')
      .first()
      .fill('اعتماد ضمان الجودة: النتائج مطابقة، والشهادة تُصدر لهذا التشغيل');
    await page.getByRole('button', { name: bilingual('توقيع', 'Sign') }).last().click();
    await settle(page);

    await expect(page.locator('body')).toContainText(/معتمد ومقفل|Approved & locked/);

    const detail = await page.request.get(`/api/v1/runs/${runId}`);
    const envelope = (await detail.json()) as {
      data: {
        is_locked: boolean;
        qa_approver_id: string | null;
        qa_approved_at: string | null;
        certificate_hash: string | null;
        overall_status: string;
      };
    };
    expect(envelope.data.qa_approver_id, 'the QA signature was not recorded').toBeTruthy();
    expect(envelope.data.qa_approved_at, 'the QA timestamp was not recorded').toBeTruthy();
    expect(envelope.data.is_locked, 'an approved run must be locked against edits').toBe(true);
    expect(envelope.data.certificate_hash, 'an approved run must carry its certificate hash').toMatch(
      /^[0-9a-f]{64}$/,
    );
    expect(envelope.data.overall_status).toBe('PASS');
  });
});

test('the certificate and the Excel export download as real files', async ({ browser, baseURL }) => {
  expect(runId, 'the analyst step must run first').not.toBe('');

  await withSignedInPage(browser, baseURL, 'qa', async (page) => {
    await open(page, '/qa');
    const item = page.locator('li', { hasText: runCode }).locator('button').first();
    await expect(item).toBeVisible({ timeout: 30_000 });
    await item.click();

    const pdfDownload = page.waitForEvent('download', { timeout: 60_000 });
    await page.getByRole('button', { name: 'PDF' }).first().click();
    const pdf = await pdfDownload;
    expect(pdf.suggestedFilename()).toContain(runCode);
    const pdfPath = await pdf.path();
    expect(pdfPath).toBeTruthy();
    const pdfBytes = readFileSync(pdfPath!);
    expect(pdfBytes.subarray(0, 5).toString('latin1'), 'the certificate is not a PDF').toBe('%PDF-');
    expect(pdfBytes.byteLength, 'the certificate is suspiciously small').toBeGreaterThan(2_000);

    const xlsxDownload = page.waitForEvent('download', { timeout: 60_000 });
    await page.getByRole('button', { name: 'XLSX' }).first().click();
    const xlsx = await xlsxDownload;
    expect(xlsx.suggestedFilename()).toContain(runCode);
    const xlsxBytes = readFileSync((await xlsx.path())!);
    // OOXML is a zip container: "PK\x03\x04"
    expect(xlsxBytes.subarray(0, 2).toString('latin1')).toBe('PK');

    // The API must hand out the same document to a signed-in session — the button is
    // not the only way in, and the media type has to be right.
    const api = await page.request.get(`/api/v1/reports/runs/${runId}/certificate.pdf`);
    expect(api.status()).toBe(200);
    expect(api.headers()['content-type']).toContain('application/pdf');
  });
});
