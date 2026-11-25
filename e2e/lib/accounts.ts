/**
 * Accounts used by the end-to-end suite, read from `e2e/fixtures/accounts.json`.
 *
 * `e2e/prepare-db.sh` seeds the E2E database from the same file, so the browser and
 * the seeder cannot drift. `E2E_<ROLE>_PASSWORD` overrides the file when a run has
 * to use different strings (the CI job does not need to).
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

export type AccountKey = 'analyst' | 'reviewer' | 'qa' | 'viewer' | 'admin';

interface AccountFileEntry {
  username: string;
  env: string;
  password: string;
}

export interface Account {
  key: AccountKey;
  username: string;
  password: string;
}

const file = JSON.parse(
  readFileSync(join(__dirname, '..', 'fixtures', 'accounts.json'), 'utf8'),
) as Record<string, AccountFileEntry>;

function account(key: AccountKey): Account {
  const entry = file[key];
  if (!entry) throw new Error(`e2e/fixtures/accounts.json has no "${key}" entry`);
  const override = process.env[`E2E_${key.toUpperCase()}_PASSWORD`];
  return { key, username: entry.username, password: override ?? entry.password };
}

export const ACCOUNTS: Record<AccountKey, Account> = {
  analyst: account('analyst'),
  reviewer: account('reviewer'),
  qa: account('qa'),
  viewer: account('viewer'),
  // the administrator owns the letterhead (settings.manage) and, like every
  // administrative role, must present a second factor
  admin: account('admin'),
};

/** Roles that mandate a second factor (mirrors `MFA_ENFORCED_ROLES`). */
export const MFA_ACCOUNTS: AccountKey[] = ['reviewer', 'qa', 'admin'];
