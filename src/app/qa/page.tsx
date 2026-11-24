'use client';

import { useEffect, useMemo, useState } from 'react';
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
import { appendAudit, db } from '@/core/db/database';
import { fingerprint } from '@/core/engine/runEngine';
import { LIMITS, TESTS } from '@/core/protocol';
import {
  LIMIT_SOURCES,
  ROLE_PERMISSIONS,
  SOURCE_LABELS,
  type AcceptanceLimit,
  type RunRecord,
  type Status,
} from '@/core/types';

type Tab = 'queue' | 'limits' | 'conflicts';

export default function QaPage() {
  const { t, lang, ready, user, notify } = useApp();
  const [tab, setTab] = useState<Tab>('queue');
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, AcceptanceLimit['approvalStatus']>>({});
  const [signOpen, setSignOpen] = useState(false);
  const [signAction, setSignAction] = useState<'review' | 'approve' | 'limit'>('review');
  const [busy, setBusy] = useState(false);
  const [activeTest, setActiveTest] = useState<string>('');

  const canReview = user ? ROLE_PERMISSIONS[user.role].includes('calibration.review') : false;
  const canApprove = user ? ROLE_PERMISSIONS[user.role].includes('calibration.approve') : false;
  const canApproveLimits = user ? ROLE_PERMISSIONS[user.role].includes('limits.approve') : false;

  useEffect(() => {
    if (!ready) return;
    void (async () => {
      setRuns(await db().runs.toArray());
      setLoading(false);
    })();
  }, [ready, signOpen]);

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

  const pending = runs.filter((r) => !r.qaApprover && r.overallStatus !== 'INCOMPLETE');
  const approved = runs.filter((r) => r.qaApprover);

  const performSigned = async (reason: string, password: string) => {
    if (!user) return;
    setBusy(true);
    try {
      if (signAction === 'limit') {
        // limit approvals are recorded as governance decisions in the audit trail
        await appendAudit({
          actor: user.username,
          role: user.role,
          action: 'ACCEPTANCE_LIMIT_APPROVED',
          entity: 'acceptance_limit',
          entityId: 'batch',
          module: 'qa',
          after: { approved: Object.keys(overrides).length, decisions: overrides },
          reason,
        });
        notify('success', t('تم اعتماد الحدود المحددة', 'Limits approved'), t('سُجل القرار في سجل التدقيق غير القابل للتعديل.', 'Decision recorded in the immutable audit trail.'));
      } else if (run) {
        // segregation of duties — enforced here as well as on the server
        if (run.analyst === user.username) {
          notify('error', t('فصل المهام', 'Segregation of duties'), t('لا يمكنك مراجعة أو اعتماد تشغيل نفّذته بنفسك.', 'You cannot review/approve a run you executed.'));
          setSignOpen(false);
          setBusy(false);
          return;
        }
        if (signAction === 'review' && !run.reviewer) {
          const updated: RunRecord = { ...run, reviewer: user.username, revision: run.revision + 1 };
          await db().runs.put(updated);
          await appendAudit({
            actor: user.username,
            role: user.role,
            action: 'RUN_TECHNICAL_REVIEW_SIGNED',
            entity: 'calibration_run',
            entityId: run.id,
            module: 'qa',
            before: { reviewer: run.reviewer },
            after: { reviewer: user.username },
            reason,
          });
          notify('success', t('تم التوقيع الفني', 'Technical review signed'), run.executionCode);
        } else if (signAction === 'approve') {
          if (!run.reviewer) {
            notify('error', t('المراجعة الفنية مطلوبة أولاً', 'Technical review required first'), t('لا يمكن اعتماد QA قبل التوقيع الفني.', 'QA approval requires the technical review signature first.'));
            setSignOpen(false);
            setBusy(false);
            return;
          }
          if (run.reviewer === user.username) {
            notify('error', t('فصل المهام', 'Segregation of duties'), t('لا يمكن اعتماد QA لنفس المراجعة الفنية.', 'QA approval must differ from the technical reviewer.'));
            setSignOpen(false);
            setBusy(false);
            return;
          }
          const approvedAt = new Date().toISOString();
          const updated: RunRecord = {
            ...run,
            qaApprover: user.username,
            qaApprovedAt: approvedAt,
            completedAt: run.completedAt ?? approvedAt,
            isLocked: true,
            revision: run.revision + 1,
          } as RunRecord & { qaApprovedAt: string };
          updated.certificateHash = await fingerprint({
            executionCode: run.executionCode,
            results: run.results,
            reviewer: run.reviewer,
            qaApprover: user.username,
            approvedAt,
          });
          await db().runs.put(updated);
          await appendAudit({
            actor: user.username,
            role: user.role,
            action: 'RUN_QA_APPROVED_AND_LOCKED',
            entity: 'calibration_run',
            entityId: run.id,
            module: 'qa',
            before: { isLocked: false, qaApprover: null },
            after: { isLocked: true, qaApprover: user.username, certificateHash: updated.certificateHash },
            reason,
          });
          notify('success', t('تم الاعتماد النهائي وإقفال النتائج', 'Final approval & lock'), run.executionCode);
        }
      }
      setSignOpen(false);
      setRuns(await db().runs.toArray());
    } catch (err) {
      notify('error', t('فشل الإجراء', 'Action failed'), (err as Error).message);
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
                  actions={<StatusChip status={run.overallStatus} />}
                >
                  <div className="grid gap-2 text-[11.5px] sm:grid-cols-2 lg:grid-cols-4">
                    {[
                      [t('رمز التشغيل', 'Execution'), run.executionCode],
                      [t('الجهاز', 'Instrument'), run.instrumentName],
                      [t('نوع التشغيل', 'Type'), run.runType],
                      [t('المحلل', 'Analyst'), run.analyst],
                      [t('الحرارة/الرطوبة', 'T/RH'), `${run.ambientTempC}°C / ${run.ambientHumidity}%`],
                      [t('البدء', 'Started'), new Date(run.startedAt).toLocaleString(lang === 'ar' ? 'ar-YE' : 'en-GB')],
                      [t('بصمة الشهادة', 'Certificate hash'), (run.certificateHash ?? '—').slice(0, 16) + '…'],
                      [t('الإصدار', 'Revision'), String(run.revision)],
                    ].map(([k, v]) => (
                      <div key={k} className="rounded-lg px-2.5 py-1.5" style={{ background: 'var(--surface-2)' }}>
                        <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          {k}
                        </p>
                        <p className="truncate font-mono text-[11px] font-semibold" title={String(v)}>
                          {v}
                        </p>
                      </div>
                    ))}
                  </div>

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
