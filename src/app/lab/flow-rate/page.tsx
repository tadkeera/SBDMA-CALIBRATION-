'use client';

/**
 * Flow Rate (T02) — the dedicated test page.
 *
 * The generic laboratory screen renders one card per test from the protocol schema; that
 * shape is right for a single reading and wrong for this test, which is thirty numbers in
 * three rows. This page owns the whole job:
 *
 *   1. the reference limits for each set point, printed as an actual mL/min band
 *      (0.980–1.020 for 1.000 mL/min) because that is what the analyst compares against
 *      while holding a flask;
 *   2. a 3 × 10 grid with statistics that update on every keystroke — mean, sample SD,
 *      %RSD and %accuracy per set point, coloured green or red the moment a row is decided;
 *   3. **Run Calibration**, which asks the *server* to recompute the grid and draws the
 *      accuracy and control charts from its answer — the browser panel is a preview, the
 *      server is the record;
 *   4. **Save**, which creates a single-test run and executes it through the same endpoint
 *      every other screen uses, and **Download**, which issues the certificate as an
 *      official document once the run is approved, or a watermarked draft until then.
 */

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import { ArrowLeft, CheckCircle2, Download, FileText, Loader2, Play, Save, ShieldCheck } from 'lucide-react';

import { api } from '@/core/api/client';
import type { ServerFlowRateDefinition, ServerFlowRateEvaluation, ServerRun } from '@/core/api/client';
import { downloadReport } from '@/core/api/client';
import { useApp } from '@/components/AppProvider';
import { Chart } from '@/components/Chart';
import { Card, Field, StatusChip } from '@/components/ui';

const READINGS = 10;

/** Client-side preview. The *authoritative* numbers come from /flow-rate/calculate. */
function preview(values: string[], nominal: number, accuracyPct: number) {
  // `Number('')` is 0, which would make an untouched row look like a pump delivering nothing
  // (mean 0.0000, accuracy −100 %). Empty cells are absent readings, not zero readings.
  const nums = values
    .filter((value) => value.trim() !== '')
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const n = nums.length;
  if (!n) {
    return { n: 0, mean: null as number | null, sd: null as number | null, rsd: null as number | null, acc: null as number | null };
  }
  const mean = nums.reduce((a, b) => a + b, 0) / n;
  const variance = n > 1 ? nums.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1) : null;
  const sd = variance === null ? null : Math.sqrt(variance);
  const rsd = sd === null || mean === 0 ? null : (sd / mean) * 100;
  const acc = ((mean - nominal) / nominal) * 100;
  return { n, mean, sd, rsd, acc };
}

function tone(pass: boolean | null) {
  if (pass === null) return { color: 'var(--text-muted)', background: 'transparent' };
  return pass
    ? { color: 'var(--pass)', background: 'rgba(22,121,79,.10)' }
    : { color: 'var(--fail)', background: 'rgba(180,35,24,.10)' };
}

