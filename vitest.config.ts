import { defineConfig } from 'vitest/config';

/**
 * Unit tests for the browser engine and the API adapters.
 *
 * `e2e/**` is excluded on purpose: those files are Playwright specs, which declare
 * tests against a running system and cannot be collected by Vitest.
 */
export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    exclude: ['node_modules/**', 'e2e/**', 'playwright-report/**', 'test-results/**', '.next/**'],
    environment: 'node',
  },
});
