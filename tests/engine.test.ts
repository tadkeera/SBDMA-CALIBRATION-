import { describe, expect, it } from 'vitest';
import {
  evalExpression,
  MathEngineError,
  ols,
  parse,
  rsDeviation,
  rsd,
  sd,
} from '../src/core/engine/safeMath';
import { TESTS, LIMITS } from '../src/core/protocol';
import { evaluateMetric, runCalibration } from '../src/core/engine/runEngine';
import REFERENCE from '../e2e/fixtures/compliant_inputs.json';

describe('safe AST math engine', () => {
  it('evaluates arithmetic with precedence', () => {
    expect(evalExpression('2 + 3 * 4')).toBe(14);
    expect(evalExpression('(2 + 3) * 4')).toBe(20);
    expect(evalExpression('-3^2')).toBe(-9);
    expect(evalExpression('2^3^2')).toBe(512);
  });

  it('applies the flow-rate formula from the protocol', () => {
    // 5.0 mL collected in 299.4 s with set flow 1.0 mL/min
    const actual = evalExpression('(collected_vol * 60) / actual_time', {
      collected_vol: 5.0,
      actual_time: 299.4,
    }) as number;
    const err = evalExpression('((actual_flow - set_flow) / set_flow) * 100', {
      actual_flow: actual,
      set_flow: 1.0,
    }) as number;
    expect(actual).toBeCloseTo(1.0020, 4);
    expect(err).toBeCloseTo(0.2, 1);
  });

  it('applies the iOQ gravimetric injection-volume formula', () => {
    // 10 injections x 50 uL, W1-W2 = 0.4992 g, density 0.9970
    const vol = evalExpression('((w1 - w2) * 1000) / water_density', {
      w1: 10.5000,
      w2: 10.0008,
      water_density: 0.997,
    }) as number;
    const acc = evalExpression('((measured_vol / (set_vol * n)) - 1) * 100', {
      measured_vol: vol,
      set_vol: 50,
      n: 10,
    }) as number;
    expect(vol).toBeCloseTo(500.7, 1);
    expect(Math.abs(acc)).toBeLessThan(1.3);
  });

  it('applies the official iOQ gradient formula element-wise', () => {
    const actual = evalExpression('((height_x - height_0) / (height_100 - height_0)) * 100', {
      height_x: [0, 1050, 50100, 90300, 100200],
      height_0: 0,
      height_100: 100200,
    }) as number[];
    expect(actual[2]).toBeCloseTo(50.0, 2);
    expect(actual[3]).toBeCloseTo(90.12, 2);
  });

  it('refuses forbidden constructs', () => {
    expect(() => parse('__proto__')).not.toThrow();
    expect(() => evalExpression('fetch("/etc/passwd")')).toThrow(MathEngineError);
    expect(() => evalExpression('alert(1)')).toThrow(MathEngineError);
    expect(() => evalExpression('process.exit(1)')).toThrow(MathEngineError);
    expect(() => evalExpression('1; rm -rf /')).toThrow(MathEngineError);
    expect(() => evalExpression('1 / 0')).toThrow(MathEngineError);
  });

  it('computes OLS statistics matching the report method', () => {
    const xs = [20, 30, 40, 50, 60];
    const ys = [0.5, 0.75, 1.0, 1.25, 1.5];
    const r = ols(xs, ys);
    expect(r.slope).toBeCloseTo(0.025, 6);
    expect(r.intercept).toBeCloseTo(0, 6);
    expect(r.r2).toBeCloseTo(1, 10);
    expect(r.residuals.every((x) => Math.abs(x) < 1e-9)).toBe(true);
  });

  it('computes sample SD with n-1 and %RSD', () => {
    const xs = [100, 101, 99, 100, 100];
    expect(sd(xs)).toBeCloseTo(0.7071, 4);
    expect(rsd(xs)).toBeCloseTo(0.7071, 3);
  });

  it('computes relative sensitivity deviation (Ch.2 detector linearity)', () => {
    const heights = [20, 30, 40, 50, 60];
    const concs = [20, 30, 40, 50, 60];
    const dev = rsDeviation(heights, concs);
    expect(Math.max(...dev.map(Math.abs))).toBeLessThan(1e-9);
  });

  it('evaluates the carryover formulas exactly as published', () => {
    const ch2 = evalExpression('(area_blank / area_sample_250) * 100', {
      area_blank: 0.02,
      area_sample_250: 200000,
    }) as number;
    expect(ch2).toBeCloseTo(0.00001, 6);
    const ioq = evalExpression('(area_blank / (5 * area_sample_50)) * 100', {
      area_blank: 0.02,
      area_sample_50: 40000,
    }) as number;
    expect(ioq).toBeCloseTo(0.00001, 6);
  });
});

