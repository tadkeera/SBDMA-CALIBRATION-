'use client';

/**
 * One test, on one unit: readings in, verdict out, charts, certificate.
 *
 * The page is built from the server's answer, not from a browser copy of the protocol:
 * ``GET /tests/{code}/definition`` returns the field list, the formulas and the limits
 * that will actually be applied for this unit's category and the chosen limit-source
 * policy. A field added to the approved protocol therefore appears here without a
 * frontend release, and the acceptance value printed next to a field is the one stored
 * in PostgreSQL.
 *
 * Four things happen on this page, in this order:
 *
 *  1. **Entry** — the readings. The panel recalculates on every keystroke so a drifting
 *     series is visible before twenty numbers have been typed, and it colours each field
 *     green or red against *its own* limit, the way the flow-rate page does.
 *  2. **Run Calibration** — ``POST /tests/{code}/evaluate`` recomputes everything on the
 *     server: every formula, every metric against its applied limit, plus the mean, SD,
 *     %RSD, deviation and range of each series. This is the number that counts; the panel
 *     is a preview.
 *  3. **Charts** — drawn from the server's answer (or, for a stored run, from the stored
 *     row), including the acceptance band.
 *  4. **Save** — creates a run for *this unit*, executes this test through the same
 *     ``/runs`` endpoints every screen uses, and routes it to the supervisor and QA. The
 *     certificate is downloadable as a watermarked draft until QA signs; after that the
 *     full certificate is available without the watermark.
 */

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  BadgeCheck,
  BookOpen,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Play,
  RotateCcw,
  Save,
  ShieldCheck,
} from 'lucide-react';
import type { EChartsOption } from 'echarts';

import { useApp } from '@/components/AppProvider';
import { Chart } from '@/components/Chart';
import { Card, Field, Modal, StatusChip } from '@/components/ui';
import {
  ApiError,
  api,
  downloadReport,
  type ServerInstrument,
  type ServerRun,
  type ServerSeriesStatistics,
  type ServerTestDefinition,
  type ServerTestEvaluation,
} from '@/core/api/client';
import { LIMIT_SOURCES, type LimitSource } from '@/core/types';

type Values = Record<string, string | string[]>;

function tone(status: string | null | undefined) {
  if (!status) return { color: 'var(--text-muted)', background: 'transparent' };
  if (status === 'PASS') return { color: 'var(--pass)', background: 'rgba(22,121,79,.10)' };
  if (status === 'FAIL') return { color: 'var(--fail)', background: 'rgba(180,35,24,.10)' };
  return { color: 'var(--warn)', background: 'rgba(154,106,18,.10)' };
}

