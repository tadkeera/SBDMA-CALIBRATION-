/**
 * Authentication and authorisation through the real UI.
 *
 * These tests pin the behaviour a reviewer of the system would check first: an
 * anonymous visitor cannot see a protected page, a wrong password yields no
 * session, a correct one yields a cookie-backed session that survives a reload,
 * signing out really ends it, and a read-only role stays read-only.
 */

import { ACCOUNTS } from './lib/accounts';
import { bilingual, open, signInAs, signOut } from './lib/browser';
import { expect, test } from './lib/fixtures';

test.describe('identity', () => {
  test('an anonymous visitor is redirected to the login page', async ({ page }) => {
    await page.goto('/qa');
    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
  });

  test('a wrong password is refused and leaves no session behind', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#username', ACCOUNTS.analyst.username);
    await page.fill('#password', 'definitely-not-the-password-1');
    await page.getByRole('button', { name: bilingual('دخول', 'Sign in') }).click();

    await expect(page).toHaveURL(/\/login/);
    // The server's own words, not a client-side guess.
    await expect(
      page.getByText(bilingual('بيانات الدخول غير صحيحة', 'Invalid credentials')),
    ).toBeVisible({ timeout: 20_000 });

    // A refused sign-in must not have planted a usable cookie.
    const me = await page.request.get('/api/v1/auth/me');
    expect(me.status()).toBe(401);
  });

  test('the analyst signs in and keeps the session across a reload', async ({ page }) => {
    await signInAs(page, 'analyst');

    await expect(page).not.toHaveURL(/\/login/);
    // the laboratory is entered through its units since 2.4.0: the shelf, then the unit,
    // then the test — the analyst's path through the twenty protocol tests
    await open(page, '/lab/units');
    await page.locator('main a[href^="/lab/"][href*="-"]').first().click();
    await expect(page.locator('a[href*="/T02"]').first()).toBeVisible({ timeout: 30_000 });
    await page.locator('a[href*="/T02"]').first().click();
    await expect(page.getByRole('button', { name: /Run Calibration|تشغيل المعايرة/ })).toBeVisible();

    const me = await page.request.get('/api/v1/auth/me');
    expect(me.ok()).toBeTruthy();
    const envelope = (await me.json()) as { data: { username: string; roles: string[] } };
    expect(envelope.data.username).toBe(ACCOUNTS.analyst.username);
    expect(envelope.data.roles).toContain('ANALYST');

    // The session is an httpOnly cookie, so a full reload stays signed in and no
    // token is reachable from JavaScript.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page).not.toHaveURL(/\/login/);
    const tokenVisible = await page.evaluate(() => {
      const dump = `${JSON.stringify(window.localStorage)}${JSON.stringify(window.sessionStorage)}`;
      return /eyJ[A-Za-z0-9_-]{10,}/.test(dump);
    });
    expect(tokenVisible, 'a JWT is reachable from browser storage').toBe(false);
  });

  test('signing out ends the session for real', async ({ page }) => {
    await signInAs(page, 'analyst');
    await open(page, '/control');
    await signOut(page);

    await open(page, '/qa');
    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
    const me = await page.request.get('/api/v1/auth/me');
    expect(me.status()).toBe(401);
  });

  test('a read-only viewer may read the register but not administer it', async ({ page }) => {
    await signInAs(page, 'viewer');

    // Reading is allowed…
    const runs = await page.request.get('/api/v1/runs?page=1&page_size=5');
    expect(runs.status()).toBe(200);

    // …administration is not, and the refusal comes from the server.
    const users = await page.request.get('/api/v1/users');
    expect(users.status(), 'a viewer must not be able to read the user register').toBe(403);

    // The same rule reaches the screen: a viewer is not an operator of the laboratory at
    // all, so the laboratory route sends it back to its own landing screen rather than
    // showing a test page with a disabled button.
    await open(page, '/lab/units');
    await expect(page).not.toHaveURL(/\/lab/, { timeout: 30_000 });
    const shelf = await page.request.get('/api/v1/instruments');
    expect(shelf.status(), 'a viewer may read the register').toBe(200);
  });
});