export default function FlowRatePage() {
  const { t, lang, user, notify, can } = useApp();
  const [definition, setDefinition] = useState<ServerFlowRateDefinition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [grid, setGrid] = useState<string[][]>(() => Array.from({ length: 3 }, () => Array(READINGS).fill('')));
  const [evaluation, setEvaluation] = useState<ServerFlowRateEvaluation | null>(null);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [run, setRun] = useState<ServerRun | null>(null);
  const [instruments, setInstruments] = useState<Array<{ id: string; label: string }>>([]);
  const [instrumentId, setInstrumentId] = useState('');
  const [errors, setErrors] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [def, list] = await Promise.all([api.flowRateDefinition(), api.instruments()]);
        if (cancelled) return;
        setDefinition(def);
        const options = list.map((i) => ({ id: i.id, label: `${i.manufacturer} ${i.model} — ${i.asset_code}` }));
        setInstruments(options);
        setInstrumentId(options[0]?.id ?? '');
      } catch (error) {
        if (!cancelled) setLoadError((error as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const accuracyPct = definition ? Number(definition.acceptance.accuracy_pct) : 2;
  const rsdPct = definition ? Number(definition.acceptance.rsd_pct) : 1;

  const local = useMemo(
    () =>
      grid.map((row, index) =>
        preview(row, definition ? Number(definition.set_points[index]?.nominal ?? 0) : 0, accuracyPct),
      ),
    [grid, definition, accuracyPct],
  );

  const filled = grid.flat().filter((v) => v.trim() !== '').length;
  const readyToRun = filled === 30;

  const setCell = (rowIndex: number, cellIndex: number, value: string) => {
    // keep only what can legitimately sit in a decimal cell: digits, one separator, sign
    if (value !== '' && !/^-?\d*[.,]?\d*$/.test(value)) return;
    setGrid((prev) => {
      const next = prev.map((row) => [...row]);
      next[rowIndex][cellIndex] = value.replace(',', '.');
      return next;
    });
    // a hand-edited grid invalidates the previous server verdict
    setEvaluation(null);
  };

  const runCalibration = async () => {
    setRunning(true);
    setErrors([]);
    try {
      const payload = grid.map((row) => row.map((v) => (v.trim() === '' ? null : Number(v))));
      const result = await api.flowRateCalculate(payload);
      setEvaluation(result);
      if (!result.complete) {
        setErrors([t('الشبكة غير مكتملة — أدخل القراءات الثلاثين قبل الاعتماد على الحساب.', 'The grid is incomplete — enter all thirty readings.')]);
      }
      notify(
        result.overall === 'PASS' ? 'success' : result.overall === 'FAIL' ? 'error' : 'warn',
        t(`حساب الخادم: ${result.overall}`, `Server verdict: ${result.overall}`),
        t(
          `أقصى دقة ${result.max_abs_accuracy ?? '—'}% · أقصى RSD ${result.max_rsd ?? '—'}%`,
          `Worst accuracy ${result.max_abs_accuracy ?? '—'}% · worst %RSD ${result.max_rsd ?? '—'}%`,
        ),
      );
    } catch (error) {
      setErrors([(error as Error).message]);
    } finally {
      setRunning(false);
    }
  };

  const saveRun = async () => {
    if (!instrumentId) {
      setErrors([t('اختر الجهاز أولاً.', 'Select the instrument first.')]);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      const created = await api.createRun({
        instrument_id: instrumentId,
        run_type: 'ROUTINE',
        limit_source_policy: 'AUTHORITY_LIMIT',
      });
      const raw = {
        T02: {
          flow_p1000: grid[0].filter((v) => v.trim() !== '').map(Number),
          flow_p1500: grid[1].filter((v) => v.trim() !== '').map(Number),
          flow_p2000: grid[2].filter((v) => v.trim() !== '').map(Number),
        },
      };
      const executed = await api.executeRun(created.id, raw, ['T02']);
      setRun(executed.run);
      notify(
        executed.overall === 'PASS' ? 'success' : executed.overall === 'FAIL' ? 'error' : 'warn',
        t(`تم حفظ التشغيل — ${executed.overall}`, `Run saved — ${executed.overall}`),
        executed.run.execution_code,
      );
    } catch (error) {
      setErrors([(error as Error).message]);
    } finally {
      setSaving(false);
    }
  };

  const download = async (stage: 'OFFICIAL' | 'PROVISIONAL') => {
    if (!run) return;
    try {
      await downloadCertificate(run.id, stage);
    } catch (error) {
      setErrors([(error as Error).message]);
    }
  };

  const chartOption = useMemo<EChartsOption | null>(() => {
    if (!evaluation) return null;
    const labels = evaluation.set_points.map((sp) => `${sp.nominal}`);
    const means = evaluation.set_points.map((sp) => (sp.mean ? Number(sp.mean) : null));
    const accuracies = evaluation.set_points.map((sp) => (sp.accuracy_pct ? Number(sp.accuracy_pct) : null));
    const band = Number(evaluation.accuracy_limit);
    const series: EChartsOption['series'] = [
      { name: t('المتوسط المقاس', 'Measured mean'), type: 'bar', data: means, itemStyle: { color: '#21695e' }, barWidth: '34%' },
      {
        name: t('الدقة %', '%accuracy'),
        type: 'line',
        yAxisIndex: 1,
        data: accuracies,
        symbolSize: 8,
        lineStyle: { width: 2, color: '#b54708' },
        itemStyle: { color: '#b54708' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            { yAxis: band, lineStyle: { color: '#b42318', type: 'dashed' }, label: { formatter: `+${band}%`, color: '#b42318', fontSize: 9 } },
            { yAxis: -band, lineStyle: { color: '#b42318', type: 'dashed' }, label: { formatter: `−${band}%`, color: '#b42318', fontSize: 9 } },
            { yAxis: 0, lineStyle: { color: '#98a2b3', type: 'solid', width: 1 }, label: { formatter: '0', color: '#667085', fontSize: 9 } },
          ],
        },
      },
    ];
    return {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { fontSize: 10.5 } },
      grid: { left: 56, right: 56, top: 34, bottom: 36 },
      xAxis: { type: 'category', data: labels, name: 'mL/min', nameLocation: 'middle', nameGap: 24 },
      yAxis: [
        { type: 'value', name: 'mL/min' },
        { type: 'value', name: '%', splitLine: { show: false } },
      ],
      series,
    } as EChartsOption;
  }, [evaluation, t]);

  const controlOption = useMemo<EChartsOption | null>(() => {
    if (!evaluation) return null;
    const points: Array<[number, number]> = [];
    evaluation.set_points.forEach((sp) => {
      sp.readings.forEach((value, index) => {
        if (value !== null) points.push([sp.index * 10 + index + 1, Number(value)]);
      });
    });
    const bandLines = evaluation.set_points.map((sp) => ({
      yAxis: Number(sp.upper_limit),
      lineStyle: { color: '#b42318', type: 'dashed' as const },
      label: { formatter: `${sp.upper_limit}`, color: '#b42318', fontSize: 9 },
    }));
    return {
      tooltip: { trigger: 'item' },
      grid: { left: 60, right: 40, top: 26, bottom: 36 },
      xAxis: { type: 'value', name: t('رقم القراءة', 'Reading #'), min: 1, max: 30, interval: 5 },
      yAxis: { type: 'value', name: 'mL/min', scale: true },
      series: [
        {
          name: t('القراءات', 'Readings'),
          type: 'scatter',
          symbolSize: 7,
          data: points,
          itemStyle: { color: '#21695e' },
          markLine: { silent: true, symbol: 'none', data: bandLines },
        },
      ],
    } as EChartsOption;
  }, [evaluation, t]);

  if (loadError) {
    return (
      <Card title={t('تعذر تحميل تعريف الاختبار', 'The test definition could not be loaded')}>
        <p className="text-[13px]" style={{ color: 'var(--fail)' }}>{loadError}</p>
        <Link href="/lab" className="btn btn-ghost mt-3">
          <ArrowLeft size={15} /> {t('العودة إلى المختبر', 'Back to the laboratory')}
        </Link>
      </Card>
    );
  }

  if (!definition) {
    return (
      <Card title={t('جارٍ التحميل…', 'Loading…')}>
        <div className="flex items-center gap-2 text-[13px]" style={{ color: 'var(--text-muted)' }}>
          <Loader2 size={16} className="animate-spin" /> {t('يُقرأ البروتوكول المعتمد وحدوده', 'Reading the approved protocol and its limits')}
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[17px] font-bold">{t('اختبار معدل التدفق', 'Flow Rate test')} — T02</h2>
          <p className="text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
            {t(
              `${definition.protocol_code} · الإصدار ${definition.protocol_version} · 3 نقاط ضبط × 10 قراءات`,
              `${definition.protocol_code} · v${definition.protocol_version} · 3 set points × 10 readings`,
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/lab" className="btn btn-ghost">
            <ArrowLeft size={15} /> {t('لوحة المختبر', 'Laboratory')}
          </Link>
        </div>
      </div>

      {errors.length > 0 && (
        <div className="card p-3 text-[12px]" style={{ borderColor: 'var(--fail)', color: 'var(--fail)' }}>
          {errors.map((message, index) => (
            <p key={index}>{message}</p>
          ))}
        </div>
      )}

      <Card
        title={t('الحدود المرجعية لكل نقطة ضبط', 'Reference limits for each set point')}
        subtitle={t(
          `الدقة المقبولة ±${definition.acceptance.accuracy_pct}% (${definition.acceptance.accuracy_band}%) و%RSD ≤ ${definition.acceptance.rsd_pct}% — من جدول الحدود المعتمد`,
          `Accepted accuracy ±${definition.acceptance.accuracy_pct}% (${definition.acceptance.accuracy_band}%) and %RSD ≤ ${definition.acceptance.rsd_pct}% — from the approved limit table`,
        )}
        dense
      >
        <table className="table">
          <thead>
            <tr>
              <th>{t('نقطة الضبط', 'Set point')}</th>
              <th>{t('الحد الأدنى', 'Lower limit')}</th>
              <th>{t('الحد الأعلى', 'Upper limit')}</th>
              <th>{t('مدى الدقة', 'Accuracy band')}</th>
              <th>{t('%RSD', '%RSD')}</th>
              <th>{t('عدد القراءات', 'Readings')}</th>
            </tr>
          </thead>
          <tbody>
            {definition.set_points.map((point) => (
              <tr key={point.index}>
                <td className="font-bold mono">{point.nominal} mL/min</td>
                <td className="mono" style={{ color: 'var(--fail)' }}>{point.lower_limit}</td>
                <td className="mono" style={{ color: 'var(--pass)' }}>{point.upper_limit}</td>
                <td className="mono">{definition.acceptance.accuracy_band}%</td>
                <td className="mono">≤ {definition.acceptance.rsd_pct}%</td>
                <td className="mono">{point.readings_per_set_point}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title={t('شبكة القراءات — 10 قراءات لكل نقطة ضبط', 'Readings grid — 10 per set point')}
        subtitle={t(
          'أدخل القيم المقاسة بوحدة mL/min. الحساب يتحدث مع كل إدخال، والحكم النهائي من الخادم.',
          'Enter the measured values in mL/min. The panel updates on every keystroke; the verdict comes from the server.',
        )}
        actions={
          <span className="text-[11px] tabular" dir="ltr" style={{ color: 'var(--text-muted)' }}>
            {filled} / 30
          </span>
        }
      >
        <div className="space-y-3">
          {definition.set_points.map((point, rowIndex) => {
            const stats = local[rowIndex];
            const accPass = stats.acc === null ? null : Math.abs(stats.acc) <= accuracyPct;
            const rsdPass = stats.rsd === null ? null : stats.rsd <= rsdPct;
            return (
              <div key={point.index} className="rounded-lg border p-2" style={{ borderColor: 'var(--border)' }}>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className="chip chip-quiet mono">{point.nominal} mL/min</span>
                  <span className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                    {t(`المدى المقبول ${point.lower_limit} – ${point.upper_limit}`, `Accepted band ${point.lower_limit} – ${point.upper_limit}`)}
                  </span>
                </div>
                <div className="grid grid-cols-5 gap-1.5 md:grid-cols-10">
                  {Array.from({ length: READINGS }, (_, cellIndex) => {
                    const value = grid[rowIndex][cellIndex];
                    const numeric = value.trim() === '' ? null : Number(value);
                    const inside =
                      numeric === null || !Number.isFinite(numeric)
                        ? null
                        : numeric >= Number(point.lower_limit) && numeric <= Number(point.upper_limit);
                    return (
                      <div key={cellIndex}>
                        <label className="mb-0.5 block text-[9.5px]" style={{ color: 'var(--text-muted)' }}>
                          {t(`قراءة ${cellIndex + 1}`, `Run ${cellIndex + 1}`)}
                        </label>
                        <input
                          className="input mono px-1.5 py-1 text-[11.5px]"
                          inputMode="decimal"
                          step="any"
                          value={value}
                          aria-label={`run-${rowIndex + 1}-${cellIndex + 1}`}
                          onChange={(event) => setCell(rowIndex, cellIndex, event.target.value)}
                          style={inside === null ? undefined : { borderColor: inside ? 'var(--pass)' : 'var(--fail)' }}
                        />
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="chip" style={tone(accPass)}>
                    {t('المتوسط', 'Mean')}: <b className="mono">{stats.mean === null ? '—' : stats.mean.toFixed(4)}</b>
                  </span>
                  <span className="chip chip-quiet">
                    SD: <b className="mono">{stats.sd === null ? '—' : stats.sd.toFixed(5)}</b>
                  </span>
                  <span className="chip" style={tone(rsdPass)}>
                    %RSD: <b className="mono">{stats.rsd === null ? '—' : stats.rsd.toFixed(3)}</b>
                  </span>
                  <span className="chip" style={tone(accPass)}>
                    {t('الدقة', 'Accuracy')}: <b className="mono">{stats.acc === null ? '—' : `${stats.acc.toFixed(3)}%`}</b>
                  </span>
                  <span className="ml-auto text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                    {stats.n} / {READINGS}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Field label={t('الجهاز', 'Instrument')}>
            <select className="select" value={instrumentId} onChange={(event) => setInstrumentId(event.target.value)}>
              {instruments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <button className="btn btn-primary" onClick={runCalibration} disabled={running || !readyToRun || !can('calibration.run')}>
            {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {t('تشغيل المعايرة', 'Run Calibration')}
          </button>
          <button className="btn btn-ghost" onClick={saveRun} disabled={saving || !evaluation || !can('calibration.run')}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            {t('حفظ', 'Save')}
          </button>
          <button className="btn btn-ghost" onClick={() => void download(run?.is_locked ? 'OFFICIAL' : 'PROVISIONAL')} disabled={!run || !can('reports.export')}>
            <Download size={15} /> {t('تنزيل الشهادة (PDF)', 'Download certificate (PDF)')}
          </button>
          {!readyToRun && (
            <span className="text-[11px]" style={{ color: 'var(--warn)' }}>
              {t('أكمل القراءات الثلاثين لبدء التشغيل.', 'Complete all thirty readings to run.')}
            </span>
          )}
        </div>
      </Card>

      {evaluation && (
        <Card
          title={t('ملخص الحساب — من الخادم', 'Calculation summary — computed by the server')}
          subtitle={t(
            `الحالة الإجمالية: ${evaluation.overall} · أقصى دقة ${evaluation.max_abs_accuracy ?? '—'}% · أقصى %RSD ${evaluation.max_rsd ?? '—'}%`,
            `Overall ${evaluation.overall} · worst accuracy ${evaluation.max_abs_accuracy ?? '—'}% · worst %RSD ${evaluation.max_rsd ?? '—'}%`,
          )}
          actions={<StatusChip status={evaluation.overall} />}
          dense
        >
          <table className="table">
            <thead>
              <tr>
                <th>{t('نقطة الضبط', 'Set point')}</th>
                <th>{t('المتوسط mL/min', 'Mean mL/min')}</th>
                <th>SD</th>
                <th>%RSD</th>
                <th>{t('الدقة %', '%Accuracy')}</th>
                <th>{t('حد الدقة', 'Accuracy limit')}</th>
                <th>{t('الحالة', 'Status')}</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.set_points.map((point) => (
                <tr key={point.index}>
                  <td className="mono font-bold">{point.nominal}</td>
                  <td className="mono">{point.mean ?? '—'}</td>
                  <td className="mono">{point.sd ?? '—'}</td>
                  <td className="mono" style={tone(point.rsd_status === 'PASS' ? true : point.rsd_status === 'FAIL' ? false : null)}>
                    {point.rsd_pct ?? '—'}
                  </td>
                  <td className="mono" style={tone(point.accuracy_status === 'PASS' ? true : point.accuracy_status === 'FAIL' ? false : null)}>
                    {point.accuracy_pct ?? '—'}
                  </td>
                  <td className="mono">{`${point.lower_limit} – ${point.upper_limit}`}</td>
                  <td>
                    <StatusChip status={point.status} small />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
            {t(
              'القيم أعلاه أعاد الخادم حسابها من نفس القراءات؛ الشهادة تُبنى من الصفوف المخزّنة بعد الحفظ، لا من هذه اللوحة.',
              'These values were recomputed by the server from the same readings; the certificate is built from stored rows after Save, not from this panel.',
            )}
          </p>
        </Card>
      )}

      {evaluation && chartOption && (
        <Card title={t('منحنى الدقة والمقارنة بالحد المعتمد', 'Accuracy curve against the adopted limit')}>
          <Chart option={chartOption} height={280} />
        </Card>
      )}

      {evaluation && controlOption && (
        <Card
          title={t('مخطط التحكم — القراءات الثلاثون وحدود القبول', 'Control chart — thirty readings and the acceptance band')}
          subtitle={t('كل نقطة قراءة واحدة؛ الخطوط المتقطعة هي حدود القبول لنقطة الضبط.', 'Each dot is one reading; the dashed lines are that set point`s acceptance band.')}
        >
          <Chart option={controlOption} height={300} />
        </Card>
      )}

      {run && (
        <Card
          title={t('حالة الاعتماد', 'Approval status')}
          subtitle={t(
            'الشهادة الرسمية تُصدر بعد مراجعة المشرف واعتماد ضمان الجودة. قبل ذلك يُتاح مستند مسودة موسوم.',
            'The official certificate is issued after supervisor review and QA approval. Until then a watermarked draft is available.',
          )}
        >
          <div className="grid gap-2 md:grid-cols-3">
            {[
              {
                ar: 'المحلل',
                en: 'Analyst',
                who: run.analyst_username ?? user?.username ?? '—',
                at: run.started_at,
                state: 'Executed',
              },
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
                  {row.at ? <CheckCircle2 size={13} className="inline" /> : <ShieldCheck size={13} className="inline" />}{' '}
                  {row.state}
                </p>
                <p className="mt-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {row.who} · {row.at ? new Date(row.at).toLocaleString(lang === 'ar' ? 'ar' : 'en') : '—'}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-ghost" onClick={() => void download('PROVISIONAL')}>
              <FileText size={15} /> {t('مسودة (موسومة)', 'Draft (watermarked)')}
            </button>
            <button className="btn btn-primary" onClick={() => void download('OFFICIAL')} disabled={!run.is_locked}>
              <Download size={15} /> {t('الشهادة الرسمية', 'Official certificate')}
            </button>
          </div>
        </Card>
      )}
    </div>
  );
}

/** Downloads through the authenticated path, with the stage in the query string. */
async function downloadCertificate(runId: string, stage: 'OFFICIAL' | 'PROVISIONAL') {
  const query = stage === 'PROVISIONAL' ? '?stage=PROVISIONAL' : '';
  await downloadReport(`/reports/runs/${runId}/tests/T02/certificate.pdf${query}`, `T02-${stage.toLowerCase()}.pdf`);
}
