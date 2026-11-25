/**
 * UI helpers shared by the specs.
 *
 * Every selector here is a *user-visible* thing (role + bilingual label, or the
 * `data-field` attributes the lab panel exposes for exactly this purpose). Nothing
 * reaches into React internals, so a refactor that keeps the screen honest keeps
 * the suite green.
 */

import { expect, type Browser, type Page } from '@playwright/test';

import { ACCOUNTS, type AccountKey } from './accounts';
import { readState, storageStatePath, writeState } from './state';
import { Totp } from './totp';

/**
 * Console noise that is a legitimate part of the app's behaviour: the 401 an
 * anonymous visitor gets while discovering there is no session, the 403 a role gets
 * for a control it may not use, and a missing favicon.
 */
export const TOLERATED_CONSOLE = [
  /\b401\b/,
  /\b403\b/,
  /favicon/i,
  /Failed to load resource: the server responded with a status of 4\d\d/,
];

/** Launch a page in a saved session, failing the callback on browser-side errors. */
export async function withSignedInPage<T>(
  browser: Browser,
  baseURL: string | undefined,
  key: AccountKey,
  body: (page: Page) => Promise<T>,
): Promise<T> {
  const context = await browser.newContext({
    baseURL,
    storageState: storageStatePath(key),
    viewport: { width: 1500, height: 1000 },
    locale: 'ar-YE',
    acceptDownloads: true,
  });
  const errors: string[] = [];
  try {
    const page = await context.newPage();
    page.on('console', (message) => {
      if (message.type() !== 'error') return;
      const text = message.text();
      if (TOLERATED_CONSOLE.some((pattern) => pattern.test(text))) return;
      errors.push(text);
    });
    page.on('pageerror', (error) => errors.push(String(error)));
    const result = await body(page);
    expect(errors, `browser console errors in the ${key} session`).toEqual([]);
    return result;
  } finally {
    await context.close();
  }
}

/** The app renders Arabic by default and English when the user switches. */
export function bilingual(ar: string, en: string): RegExp {
  const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`${escape(ar)}|${escape(en)}`);
}

/**
 * Sign in through the login form, exactly as a person does.
 *
 * Accounts whose role mandates a second factor get a fresh code; the counter is
 * written back to the shared state so a later sign-in in the same run cannot replay
 * a spent code (the server rejects replays by design).
 */
export async function signInAs(page: Page, key: AccountKey): Promise<void> {
  const account = ACCOUNTS[key];
  await page.goto('/login');
  await page.waitForSelector('#username');
  await page.fill('#username', account.username);
  await page.fill('#password', account.password);
  await page.getByRole('button', { name: bilingual('دخول', 'Sign in') }).click();

  const totpField = page.locator('#totp');
  const enrolment = page.locator('input[placeholder="000000"]');

  // The password step can end in three ways: signed in, a code is demanded, or the
  // account still has to enrol. The suite only ever sees the first two.
  await Promise.race([
    page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30_000 }),
    totpField.waitFor({ state: 'visible', timeout: 30_000 }),
    enrolment.waitFor({ state: 'visible', timeout: 30_000 }),
  ]).catch(() => undefined);

  if (await totpField.isVisible().catch(() => false)) {
    const state = readState();
    const stored = state.mfa[key];
    if (!stored) {
      throw new Error(`${account.username} demands a code but global setup stored no secret`);
    }
    const totp = new Totp(stored);
    const { code, counter } = totp.reserve();
    await page.fill('#totp', code);
    await page.getByRole('button', { name: bilingual('دخول', 'Sign in') }).click();
    await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30_000 });
    totp.commit(counter);
    state.mfa[key] = totp.state;
    writeState(state);
  }

  if (await enrolment.isVisible().catch(() => false)) {
    throw new Error(
      `${account.username} was routed to enrolment — global setup should have enrolled it first`,
    );
  }

  await expect(page).not.toHaveURL(/\/login/);
}

/** Sign out through the identity menu (the only place the action exists). */
export async function signOut(page: Page): Promise<void> {
  await page.locator('button[aria-haspopup="menu"]').first().click();
  await page.getByRole('menuitem', { name: bilingual('تسجيل الخروج', 'Sign out') }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
}

/**
 * Navigate and wait until the page has stopped talking to the API.
 *
 * The panel fetches limits, instruments and history on mount; asserting on text
 * before those land is how a suite becomes flaky.
 */
export async function open(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' });
  await settle(page);
}

/** Wait for the in-flight `/api/v1/*` chatter to go quiet (max ~12 s). */
export async function settle(page: Page, quietRounds = 6): Promise<void> {
  let quiet = 0;
  for (let attempt = 0; attempt < 40 && quiet < quietRounds; attempt += 1) {
    const seen = await page
      .waitForResponse((response) => response.url().includes('/api/v1/'), { timeout: 400 })
      .then(() => true)
      .catch(() => false);
    quiet = seen ? 0 : quiet + 1;
  }
}

export interface FieldValue {
  [key: string]: number | string | Array<number | string>;
}

/**
 * Type the reference dataset into the lab panel.
 *
 * T13 tests sit behind one tab each; the panel re-mounts its inputs per tab, so the
 * tab is clicked before its fields are filled.
 */
export async function fillLabForm(page: Page, inputs: Record<string, FieldValue>): Promise<void> {
  for (const [code, values] of Object.entries(inputs)) {
    await page.locator(`button:has-text("${code}")`).first().click();
    for (const [key, value] of Object.entries(values)) {
      if (Array.isArray(value)) {
        for (const [index, item] of value.entries()) {
          const locator = page.locator(`[data-field="${code}.${key}.${index}"]`);
          if ((await locator.count()) > 0) await locator.first().fill(String(item));
        }
        continue;
      }
      const locator = page.locator(`[data-field="${code}.${key}"]`);
      if ((await locator.count()) === 0) continue;
      const tag = await locator
        .first()
        .evaluate((element) => element.tagName)
        .catch(() => 'INPUT');
      if (tag === 'SELECT') await locator.first().selectOption(String(value));
      else await locator.first().fill(String(value));
    }
  }
}

/** Open the newest item in a queue list (`/qa` shows one list of runs). */
export async function openNewestRun(page: Page, runCode?: string): Promise<void> {
  if (runCode) {
    const item = page.locator('li', { hasText: runCode }).locator('button').first();
    if ((await item.count()) > 0) {
      await item.click();
      return;
    }
  }
  await page.locator('li button').first().click();
}
