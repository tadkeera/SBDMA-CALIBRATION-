/**
 * End-to-end suite configuration.
 *
 * Two servers are started around the tests and torn down after them:
 *   - FastAPI (uvicorn) on :8000, pointed at the disposable E2E database;
 *   - the production Next.js build on :3000, whose `/api/v1/*` rewrite proxies to
 *     the API — the same wiring the deployed system uses, so the suite exercises
 *     same-origin cookies rather than a CORS shortcut.
 *
 * `npm run e2e:prepare` must have run once (it rebuilds the database and seeds the
 * E2E passwords); global setup refuses to start otherwise.
 */

import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { defineConfig, devices } from '@playwright/test';

const ROOT = __dirname;
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:3000';
const API_ORIGIN = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000';

/** Prefer the repository virtualenv; fall back to whatever `python` resolves to. */
const PYTHON = existsSync(join(ROOT, '.venv', 'bin', 'python'))
  ? join(ROOT, '.venv', 'bin', 'python')
  : 'python';

/**
 * Environment for the API under test.
 *
 * `COOKIE_SECURE=false` is not a weakening of the system: the suite runs over plain
 * HTTP on loopback, and a `Secure` cookie would simply never come back, making every
 * authenticated request fail. Production keeps the default (`true`).
 *
 * The auth rate limit is raised because the suite signs in several times on purpose;
 * the limiter itself is covered by the backend tests (`test_rate_limit.py`), where a
 * low budget is asserted directly.
 */
const API_ENV = {
  ENVIRONMENT: 'test',
  DATABASE_URL:
    process.env.E2E_DATABASE_URL ??
    'postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432/sbdma_e2e',
  JWT_SECRET: process.env.E2E_JWT_SECRET ?? 'e2e-only-jwt-secret-not-used-anywhere-else-0123456789',
  MFA_ENCRYPTION_KEY: process.env.E2E_MFA_KEY ?? 'e2e-only-mfa-key-not-used-anywhere-else-9876543210',
  COOKIE_SECURE: 'false',
  RATE_LIMIT_BACKEND: 'memory',
  RATE_LIMIT_PER_MINUTE: '10000',
  RATE_LIMIT_AUTH_PER_MINUTE: '300',
  SCHEDULER: 'celery',
  STORAGE_PATH: process.env.E2E_STORAGE_PATH ?? '/tmp/sbdma-e2e-storage',
  CORS_ORIGINS: BASE_URL,
};

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  // A calibration run filled in by hand, three signatures and a PDF export take time.
  timeout: 180_000,
  expect: { timeout: 20_000 },
  // The lifecycle spec is a serial story; one worker keeps the story, and the
  // single-use TOTP counters, unambiguous.
  fullyParallel: false,
  workers: 1,
  // Retries would repeat a sign-in whose code was already spent, so a flake here is
  // a real failure worth seeing rather than something to paper over.
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }], ['github']]
    : [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1500, height: 1000 },
    locale: 'ar-YE',
    timezoneId: 'Asia/Aden',
    acceptDownloads: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1500, height: 1000 } },
    },
  ],
  webServer: [
    {
      name: 'api',
      command: `${PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: join(ROOT, 'backend'),
      url: `${API_ORIGIN}/api/v1/health`,
      env: API_ENV,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'web',
      // The suite runs the production build: dev-mode compiles make the timings
      // meaningless and hide production-only behaviour.
      command: 'npm run build && npm run start',
      cwd: ROOT,
      url: `${BASE_URL}/login`,
      env: { ...process.env, API_ORIGIN, NEXT_TELEMETRY_DISABLED: '1' } as Record<string, string>,
      reuseExistingServer: !process.env.CI,
      timeout: 300_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
});
