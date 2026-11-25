import Decimal from 'decimal.js';
import { LIMITS, TESTS } from '../protocol';
import type {
  AcceptanceLimit,
  LimitSource,
  MetricEvaluation,
  RunTestResult,
  Status,
  TestSpec,
} from '../types';
import { evalExpression, roundForDisplay } from './safeMath';

export const PREFERRED_SOURCE_ORDER: LimitSource[] = [
  'AUTHORITY_LIMIT',
  'INTEGRITY_GUIDE_CH2',
  'IOQ_PROTOCOL_CH4',
  'MANUFACTURER_SPEC',
  'SOP_LIMIT',
];

export interface EngineOptions {
  /** limit source the QA unit has designated for this run */
  policySource: LimitSource;
}

/** Select values that count as a failure — `FAIL`/`Failed`, case-insensitive. */
const FAIL_VALUES = new Set(['fail', 'failed', 'reject', 'rejected']);

export function isFailedValue(value: unknown): boolean {
  return typeof value === 'string' && FAIL_VALUES.has(value.trim().toLowerCase());
}

export function limitFor(
  testCode: string,
  metricKey: string,
  source: LimitSource,
  limits: AcceptanceLimit[] = LIMITS,
): AcceptanceLimit | undefined {
  return limits.find(
    (l) => l.testCode === testCode && l.metricKey === metricKey && l.sourceType === source,
  );
}

export function formatLimit(l: AcceptanceLimit | undefined): string {
  if (!l) return '—';
  const f = (v: number | null) =>
    v === null ? '—' : new Decimal(v).toDecimalPlaces(Math.abs(v) < 1 ? 5 : 3).toString();
  switch (l.operator) {
    case 'lte':
      return `≤ ${f(l.maxValue)} ${l.unit}`;
    case 'gte':
      return `≥ ${f(l.minValue)} ${l.unit}`;
    case 'abs_lte':
      return `|x| ≤ ${f(l.maxValue)} ${l.unit}`;
    case 'between':
      return `${f(l.minValue)} … ${f(l.maxValue)} ${l.unit}`;
    case 'equals':
      return `= ${f(l.minValue)} ${l.unit}`;
  }
}

function compare(value: number, l: AcceptanceLimit): boolean {
  switch (l.operator) {
    case 'lte':
      return l.maxValue !== null && value <= l.maxValue;
    case 'gte':
      return l.minValue !== null && value >= l.minValue;
    case 'abs_lte':
      return l.maxValue !== null && Math.abs(value) <= l.maxValue;
    case 'between':
      return l.minValue !== null && l.maxValue !== null && value >= l.minValue && value <= l.maxValue;
    case 'equals':
      return l.minValue !== null && value === l.minValue;
  }
}

/**
 * Governance guard: a metric can never be judged PASS while its governing limit is
 * unapproved or in conflict. This is the single choke point that enforces it.
 */
export function evaluateMetric(
  testCode: string,
  metricKey: string,
  value: number | null,
  source: LimitSource,
  unit: string,
  limits: AcceptanceLimit[] = LIMITS,
): MetricEvaluation {
  const limit = limitFor(testCode, metricKey, source, limits);
  const base: MetricEvaluation = {
    metricKey,
    value,
    unit: limit?.unit ?? unit,
    appliedLimitId: limit?.id ?? null,
    appliedSource: source,
    comparator: limit?.operator ?? '—',
    limitText: formatLimit(limit),
    status: 'INCOMPLETE',
  };
  if (!limit) {
    return {
      ...base,
      status: 'UNDER_REVIEW',
      message: 'لا يوجد حد قبول مسجل لهذا المقياس من المصدر المختار — يلزم اعتماد QA.',
    };
  }
  if (value === null || !Number.isFinite(value)) {
    return { ...base, status: 'INCOMPLETE', message: 'قيمة غير محسوبة أو غير صالحة.' };
  }
  if (limit.approvalStatus === 'REJECTED') {
    return { ...base, status: 'UNDER_REVIEW', message: 'الحد مرفوض من ضمان الجودة ولا يجوز استخدامه.' };
  }
  if (limit.approvalStatus === 'CONFLICT_REQUIRES_QA' || limit.approvalStatus === 'UNAPPROVED') {
    return {
      ...base,
      status: 'UNDER_REVIEW',
      message:
        limit.approvalStatus === 'CONFLICT_REQUIRES_QA'
          ? 'الحد متعارض أو موثّق الخطأ ويلزم حسم ضمان الجودة قبل إصدار الحكم.'
          : 'الحد غير معتمد من ضمان الجودة.',
    };
  }
  const ok = compare(value, limit);
  return {
    ...base,
    status: ok ? 'PASS' : 'FAIL',
    message: ok ? undefined : 'القيمة خارج حد القبول المعتمد — انحراف OOS.',
  };
}

function worstStatus(list: Status[]): Status {
  if (list.includes('FAIL')) return 'FAIL';
  if (list.includes('UNDER_REVIEW')) return 'UNDER_REVIEW';
  if (list.includes('INCOMPLETE')) return 'INCOMPLETE';
  return 'PASS';
}

