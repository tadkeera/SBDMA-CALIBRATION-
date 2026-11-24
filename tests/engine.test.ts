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
    // SOP noise limit is documented as a unit error (GAP-02)
    const ev = evaluateMetric('T11', 'noise', 0.001, 'SOP_LIMIT', 'mAU');
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
    // carryover_ch2 is only governed by Ch.2 / SOP / AUTHORITY sources
    const ev = evaluateMetric('T12', 'carryover_ch2', 0.001, 'IOQ_PROTOCOL_CH4', '%');
    expect(ev.status).toBe('UNDER_REVIEW');
    expect(ev.appliedLimitId).toBeNull();
  });
});

describe('protocol blueprint integrity', () => {
  it('contains exactly 13 tests', () => {
    expect(TESTS).toHaveLength(13);
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

  it('flags the defective SOP limits as conflicts', () => {
    const sopConflicts = LIMITS.filter(
      (l) => l.sourceType === 'SOP_LIMIT' && l.approvalStatus === 'CONFLICT_REQUIRES_QA',
    );
    expect(sopConflicts.length).toBeGreaterThanOrEqual(4);
  });
});

describe('full run engine', () => {
  const goodInputs = {
    T01: {
      wavelength_dev: 0.2,
      d2_energy: 1517,
      pulsation: 0.08,
      oven_stability: 0.05,
      absorbance_dev: 0.4,
      noise: 0.008,
      drift: 0.12,
      gradient_dev: 0.6,
      pressure_limiter: 'Passed',
    },
    T02: { set_flow: [0.5, 1, 2], collected_vol: [5, 5, 5], actual_time: [599.9, 299.4, 150.1] },
    T03: { pulsation: 0.09, upper_limiter: 'Passed', lower_limiter: 'Passed' },
    T04: {
      height_0: [0, 0, 0],
      height_10: [10040, 10060, 10020],
      height_50: [50100, 50200, 49900],
      height_90: [90200, 90100, 90300],
      height_100: [100200, 100300, 100100],
    },
    T05: { w1: 10.5, w2: 10.0008, water_density: 0.997, set_vol: 50, n_injections: 10 },
    T06: {
      volumes: [2, 5, 10, 20, 50],
      linearity_areas: [1000, 2500, 5000, 10000, 25000],
      loop_areas: [24950, 25010, 24980, 25005, 24990],
    },
    T07: { t_set: 4, t_ref_raw: 4.4, ref_offset: 0.08, wait_minutes: 95, ambient_temp: 26 },
    T08: { t_set: 40, t_display: 40.1, t_ref_raw: 40.3, ref_offset: 0.05, fluctuation: 0.07, gas_sensor: 'Passed' },
    T09: { d2_energy: 1517, lamp_hours: 1420, wavelength_dev: 0.3, peak_205: 205.2, valley_245: 244.8, peak_273: 273.4 },
    T10: { absorbance_dev: 0.5, concs: [20, 30, 40, 50, 60], heights: [0.5, 0.75, 1.0, 1.25, 1.5] },
    T11: { noise: 0.009, drift: -0.21 },
    T12: {
      rt_values: [2.451, 2.449, 2.452, 2.45, 2.448, 2.451],
      areas: [25010, 24980, 25005, 24995, 25020, 24990],
      area_blank: 0.02,
      area_sample_250: 200000,
      area_sample_50: 40000,
    },
    T13: {
      detector_sensor: 'Passed',
      pump_sensor: 'Passed',
      hpv_sensor: 'Passed',
      lpv_sensor: 'Passed',
      rack_setting: 'Not Required',
      port_teaching: 'Not Required',
    },
  };

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
    const inputs = { ...goodInputs, T02: { set_flow: [0.5, 1, 2] } };
    const res = runCalibration(inputs, { policySource: 'AUTHORITY_LIMIT' });
    expect(res.perTest['T02'].status).toBe('INCOMPLETE');
  });

  it('escalates to UNDER_REVIEW when the governing source is conflicted', () => {
    const res = runCalibration(goodInputs, { policySource: 'SOP_LIMIT' });
    expect(res.overall).toBe('UNDER_REVIEW');
  });

  it('fails a run when a leak sensor reports Failed', () => {
    const inputs = {
      ...goodInputs,
      T13: { ...goodInputs.T13, lpv_sensor: 'Failed' },
    };
    const res = runCalibration(inputs, { policySource: 'AUTHORITY_LIMIT' });
    expect(res.perTest['T13'].status).toBe('FAIL');
  });
});
