import { describe, expect, it } from 'vitest';
import {
  ApiError,
  OfflineError,
  toInstrument,
  toRunRecord,
  toRunTestResults,
  toUserAccount,
  type ServerInstrument,
  type ServerMetricEvaluation,
  type ServerRun,
  type ServerTestResult,
  type ServerUser,
} from '../src/core/api/client';

/**
 * The server serialises `Decimal` as a JSON string so no precision is lost in
 * transit. Every consumer downstream (charts, limit comparison, re-evaluation)
 * works on numbers, so the adapters are the single place that revives them.
 * These tests pin that behaviour — a regression here silently blanks charts.
 */

function testResult(overrides: Partial<ServerTestResult> = {}): ServerTestResult {
  return {
    test_code: 'T01',
    status: 'PASS',
    metric_evaluations: [],
    outputs: {},
    ...overrides,
  };
}

function metric(overrides: Partial<ServerMetricEvaluation> = {}): ServerMetricEvaluation {
  return {
    metric_key: 'wavelength_dev_abs',
    value: '0.4',
    unit: 'nm',
    applied_limit_id: 'limit-1',
    applied_source: 'AUTHORITY_LIMIT',
    comparator: 'lte',
    limit_text: '≤ 1 nm',
    status: 'PASS',
    message_ar: null,
    ...overrides,
  } as ServerMetricEvaluation;
}

describe('toRunTestResults', () => {
  it('revives decimal strings in `outputs` to numbers', () => {
    const [result] = toRunTestResults([
      testResult({
        outputs: { noise: '0.01', d2_energy: '1450', drift_abs: '0.1', flag: 'PASS' },
      }),
    ]);
    expect(result.outputs).toEqual({ noise: 0.01, d2_energy: 1450, drift_abs: 0.1, flag: 'PASS' });
  });

  it('revives nested arrays (chart series) without touching non-numeric text', () => {
    const [result] = toRunTestResults([
      testResult({
        outputs: {
          actual_flow: ['1.002', '4.998'],
          pct_error: ['0.2', '-0.04'],
          series: [{ set_flow: '1.0', label: 'mL/min' }],
        },
      }),
    ]);
    expect(result.outputs).toEqual({
      actual_flow: [1.002, 4.998],
      pct_error: [0.2, -0.04],
      series: [{ set_flow: 1.0, label: 'mL/min' }],
    });
  });

  it('carries raw inputs through the adapter, because charts replay them', () => {
    const [result] = toRunTestResults([
      testResult({ raw_inputs: { set_flow: ['1', '2', '5'], collected_vol: '5.0' } }),
    ]);
    expect(result.rawInputs).toEqual({ set_flow: [1, 2, 5], collected_vol: 5 });
  });

  it('does not invent raw inputs when the server omits them', () => {
    const [result] = toRunTestResults([testResult()]);
    expect(result.rawInputs).toEqual({});
  });

  it('maps metric evaluations, keeping the applied limit and comparator', () => {
    const [result] = toRunTestResults([
      testResult({
        outputs: { wavelength_dev_abs: '0.4' },
        metric_evaluations: [metric()],
      }),
    ]);
    expect(result.metricEvaluations).toHaveLength(1);
    const ev = result.metricEvaluations[0];
    expect(ev.metricKey).toBe('wavelength_dev_abs');
    expect(ev.value).toBe(0.4);
    expect(ev.appliedSource).toBe('AUTHORITY_LIMIT');
    expect(ev.comparator).toBe('lte');
    expect(ev.limitText).toBe('≤ 1 nm');
    expect(ev.appliedLimitId).toBe('limit-1');
    expect(ev.status).toBe('PASS');
  });

  it('keeps a null metric value null instead of coercing it to 0', () => {
    const [result] = toRunTestResults([
      testResult({ metric_evaluations: [metric({ value: null, status: 'INCOMPLETE' })] }),
    ]);
    expect(result.metricEvaluations[0].value).toBeNull();
  });

  it('preserves the test order the server returned', () => {
    const codes = toRunTestResults([
      testResult({ test_code: 'T12' }),
      testResult({ test_code: 'T01' }),
      testResult({ test_code: 'T07' }),
    ]).map((r) => r.testCode);
    expect(codes).toEqual(['T12', 'T01', 'T07']);
  });
});