export interface RunComputation {
  results: RunTestResult[];
  overall: Status;
  perTest: Record<string, RunTestResult>;
}

/** Execute every test in the protocol for a set of raw inputs. */
export function runCalibration(
  inputs: Record<string, Record<string, unknown>>,
  opts: EngineOptions,
  tests: TestSpec[] = TESTS,
  limits: AcceptanceLimit[] = LIMITS,
): RunComputation {
  const results: RunTestResult[] = [];

  for (const test of tests) {
    const raw = inputs[test.code] ?? {};
    const scope: Record<string, number | number[]> = {};
    const outputs: Record<string, number | number[] | string> = {};
    const isComplete = requiredFieldsPresent(test, raw);

    if (!isComplete) {
      results.push({
        testCode: test.code,
        rawInputs: raw,
        outputs: {},
        metricEvaluations: test.metrics.map((m) =>
          evaluateMetric(test.code, m, null, opts.policySource, '', limits),
        ),
        status: 'INCOMPLETE',
      });
      continue;
    }

    // numeric coercion into scope
    for (const f of test.fields) {
      const v = raw[f.key];
      if (v === undefined || v === null || v === '') continue;
      if (f.type === 'series' || f.type === 'spectrum') {
        scope[f.key] = (Array.isArray(v) ? v : String(v).split(/[,;\s]+/))
          .map((x) => Number(x))
          .filter((x) => Number.isFinite(x));
      } else if (f.type === 'boolean') {
        scope[f.key] = v ? 1 : 0;
      } else if (f.type === 'select' || f.type === 'text') {
        // The v2 protocol writes PASS/FAIL; the earlier revision wrote Passed/Failed.
        // Both spellings must map to the same numeric value or the two engines would
        // disagree on a stored reading.
        scope[f.key] = isFailedValue(v) ? 0 : 1;
        outputs[f.key] = String(v);
      } else {
        scope[f.key] = Number(v);
      }
    }

    // sequential formula evaluation (later formulas may reference earlier outputs)
    for (const formula of test.formulas) {
      try {
        const value = evalExpression(formula.expression, scope);
        outputs[formula.key] = value as number | number[];
        if (typeof value === 'number') scope[formula.key] = value;
        else scope[formula.key] = value;
      } catch (err) {
        outputs[formula.key] = `ERROR: ${(err as Error).message}`;
      }
    }

    const metricEvaluations = test.metrics.map((m) => {
      const v = typeof outputs[m] === 'number' ? (outputs[m] as number) : null;
      const unit = test.formulas.find((f) => f.key === m) ? unitFor(test, m) : '';
      return evaluateMetric(test.code, m, v, opts.policySource, unit, limits);
    });

    // select-field gates that are not plain numeric metrics
    const selectFailures: string[] = [];
    for (const f of test.fields) {
      if (f.type === 'select' && isFailedValue(raw[f.key])) selectFailures.push(f.labelAr);
    }

    const status = selectFailures.length
      ? 'FAIL'
      : worstStatus(metricEvaluations.map((m) => m.status));

    results.push({
      testCode: test.code,
      rawInputs: raw,
      outputs,
      metricEvaluations,
      status,
      notes: selectFailures.length ? `عناصر غير مطابقة: ${selectFailures.join('، ')}` : undefined,
    });
  }

  const overall = worstStatus(results.map((r) => r.status));
  const perTest: Record<string, RunTestResult> = {};
  results.forEach((r) => (perTest[r.testCode] = r));
  return { results, overall, perTest };
}

function unitFor(test: TestSpec, metric: string): string {
  const f = test.fields.find((x) => x.key === metric);
  return f?.unit ?? '—';
}

function requiredFieldsPresent(test: TestSpec, raw: Record<string, unknown>): boolean {
  for (const f of test.fields) {
    if (!f.required) continue;
    const v = raw[f.key];
    if (v === undefined || v === null || v === '') return false;
    if ((f.type === 'series' || f.type === 'spectrum') && Array.isArray(v)) {
      const need = f.length ?? 1;
      const clean = v.filter((x) => x !== '' && x !== null && x !== undefined && Number.isFinite(Number(x)));
      if (clean.length < need) return false;
    }
  }
  return true;
}

export function dec(v: number, d: number) {
  return roundForDisplay(v, d);
}

/** Deterministic certificate fingerprint (SHA-256 via WebCrypto where available). */
export async function fingerprint(payload: unknown): Promise<string> {
  const json = JSON.stringify(payload);
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(json));
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }
  // fallback for non-secure contexts — same shape, weaker hash
  let h1 = 0x811c9dc5;
  for (let i = 0; i < json.length; i++) {
    h1 ^= json.charCodeAt(i);
    h1 = Math.imul(h1, 0x01000193) >>> 0;
  }
  return h1.toString(16).padStart(8, '0').repeat(8);
}
