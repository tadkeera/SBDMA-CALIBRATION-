/**
 * RFC 6238 TOTP, verified against the same secret the server holds.
 *
 * The suite must be able to sign in as the roles that mandate a second factor
 * (SUPERVISOR, QA_APPROVER) with no phone in the loop. The enrolment API
 * hands the secret back exactly once, so the suite keeps it and derives codes the
 * way an authenticator app would.
 *
 * One server rule shapes every helper here: a code may be spent only once
 * (`users.totp_last_counter` is monotonic). Since `MFA_VALID_WINDOW` is 1, an
 * account has at most two usable counters per 30 s step, so `Totp.next()` always
 * returns the *next unused* counter and never replays one.
 */

import { createHmac } from 'node:crypto';

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
export const STEP_SECONDS = 30;

/** Decode an RFC 4648 base32 string (no padding required) into bytes. */
export function base32Decode(secret: string): Buffer {
  const cleaned = secret.replace(/=+$/, '').replace(/\s+/g, '').toUpperCase();
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const char of cleaned) {
    const index = BASE32_ALPHABET.indexOf(char);
    if (index === -1) throw new Error(`invalid base32 character: ${char}`);
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

/** The 30-second step number for a point in time (Unix epoch based). */
export function counterAt(nowMs: number = Date.now()): number {
  return Math.floor(nowMs / 1000 / STEP_SECONDS);
}

/** HOTP value for an explicit counter, as six zero-padded digits. */
export function codeForCounter(secret: string, counter: number): string {
  const key = base32Decode(secret);
  const message = Buffer.alloc(8);
  message.writeUInt32BE(Math.floor(counter / 2 ** 32), 0);
  message.writeUInt32BE(counter % 2 ** 32, 4);
  const digest = createHmac('sha1', key).update(message).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    (digest[offset + 1] << 16) |
    (digest[offset + 2] << 8) |
    digest[offset + 3];
  return String(binary % 1_000_000).padStart(6, '0');
}

export interface TotpState {
  secret: string;
  /** Highest counter already spent on the server; `null` before the first code. */
  lastCounter: number | null;
}

/**
 * A single account's authenticator, persisting the spent counter.
 *
 * `reserve()` returns `{ code, counter }`; the caller writes `counter` back into
 * the state file once the server has accepted it.
 */
export class Totp {
  private readonly secret: string;
  private lastCounter: number | null;

  constructor(state: TotpState) {
    this.secret = state.secret;
    this.lastCounter = state.lastCounter;
  }

  get state(): TotpState {
    return { secret: this.secret, lastCounter: this.lastCounter };
  }

  /** Current code without spending a counter (for assertions only). */
  peek(nowMs: number = Date.now()): string {
    return codeForCounter(this.secret, counterAt(nowMs));
  }

  /**
   * The next code the server will accept.
   *
   * Prefers the current step; falls back to `lastCounter + 1` when that step was
   * already spent (the enrol → sign-in sequence inside one step). The server
   * accepts ±1 step of drift, so `lastCounter + 1` is in range for a sign-in that
   * follows activation within a minute.
   */
  reserve(nowMs: number = Date.now()): { code: string; counter: number } {
    const now = counterAt(nowMs);
    const counter = this.lastCounter === null ? now : Math.max(now, this.lastCounter + 1);
    return { code: codeForCounter(this.secret, counter), counter };
  }

  /** Record that `counter` was accepted by the server. */
  commit(counter: number): void {
    this.lastCounter = this.lastCounter === null ? counter : Math.max(this.lastCounter, counter);
  }
}
