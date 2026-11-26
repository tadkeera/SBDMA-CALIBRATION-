/**
 * The Flow Rate page's contract with the protocol and the server.
 *
 * The page recomputes statistics in the browser so the analyst sees a number while typing.
 * That preview must agree with the server's arithmetic to the last displayed digit, or the
 * screen becomes a second, silently different engine — the exact defect the parity suite
 * exists to prevent. These tests pin the shared definition (three set points of ten, the
 * accepted band, the two metrics) and the preview formula against the reference dataset.
 */

import { describe, expect, it } from 'vitest';
import REFERENCE from '../e2e/fixtures/compliant_inputs.json';
import { LIMITS, PROTOCOL_VERSION, TESTS } from '../src/core/protocol';
import { runCalibration } from '../src/core/engine/runEngine';

const T02 = TESTS.find((test) => test.code === 'T02')!;

/** Same arithmetic the page performs: mean, sample SD (n − 1), %RSD, %accuracy. */
function preview(values: number[], nominal: number) {
  const n = values.length;
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const variance = n > 1 ? values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1) : null;
  const sd = variance === null ? null : Math.sqrt(variance);
  return {
    mean,
    sd,
    rsd: sd === null ? null : (sd / mean) * 100,
    accuracy: ((mean - nominal) / nominal) * 100,
  };
}

describe('protocol 2.1.0 · flow rate definition', () => {
  it('is version 2.1.0 and still spans twenty tests', () => {
    expect(PROTOCOL_VERSION).toBe('2.1.0');
    expect(TESTS).toHaveLength(20);
  });

  it('declares three series of ten readings in mL/min', () => {
    expect(T02.fields.map((f) => f.key)).toEqual(['flow_p1000', 'flow_p1500', 'flow_p2000']);
    for (const field of T02.fields) {
      expect(field.type).toBe('series');
      expect(field.length).toBe(10);
      expect(field.unit).toBe('mL/min');
    }
  });

  it('carries the accepted accuracy band and the precision limit', () => {
    const limits = LIMITS.filter((limit) => limit.testCode === 'T02');
    const accuracy = limits.filter((limit) => limit.metricKey === 'max_abs_error');
    const rsd = limits.filter((limit) => limit.metricKey === 'max_rsd');
    expect(accuracy.length).toBeGreaterThan(0);
    expect(rsd.length).toBeGreaterThan(0);
    expect(accuracy.some((limit) => limit.approvalStatus === 'APPROVED' && limit.maxValue === 2)).toBe(true);
    expect(rsd.some((limit) => limit.approvalStatus === 'APPROVED' && limit.maxValue === 1)).toBe(true);
    const bands = T02.fields.map((f) => `${f.hintAr ?? ''}${f.hintEn ?? ''}`);
    expect(bands[0]).toContain('0.980–1.020');
    expect(bands[1]).toContain('1.470–1.530');
    expect(bands[2]).toContain('1.960–2.040');
  });

  it('judges the test on the worst accuracy and the worst %RSD', () => {
    expect(T02.metrics).toEqual(expect.arrayContaining(['max_abs_error', 'max_rsd']));
  });
});

describe('client preview agrees with the reference dataset', () => {
  const raw = REFERENCE as unknown as Record<string, Record<string, number[]>>;
  const grid = [raw.T02.flow_p1000, raw.T02.flow_p1500, raw.T02.flow_p2000];

  it('shows an accepted mean, %RSD and accuracy for every set point', () => {
    [1, 1.5, 2].forEach((nominal, index) => {
      const stats = preview(grid[index], nominal);
      expect(stats.mean).toBeCloseTo(nominal, 2);
      expect(Math.abs(stats.accuracy)).toBeLessThan(2);
      expect(stats.rsd).not.toBeNull();
      expect(stats.rsd!).toBeLessThan(1);
    });
  });

  it('matches the engine result the backend also produces', () => {
    const outcome = runCalibration({ 'T02': { ...raw.T02 } }, {
      policySource: 'AUTHORITY_LIMIT',
      disabledTests: [],
    } as never);
    const result = outcome.perTest['T02'];
    expect(result.status).toBe('PASS');
    const output = result.outputs as Record<string, number>;
    expect(output.max_abs_error).toBeLessThan(2);
    expect(output.max_rsd).toBeLessThan(1);
    // the engine's mean for the first set point is the page's mean
    expect(output.mean_p1000).toBeCloseTo(preview(grid[0], 1).mean, 4);
    expect(output.rsd_p1000).toBeCloseTo(preview(grid[0], 1).rsd!, 6);
  });

  it('flags a pump that runs three percent fast even though it is steady', () => {
    const drifting = grid[0].map((value) => value * 1.03);
    const stats = preview(drifting, 1);
    expect(Math.abs(stats.accuracy)).toBeGreaterThan(2);
    expect(stats.rsd!).toBeLessThan(1);
  });

  it('leaves %RSD undefined for a single reading, exactly as the server does', () => {
    const stats = preview([grid[0][0]], 1);
    expect(stats.sd).toBeNull();
    expect(stats.rsd).toBeNull();
    expect(stats.accuracy).not.toBeNull();
  });
});
