'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  FileSignature,
  GitCompareArrows,
  Lock,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Metric, SignatureDialog, Skeleton, StatusChip, Toolbar } from '@/components/ui';
import { TestChart } from '@/components/TestCharts';
import { db } from '@/core/db/database';
import { LIMITS, TESTS } from '@/core/protocol';
import {
  ApiError,
  api,
  downloadReport,
  toRunRecord,
  toRunTestResults,
  type ServerRun,
  type ServerRunSummary,
} from '@/core/api/client';
import {
  LIMIT_SOURCES,
  SOURCE_LABELS,
  type AcceptanceLimit,
  type RunRecord,
  type Status,
} from '@/core/types';

type Tab = 'queue' | 'limits' | 'conflicts';

export default function QaPage() {
  const { t, lang, ready, user, session, notify, can } = useApp();
  const [tab, setTab] = useState<Tab>('queue');
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, AcceptanceLimit['approvalStatus']>>({});
  const [signOpen, setSignOpen] = useState(false);
  const [signAction, setSignAction] = useState<'review' | 'approve' | 'limit'>('review');
  const [busy, setBusy] = useState(false);
  const [activeTest, setActiveTest] = useState<string>('');
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState<string | null>(null);

  const canReview = can('calibration.review');
  const canApprove = can('calibration.approve');
  const canApproveLimits = can('limits.approve');
  const canExport = can('reports.export');

  /**
   * Loads from the server, falling back to the cached snapshot only when the API
   * is unreachable. Identity names are resolved from the returned run rows so the
   * queue reflects what is actually stored.
   */
  const loadRuns = useCallback(async () => {
    try {
      const [summaries, pending] = await Promise.all([api.runs({ page_size: 100 }), canApprove ? api.pendingApprovals() : Promise.resolve([])]);
      const detailed = await Promise.all(summaries.map((row) => api.run(row.id)));
      const mapped: RunRecord[] = detailed.map((run: ServerRun) =>
        toRunRecord(run, {
          instrumentName: run.instrument_id,
          analyst: run.analyst_id,
          reviewer: run.reviewer_id,
          qaApprover: run.qa_approver_id,
        }),
      );
      setRuns(mapped);
      setPendingIds(new Set(pending.map((p: ServerRunSummary) => p.id)));
      setLoadError(null);
    } catch (error) {
      if (error instanceof ApiError) {
        setLoadError(error.text(lang));
      } else {
        const cached = await db().runs.toArray();
        setRuns(cached);
        setLoadError(
          cached.length
            ? t('الخادم غير متاح — تُعرض نسخة مخزّنة للقراءة فقط.', 'Server unreachable — showing a read-only cached copy.')
            : t('تعذر تحميل التشغيلات.', 'Runs could not be loaded.'),
        );
      }
    } finally {
      setLoading(false);
    }
  }, [canApprove, lang, t]);

  useEffect(() => {
    if (!ready) return;
    void loadRuns();
  }, [ready, loadRuns]);

  const run = runs.find((r) => r.id === selected) ?? null;

  const conflicts = useMemo(
    () => LIMITS.filter((l) => l.approvalStatus === 'CONFLICT_REQUIRES_QA' || l.flagged),
    [],
  );

  const limitMatrix = useMemo(() => {
    const rows: { testCode: string; metricKey: string; bySource: Partial<Record<string, AcceptanceLimit>> }[] = [];
    for (const test of TESTS) {
      for (const metric of test.metrics) {
        const bySource: Partial<Record<string, AcceptanceLimit>> = {};
        for (const s of LIMIT_SOURCES) {
          const l = LIMITS.find((x) => x.testCode === test.code && x.metricKey === metric && x.sourceType === s);
          if (l) bySource[s] = l;
        }
        if (Object.keys(bySource).length) rows.push({ testCode: test.code, metricKey: metric, bySource });
      }
    }
    return rows;
  }, []);

  // pendingIds comes from GET /runs/pending/approvals — the server's own view of
  // what still needs a QA decision (approved rows leave the list)
  const pending = runs.filter((r) => pendingIds.has(r.id) || (!r.qaApprover && r.overallStatus !== 'INCOMPLETE'));
  const approved = runs.filter((r) => r.isLocked);

  /**
   * Signatures are verified server-side: the run service re-checks the password
   * with Argon2id, enforces segregation of duties and writes the audit entry. The
   * client cannot bypass any of it, and shows the server's rejection verbatim.
   */
  const performSigned = async (reason: string, password: string) => {
    if (!user) return;
    setBusy(true);
    try {
      if (signAction === 'limit') {
        const ids = Object.keys(overrides);
        if (!ids.length) {
          notify('info', t('لا توجد حدود محددة للاعتماد', 'No limits selected'), '');
          setSignOpen(false);
          return;
        }
        const results = await Promise.allSettled(
          ids.map((id) => api.approveLimit(id, password, reason)),
        );
        const ok = results.filter((r) => r.status === 'fulfilled').length;
        const failed = results.filter((r) => r.status === 'rejected') as PromiseRejectedResult[];
        if (ok) {
          notify(
            'success',
            t(`تم اعتماد ${ok} حد قبول`, `${ok} limit(s) approved`),
            t('كل اعتماد موقّع ومُسجل في سجل التدقيق.', 'Each approval is signed and audited.'),
          );
          setOverrides({});
        }
        if (failed.length) {
          const first = failed[0].reason;
          notify(
            'error',
            t(`${failed.length} حداً لم يُعتمد`, `${failed.length} approval(s) rejected`),
            first instanceof ApiError ? first.text(lang) : String(first),
          );
        }
      } else if (run) {
        if (signAction === 'review') {
          const reviewed = await api.reviewRun(run.id, password, reason);
          notify('success', t('تم التوقيع الفني', 'Technical review signed'), reviewed.execution_code);
        } else {
          const approved = await api.approveRun(run.id, password, reason);
          notify(
            'success',
            t('تم الاعتماد النهائي وإقفال النتائج', 'Final approval & lock'),
            `${approved.execution_code} · ${approved.certificate_hash?.slice(0, 16)}…`,
          );
        }
      }
      setSignOpen(false);
      await loadRuns();
    } catch (error) {
      const message =
        error instanceof ApiError
          ? `${error.code} — ${error.text(lang)}`
          : error instanceof Error
            ? error.message
            : String(error);
      notify('error', t('فشل الإجراء', 'Action failed'), message);
      setSignOpen(false);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Skeleton rows={8} />;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('تشغيلات بانتظار الاعتماد', 'Runs awaiting approval')} value={pending.length} tone={pending.length ? 'warn' : 'neutral'} />
        <Metric label={t('تشغيلات معتمدة ومقفلة', 'Approved & locked')} value={approved.length} tone="pass" />
        <Metric label={t('حدود متعارضة تحتاج حسم', 'Conflicted limits')} value={conflicts.length} tone={conflicts.length ? 'fail' : 'neutral'} />
        <Metric label={t('حدود القبول المسجلة', 'Registered limits')} value={LIMITS.length} hint={t('من 5 مصادر مستقلة', 'From 5 independent sources')} />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(
          [
            { k: 'queue', ar: 'قائمة المراجعة والاعتماد', en: 'Review & approval queue', icon: ShieldCheck },
            { k: 'limits', ar: 'مصفوفة حدود القبول', en: 'Acceptance limit matrix', icon: GitCompareArrows },
            { k: 'conflicts', ar: 'التعارضات وقرارات QA', en: 'Conflicts & QA decisions', icon: ShieldAlert },
          ] as { k: Tab; ar: string; en: string; icon: typeof ShieldCheck }[]
        ).map(({ k, ar, en, icon: Icon }) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className="btn"
            style={{
              background: tab === k ? 'var(--brand)' : 'var(--surface)',
              color: tab === k ? '#fff' : 'var(--text)',
              borderColor: 'var(--border)',
            }}
          >
            <Icon size={14} /> {t(ar, en)}
          </button>
        ))}
      </div>

      {tab === 'queue' && (
        <div className="grid gap-3 xl:grid-cols-[360px_1fr]">
          <Card title={t('قائمة التشغيلات', 'Runs')} subtitle={t('مرتبة من الأحدث', 'Newest first')} dense>
            {runs.length === 0 ? (
              <EmptyState title={t('لا توجد تشغيلات', 'No runs')} detail={t('نفّذ معايرة من لوحة المختبر أولاً.', 'Execute a run from the laboratory panel first.')} />
            ) : (
              <ul className="max-h-[560px] overflow-y-auto">
                {runs
                  .slice()
                  .sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())
                  .map((r) => (
                    <li key={r.id}>
                      <button
                        onClick={() => {
                          setSelected(r.id);
                          setActiveTest(r.results[0]?.testCode ?? '');
                        }}
                        className="w-full border-b px-3 py-2 text-start"
                        style={{
                          borderColor: 'var(--border)',
                          background: selected === r.id ? 'var(--brand-soft)' : 'transparent',
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-mono text-[11px] font-bold">{r.executionCode}</span>
                          <StatusChip status={r.overallStatus} small />
                        </div>
                        <p className="mt-0.5 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                          {r.instrumentName} · {r.runType}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-1 text-[9.5px]">
                          <span className="chip" style={{ background: 'var(--surface-3)' }}>
                            {t('محلل', 'Analyst')}: {r.analyst}
                          </span>
                          {r.reviewer && (
                            <span className="chip" style={{ background: 'rgba(29,78,216,.10)', color: 'var(--review)' }}>
                              {t('مراجع', 'Reviewer')}: {r.reviewer}
                            </span>
                          )}
                          {r.qaApprover && (
                            <span className="chip" style={{ background: 'rgba(22,121,79,.12)', color: 'var(--pass)' }}>
                              QA: {r.qaApprover}
                            </span>
                          )}
                          {r.isLocked && (
                            <span className="chip" style={{ background: 'var(--surface-3)' }}>
                              <Lock size={9} /> {t('مقفل', 'locked')}
                            </span>
                          )}
                        </div>
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </Card>

          <div className="space-y-3">
            {!run ? (
              <Card>
                <EmptyState title={t('اختر تشغيلاً للمراجعة', 'Select a run to review')} detail={t('ستظهر جميع نتائج الاختبارات الـ 13 ومقارنة الحدود وسلسلة التوقيعات.', 'All 13 test results, limit comparison and the signature chain appear here.')} />
              </Card>
            ) : (
              <>
                <Card
                  title={t('ملخص التشغيل', 'Run summary')}
                  actions={
                    <div className="flex items-center gap-1.5">
                      <StatusChip status={run.overallStatus} />
                      <button
                        className="btn btn-ghost px-2 py-1 text-[10.5px]"
                        disabled={!canExport}
                        onClick={() =>
                          downloadReport(`/reports/runs/${run.id}/data.xlsx`, `${run.executionCode}-data.xlsx`).catch(
                            (e: unknown) =>
                              notify(
                                'error',
                                t('تعذر التصدير', 'Export failed'),
                                e instanceof ApiError ? e.text(lang) : String(e),
                              ),
                          )
                        }
                      >
                        <FileSignature size={12} /> XLSX
                      </button>
                      <button
                        className="btn btn-ghost px-2 py-1 text-[10.5px]"
                        disabled={!run.isLocked || !canExport}
                        title={t('تُصدر الشهادة فقط لتشغيل معتمد ومقفل', 'Issued only for an approved and locked run')}
                        onClick={() =>
                          downloadReport(
                            `/reports/runs/${run.id}/certificate.pdf`,
                            `${run.executionCode}-certificate.pdf`,
                          ).catch((e: unknown) =>
                            notify(
                              'error',
                              t('تعذر إصدار الشهادة', 'Certificate failed'),
                              e instanceof ApiError ? e.text(lang) : String(e),
                            ),
                          )
                        }
                      >
                        <FileSignature size={12} /> PDF
                      </button>
                    </div>
                  }
                >
                  <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-[11.5px] sm:grid-cols-2">
                    {[
                      [t('رمز التشغيل', 'Execution'), run.executionCode],
                      [t('الجهاز', 'Instrument'), run.instrumentName],
                      [t('نوع التشغيل', 'Type'), run.runType],
                      [t('المحلل', 'Analyst'), run.analyst],
                      [t('الحرارة/الرطوبة', 'T/RH'), `${run.ambientTempC}°C / ${run.ambientHumidity}%`],
                      [t('البدء', 'Started'), new Date(run.startedAt).toLocaleString(lang === 'ar' ? 'ar-YE' : 'en-GB')],
                      [t('بصمة الشهادة', 'Certificate hash'), run.certificateHash ?? '—'],
                      [t('الإصدار', 'Revision'), String(run.revision)],
                    ].map(([k, v]) => (
                      <div
                        key={k}
                        className="flex min-w-0 flex-col gap-0.5 rounded-lg px-2.5 py-1.5"
                        style={{ background: 'var(--surface-2)' }}
                      >
                        <dt className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          {k}
                        </dt>
                        <dd
                          className="break-all font-mono text-[11px] font-semibold"
                          style={{ direction: 'ltr', textAlign: 'start' }}
                          title={String(v)}
                        >
                          {String(v)}
                        </dd>
                      </div>
                    ))}
                  </dl>

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {run.results.map((r) => (
                      <button
                        key={r.testCode}
                        onClick={() => setActiveTest(r.testCode)}
                        className="chip"
                        style={{
                          background: activeTest === r.testCode ? 'var(--brand)' : 'var(--surface-3)',
                          color: activeTest === r.testCode ? '#fff' : 'var(--text)',
                          cursor: 'pointer',
                        }}
                        title={TESTS.find((x) => x.code === r.testCode)?.nameAr}
                      >
                        {r.testCode} · {r.status}
                      </button>
                    ))}
                  </div>

                  <Toolbar>
                    <div className="mt-auto flex flex-wrap gap-2 pt-3">
                      <button
                        className="btn btn-ghost"
                        disabled={!canReview || !!run.reviewer}
                        onClick={() => {
                          setSignAction('review');
                          setSignOpen(true);
                        }}
                      >
                        <FileSignature size={14} /> {run.reviewer ? t('تم التوقيع الفني', 'Review signed') : t('توقيع المراجعة الفنية', 'Sign technical review')}
                      </button>
                      <button
                        className="btn btn-primary"
                        disabled={!canApprove || !!run.qaApprover}
                        onClick={() => {
                          setSignAction('approve');
                          setSignOpen(true);
                        }}
                      >
                        <CheckCircle2 size={14} />
                        {run.qaApprover ? t('معتمد ومقفل', 'Approved & locked') : t('اعتماد ضمان الجودة النهائي', 'Final QA approval')}
                      </button>
                      {!canReview && !canApprove && (
                        <span className="flex items-center gap-1 text-[11px]" style={{ color: 'var(--warn)' }}>
                          <ShieldAlert size={12} /> {t('دورك الحالي لا يملك صلاحية المراجعة أو الاعتماد.', 'Your role lacks review/approval permission.')}
                        </span>
                      )}
                    </div>
                  </Toolbar>
                </Card>

                {activeTest && (
                  <>
                    <Card
                      title={`${activeTest} · ${lang === 'ar' ? TESTS.find((x) => x.code === activeTest)?.nameAr : TESTS.find((x) => x.code === activeTest)?.nameEn}`}
                      actions={<StatusChip status={run.results.find((r) => r.testCode === activeTest)?.status ?? 'INCOMPLETE'} />}
                      dense
                    >
                      <div className="overflow-x-auto">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>{t('المقياس', 'Metric')}</th>
                              <th>{t('القيمة', 'Value')}</th>
                              <th>{t('الحد', 'Limit')}</th>
                              <th>{t('المصدر', 'Source')}</th>
                              <th>{t('الحكم', 'Verdict')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {run.results
                              .find((r) => r.testCode === activeTest)
                              ?.metricEvaluations.map((m) => (
                                <tr key={m.metricKey}>
                                  <td className="font-mono text-[11px]">{m.metricKey}</td>
                                  <td className="font-mono text-[11.5px] font-bold tabular-nums">
                                    {m.value === null ? '—' : m.value.toPrecision(6)}
                                  </td>
                                  <td className="font-mono text-[11px]">{m.limitText}</td>
                                  <td className="text-[11px]">{m.appliedSource ? SOURCE_LABELS[m.appliedSource][lang] : '—'}</td>
                                  <td>
                                    <StatusChip status={m.status as Status} small />
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>
                    <Card title={t('المخطط العلمي', 'Scientific chart')}>
                      <TestChart
                        test={TESTS.find((x) => x.code === activeTest)!}
                        result={run.results.find((r) => r.testCode === activeTest)}
                      />
                    </Card>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {tab === 'limits' && (
        <Card
          title={t('مصفوفة حدود القبول متعددة المصادر', 'Multi-source acceptance limit matrix')}
          subtitle={t('كل حد معروض بمصدره وحالة اعتماده — لا يمكن استخدام حد غير معتمد لحكم PASS', 'Each limit shows its source and approval state — unapproved limits can never produce PASS')}
          dense
        >
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('الاختبار', 'Test')}</th>
                  <th>{t('المقياس', 'Metric')}</th>
                  {LIMIT_SOURCES.map((s) => (
                    <th key={s} title={SOURCE_LABELS[s][lang]}>
                      {SOURCE_LABELS[s].short}
                    </th>
                  ))}
                  <th>{t('قرار QA', 'QA decision')}</th>
                </tr>
              </thead>
              <tbody>
                {limitMatrix.map((row) => (
                  <tr key={`${row.testCode}-${row.metricKey}`}>
                    <td className="font-mono text-[11px] font-bold">{row.testCode}</td>
                    <td className="font-mono text-[10.5px]">{row.metricKey}</td>
                    {LIMIT_SOURCES.map((s) => {
                      const l = row.bySource[s];
                      if (!l) return <td key={s} className="text-[11px]" style={{ color: 'var(--text-muted)' }}>—</td>;
                      const bad = l.approvalStatus !== 'APPROVED';
                      return (
                        <td key={s}>
                          <span className="font-mono text-[10.5px]" style={{ color: bad ? 'var(--warn)' : 'var(--text)' }}>
                            {l.operator === 'gte' ? '≥ ' : '≤ '}
                            {l.operator === 'gte' ? l.minValue : l.maxValue} {l.unit}
                          </span>
                          <span className="ms-1">{bad && <ShieldAlert size={10} style={{ color: 'var(--warn)', display: 'inline' }} />}</span>
                        </td>
                      );
                    })}
                    <td>
                      <select
                        className="select py-1 text-[10.5px]"
                        value={overrides[`${row.testCode}-${row.metricKey}`] ?? (row.bySource.AUTHORITY_LIMIT?.approvalStatus ?? 'UNAPPROVED')}
                        disabled={!canApproveLimits}
                        onChange={(e) =>
                          setOverrides((p) => ({ ...p, [`${row.testCode}-${row.metricKey}`]: e.target.value as AcceptanceLimit['approvalStatus'] }))
                        }
                      >
                        <option value="APPROVED">{t('اعتماد', 'Approve')}</option>
                        <option value="UNAPPROVED">{t('غير معتمد', 'Unapproved')}</option>
                        <option value="CONFLICT_REQUIRES_QA">{t('تعارض', 'Conflict')}</option>
                        <option value="REJECTED">{t('رفض', 'Reject')}</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex justify-end">
            <button
              className="btn btn-primary"
              disabled={!canApproveLimits || Object.keys(overrides).length === 0}
              onClick={() => {
                setSignAction('limit');
                setSignOpen(true);
              }}
            >
              <FileSignature size={14} /> {t('توقيع قرارات الحدود', 'Sign limit decisions')}
            </button>
          </div>
        </Card>
      )}

      {tab === 'conflicts' && (
        <div className="grid gap-3 lg:grid-cols-2">
          {conflicts.map((l) => {
            const test = TESTS.find((x) => x.code === l.testCode);
            return (
              <Card
                key={l.id}
                title={`${l.testCode} · ${lang === 'ar' ? test?.nameAr : test?.nameEn}`}
                subtitle={`${l.metricKey} — ${SOURCE_LABELS[l.sourceType][lang]}`}
                actions={<StatusChip status={l.approvalStatus} small />}
              >
                <div className="space-y-2 text-[11.5px] leading-relaxed">
                  <div className="flex items-center justify-between rounded-lg px-2.5 py-1.5" style={{ background: 'var(--surface-2)' }}>
                    <span className="font-semibold">{t('الحد الوارد', 'Recorded limit')}</span>
                    <span className="font-mono">
                      {l.operator === 'gte' ? '≥ ' : l.operator === 'lte' ? '≤ ' : ''}
                      {l.operator === 'gte' ? l.minValue : l.maxValue} {l.unit}
                    </span>
                  </div>
                  <p style={{ color: 'var(--text-muted)' }}>{l.note}</p>
                  <div className="flex items-start gap-1.5 rounded-lg px-2.5 py-1.5" style={{ background: 'rgba(181,71,8,.08)', color: 'var(--warn)' }}>
                    <XCircle size={12} className="mt-0.5 shrink-0" />
                    {t(
                      'هذا الحد لا يُستخدم لإصدار حكم PASS حتى يُحسم بقرار موقّع من ضمان الجودة.',
                      'This limit cannot produce a PASS verdict until resolved by a signed QA decision.',
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <SignatureDialog
        open={signOpen}
        busy={busy}
        title={
          signAction === 'limit'
            ? t('توقيع قرار حدود القبول', 'Sign acceptance-limit decision')
            : signAction === 'review'
              ? t('توقيع المراجعة الفنية', 'Sign technical review')
              : t('اعتماد ضمان الجودة النهائي', 'Final QA approval')
        }
        description={t(
          'التوقيع الإلكتروني وفق 21 CFR Part 11 يتطلب تأكيد كلمة المرور وسبباً موثقاً، ويُسجَّل بختم زمني وبصمة في سجل تدقيق غير قابل للتعديل.',
          'An electronic signature under 21 CFR Part 11 requires password confirmation and a documented reason, recorded with a timestamp and hash in the immutable audit trail.',
        )}
        onClose={() => setSignOpen(false)}
        onConfirm={performSigned}
      />
    </div>
  );
}