describe('toRunRecord', () => {
  const run: ServerRun = {
    id: 'run-1',
    execution_code: 'RUN-20261124-0008',
    instrument_id: 'inst-1',
    run_type: 'ROUTINE',
    overall_status: 'PASS',
    analyst_id: 'user-analyst',
    reviewer_id: 'user-reviewer',
    qa_approver_id: null,
    limit_source_policy: 'AUTHORITY_LIMIT',
    ambient_temp_c: '24.5',
    ambient_humidity: '48',
    certificate_hash: 'a1d5f7bcdeaa5dd9be51ea9d5c9b6d4fbd5deba50624787ccb17d13d8480ccf7',
    is_locked: true,
    revision: 2,
    started_at: '2026-11-24T23:30:04.076472Z',
    completed_at: '2026-11-24T23:30:04.111117Z',
    reviewed_at: '2026-11-24T23:40:00.000000Z',
    qa_approved_at: null,
    breakdown_component: null,
    results: [testResult()],
  };

  it('keeps the certificate hash verbatim and reports the lock state', () => {
    const record = toRunRecord(run, {
      instrumentName: 'Shimadzu LC-2050C',
      analyst: 'Analyst',
      reviewer: 'Reviewer',
    });
    expect(record.certificateHash).toBe(run.certificate_hash);
    expect(record.isLocked).toBe(true);
    expect(record.revision).toBe(2);
    expect(record.executionCode).toBe('RUN-20261124-0008');
    expect(record.reviewer).toBe('Reviewer');
    expect(record.qaApprover).toBeNull();
    // decimals arrive as strings and must reach the UI as numbers
    expect(record.ambientTempC).toBe(24.5);
    expect(record.ambientHumidity).toBe(48);
  });

  it('never fabricates a certificate hash for an unlocked run', () => {
    const record = toRunRecord({ ...run, is_locked: false, certificate_hash: null }, {
      instrumentName: 'Shimadzu LC-2050C',
      analyst: 'Analyst',
    });
    expect(record.certificateHash).toBeNull();
    expect(record.isLocked).toBe(false);
  });

  it('adapts every nested test result', () => {
    const record = toRunRecord(run, { instrumentName: 'X', analyst: 'Y' });
    expect(record.results).toHaveLength(1);
    expect(record.results[0].testCode).toBe('T01');
  });
});

describe('toInstrument', () => {
  it('maps the instrument register row', () => {
    const row: ServerInstrument = {
      id: 'inst-1',
      department_id: 'dept-phys',
      asset_code: 'HPLC-UV-001',
      category: 'UV_DETECTOR',
      manufacturer: 'Shimadzu',
      model: 'LC-2050C',
      part_number: 'S228-65821-58',
      serial_number: 'L22976302572',
      software_version: 'LabSolutions 6.92',
      calibration_freq_days: 180,
      last_calibration_date: '2026-11-24',
      next_due_date: '2027-05-23',
      status: 'ACTIVE',
      d2_lamp_hours: 1150,
    } as ServerInstrument;
    const inst = toInstrument(row, 'PHYS');
    expect(inst.assetCode).toBe('HPLC-UV-001');
    expect(inst.model).toBe('LC-2050C');
    expect(inst.serialNumber).toBe('L22976302572');
    expect(inst.departmentCode).toBe('PHYS');
    expect(inst.nextDueDate).toBe('2027-05-23');
    expect(inst.calibrationFreqDays).toBe(180);
  });
});

describe('toUserAccount', () => {
  it('derives identity and role from the server session only', () => {
    const user: ServerUser = {
      id: 'u1',
      username: 'qa.manager',
      email: 'qa.manager@sbdma.local',
      full_name_ar: 'مسؤول ضمان الجودة',
      full_name_en: 'QA Manager',
      roles: ['QA_MANAGER'],
      permissions: ['run.approve', 'run.review'],
      department_id: 'dept-qa',
      department_code: 'QA',
      must_change_password: false,
    };
    const account = toUserAccount(user);
    expect(account.username).toBe('qa.manager');
    expect(account.role).toBe('QA_MANAGER');
    expect(account.fullNameAr).toBe('مسؤول ضمان الجودة');
    expect(account.departmentCode).toBe('QA');
  });
});

describe('ApiError', () => {
  it('localises the server message and keeps the machine-readable code', () => {
    const err = new ApiError(409, {
      code: 'RESULT_LOCKED',
      field: null,
      message_ar: 'النتيجة مقفلة ولا يمكن تعديلها',
      message_en: 'The result is locked and cannot be changed',
      details: { run: 'RUN-1' },
    });
    expect(err.text('ar')).toBe('النتيجة مقفلة ولا يمكن تعديلها');
    expect(err.text('en')).toBe('The result is locked and cannot be changed');
    expect(err.code).toBe('RESULT_LOCKED');
    expect(err.status).toBe(409);
    expect(err.details).toEqual({ run: 'RUN-1' });
    expect(err).toBeInstanceOf(Error);
  });

  it('surfaces segregation-of-duties refusals as a 403 code', () => {
    const err = new ApiError(403, {
      code: 'SEGREGATION_OF_DUTIES',
      field: null,
      message_ar: 'فصل الواجبات: لا يجوز أن يعتمد المحلل تشغيله',
      message_en: 'Segregation of duties: the analyst cannot approve their own run',
    });
    expect(err.status).toBe(403);
    expect(err.code).toBe('SEGREGATION_OF_DUTIES');
    expect(err.text('ar')).toContain('فصل الواجبات');
  });
});

describe('OfflineError', () => {
  it('is distinguishable so pages can fall back to the cached snapshot', () => {
    const err = new OfflineError(new Error('ECONNREFUSED'));
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('OfflineError');
  });
});
