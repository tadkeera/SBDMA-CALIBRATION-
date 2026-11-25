/**
 * The E2E suite signs in as the roles that mandate a second factor, so its TOTP
 * implementation must agree with the server's `pyotp` bit for bit. These are the
 * RFC 4226 Appendix D vectors — the same ones `pyotp` is built to satisfy — so a
 * passing run here means the browser and the API cannot disagree about a code.
 */

import { describe, expect, it } from 'vitest';

import { base32Decode, codeForCounter, counterAt } from '../e2e/lib/totp';

// base32 of the RFC's ASCII secret "12345678901234567890"
const SECRET = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';

describe('TOTP (RFC 4226/6238)', () => {
  it('decodes base32 the way an authenticator app does', () => {
    expect(base32Decode(SECRET).toString('latin1')).toBe('12345678901234567890');
    // padding is optional, case is irrelevant
    expect(base32Decode('mzxw6===').toString('latin1')).toBe('foo');
  });

  it('matches the published six-digit HOTP vectors', () => {
    const expected = [
      '755224',
      '287082',
      '359152',
      '969429',
      '338314',
      '254676',
      '287922',
      '162583',
      '399871',
      '520489',
    ];
    expected.forEach((code, counter) => {
      expect(codeForCounter(SECRET, counter), `counter ${counter}`).toBe(code);
    });
  });

  it('places a timestamp in a 30 second step', () => {
    expect(counterAt(0)).toBe(0);
    expect(counterAt(29_999)).toBe(0);
    expect(counterAt(30_000)).toBe(1);
    // 2026-01-01T00:00:00Z = 1767225600 → a step boundary
    expect(counterAt(Date.UTC(2026, 0, 1))).toBe(58_907_520);
  });

  it('never returns a counter the server has already spent', async () => {
    const { Totp } = await import('../e2e/lib/totp');
    const totp = new Totp({ secret: SECRET, lastCounter: null });
    const first = totp.reserve();
    totp.commit(first.counter);
    const second = totp.reserve();
    // the replay guard is monotonic: a second code inside the same step must move on
    expect(second.counter).toBe(first.counter + 1);
    expect(second.code).not.toBe(first.code);
    // a later step wins over the stored counter
    const later = totp.reserve((first.counter + 10) * 30_000);
    expect(later.counter).toBe(first.counter + 10);
  });
});
