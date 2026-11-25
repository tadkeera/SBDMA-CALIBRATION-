/**
 * Playwright fixture that turns browser console noise into a test failure.
 *
 * A calibration platform that renders a plausible page while its client is throwing
 * is worse than one that fails loudly, so every spec asserts a clean console. The
 * only tolerated messages are the ones the app legitimately produces: the 401 that
 * an anonymous visitor gets while discovering there is no session, and a missing
 * favicon.
 */

import { expect, test as base } from '@playwright/test';

import { TOLERATED_CONSOLE } from './browser';

export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on('console', (message) => {
        if (message.type() !== 'error') return;
        const text = message.text();
        if (TOLERATED_CONSOLE.some((pattern) => pattern.test(text))) return;
        errors.push(text);
      });
      page.on('pageerror', (error) => errors.push(String(error)));

      await use(errors);

      expect(errors, 'the browser console reported errors').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
