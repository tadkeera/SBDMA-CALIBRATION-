/**
 * Pre-flight for the whole suite.
 *
 * 1. Refuse to start unless the API is up and reports a live database — a browser
 *    run against a dead backend produces forty confusing timeouts instead of one
 *    honest failure.
 * 2. Record the run ids that already exist, so the lifecycle spec can identify the
 *    calibration *it* created instead of trusting queue order.
 * 3. Enrol the second factor for the roles that mandate one (SUPERVISOR,
 *    QA_APPROVER) and sign each of them in *through the login form*, including the
 *    authenticator code field. The resulting cookie jar is saved as a Playwright
 *    storage state, so the specs that need those roles start from a real UI session.
 */

import { chromium } from '@playwright/test';

import { ACCOUNTS, MFA_ACCOUNTS } from './lib/accounts';
import { ApiFailure, activate, enrol, health, listRuns, login, newApiSession } from './lib/api';
import { signInAs } from './lib/browser';
import { readState, storageStatePath, writeState, type SuiteState } from './lib/state';
import { Totp } from './lib/totp';

function tryReadState(): SuiteState | null {
  try {
    return readState();
  } catch {
    return null;
  }
}

export default async function globalSetup(): Promise<void> {
  const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000';
  const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:3000';

  // ---- 1. the API must be alive and connected to a database ------------------
  const probe = await newApiSession();
  try {
    const report = await health(probe);
    if (report.status !== 'ok') {
      throw new Error(`API health is "${report.status}", expected "ok" (${JSON.stringify(report)})`);
    }
  } finally {
    await probe.dispose();
  }

  // ---- 2. baseline runs ------------------------------------------------------
  const analyst = await newApiSession();
  let baselineRunIds: string[] = [];
  try {
    await login(analyst, ACCOUNTS.analyst.username, ACCOUNTS.analyst.password);
    baselineRunIds = (await listRuns(analyst, 100)).map((run) => run.id);
  } catch (error) {
    throw new Error(
      'the analyst account could not sign in — run `npm run e2e:prepare` first. ' +
        `Underlying error: ${(error as Error).message}`,
    );
  } finally {
    await analyst.dispose();
  }

  const previous = tryReadState();
  const state: SuiteState = {
    createdAt: new Date().toISOString(),
    apiOrigin,
    baseURL,
    baselineRunIds,
    mfa: {},
  };
  // Written before the first UI sign-in: `signInAs` reads this file to derive codes.
  writeState(state);

  const browser = await chromium.launch();
  try {
    for (const key of MFA_ACCOUNTS) {
      const account = ACCOUNTS[key];

      // ---- 3a. make sure the account has an enrolled second factor ----------
      const stored = previous?.mfa[key];
      if (stored) {
        state.mfa[key] = stored;
        writeState(state);
        console.log(`  ${account.username}: reusing the stored second factor`);
      } else {
        const session = await newApiSession();
        try {
          const result = await login(session, account.username, account.password).catch(
            (error: unknown) => {
              if (error instanceof ApiFailure && error.code === 'SECOND_FACTOR_REQUIRED') {
                throw new Error(
                  `${account.username} is already enrolled in two-step verification but no ` +
                    'secret was carried over. The E2E database is not fresh — run ' +
                    '`npm run e2e:prepare` to rebuild it.',
                );
              }
              throw error;
            },
          );
          if (!result.user.mfa_enrolment_required) {
            console.log(`  ${account.username}: no second factor required`);
            continue;
          }
          const { secret } = await enrol(session);
          const totp = new Totp({ secret, lastCounter: null });
          const activation = totp.reserve();
          await activate(session, activation.code);
          totp.commit(activation.counter);
          state.mfa[key] = totp.state;
          writeState(state);
          console.log(`  ${account.username}: two-step verification enrolled`);
        } finally {
          await session.dispose();
        }
      }

      // ---- 3b. sign in through the form, entering the authenticator code ----
      const context = await browser.newContext({
        baseURL,
        viewport: { width: 1500, height: 1000 },
        locale: 'ar-YE',
      });
      try {
        const page = await context.newPage();
        await signInAs(page, key);
        await context.storageState({ path: storageStatePath(key) });
        console.log(`  ${account.username}: signed in through the UI, session saved`);
      } finally {
        await context.close();
      }

      // `signInAs` persisted the counter it spent; adopt it before the next account.
      const refreshed = tryReadState();
      if (refreshed?.mfa[key]) state.mfa[key] = refreshed.mfa[key];
      writeState(state);
    }
  } finally {
    await browser.close();
  }

  writeState(state);
  console.log(
    `global setup: ${baselineRunIds.length} existing run(s), ` +
      `${Object.keys(state.mfa).length} second factor(s) ready`,
  );
}
