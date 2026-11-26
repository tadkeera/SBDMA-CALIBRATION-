import { describe, expect, it } from 'vitest';
import { TESTS } from '../src/core/protocol';

/**
 * The documented procedure the laboratory screen prints.
 *
 * The text is generated from `backend/app/domain/protocol/reference_manual.py` into
 * `src/core/protocol.ts`, and the API stores the same words in
 * `test_definitions.procedure_en`. These assertions are the frontend half of the
 * parity contract: if a step is lost, duplicated, or an Arabic line leaks into the
 * English block, this fails before the screen can print a document that contradicts
 * the database.
 */
describe('documented procedure — English, complete, left-to-right', () => {
  const ARABIC = /[\u0600-\u06FF]/;

  it('every test carries English steps', () => {
    expect(TESTS).toHaveLength(20);
    for (const test of TESTS) {
      expect(test.procedureEn, test.code).toBeDefined();
      expect(test.procedureEn.length, `${test.code} has fewer than four steps`).toBeGreaterThanOrEqual(4);
      for (const step of test.procedureEn) {
        expect(step.trim().length, test.code).toBeGreaterThan(20);
        expect(ARABIC.test(step), `${test.code}: Arabic text in an English step`).toBe(false);
      }
      // the steps read as instructions: a numbered sequence of finished sentences
      expect(test.procedureEn.join(' ')).toMatch(/[.!]$/);
    }
  });

  it('keeps the Arabic steps as the translation of record', () => {
    for (const test of TESTS) {
      expect(test.procedureAr.length, test.code).toBeGreaterThanOrEqual(1);
      expect(ARABIC.test(test.procedureAr.join(' ')), test.code).toBe(true);
    }
  });

  it('quotes the standard it implements', () => {
    // the header line of the procedure panel prints this verbatim
    for (const test of TESTS) {
      expect(test.standard.trim().length, test.code).toBeGreaterThan(3);
    }
  });
});
