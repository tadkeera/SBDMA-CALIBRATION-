'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BadgeCheck,
  ChevronLeft,
  ClipboardList,
  Download,
  FlaskConical,
  Info,
  Play,
  RotateCcw,
  Save,
} from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Field, Metric, Modal, Skeleton, StatusChip, Toolbar } from '@/components/ui';
import { TestChart } from '@/components/TestCharts';
import { db } from '@/core/db/database';
import {
  ApiError,
  OfflineError,
  api,
  downloadReport,
  toInstrument,
  toReferenceEquipment,
  toRunTestResults,
  type ServerRun,
} from '@/core/api/client';
import { SOURCE_LABEL } from '@/core/api/mode';
import { runCalibration } from '@/core/engine/runEngine';
import { roundForDisplay } from '@/core/engine/safeMath';
import { BREAKDOWN_MATRIX, LIMITS, TESTS, testsForComponent } from '@/core/protocol';
import {
  LIMIT_SOURCES,
  SOURCE_LABELS,
  type Instrument,
  type LimitSource,
  type ReferenceEquipment,
  type RunRecord,
  type Status,
  type TestSpec,
} from '@/core/types';

export default function LabPage() {
  const { t, lang, ready, user, notify, can, readThrough, source, setSource } = useApp();
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [refEq, setRefEq] = useState<ReferenceEquipment[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedInstrument, setSelectedInstrument] = useState<string>('');
  const [runType, setRunType] = useState<RunRecord['runType']>('ROUTINE');
  const [component, setComponent] = useState<string>('PUMP');
  const [ambientTemp, setAmbientTemp] = useState('24.5');
  const [ambientHumidity, setAmbientHumidity] = useState('48');
  const [refThermo, setRefThermo] = useState<string>('');
  const [policySource, setPolicySource] = useState<LimitSource>('AUTHORITY_LIMIT');
  const [inputs, setInputs] = useState<Record<string, Record<string, unknown>>>({});
  const [activeTest, setActiveTest] = useState<string>('T01');
  const [result, setResult] = useState<ReturnType<typeof runCalibration> | null>(null);
  const [running, setRunning] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [savedRun, setSavedRun] = useState<RunRecord | null>(null);
  const [serverRun, setServerRun] = useState<ServerRun | null>(null);
  const [signatureOpen, setSignatureOpen] = useState(false);
  const [deviationOpen, setDeviationOpen] = useState(false);
  const [devTitle, setDevTitle] = useState('');
  const [devDescription, setDevDescription] = useState('');
  const [devClass, setDevClass] = useState('MAJOR');
  const [devBusy, setDevBusy] = useState(false);
  const [signaturePassword, setSignaturePassword] = useState('');
  const [signatureReason, setSignatureReason] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    if (!ready) return;
    (async () => {
      try {
        const [{ data: rows, source: stamp }, refs] = await Promise.all([
          readThrough(
            () => api.instruments(),
            async () => {
              const cached = await db().instruments.toArray();
              return cached.map((c) => ({
                id: c.id,
                department_id: c.departmentCode,
                asset_code: c.assetCode,
                category: c.category,
                manufacturer: c.manufacturer,
                model: c.model,
                part_number: c.partNumber,
                serial_number: c.serialNumber,
                software_version: c.softwareVersion,
                calibration_freq_days: c.calibrationFreqDays,
                last_calibration_date: c.lastCalibrationDate,
                next_due_date: c.nextDueDate,
                status: c.status,
                d2_lamp_hours: c.d2LampHours,
              }));
            },
          ),
          readThrough(
            () => api.referenceEquipment(),
            async () => {
              const cached = await db().referenceEquipment.toArray();
              return cached.map((c) => ({
                id: c.id,
                equipment_code: c.code,
                name_ar: c.nameAr,
                name_en: c.nameEn,
                serial_number: c.serialNumber,
                certificate_no: c.certificateNo,
                calibrated_by: c.calibratedBy,
                calibration_date: c.calibrationDate,
                expiry_date: c.expiryDate,
                correction_table_jsonb: c.correctionTable ?? [],
                is_active: c.isActive,
                expired: new Date(c.expiryDate).getTime() < Date.now(),
                days_to_expiry: Math.ceil((new Date(c.expiryDate).getTime() - Date.now()) / 86400000),
              }));
            },
          ),
        ]);
        setSource(stamp);
        setInstruments(rows.map((row) => toInstrument(row)));
        setRefEq(refs.data.map((row) => toReferenceEquipment(row)));
        if (rows.length) setSelectedInstrument((prev) => prev || rows[0].id);
      } catch (error) {
        setLoadError(
          error instanceof ApiError
            ? error.text(lang)
            : t('تعذر تحميل سجل الأجهزة من الخادم.', 'The instrument register could not be loaded.'),
        );
      } finally {
        setLoading(false);
      }
    })();
  }, [ready, readThrough, setSource, lang, t]);

  const instrument = instruments.find((i) => i.id === selectedInstrument) ?? null;
  const canRun = can('calibration.run');
  const canExport = can('reports.export');

  /** Break-down mode restricts the required scope to the mandatory retest matrix. */
  const scopedTests: TestSpec[] = useMemo(() => {
    if (runType !== 'POST_BREAKDOWN') return TESTS;
    const required = testsForComponent(component);
    return TESTS.filter((x) => required.includes(x.code) || x.code === 'T01');
  }, [runType, component]);

  const activeSpec = TESTS.find((x) => x.code === activeTest)!;

  const setField = (testCode: string, key: string, value: unknown) => {
    setInputs((prev) => ({ ...prev, [testCode]: { ...(prev[testCode] ?? {}), [key]: value } }));
  };

  const seriesValue = (testCode: string, key: string, idx: number): string => {
    const v = inputs[testCode]?.[key];
    if (Array.isArray(v)) return String(v[idx] ?? '');
    return '';
  };

  const setSeries = (testCode: string, key: string, idx: number, raw: string, length: number) => {
    setInputs((prev) => {
      const cur = Array.isArray(prev[testCode]?.[key]) ? [...(prev[testCode]![key] as unknown[])] : [];
      while (cur.length < length) cur.push('');
      cur[idx] = raw === '' ? '' : Number(raw);
      return { ...prev, [testCode]: { ...(prev[testCode] ?? {}), [key]: cur } };
    });
  };

  const missing = useMemo(() => {
    const out: string[] = [];
    for (const test of scopedTests) {
      for (const f of test.fields) {
        if (!f.required) continue;
        const v = inputs[test.code]?.[f.key];
        if (v === undefined || v === null || v === '') {
          out.push(`${test.code} · ${lang === 'ar' ? f.labelAr : f.labelEn}`);
          continue;
        }
        if ((f.type === 'series' || f.type === 'spectrum') && Array.isArray(v)) {
          const clean = v.filter((x) => x !== '' && Number.isFinite(Number(x)));
          if (clean.length < (f.length ?? 1)) out.push(`${test.code} · ${lang === 'ar' ? f.labelAr : f.labelEn}`);
        }
      }
    }
    return out;
  }, [inputs, scopedTests, lang]);

  /** Expiry guard — a run may not proceed on an expired reference thermometer. */
  const expiryBlocked = useMemo(() => {
    const chosen = refEq.find((e) => e.id === refThermo);
    if (chosen && new Date(chosen.expiryDate).getTime() < Date.now()) return chosen;
    return null;
  }, [refEq, refThermo]);

  const handleRun = async () => {
    setErrors([]);
    if (!canRun) {
      notify('error', t('صلاحية غير كافية', 'Insufficient permission'), t('دورك الحالي لا يملك صلاحية calibration.run.', 'Your role lacks calibration.run.'));
      return;
    }
    if (!instrument) {
      setErrors([t('اختر الجهاز المستهدف قبل التشغيل.', 'Select the target instrument first.')]);
      return;
    }
    if (expiryBlocked) {
      setErrors([
        t(
          `الحد الأدنى للسلامة: الأداة المرجعية ${expiryBlocked.code} منتهية الصلاحية (${expiryBlocked.expiryDate}) — يمنع النظام التشغيل.`,
          `Safety guard: reference item ${expiryBlocked.code} expired on ${expiryBlocked.expiryDate} — execution blocked.`,
        ),
      ]);
      notify('error', t('حاجز الصلاحية', 'Expiry guard'), t('اختر أداة مرجعية سارية.', 'Choose a non-expired reference item.'));
      return;
    }
    if (missing.length) {
      setErrors([t(`يوجد ${missing.length} حقلاً إلزامياً غير مكتمل.`, `${missing.length} mandatory fields are missing.`)]);
      return;
    }

    setRunning(true);
    try {
      // Only scoped tests participate; unscoped mandatory tests are excluded explicitly.
      const scopedInputs: Record<string, Record<string, unknown>> = {};
      for (const test of scopedTests) scopedInputs[test.code] = inputs[test.code] ?? {};
      const computed = runCalibration(scopedInputs, { policySource }, scopedTests, LIMITS);
      setResult(computed);
      setConfirmOpen(true);
      const incomplete = computed.results.filter((r) => r.status === 'INCOMPLETE').length;
      if (incomplete) {
        setErrors([t(`${incomplete} اختباراً لم يكتمل بسبب نقص القراءات.`, `${incomplete} tests incomplete.`)]);
      }
    } catch (err) {
      setErrors([(err as Error).message]);
    } finally {
      setRunning(false);
    }
  };

  /**
   * Save path. The client engine above is a preview; the server engine is
   * authoritative and its verdict is what gets stored. We create the run, execute
   * it with the raw readings, then surface the server's own summary.
   */
  const persistRun = async () => {
    if (!result || !instrument || !user) return;
    setSaving(true);
    setErrors([]);
    try {
      const created = await api.createRun({
        instrument_id: instrument.id,
        reference_equipment_id: refThermo || null,
        run_type: runType,
        ambient_temp_c: ambientTemp === '' ? null : Number(ambientTemp),
        ambient_humidity: ambientHumidity === '' ? null : Number(ambientHumidity),
        limit_source_policy: policySource,
        breakdown_component: runType === 'POST_BREAKDOWN' ? component : null,
      });

      const scopedInputs: Record<string, Record<string, unknown>> = {};
      for (const test of scopedTests) {
        const raw = inputs[test.code] ?? {};
        const cleaned: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(raw)) {
          if (Array.isArray(value)) {
            const nums = value.map((v) => (v === '' || v === null ? null : Number(v)));
            if (nums.some((v) => v !== null && Number.isFinite(v))) cleaned[key] = nums.filter((v) => v !== null);
          } else if (value !== '' && value !== undefined && value !== null) {
            cleaned[key] = value;
          }
        }
        scopedInputs[test.code] = cleaned;
      }

      const executed = await api.executeRun(created.id, scopedInputs);
      setServerRun(executed.run);
      setConfirmOpen(false);

      // the server verdict may differ from the preview (it governs on stored limits)
      const record: RunRecord = {
        id: executed.run.id,
        executionCode: executed.run.execution_code,
        instrumentId: executed.run.instrument_id,
        instrumentName: `${instrument.manufacturer} ${instrument.model}`,
        protocolCode: 'SHIMADZU-LC2050C-UV-CAL',
        runType: executed.run.run_type,
        ambientTempC: Number(executed.run.ambient_temp_c ?? 0),
        ambientHumidity: Number(executed.run.ambient_humidity ?? 0),
        analyst: user.username,
        reviewer: null,
        qaApprover: null,
        overallStatus: executed.overall,
        results: toRunTestResults(executed.results),
        startedAt: executed.run.started_at,
        completedAt: executed.run.completed_at,
        isLocked: executed.run.is_locked,
        certificateHash: executed.run.certificate_hash,
        breakdownComponent: executed.run.breakdown_component,
        revision: executed.run.revision,
      };
      setSavedRun(record);
      notify(
        executed.overall === 'PASS' ? 'success' : executed.overall === 'FAIL' ? 'error' : 'warn',
        t(`تم تسجيل التشغيل — الحالة ${executed.overall}`, `Run recorded — ${executed.overall}`),
        `${record.executionCode} · ${executed.summary.pass}P / ${executed.summary.fail}F / ${executed.summary.review}R`,
      );
    } catch (error) {
      if (error instanceof ApiError) {
        setErrors([error.text(lang)]);
        notify('error', t('تعذر حفظ التشغيل', 'Run not saved'), error.code);
      } else if (error instanceof OfflineError) {
        setErrors([
          t('الخادم غير متاح — لا يمكن حفظ تشغيل معايرة دون اتصال بقاعدة البيانات المركزية.', 'Server unreachable — a calibration run cannot be stored without the central database.'),
        ]);
      } else {
        setErrors([(error as Error).message]);
      }
    } finally {
      setSaving(false);
    }
  };

  /**
   * Raise an OOS deviation against the stored run.
   *
   * Only offered for a FAIL or INCOMPLETE verdict: a passing result must not be
   * dressed up as an investigation, and the server refuses it anyway.
   */
  const raiseDeviation = async () => {
    if (!serverRun) return;
    setDevBusy(true);
    try {
      const deviation = await api.raiseDeviation({
        run_id: serverRun.id,
        title: devTitle.trim(),
        description: devDescription.trim(),
        classification: devClass,
      });
      setDeviationOpen(false);
      setDevTitle('');
      setDevDescription('');
      notify(
        'success',
        t('فُتح انحراف OOS', 'OOS deviation raised'),
        `${deviation.reference} · ${t('بانتظار تحقيق ضمان الجودة', 'awaiting QA investigation')}`,
      );
    } catch (error) {
      notify(
        'error',
        t('تعذّر فتح الانحراف', 'Deviation not raised'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setDevBusy(false);
    }
  };

  /** Electronic signature for the technical review (21 CFR Part 11). */
  const submitReviewSignature = async () => {
    if (!serverRun) return;
    setSigning(true);
    try {
      const reviewed = await api.reviewRun(serverRun.id, signaturePassword, signatureReason);
      setServerRun(reviewed);
      setSignatureOpen(false);
      setSignaturePassword('');
      notify('success', t('تم توقيع المراجعة الفنية', 'Technical review signed'), reviewed.execution_code);
    } catch (error) {
      notify(
        'error',
        t('تعذر توقيع المراجعة', 'Signature rejected'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setSigning(false);
    }
  };

  /**
   * Reports are produced by the server from stored rows, never from client state:
   * the PDF is only issued for an approved + locked run and carries the stored
   * certificate fingerprint; the XLSX exports raw inputs, verdicts, limits and the
   * run's own audit trail.
   */
  const downloadReportFile = async (kind: 'certificate.pdf' | 'data.xlsx') => {
    if (!serverRun) return;
    try {
      await downloadReport(`/reports/runs/${serverRun.id}/${kind}`, `${serverRun.execution_code}-${kind}`);
      notify('success', t('تم توليد الملف', 'File generated'), kind);
    } catch (error) {
      notify(
        'error',
        t('تعذر توليد الملف', 'File could not be generated'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    }
  };

  if (loading) return <Skeleton rows={8} />;

  return (
    <div className="space-y-3">
      {/* run header */}
      <Card>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <Field label={t('الجهاز المستهدف', 'Target instrument')}>
            <select className="select" value={selectedInstrument} onChange={(e) => setSelectedInstrument(e.target.value)}>
              <option value="">{t('— اختر —', '— select —')}</option>
              {instruments.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.assetCode} · {i.model}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('نوع التشغيل', 'Run type')}>
            <select className="select" value={runType} onChange={(e) => setRunType(e.target.value as RunRecord['runType'])}>
              <option value="ROUTINE">{t('دوري نصف سنوي', 'Routine semi-annual')}</option>
              <option value="POST_BREAKDOWN">{t('بعد عطل / صيانة', 'Post-breakdown')}</option>
              <option value="INSTALLATION">{t('تأهيل تركيبي IQ/OQ', 'Installation (IQ/OQ)')}</option>
              <option value="ANNUAL">{t('سنوي', 'Annual')}</option>
            </select>
          </Field>
          {runType === 'POST_BREAKDOWN' && (
            <Field label={t('المكوّن المتعطل', 'Failed component')}>
              <select className="select" value={component} onChange={(e) => setComponent(e.target.value)}>
                {BREAKDOWN_MATRIX.map((b) => (
                  <option key={b.key} value={b.key}>
                    {lang === 'ar' ? b.ar : b.en}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={t('مصدر حدود القبول', 'Limit source')}>
            <select className="select" value={policySource} onChange={(e) => setPolicySource(e.target.value as LimitSource)}>
              {LIMIT_SOURCES.map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABELS[s][lang]}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('الأداة المرجعية للحرارة', 'Reference thermometer')}>
            <select className="select" value={refThermo} onChange={(e) => setRefThermo(e.target.value)}>
              <option value="">{t('— اختر —', '— select —')}</option>
              {refEq.map((e) => {
                const expired = new Date(e.expiryDate).getTime() < Date.now();
                return (
                  <option key={e.id} value={e.id}>
                    {e.code} · {expired ? t('منتهية', 'EXPIRED') : e.expiryDate}
                  </option>
                );
              })}
            </select>
          </Field>
          <Field label={t('حرارة / رطوبة الغرفة', 'Ambient temp / RH')}>
            <div className="flex gap-1.5">
              <input className="input mono" value={ambientTemp} onChange={(e) => setAmbientTemp(e.target.value)} aria-label="°C" />
              <input className="input mono" value={ambientHumidity} onChange={(e) => setAmbientHumidity(e.target.value)} aria-label="%RH" />
            </div>
          </Field>
        </div>

        {instrument && (
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg px-3 py-2 text-[11px]" style={{ background: 'var(--surface-2)' }}>
            <span className="font-mono">{instrument.partNumber}</span>
            <span className="font-mono">SN {instrument.serialNumber}</span>
            <span>{instrument.departmentCode}</span>
            <span>
              {t('الاستحقاق القادم', 'Next due')}: <b>{instrument.nextDueDate}</b>
            </span>
            <span>
              {t('ساعات لمبة D2', 'D2 lamp hours')}: <b>{instrument.d2LampHours}</b>
            </span>
            <StatusChip status={instrument.status} small />
          </div>
        )}

        {expiryBlocked && (
          <div className="mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-[11.5px]" style={{ background: 'rgba(180,35,24,.09)', color: 'var(--fail)' }}>
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t(
              `حاجز الصلاحية: ${expiryBlocked.code} انتهت صلاحيتها في ${expiryBlocked.expiryDate}. لا يمكن تشغيل المعايرة بأداة مرجعية منتهية.`,
              `Expiry guard: ${expiryBlocked.code} expired on ${expiryBlocked.expiryDate}. Runs on expired reference items are blocked.`,
            )}
          </div>
        )}
      </Card>

      <div className="grid gap-3 xl:grid-cols-[300px_1fr]">
        {/* test navigator */}
        <Card title={t('اختبارات البروتوكول', 'Protocol tests')} subtitle={t(`${scopedTests.length} اختباراً في النطاق`, `${scopedTests.length} tests in scope`)} dense>
          <ul className="max-h-[520px] overflow-y-auto">
            {TESTS.map((test) => {
              const inScope = scopedTests.some((x) => x.code === test.code);
              const res = result?.perTest[test.code];
              const filled = test.fields.filter((f) => {
                const v = inputs[test.code]?.[f.key];
                if (Array.isArray(v)) return v.filter((x) => x !== '' && Number.isFinite(Number(x))).length >= (f.length ?? 1);
                return v !== undefined && v !== '';
              }).length;
              return (
                <li key={test.code}>
                  <button
                    onClick={() => setActiveTest(test.code)}
                    disabled={!inScope}
                    className="flex w-full items-center gap-2 border-b px-3 py-2 text-start transition-colors disabled:opacity-40"
                    style={{
                      borderColor: 'var(--border)',
                      background: activeTest === test.code ? 'var(--brand-soft)' : 'transparent',
                    }}
                  >
                    <span
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md font-mono text-[10px] font-bold"
                      style={{ background: 'var(--surface-3)', color: 'var(--text)' }}
                    >
                      {test.code}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11.5px] font-semibold">{lang === 'ar' ? test.nameAr : test.nameEn}</span>
                      <span className="mt-0.5 block text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        {filled}/{test.fields.filter((f) => f.required).length} {t('حقول مكتملة', 'required fields')}
                      </span>
                    </span>
                    {res ? <StatusChip status={res.status as Status} small /> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        {/* active test form */}
        <div className="space-y-3">
          <Card
            title={`${activeSpec.code} · ${lang === 'ar' ? activeSpec.nameAr : activeSpec.nameEn}`}
            subtitle={activeSpec.standard}
            actions={
              <button
                className="btn btn-ghost px-2 py-1 text-[11px]"
                onClick={() => setInputs((p) => ({ ...p, [activeSpec.code]: {} }))}
                title={t('تفريغ حقول الاختبار', 'Clear test fields')}
              >
                <RotateCcw size={12} /> {t('تفريغ', 'Clear')}
              </button>
            }
          >
            <details className="mb-3 rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)' }}>
              <summary className="cursor-pointer text-[11.5px] font-bold" style={{ color: 'var(--brand)' }}>
                {t('خطوات التنفيذ الموثقة', 'Documented procedure')}
              </summary>
              <ol className="mt-2 list-inside list-decimal space-y-1 text-[11.5px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                {activeSpec.procedureAr.map((p, i) => (
                  <li key={i}>{lang === 'ar' ? p : p}</li>
                ))}
              </ol>
            </details>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {activeSpec.fields.map((f) => (
                <div key={f.key}>
                  <Field label={`${lang === 'ar' ? f.labelAr : f.labelEn}${f.unit ? ` (${f.unit})` : ''}`} hint={f.hintAr && lang === 'ar' ? f.hintAr : undefined}>
                    {f.type === 'select' ? (
                      <select
                        className="select"
                        data-field={`${activeSpec.code}.${f.key}`}
                        value={String(inputs[activeSpec.code]?.[f.key] ?? '')}
                        onChange={(e) => setField(activeSpec.code, f.key, e.target.value)}
                      >
                        <option value="">{t('— اختر —', '— select —')}</option>
                        {f.options!.map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </select>
                    ) : f.type === 'series' || f.type === 'spectrum' ? (
                      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                        {Array.from({ length: f.length ?? 3 }).map((_, idx) => (
                          <input
                            key={idx}
                            className="input mono"
                            data-field={`${activeSpec.code}.${f.key}.${idx}`}
                            inputMode="decimal"
                            placeholder={f.hintAr?.split('،')[idx]?.trim() ?? `#${idx + 1}`}
                            value={seriesValue(activeSpec.code, f.key, idx)}
                            onChange={(e) => setSeries(activeSpec.code, f.key, idx, e.target.value, f.length ?? 3)}
                            aria-label={`${f.labelEn} ${idx + 1}`}
                          />
                        ))}
                      </div>
                    ) : (
                      <input
                        className="input mono"
                        data-field={`${activeSpec.code}.${f.key}`}
                        inputMode={f.type === 'number' || f.type === 'integer' ? 'decimal' : 'text'}
                        step={f.step}
                        value={String(inputs[activeSpec.code]?.[f.key] ?? '')}
                        onChange={(e) => setField(activeSpec.code, f.key, e.target.value)}
                      />
                    )}
                  </Field>
                </div>
              ))}
            </div>
          </Card>

          {result?.perTest[activeSpec.code] && (
            <>
              <Card
                title={t('نتيجة الاختبار ومقارنة حدود القبول', 'Test result & acceptance comparison')}
                actions={<StatusChip status={result.perTest[activeSpec.code].status} />}
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
                        <th>{t('ملاحظة', 'Note')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.perTest[activeSpec.code].metricEvaluations.map((m) => {
                        const formula = activeSpec.formulas.find((f) => f.key === m.metricKey);
                        return (
                          <tr key={m.metricKey}>
                            <td className="font-mono text-[11px]">{m.metricKey}</td>
                            <td className="font-mono text-[11.5px] font-bold tabular-nums">
                              {m.value === null ? '—' : roundForDisplay(m.value, formula?.decimals ?? 3)}
                              <span className="ms-1 text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>
                                {m.unit}
                              </span>
                            </td>
                            <td className="font-mono text-[11px]">{m.limitText}</td>
                            <td className="text-[11px]">{m.appliedSource ? SOURCE_LABELS[m.appliedSource][lang] : '—'}</td>
                            <td>
                              <StatusChip status={m.status} small />
                            </td>
                            <td className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                              {m.message ?? '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>

              {activeSpec.chart !== 'none' && (
                <Card title={t('المخطط العلمي', 'Scientific chart')} subtitle={t('مستخرج من القيم الخام مباشرة', 'Derived directly from raw values')}>
                  <TestChart test={activeSpec} result={result.perTest[activeSpec.code]} />
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      {/* run bar */}
      <div className="card sticky bottom-3 z-20 flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0 text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
          {result ? (
            <span className="flex items-center gap-2">
              <StatusChip status={result.overall} />
              {t('الحالة الكلية للتشغيل', 'Overall run status')} · {result.results.filter((r) => r.status === 'PASS').length}/{result.results.length}{' '}
              {t('اختبار مطابق', 'tests passing')}
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <Info size={13} />
              {missing.length
                ? t(`${missing.length} حقلاً إلزامياً ناقصاً`, `${missing.length} mandatory fields missing`)
                : t('جميع الحقول الإلزامية مكتملة — جاهز للتشغيل', 'All mandatory fields complete — ready to run')}
            </span>
          )}
        </div>
        <Toolbar>
          {savedRun && (
            <span className="chip" style={{ background: 'rgba(22,121,79,.12)', color: 'var(--pass)' }}>
              <BadgeCheck size={12} /> {savedRun.executionCode}
            </span>
          )}
          <button
            className="btn btn-ghost"
            onClick={() => downloadReportFile('data.xlsx')}
            disabled={!serverRun || !canExport}
            title={t('تصدير بيانات التشغيل من الخادم إلى Excel', 'Export the stored run data to Excel')}
          >
            <Download size={14} /> {t('Excel', 'Excel')}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => downloadReportFile('certificate.pdf')}
            disabled={!serverRun?.is_locked || !canExport}
            title={t('الشهادة تُصدر فقط بعد الاعتماد النهائي', 'The certificate is issued only after QA approval')}
          >
            <Download size={14} /> {t('شهادة PDF', 'Certificate PDF')}
          </button>
          {serverRun &&
            (serverRun.overall_status === 'FAIL' || serverRun.overall_status === 'INCOMPLETE') && (
            <button
              className="btn btn-ghost"
              style={{ color: 'var(--fail)' }}
              onClick={() => setDeviationOpen(true)}
              title={t(
                'التشغيل غير المطابق لا يُعتمد — يفتح له انحراف OOS ويُغلق بإعادة اختبار ناجحة',
                'A failing run is never approved — it gets an OOS deviation, closed with a passing retest',
              )}
            >
              <AlertTriangle size={14} /> {t('فتح انحراف OOS', 'Raise OOS deviation')}
            </button>
          )}
          <button className="btn btn-primary" onClick={handleRun} disabled={running || !instrument}>
            <Play size={14} /> {running ? t('جارٍ الحساب…', 'Computing…') : t('Run Calibration', 'Run Calibration')}
          </button>
        </Toolbar>
      </div>

      {errors.length > 0 && (
        <Card title={t('تعذر إكمال العملية', 'Action could not be completed')}>
          <ul className="space-y-1 text-[12px]" style={{ color: 'var(--fail)' }}>
            {errors.map((e, i) => (
              <li key={i} className="flex items-start gap-2">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {e}
              </li>
            ))}
          </ul>
          {missing.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[11.5px] font-bold" style={{ color: 'var(--brand)' }}>
                {t('عرض الحقول الناقصة', 'Show missing fields')}
              </summary>
              <ul className="mt-1 grid gap-1 text-[11px] sm:grid-cols-2" style={{ color: 'var(--text-muted)' }}>
                {missing.slice(0, 40).map((m, i) => (
                  <li key={i}>• {m}</li>
                ))}
              </ul>
            </details>
          )}
        </Card>
      )}

      <Modal
        open={deviationOpen}
        title={t('فتح انحراف خارج المواصفة (OOS)', 'Raise an out-of-specification deviation')}
        onClose={() => setDeviationOpen(false)}
        width={640}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setDeviationOpen(false)} disabled={devBusy}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button
              className="btn btn-primary"
              disabled={devBusy || devTitle.trim().length < 8 || devDescription.trim().length < 20}
              onClick={() => void raiseDeviation()}
            >
              {devBusy ? t('جارٍ الفتح…', 'Raising…') : t('فتح الانحراف', 'Raise deviation')}
            </button>
          </>
        }
      >
        <p className="mb-3 text-[11.5px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {t(
            'الانحراف يوثّق الفشل ولا يغيّر نتيجته. يبقى التشغيل غير المطابق غير معتمد، ويُغلق الانحراف بإعادة اختبار ناجحة هي التي تحمل الشهادة.',
            'A deviation documents the failure without altering it. The failing run stays unapproved; the deviation closes against a passing retest, and the retest carries the certificate.',
          )}
        </p>
        <Field label={t('عنوان الانحراف', 'Deviation title')}>
          <input className="input" value={devTitle} onChange={(event) => setDevTitle(event.target.value)} />
        </Field>
        <div className="mt-2">
          <Field label={t('الوصف والملاحظة الأولية', 'Description and initial observation')}>
            <textarea className="textarea" rows={4} value={devDescription} onChange={(event) => setDevDescription(event.target.value)} />
          </Field>
        </div>
        <div className="mt-2">
          <Field
            label={t('التصنيف', 'Classification')}
            hint={t(
              'الانحراف الحرج يتطلب أن يغلقه شخص آخر غير المحقّق عند توفّر مسؤول جودة ثانٍ.',
              'A critical deviation must be closed by someone other than the investigator when a second QA officer exists.',
            )}
          >
            <select className="input" value={devClass} onChange={(event) => setDevClass(event.target.value)}>
              <option value="CRITICAL">{t('حرج', 'Critical')}</option>
              <option value="MAJOR">{t('جسيم', 'Major')}</option>
              <option value="MINOR">{t('بسيط', 'Minor')}</option>
            </select>
          </Field>
        </div>
      </Modal>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t('تأكيد حفظ تشغيل المعايرة', 'Confirm calibration run')}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setConfirmOpen(false)}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button className="btn btn-primary" onClick={persistRun} disabled={!canRun || saving}>
              <Save size={14} /> {t('حفظ وإرسال للمراجعة الفنية', 'Save & submit for review')}
            </button>
          </>
        }
      >
        {result && (
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)' }}>
              <span className="text-[12px] font-bold">{t('الحالة الكلية', 'Overall status')}</span>
              <StatusChip status={result.overall} />
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric label={t('مطابق', 'Pass')} value={result.results.filter((r) => r.status === 'PASS').length} tone="pass" />
              <Metric label={t('غير مطابق', 'Fail')} value={result.results.filter((r) => r.status === 'FAIL').length} tone="fail" />
              <Metric label={t('قيد المراجعة', 'Review')} value={result.results.filter((r) => r.status === 'UNDER_REVIEW').length} tone="warn" />
              <Metric label={t('غير مكتمل', 'Incomplete')} value={result.results.filter((r) => r.status === 'INCOMPLETE').length} />
            </div>
            <p className="text-[11.5px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              {t(
                'سيُحفظ التشغيل مع بصمة SHA-256 لكل النتائج، ويُرسل إلى المراجعة الفنية ثم اعتماد ضمان الجودة. لا يمكن تعديل النتائج بعد الاعتماد النهائي (is_locked).',
                'The run is stored with a SHA-256 fingerprint and routed to technical review then QA approval. Results are immutable once approved (is_locked).',
              )}
            </p>
            <div className="flex items-start gap-2 rounded-lg px-3 py-2 text-[11px]" style={{ background: 'rgba(29,78,216,.08)', color: 'var(--review)' }}>
              <ClipboardList size={13} className="mt-0.5 shrink-0" />
              {t(
                'فصل المهام: لا يجوز أن يكون المحلل هو المراجع الفني أو معتمد ضمان الجودة لنفس التشغيل.',
                'Segregation of duties: the analyst cannot also be the reviewer or QA approver of the same run.',
              )}
            </div>
          </div>
        )}
      </Modal>

      {!instrument && (
        <EmptyState
          title={t('ابدأ باختيار الجهاز', 'Start by selecting an instrument')}
          detail={t('اختر الجهاز المستهدف ثم أكمل قراءات الاختبارات الـ 13 ثم اضغط Run Calibration.', 'Pick the target instrument, complete the 13 tests, then press Run Calibration.')}
        />
      )}
    </div>
  );
}