export default function TestWorkbenchPage() {
  const { t, lang, notify, can } = useApp();
  // Next 15 hands route params to client components as a promise; useParams unwraps it.
  const routeParams = useParams<{ unitId: string; testCode: string }>();
  const params = {
    unitId: String(routeParams?.unitId ?? ''),
    testCode: String(routeParams?.testCode ?? ''),
  };
  const code = params.testCode.toUpperCase();

  const [unit, setUnit] = useState<ServerInstrument | null>(null);
  const [definition, setDefinition] = useState<ServerTestDefinition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<LimitSource>('AUTHORITY_LIMIT');
  const [values, setValues] = useState<Values>({});
  const [evaluation, setEvaluation] = useState<ServerTestEvaluation | null>(null);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [run, setRun] = useState<ServerRun | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  // ── load the unit and the test's definition ────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const units = await api.instruments();
        const found = units.find((row) => row.id === params.unitId) ?? null;
        if (cancelled) return;
        setUnit(found);
        const def = await api.testDefinition(code, {
          instrumentId: found?.id,
          limitSourcePolicy: 'AUTHORITY_LIMIT',
        });
        if (cancelled) return;
        setDefinition(def);
        setPolicy((def.limit_source_policy as LimitSource) ?? 'AUTHORITY_LIMIT');
        // series fields start as arrays of the length the protocol requires
        const seed: Values = {};
        for (const field of def.fields) {
          if (field.type === 'series' || field.type === 'spectrum') {
            seed[field.key] = Array.from({ length: field.length ?? 3 }, () => '');
          } else {
            seed[field.key] = '';
          }
        }
        setValues(seed);
      } catch (cause) {
        if (!cancelled) {
          setLoadError(cause instanceof ApiError ? cause.text(lang) : (cause as Error).message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.unitId, code, lang]);

  const setScalar = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setEvaluation(null);
  };

  const setSeriesCell = (key: string, index: number, value: string, length: number) => {
    if (value !== '' && !/^-?\d*[.,]?$|^-?\d*[.,]?\d*$/.test(value)) return;
    setValues((prev) => {
      const current = Array.isArray(prev[key]) ? [...(prev[key] as string[])] : Array(length).fill('');
      while (current.length < length) current.push('');
      current[index] = value.replace(',', '.');
      return { ...prev, [key]: current };
    });
    setEvaluation(null);
  };

  /** The readings in the shape the API expects: numbers where they are numbers. */
  const payload = useMemo(() => {
    const raw: Record<string, unknown> = {};
    for (const field of definition?.fields ?? []) {
      const value = values[field.key];
      if (field.type === 'series' || field.type === 'spectrum') {
        const list = Array.isArray(value) ? value : [];
        const numbers = list.filter((item) => String(item).trim() !== '').map((item) => Number(item));
        if (numbers.length) raw[field.key] = numbers;
      } else if (typeof value === 'string' && value.trim() !== '') {
        raw[field.key] = field.type === 'select' || field.type === 'text' ? value : Number(value);
      }
    }
    return raw;
  }, [definition, values]);

  const missing = useMemo(() => {
    const out: string[] = [];
    for (const field of definition?.fields ?? []) {
      const value = values[field.key];
      const isSeries = field.type === 'series' || field.type === 'spectrum';
      const filled = isSeries
        ? (Array.isArray(value) ? value : []).filter((item) => String(item).trim() !== '').length
        : String(value ?? '').trim() !== '';
      if (field.required !== false && !filled) out.push(lang === 'ar' ? field.label_ar : field.label_en);
      if (isSeries && filled && (field.length ?? 0) > 0) {
        const count = (Array.isArray(value) ? value : []).filter((item) => String(item).trim() !== '').length;
        if (count < (field.length ?? 0)) out.push(`${lang === 'ar' ? field.label_ar : field.label_en} (${count}/${field.length})`);
      }
    }
    return out;
  }, [definition, values, lang]);

  // ── Run Calibration: the server's own recomputation ────────────────────────
  const runCalibration = useCallback(async () => {
    if (!unit || !definition) return;
    setRunning(true);
    setErrors([]);
    try {
      const result = await api.testEvaluate(code, {
        raw_inputs: payload,
        instrument_id: unit.id,
        limit_source_policy: policy,
      });
      setEvaluation(result);
      notify(
        result.status === 'PASS' ? 'success' : result.status === 'FAIL' ? 'error' : 'warn',
        t(`حساب الخادم: ${result.status}`, `Server verdict: ${result.status}`),
        `${definition.test_code} · ${result.metrics.filter((metric) => metric.status === 'PASS').length}/${result.metrics.length} ${t('حدود مطابقة', 'limits met')}`,
      );
    } catch (cause) {
      setErrors([cause instanceof ApiError ? cause.text(lang) : String(cause)]);
    } finally {
      setRunning(false);
    }
  }, [unit, definition, payload, policy, code, notify, t, lang]);

  // ── Save: a run for this unit, executed through the shared endpoint ────────
  const saveRun = useCallback(async () => {
    if (!unit || !definition || saving) return;
    setSaving(true);
    setErrors([]);
    try {
      const created = await api.createRun({
        instrument_id: unit.id,
        run_type: 'ROUTINE',
        limit_source_policy: policy,
      });
      const executed = await api.executeRun(created.id, { [code]: payload }, [code]);
      setRun(executed.run);
      setConfirmOpen(false);
      notify(
        executed.overall === 'PASS' ? 'success' : executed.overall === 'FAIL' ? 'error' : 'warn',
        t(`تم الحفظ — ${executed.overall}`, `Saved — ${executed.overall}`),
        t(
          `${executed.run.execution_code} · أُرسل إشعار إلى مشرف المختبر وضمان الجودة`,
          `${executed.run.execution_code} · supervisor and QA have been notified`,
        ),
      );
    } catch (cause) {
      setErrors([cause instanceof ApiError ? cause.text(lang) : String(cause)]);
    } finally {
      setSaving(false);
    }
  }, [unit, definition, saving, policy, code, payload, notify, t, lang]);

  const download = useCallback(
    async (stage: 'OFFICIAL' | 'PROVISIONAL') => {
      if (!run) return;
      const query = stage === 'PROVISIONAL' ? '?stage=PROVISIONAL' : '';
      try {
        await downloadReport(
          `/reports/runs/${run.id}/tests/${code}/certificate.pdf${query}`,
          `${run.execution_code}-${code}-${stage.toLowerCase()}.pdf`,
        );
      } catch (cause) {
        setErrors([cause instanceof ApiError ? cause.text(lang) : String(cause)]);
      }
    },
    [run, code, lang],
  );

  // ── charts from the server's answer ───────────────────────────────────────
  const metricChart = useMemo<EChartsOption | null>(() => {
    if (!evaluation) return null;
    const metrics = evaluation.metrics.filter((metric) => metric.value !== null);
    if (!metrics.length) return null;
    // Share of the applied limit; a one-sided "≥" limit is inverted so a large value is
    // not drawn as a failure (the same rule the certificate charts use).
    const rows = metrics.map((metric) => {
      const value = Number(metric.value);
      const numbers = /-?\d+(?:\.\d+)?/g;
      const bounds = (metric.limit_text.match(numbers) ?? []).map(Number);
      const isLowerBound = metric.limit_text.includes('≥');
      const bound = isLowerBound ? bounds[0] : bounds[bounds.length - 1];
      const share =
        Number.isFinite(bound) && bound !== 0
          ? Number(((isLowerBound ? bound / value : value / bound) * 100).toFixed(1))
          : null;
      return { key: metric.metric_key, share, value, unit: metric.unit, limit: metric.limit_text, ok: metric.status === 'PASS' };
    });
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params: unknown) => {
          const row = rows[(params as Array<{ dataIndex: number }>)[0].dataIndex];
          return [
            `<b>${row.key}</b>`,
            `${t('القيمة', 'Value')}: ${row.value} ${row.unit}`,
            `${t('الحد المطبق', 'Applied limit')}: ${row.limit}`,
            `${t('النسبة من الحد', 'Share of limit')}: ${row.share ?? '—'} %`,
          ].join('<br/>');
        },
      },
      grid: { left: 120, right: 40, top: 18, bottom: 34 },
      xAxis: { type: 'value', name: t('% من حد القبول', '% of limit'), nameLocation: 'middle', nameGap: 24 },
      yAxis: {
        type: 'category',
        data: rows.map((row) => row.key),
        axisLabel: { fontSize: 9.5, width: 110, overflow: 'truncate' },
      },
      series: [
        {
          type: 'bar',
          barWidth: '52%',
          data: rows.map((row) => ({
            value: row.share,
            itemStyle: { color: row.ok ? '#21695e' : '#b42318' },
          })),
          label: { show: true, position: 'right', fontSize: 9.5, formatter: (p: { value: number }) => `${p.value ?? '—'}%` },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: '#b42318', type: 'dashed' },
            data: [{ xAxis: 100 }],
          },
        },
      ],
    } as EChartsOption;
  }, [evaluation, t]);

  const seriesChart = useMemo<EChartsOption | null>(() => {
    if (!evaluation) return null;
    const entries = Object.entries(evaluation.signals ?? {}).filter(([, value]) => Array.isArray(value));
    if (!entries.length) return null;
    const longest = Math.max(...entries.map(([, value]) => (value as unknown[]).length));
    return {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { fontSize: 10 } },
      grid: { left: 52, right: 24, top: 34, bottom: 34 },
      xAxis: {
        type: 'category',
        data: Array.from({ length: longest }, (_, index) => `#${index + 1}`),
        name: t('التكرار', 'replicate'),
        nameLocation: 'middle',
        nameGap: 22,
      },
      yAxis: { type: 'value', scale: true },
      series: entries.map(([key, value], index) => ({
        name: key,
        type: 'line' as const,
        symbolSize: 6,
        data: (value as unknown[]).map((item) => (item === null || item === '' ? null : Number(item))),
        lineStyle: { width: 2, color: ['#21695e', '#b54708', '#1d4ed8', '#6b7280'][index % 4] },
        itemStyle: { color: ['#21695e', '#b54708', '#1d4ed8', '#6b7280'][index % 4] },
      })),
    } as EChartsOption;
  }, [evaluation, t]);

  if (loading) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-[13px]" style={{ color: 'var(--text-muted)' }}>
          <Loader2 size={16} className="animate-spin" /> {t('يُقرأ تعريف الاختبار وحدوده المعتمدة من الخادم…', 'Reading the test definition and its approved limits from the server…')}
        </div>
      </Card>
    );
  }

  if (loadError || !definition) {
    return (
      <Card title={t('تعذر فتح الاختبار', 'The test could not be opened')}>
        <p className="text-[12.5px]" style={{ color: 'var(--fail)' }}>{loadError ?? '—'}</p>
        <Link href={`/lab/${params.unitId}`} className="btn btn-ghost mt-3">
          <ArrowLeft size={15} /> {t('اختبارات الجهاز', 'Unit tests')}
        </Link>
      </Card>
    );
  }

  const unitLabel = unit ? ((lang === 'ar' ? unit.label_ar : unit.label_en) ?? unit.asset_code) : '';
  const statusCounts = evaluation
    ? {
        pass: evaluation.metrics.filter((metric) => metric.status === 'PASS').length,
        fail: evaluation.metrics.filter((metric) => metric.status === 'FAIL').length,
      }
    : null;

  return (
    <div className="space-y-4">
      {/* ── header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Link href={`/lab/${params.unitId}`} className="btn btn-ghost px-2 py-1">
            <ArrowLeft size={15} />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-lg px-2 py-0.5 font-mono text-[11px] font-bold" style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }}>
                {definition.test_code}
              </span>
              <h2 className="text-[16px] font-bold">{lang === 'ar' ? definition.name_ar : definition.name_en}</h2>
            </div>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {unitLabel} · {definition.protocol_code} v{definition.protocol_version} · {definition.standard_ref}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Field label={t('مصدر حدود القبول', 'Limit source')}>
            <select
              className="select text-[11.5px]"
              value={policy}
              onChange={(event) => {
                setPolicy(event.target.value as LimitSource);
                setEvaluation(null);
              }}
            >
              {LIMIT_SOURCES.map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
          </Field>
          {run && <StatusChip status={run.overall_status} small />}
        </div>
      </div>

      {errors.length > 0 && (
        <div className="card p-3 text-[12px]" style={{ borderColor: 'var(--fail)', color: 'var(--fail)' }}>
          {errors.map((message, index) => (
            <p key={index} className="flex items-start gap-1.5">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {message}
            </p>
          ))}
        </div>
      )}

      {/* ── the accepted limits for this test ─────────────────────────── */}
      <Card
        title={t('حدود القبول المطبقة', 'Acceptance limits applied')}
        subtitle={t(
          `تُقرأ من جدول الحدود في قاعدة البيانات لمصدر ${policy}؛ الحد الذي لم يُعتمد يجعل النتيجة «قيد المراجعة» لا «مطابق».`,
          `Read from the limit table in PostgreSQL for source ${policy}; an unapproved limit makes the result UNDER_REVIEW, never PASS.`,
        )}
        dense
      >
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t('المقياس', 'Metric')}</th>
                <th>{t('الحد', 'Limit')}</th>
                <th>{t('الوحدة', 'Unit')}</th>
                <th>{t('المصدر', 'Source')}</th>
                <th>{t('حالة الاعتماد', 'Approval')}</th>
              </tr>
            </thead>
            <tbody>
              {definition.limits
                .filter((limit) => limit.source_type === policy)
                .map((limit) => (
                  <tr key={limit.id}>
                    <td className="font-mono text-[11px]">{limit.metric_key}</td>
                    <td className="font-mono">
                      {limit.min_value !== null && limit.max_value !== null
                        ? `${limit.min_value} … ${limit.max_value}`
                        : limit.max_value !== null
                          ? `≤ ${limit.max_value}`
                          : `≥ ${limit.min_value}`}
                    </td>
                    <td className="font-mono">{limit.unit}</td>
                    <td className="text-[10.5px]">{limit.source_type}</td>
                    <td>
                      <span className="chip" style={tone(limit.approval_status === 'APPROVED' ? 'PASS' : 'UNDER_REVIEW')}>
                        {limit.approval_status}
                      </span>
                    </td>
                  </tr>
                ))}
              {definition.limits.filter((limit) => limit.source_type === policy).length === 0 && (
                <tr>
                  <td colSpan={5} className="text-[11.5px]" style={{ color: 'var(--warn)' }}>
                    {t(
                      `لا توجد حدود مسجلة للمصدر ${policy} لهذا الاختبار — اختر مصدراً آخر أو اعتمد الحدود أولاً.`,
                      `No limits are recorded for source ${policy} on this test — choose another source or approve the limits first.`,
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── procedure ─────────────────────────────────────────────────── */}
      {definition.procedure_en.length > 0 && (
        <Card title={t('Documented procedure', 'Documented procedure')}>
          <ol dir="ltr" lang="en" className="list-inside list-decimal space-y-1 text-[11.5px] leading-relaxed" style={{ textAlign: 'left', color: 'var(--text-muted)' }}>
            {definition.procedure_en.map((step, index) => (
              <li key={index} style={{ textAlign: 'left' }}>
                {step}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {/* ── readings ──────────────────────────────────────────────────── */}
      <Card
        title={t('القراءات', 'Readings')}
        subtitle={t(
          'أدخل القيم؛ يتلوّن الحقل مقابل حده المطبق، والحكم النهائي من الخادم بعد «تشغيل المعايرة».',
          'Enter the values; each field is coloured against its applied limit, and the verdict comes from the server after Run Calibration.',
        )}
        actions={
          <span className="chip chip-quiet text-[10.5px]">
            {missing.length
              ? t(`${missing.length} حقل ناقص`, `${missing.length} field(s) missing`)
              : t('مكتمل', 'Complete')}
          </span>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {definition.fields.map((field) => {
            const isSeries = field.type === 'series' || field.type === 'spectrum';
            const series = Array.isArray(values[field.key]) ? (values[field.key] as string[]) : [];
            const metric = evaluation?.metrics.find((item) => item.metric_key === field.key);
            const fieldTone = metric ? tone(metric.status) : null;
            return (
              <div key={field.key} className={isSeries ? 'sm:col-span-2 lg:col-span-3' : ''}>
                <Field
                  label={`${lang === 'ar' ? field.label_ar : field.label_en}${field.unit ? ` (${field.unit})` : ''}`}
                  hint={field.hint_ar && lang === 'ar' ? field.hint_ar : undefined}
                >
                  {field.type === 'select' ? (
                    <select
                      className="select"
                      value={String(values[field.key] ?? '')}
                      onChange={(event) => setScalar(field.key, event.target.value)}
                      style={fieldTone ?? undefined}
                    >
                      <option value="">{t('— اختر —', '— select —')}</option>
                      {(field.options ?? []).map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : isSeries ? (
                    <div className="grid grid-cols-5 gap-1.5 md:grid-cols-10">
                      {Array.from({ length: field.length ?? 3 }, (_, index) => (
                        <input
                          key={index}
                          className="input mono px-1.5 py-1 text-[11.5px]"
                          inputMode="decimal"
                          aria-label={`${field.key}-${index + 1}`}
                          value={series[index] ?? ''}
                          onChange={(event) => setSeriesCell(field.key, index, event.target.value, field.length ?? 3)}
                          onClick={(event) => event.stopPropagation()}
                        />
                      ))}
                    </div>
                  ) : (
                    <input
                      className="input mono"
                      inputMode={field.type === 'text' ? 'text' : 'decimal'}
                      value={String(values[field.key] ?? '')}
                      onChange={(event) => setScalar(field.key, event.target.value)}
                      style={fieldTone ?? undefined}
                    />
                  )}
                </Field>
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            className="btn btn-primary"
            onClick={() => void runCalibration()}
            disabled={running || !can('calibration.run')}
          >
            {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {t('تشغيل المعايرة', 'Run Calibration')}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setConfirmOpen(true)}
            disabled={saving || !evaluation || !can('calibration.run')}
            title={!evaluation ? t('شغّل الحساب على الخادم أولاً', 'Run the server calculation first') : undefined}
          >
            <Save size={15} /> {t('حفظ', 'Save')}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              const seed: Values = {};
              for (const field of definition.fields) {
                seed[field.key] =
                  field.type === 'series' || field.type === 'spectrum'
                    ? Array.from({ length: field.length ?? 3 }, () => '')
                    : '';
              }
              setValues(seed);
              setEvaluation(null);
            }}
          >
            <RotateCcw size={14} /> {t('تفريغ', 'Clear')}
          </button>
          {!can('calibration.run') && (
            <span className="text-[11px]" style={{ color: 'var(--warn)' }}>
              {t(
                'أنت تقرأ هذه الصفحة فقط: إدخال القراءات وتشغيل المعايرة من عمل المنضدة، والحدود والنتائج المخزَّنة معروضة كما هي.',
                'This page is read-only for your role: entering readings and running the calibration belong to the bench; limits and stored results are shown as they are.',
              )}
            </span>
          )}
        </div>
      </Card>

      {/* ── server summary ────────────────────────────────────────────── */}
      {evaluation && (
        <Card
          title={t('ملخص الحساب — من الخادم', 'Calculation summary — computed by the server')}
          subtitle={
            statusCounts
              ? t(
                  `${statusCounts.pass} حداً مطابقاً · ${statusCounts.fail} خارج الحد · المصدر ${evaluation.limit_source_policy}`,
                  `${statusCounts.pass} limits met · ${statusCounts.fail} outside the limit · source ${evaluation.limit_source_policy}`,
                )
              : undefined
          }
          actions={<StatusChip status={evaluation.status} />}
          dense
        >
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('المقياس', 'Metric')}</th>
                  <th>{t('القيمة', 'Value')}</th>
                  <th>{t('الحد المطبق', 'Applied limit')}</th>
                  <th>{t('المصدر', 'Source')}</th>
                  <th>{t('الحكم', 'Verdict')}</th>
                </tr>
              </thead>
              <tbody>
                {evaluation.metrics.map((metric) => (
                  <tr key={metric.metric_key}>
                    <td className="font-mono text-[11px]">{metric.metric_key}</td>
                    <td className="mono" style={tone(metric.status)}>
                      {metric.value ?? '—'} {metric.unit}
                    </td>
                    <td className="mono text-[11px]">{metric.limit_text || '—'}</td>
                    <td className="text-[10.5px]">{metric.applied_source ?? '—'}</td>
                    <td>
                      <StatusChip status={metric.status} small />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
            {t(
              'هذه القيم أعاد الخادم حسابها من نفس القراءات؛ الشهادة تُبنى من الصفوف المخزّنة بعد الحفظ.',
              'These values were recomputed by the server from the same readings; the certificate is built from stored rows after Save.',
            )}
          </p>
        </Card>
      )}

      {/* ── statistics per series ─────────────────────────────────────── */}
      {evaluation && Object.keys(evaluation.statistics).length > 0 && (
        <Card
          title={t('إحصاءات السلاسل — المتوسط، الانحراف المعياري، %RSD، الانحراف', 'Series statistics — mean, SD, %RSD, deviation')}
          subtitle={t('محسوبة بـ Decimal على الخادم من نفس القراءات.', 'Computed in Decimal on the server from the same readings.')}
          dense
        >
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('السلسلة', 'Series')}</th>
                  <th>n</th>
                  <th>Mean</th>
                  <th>SD</th>
                  <th>%RSD</th>
                  <th>{t('أدنى', 'Min')}</th>
                  <th>{t('أعلى', 'Max')}</th>
                  <th>{t('أقصى انحراف عن المتوسط', 'Max deviation')}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(evaluation.statistics as Record<string, ServerSeriesStatistics>).map(([key, stats]) => (
                  <tr key={key}>
                    <td className="font-mono text-[11px]">{key}</td>
                    <td className="mono">{stats.n}</td>
                    <td className="mono">{stats.mean ?? '—'}</td>
                    <td className="mono">{stats.sd ?? '—'}</td>
                    <td className="mono">{stats.rsd_pct ?? '—'}</td>
                    <td className="mono">{stats.min}</td>
                    <td className="mono">{stats.max}</td>
                    <td className="mono">{stats.deviation ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ── charts ────────────────────────────────────────────────────── */}
      {evaluation && metricChart && (
        <Card
          title={t('الحدود المطبقة مقابل القياس', 'Applied limits against the measurement')}
          subtitle={t('100 % هو حد القبول المطبق؛ ما فوقه خارج الحد.', '100 % is the applied acceptance limit; anything above it is outside.')}
        >
          <Chart option={metricChart} height={Math.max(220, evaluation.metrics.length * 34)} />
        </Card>
      )}

      {evaluation && seriesChart && (
        <Card title={t('القراءات المتكررة بالترتيب', 'Replicates in run order')}>
          <Chart option={seriesChart} height={280} />
        </Card>
      )}

      {/* ── approval status & certificate ─────────────────────────────── */}
      {run && (
        <Card
          title={t('حالة الاعتماد والشهادة', 'Approval status and certificate')}
          subtitle={t(
            'الحفظ أرسل إشعاراً إلى مشرف المختبر وضمان الجودة. الشهادة الرسمية بدون علامة مسودة تُتاح بعد اعتماد ضمان الجودة.',
            'Saving notified the supervisor and QA. The official certificate — no DRAFT watermark — becomes available after QA approval.',
          )}
        >
          <div className="grid gap-2 md:grid-cols-3">
            {[
              { ar: 'المحلل', en: 'Analyst', who: run.analyst_username ?? '—', at: run.started_at, state: 'Executed' },
              {
                ar: 'مراجعة المشرف',
                en: 'Supervisor review',
                who: run.reviewer_username ?? '—',
                at: run.reviewed_at,
                state: run.reviewed_at ? 'Approved' : 'Pending Review',
              },
              {
                ar: 'اعتماد ضمان الجودة',
                en: 'QA approval',
                who: run.qa_approver_username ?? '—',
                at: run.qa_approved_at,
                state: run.qa_approved_at ? 'Approved' : 'Pending QA Approval',
              },
            ].map((row) => (
              <div key={row.en} className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border)' }}>
                <p className="text-[11px] font-bold">{t(row.ar, row.en)}</p>
                <p className="mt-1 text-[12px]" style={{ color: row.at ? 'var(--pass)' : 'var(--warn)' }}>
                  {row.at ? <CheckCircle2 size={13} className="inline" /> : <ShieldCheck size={13} className="inline" />} {row.state}
                </p>
                <p className="mt-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {row.who} · {row.at ? new Date(row.at).toLocaleString(lang === 'ar' ? 'ar' : 'en') : '—'}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-ghost" onClick={() => void download('PROVISIONAL')} disabled={!can('reports.export')}>
              <FileText size={15} /> {t('مسودة (موسومة)', 'Draft (watermarked)')}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => void download('OFFICIAL')}
              disabled={!run.is_locked || !can('reports.export')}
              title={
                run.is_locked
                  ? t('الشهادة الكاملة بعد اعتماد ضمان الجودة', 'The full certificate, after QA approval')
                  : t('تُتاح بعد اعتماد ضمان الجودة', 'Available after QA approval')
              }
            >
              <Download size={15} /> {t('الشهادة الرسمية (PDF)', 'Official certificate (PDF)')}
            </button>
            <Link href="/qa" className="btn btn-ghost">
              <BadgeCheck size={15} /> {t('مسار الاعتماد', 'Approval queue')}
            </Link>
            <Link href={`/reference-manual`} className="btn btn-ghost">
              <BookOpen size={15} /> {t('الدليل المرجعي', 'Reference manual')}
            </Link>
          </div>
          {run.is_locked && (
            <p className="mt-2 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
              {t(
                'بصمة الشهادة: ',
                'Certificate fingerprint: ',
              )}
              <span className="font-mono">{run.certificate_hash ?? '—'}</span>
            </p>
          )}
        </Card>
      )}

      {/* ── save confirmation ─────────────────────────────────────────── */}
      <Modal
        open={confirmOpen}
        title={t('تأكيد حفظ المعايرة', 'Confirm saving the calibration')}
        onClose={() => (saving ? undefined : setConfirmOpen(false))}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setConfirmOpen(false)} disabled={saving}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button className="btn btn-primary" onClick={() => void saveRun()} disabled={saving}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              {saving ? t('جارٍ الحفظ…', 'Saving…') : t('حفظ وإرسال للمراجعة', 'Save & submit for review')}
            </button>
          </>
        }
      >
        <div className="space-y-2 text-[12px]">
          <div className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)' }}>
            <span className="font-bold">{t('حكم الخادم', 'Server verdict')}</span>
            {evaluation ? <StatusChip status={evaluation.status} /> : '—'}
          </div>
          <p className="leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {t(
              `سيُحفظ تشغيل لهذه الوحدة (${unitLabel}) يتضمن الاختبار ${code} فقط، ببصمة SHA-256، ويُرسل إشعار إلى مشرف المختبر وضمان الجودة. لا يمكن تعديل النتائج بعد الاعتماد.`,
              `A run will be stored for this unit (${unitLabel}) containing only ${code}, fingerprinted with SHA-256, and the supervisor and QA will be notified. Results cannot change after approval.`,
            )}
          </p>
        </div>
      </Modal>
    </div>
  );
}