describe('QA governance guard', () => {
  it('never issues PASS on a CONFLICT_REQUIRES_QA limit', () => {
    // The iOQ carryover limit is 10× looser than the adopted 0.010% (GAP-08)
    const ev = evaluateMetric('T12', 'carryover_pct', 0.001, 'IOQ_PROTOCOL_CH4', '%');
    expect(ev.status).toBe('UNDER_REVIEW');
    expect(ev.message).toContain('متعارض');
  });

  it('issues PASS within an approved limit', () => {
    const ev = evaluateMetric('T11', 'noise', 0.008, 'AUTHORITY_LIMIT', 'mAU');
    expect(ev.status).toBe('PASS');
  });

  it('issues FAIL outside an approved limit', () => {
    const ev = evaluateMetric('T11', 'drift_abs', 0.85, 'AUTHORITY_LIMIT', 'mAU/h');
    expect(ev.status).toBe('FAIL');
  });

  it('returns UNDER_REVIEW when no limit exists for the chosen source', () => {
    // rt_rsd is governed by Ch.2 and the authority limit only
    const ev = evaluateMetric('T12', 'rt_rsd', 0.2, 'MANUFACTURER_SPEC', '%');
    expect(ev.status).toBe('UNDER_REVIEW');
    expect(ev.appliedLimitId).toBeNull();
  });
});

describe('protocol blueprint integrity', () => {
  it('contains the 20 tests of protocol v2.0.0', () => {
    expect(TESTS).toHaveLength(20);
    expect(TESTS.map((t) => t.code)).toEqual(
      Array.from({ length: 20 }, (_, i) => `T${String(i + 1).padStart(2, '0')}`),
    );
  });

  it('every metric has at least one AUTHORITY_LIMIT', () => {
    const missing: string[] = [];
    for (const t of TESTS) {
      for (const m of t.metrics) {
        const found = LIMITS.some(
          (l) => l.testCode === t.code && l.metricKey === m && l.sourceType === 'AUTHORITY_LIMIT',
        );
        if (!found) missing.push(`${t.code}:${m}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('every formula parses and is safe', () => {
    for (const t of TESTS) {
      for (const f of t.formulas) {
        expect(() => parse(f.expression)).not.toThrow();
      }
    }
  });

  it('keeps the looser iOQ carryover limit as an explicit conflict', () => {
    const conflicts = LIMITS.filter((l) => l.approvalStatus === 'CONFLICT_REQUIRES_QA');
    expect(conflicts.map((l) => `${l.testCode}:${l.metricKey}:${l.sourceType}`)).toEqual([
      'T12:carryover_pct:IOQ_PROTOCOL_CH4',
    ]);
    // and the adopted limit is ten times stricter
    const authority = LIMITS.find(
      (l) => l.testCode === 'T12' && l.metricKey === 'carryover_pct' && l.sourceType === 'AUTHORITY_LIMIT',
    );
    expect(authority?.maxValue).toBe(0.01);
    expect(conflicts[0].maxValue).toBe(0.1);
  });
});

describe('full run engine', () => {
  // The reference dataset is authored once, in backend/tests/test_api_runs.py, and
  // exported to this JSON file for the browser, the E2E suite and this test — so a
  // divergence between the two engines cannot hide behind two hand-kept copies.
  const goodInputs: Record<string, Record<string, unknown>> = REFERENCE;

  it('produces PASS for a compliant instrument', () => {
    const res = runCalibration(goodInputs, { policySource: 'AUTHORITY_LIMIT' });
    const failing = res.results.filter((r) => r.status !== 'PASS');
    expect(failing.map((r) => r.testCode)).toEqual([]);
    expect(res.overall).toBe('PASS');
  });

  it('flags drift OOS as FAIL', () => {
    const inputs = { ...goodInputs, T11: { noise: 0.009, drift: 1.2 } };
    const res = runCalibration(inputs, { policySource: 'AUTHORITY_LIMIT' });
    expect(res.perTest['T11'].status).toBe('FAIL');
    expect(res.overall).toBe('FAIL');
  });

  it('reports INCOMPLETE when required raw data is missing', () => {
    const inputs = { ...goodInputs, T02: { flow_p1000: [1.0, 1.0, 1.0] } };
    const res = runCalibration(inputs, { policySource: 'AUTHORITY_LIMIT' });
    expect(res.perTest['T02'].status).toBe('INCOMPLETE');
  });

  it('escalates to UNDER_REVIEW when the governing source is conflicted', () => {
    const res = runCalibration(goodInputs, { policySource: 'SOP_LIMIT' });
    expect(res.overall).toBe('UNDER_REVIEW');
  });

  it('fails a run when a leak sensor reports FAIL', () => {
    const inputs = {
      ...goodInputs,
      T13: { ...goodInputs.T13, leak_lpv: 'FAIL' },
    };
    const res = runCalibration(inputs, { policySource: 'AUTHORITY_LIMIT' });
    expect(res.perTest['T13'].status).toBe('FAIL');
  });
});
