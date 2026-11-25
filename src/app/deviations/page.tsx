'use client';

/**
 * OOS deviations register.
 *
 * A failing calibration used to end in a refusal with nowhere to go: the approval
 * screen said "raise an OOS deviation" and no such record existed. This page is
 * that record — but it is deliberately *not* an approval screen. Nothing here
 * changes a run's verdict. The run stays failed; the closure points at the retest
 * that superseded it, and the retest is what carries a certificate.
 *
 * The three phases are shown as three separate steps because they are three
 * separate permissions: the analyst who saw the failure raises it, QA
 * investigates, QA closes. The page shows each button to anyone who can reach the
 * page and lets the server refuse, because "why can't I do this" is an audit
 * question, not a UI question.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ClipboardList, FlaskConical, RotateCcw, ShieldCheck } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Field, Metric, Modal, Skeleton, StatusChip, Toolbar } from '@/components/ui';
import { ApiError, api, type ServerDeviation } from '@/core/api/client';

const CLASSIFICATIONS = [
  { code: 'CRITICAL', ar: 'حرج', en: 'Critical' },
  { code: 'MAJOR', ar: 'جسيم', en: 'Major' },
  { code: 'MINOR', ar: 'بسيط', en: 'Minor' },
] as const;

const ROOT_CAUSES = [
  { code: 'INSTRUMENT_FAULT', ar: 'عطل بالجهاز', en: 'Instrument fault' },
  { code: 'METHOD_ERROR', ar: 'خطأ في الطريقة', en: 'Method error' },
  { code: 'OPERATOR_ERROR', ar: 'خطأ من المنفّذ', en: 'Operator error' },
  { code: 'MATERIAL_FAILURE', ar: 'خلل في المواد/الأعمدة', en: 'Material failure' },
  { code: 'ENVIRONMENTAL', ar: 'ظروف بيئية', en: 'Environmental' },
  { code: 'REFERENCE_STANDARD', ar: 'معيار مرجعي غير صالح', en: 'Reference standard' },
] as const;

const CAPA_ACTIONS = [
  { code: 'INSTRUMENT_RESTORED', ar: 'إصلاح الجهاز وإعادته للخدمة', en: 'Instrument restored' },
  { code: 'METHOD_REVISED', ar: 'تنقيح الطريقة', en: 'Method revised' },
  { code: 'RETRAINING', ar: 'إعادة تدريب المنفّذ', en: 'Retraining' },
  { code: 'MATERIAL_REPLACED', ar: 'استبدال المواد', en: 'Materials replaced' },
  { code: 'NO_ACTION_REQUIRED', ar: 'لا يلزم إجراء تصحيحي', en: 'No action required' },
] as const;

const PHASES = ['OPEN', 'INVESTIGATING', 'PENDING_VERIFICATION', 'CLOSED'] as const;

const label = <T extends { code: string; ar: string; en: string }>(
  list: readonly T[],
  code: string | null,
  lang: string,
) => {
  const found = list.find((item) => item.code === code);
  return found ? (lang === 'ar' ? found.ar : found.en) : (code ?? '—');
};

export default function DeviationsPage() {
  const { t, lang, notify, can } = useApp();

  const [rows, setRows] = useState<ServerDeviation[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('');
  const [selected, setSelected] = useState<ServerDeviation | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.deviations(filter ? { status: filter } : {}));
    } catch (error) {
      notify(
        'error',
        t('تعذّر تحميل الانحرافات', 'Could not load deviations'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setLoading(false);
    }
  }, [filter, lang, notify, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(() => {
    const count = (status: string) => rows.filter((row) => row.status === status).length;
    return {
      total: rows.length,
      open: count('OPEN'),
      investigating: count('INVESTIGATING') + count('PENDING_VERIFICATION'),
      closed: count('CLOSED'),
    };
  }, [rows]);

  const run = async (fn: () => Promise<ServerDeviation>, done: [string, string]) => {
    setBusy(true);
    try {
      const updated = await fn();
      notify('success', t(done[0], done[1]), updated.reference);
      setSelected(updated);
      await load();
    } catch (error) {
      notify(
        'error',
        t('رُفض الإجراء', 'Action refused'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Toolbar>
        <div className="flex flex-wrap items-center gap-1.5">
          {[
            { code: '', ar: 'الكل', en: 'All' },
            ...PHASES.map((code) => ({
              code,
              ar: code === 'OPEN' ? 'مفتوحة' : code === 'INVESTIGATING' ? 'قيد التحقيق' : code === 'PENDING_VERIFICATION' ? 'بانتظار التحقق' : 'مغلقة',
              en: code === 'PENDING_VERIFICATION' ? 'Pending verification' : code.charAt(0) + code.slice(1).toLowerCase(),
            })),
          ].map((option) => (
            <button
              key={option.code || 'all'}
              className={`btn ${filter === option.code ? 'btn-primary' : 'btn-ghost'} px-2.5 py-1 text-[11.5px]`}
              onClick={() => setFilter(option.code)}
            >
              {t(option.ar, option.en)}
            </button>
          ))}
        </div>
        <button className="btn btn-ghost" onClick={() => void load()} disabled={loading}>
          <RotateCcw size={15} />
          {t('تحديث', 'Refresh')}
        </button>
      </Toolbar>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('إجمالي الانحرافات', 'Deviations')} value={stats.total} />
        <Metric label={t('مفتوحة', 'Open')} value={stats.open} tone={stats.open ? 'warn' : 'neutral'} />
        <Metric
          label={t('تحت التحقيق', 'Under investigation')}
          value={stats.investigating}
          tone={stats.investigating ? 'warn' : 'neutral'}
        />
        <Metric label={t('مغلقة', 'Closed')} value={stats.closed} tone="pass" />
      </div>

      <Card
        title={t('سجل الانحرافات خارج المواصفة (OOS)', 'Out-of-specification deviations')}
        subtitle={t(
          'الانحراف يوثّق الفشل ولا يغيّره: نتيجة التشغيل الفاشل تبقى فاشلة، والطريق إلى الشهادة هو تشغيل إعادة اختبار جديد يُربط بالإغلاق.',
          'A deviation documents a failure; it never alters it. The failed run stays failed — the route to a certificate is a new retest run, cited at closure.',
        )}
        dense
        actions={
          <span className="chip" style={{ background: 'var(--surface-3)', color: 'var(--text-muted)' }}>
            <FlaskConical size={13} />
            {t('ضوابط OOS', 'OOS control')}
          </span>
        }
      >
        {loading ? (
          <Skeleton rows={5} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={t('لا توجد انحرافات', 'No deviations')}
            detail={t(
              'يُفتح الانحراف من شاشة نتيجة غير مطابقة أو غير مكتملة في لوحة المختبر.',
              'A deviation is raised from a failing or incomplete result in the Laboratory workspace.',
            )}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr style={{ color: 'var(--text-muted)' }}>
                  <th className="px-4 py-2 text-start font-semibold">{t('المرجع', 'Reference')}</th>
                  <th className="px-4 py-2 text-start font-semibold">{t('التشغيل', 'Run')}</th>
                  <th className="px-4 py-2 text-start font-semibold">{t('الوصف', 'Subject')}</th>
                  <th className="px-4 py-2 text-start font-semibold">{t('التصنيف', 'Class')}</th>
                  <th className="px-4 py-2 text-start font-semibold">{t('الحالة', 'Status')}</th>
                  <th className="px-4 py-2 text-start font-semibold">{t('تاريخ الفتح', 'Raised')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="cursor-pointer border-t hover:bg-[var(--surface-3)]"
                    style={{ borderColor: 'var(--border)' }}
                    onClick={() => setSelected(row)}
                  >
                    <td className="mono px-4 py-2 font-semibold">{row.reference}</td>
                    <td className="mono px-4 py-2">{row.run_code ?? row.run_id.slice(0, 8)}</td>
                    <td className="max-w-[280px] truncate px-4 py-2">{row.title}</td>
                    <td className="px-4 py-2">{label(CLASSIFICATIONS, row.classification, lang)}</td>
                    <td className="px-4 py-2">
                      <StatusChip status={row.status} small />
                    </td>
                    <td className="px-4 py-2 tabular-nums" style={{ color: 'var(--text-muted)' }}>
                      {row.raised_at ? new Date(row.raised_at).toLocaleString(lang === 'ar' ? 'ar' : 'en-GB') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {!can('deviations.raise') && !can('deviations.close') && (
        <p className="px-1 text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
          {t(
            'لديك صلاحية العرض فقط: رفع الانحراف ودراسته وإغلاقه موزعة على أدوار مختلفة.',
            'View only: raising, investigating and closing are distributed across different roles.',
          )}
        </p>
      )}

      {selected && (
        <DeviationDialog
          deviation={selected}
          busy={busy}
          onClose={() => setSelected(null)}
          onStartInvestigation={(plan) =>
            run(() => api.startInvestigation(selected.id, plan), ['بدأ التحقيق', 'Investigation opened'])
          }
          onRecordOutcome={(body) =>
            run(() => api.recordInvestigation(selected.id, body), ['سُجّل سبب الجذر', 'Root cause recorded'])
          }
          onClose_deviation={(body) =>
            run(() => api.closeDeviation(selected.id, body), ['أُغلق الانحراف', 'Deviation closed'])
          }
          onCancel={(reason) =>
            run(() => api.cancelDeviation(selected.id, reason), ['أُلغي الانحراف', 'Deviation cancelled'])
          }
        />
      )}
    </div>
  );
}

/* ------------------------------- detail dialog ---------------------------- */

function DeviationDialog({
  deviation,
  busy,
  onClose,
  onStartInvestigation,
  onRecordOutcome,
  onClose_deviation,
  onCancel,
}: {
  deviation: ServerDeviation;
  busy: boolean;
  onClose: () => void;
  onStartInvestigation: (plan: string) => void;
  onRecordOutcome: (body: { root_cause_category: string; root_cause: string; immediate_action: string }) => void;
  onClose_deviation: (body: {
    capa_action: string;
    capa_notes: string;
    closure_notes: string;
    retest_run_id?: string | null;
  }) => void;
  onCancel: (reason: string) => void;
}) {
  const { t, lang } = useApp();
  const [plan, setPlan] = useState('');
  const [category, setCategory] = useState<string>('INSTRUMENT_FAULT');
  const [rootCause, setRootCause] = useState('');
  const [immediate, setImmediate] = useState('');
  const [capaAction, setCapaAction] = useState<string>('INSTRUMENT_RESTORED');
  const [capaNotes, setCapaNotes] = useState('');
  const [closureNotes, setClosureNotes] = useState('');
  const [retest, setRetest] = useState('');

  const timeline = [
    { key: 'raised', at: deviation.raised_at, ar: 'فُتح الانحراف', en: 'Raised' },
    { key: 'investigated', at: deviation.investigated_at, ar: 'بدأ التحقيق', en: 'Investigation opened' },
    { key: 'closed', at: deviation.closed_at, ar: deviation.status === 'CANCELLED' ? 'أُلغي' : 'أُغلق', en: deviation.status === 'CANCELLED' ? 'Cancelled' : 'Closed' },
  ].filter((item) => item.at);

  return (
    <Modal open title={`${deviation.reference} — ${deviation.title}`} onClose={onClose} width={780}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StatusChip status={deviation.status} />
        <span className="chip" style={{ background: 'var(--surface-3)', color: 'var(--text-muted)' }}>
          {label(CLASSIFICATIONS, deviation.classification, lang)}
        </span>
        <span className="mono text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
          {deviation.run_code ?? deviation.run_id}
        </span>
      </div>

      <p className="mb-4 whitespace-pre-wrap text-[12px] leading-relaxed">{deviation.description}</p>

      {timeline.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-3">
          {timeline.map((item) => (
            <div key={item.key} className="rounded-lg border px-2.5 py-1.5" style={{ borderColor: 'var(--border)' }}>
              <p className="text-[10.5px] font-semibold" style={{ color: 'var(--text-muted)' }}>
                {t(item.ar, item.en)}
              </p>
              <p className="tabular-nums text-[11.5px]">
                {new Date(item.at as string).toLocaleString(lang === 'ar' ? 'ar' : 'en-GB')}
              </p>
            </div>
          ))}
        </div>
      )}

      {deviation.root_cause && (
        <div className="mb-4 rounded-lg p-3" style={{ background: 'var(--surface-3)' }}>
          <p className="text-[11px] font-bold">{t('السبب الجذري', 'Root cause')}</p>
          <p className="text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
            {label(ROOT_CAUSES, deviation.root_cause_category, lang)}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed">{deviation.root_cause}</p>
          {deviation.immediate_action && (
            <>
              <p className="mt-2 text-[11px] font-bold">{t('الإجراء الفوري', 'Immediate action')}</p>
              <p className="whitespace-pre-wrap text-[12px] leading-relaxed">{deviation.immediate_action}</p>
            </>
          )}
        </div>
      )}

      {deviation.status === 'OPEN' && (
        <div className="mb-3 rounded-lg border p-3" style={{ borderColor: 'var(--border)' }}>
          <p className="mb-2 flex items-center gap-1.5 text-[12px] font-bold">
            <ClipboardList size={15} />
            {t('بدء التحقيق', 'Open the investigation')}
          </p>
          <Field label={t('خطة التحقيق (إلزامية)', 'Investigation plan (mandatory)')}>
            <textarea
              className="textarea"
              rows={3}
              value={plan}
              onChange={(event) => setPlan(event.target.value)}
              placeholder={t(
                'مثال: مراجعة سجل الجهاز، فحص العمود والكواشف، وإعادة الاختبار على معيار مرجعي',
                'e.g. Review the instrument log, inspect column and reagents, retest against a reference standard',
              )}
            />
          </Field>
          <p className="mt-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
            {t(
              'لا يجوز أن يحقّق الشخص نفسه الذي فتح الانحراف — يرفض الخادم ذلك.',
              'The person who raised the deviation may not investigate it — the server refuses this.',
            )}
          </p>
          <div className="mt-2 flex justify-end">
            <button
              className="btn btn-primary"
              disabled={busy || plan.trim().length < 20}
              onClick={() => onStartInvestigation(plan.trim())}
            >
              <ShieldCheck size={15} />
              {t('بدء التحقيق', 'Start investigation')}
            </button>
          </div>
        </div>
      )}

      {deviation.status === 'INVESTIGATING' && (
        <div className="mb-3 rounded-lg border p-3" style={{ borderColor: 'var(--border)' }}>
          <p className="mb-2 text-[12px] font-bold">{t('نتيجة التحقيق', 'Investigation outcome')}</p>
          <Field label={t('تصنيف السبب', 'Root-cause category')}>
            <select className="input" value={category} onChange={(event) => setCategory(event.target.value)}>
              {ROOT_CAUSES.map((item) => (
                <option key={item.code} value={item.code}>
                  {t(item.ar, item.en)}
                </option>
              ))}
            </select>
          </Field>
          <div className="mt-2">
            <Field label={t('السبب الجذري الموثّق', 'Documented root cause')}>
              <textarea className="textarea" rows={3} value={rootCause} onChange={(event) => setRootCause(event.target.value)} />
            </Field>
          </div>
          <div className="mt-2">
            <Field label={t('الإجراء الفوري المتخذ', 'Immediate action taken')}>
              <textarea className="textarea" rows={2} value={immediate} onChange={(event) => setImmediate(event.target.value)} />
            </Field>
          </div>
          <div className="mt-2 flex justify-end">
            <button
              className="btn btn-primary"
              disabled={busy || rootCause.trim().length < 20 || immediate.trim().length < 10}
              onClick={() =>
                onRecordOutcome({
                  root_cause_category: category,
                  root_cause: rootCause.trim(),
                  immediate_action: immediate.trim(),
                })
              }
            >
              {t('تسجيل النتيجة', 'Record outcome')}
            </button>
          </div>
        </div>
      )}

      {deviation.status === 'PENDING_VERIFICATION' && (
        <div className="mb-3 rounded-lg border p-3" style={{ borderColor: 'var(--border)' }}>
          <p className="mb-2 flex items-center gap-1.5 text-[12px] font-bold">
            <AlertTriangle size={15} style={{ color: 'var(--warn)' }} />
            {t('إغلاق الانحراف بقرار CAPA', 'Close with a CAPA decision')}
          </p>
          <Field label={t('إجراء CAPA', 'CAPA action')}>
            <select className="input" value={capaAction} onChange={(event) => setCapaAction(event.target.value)}>
              {CAPA_ACTIONS.map((item) => (
                <option key={item.code} value={item.code}>
                  {t(item.ar, item.en)}
                </option>
              ))}
            </select>
          </Field>
          <div className="mt-2">
            <Field label={t('تفاصيل الإجراء التصحيحي', 'CAPA details')}>
              <textarea className="textarea" rows={2} value={capaNotes} onChange={(event) => setCapaNotes(event.target.value)} />
            </Field>
          </div>
          <div className="mt-2">
            <Field
              label={t('مُعرّف تشغيل إعادة الاختبار (اختياري)', 'Retest run id (optional)')}
              hint={t(
                'إن أُجريت إعادة اختبار ناجحة، اربطها هنا: هي التشغيل الذي يُعتمد ويحمل الشهادة.',
                'If a passing retest was performed, cite it here: that is the run that gets approved and carries the certificate.',
              )}
            >
              <input className="input mono" value={retest} onChange={(event) => setRetest(event.target.value)} placeholder="00000000-0000-0000-0000-000000000000" />
            </Field>
          </div>
          <div className="mt-2">
            <Field label={t('ملاحظات الإغلاق', 'Closure notes')}>
              <textarea className="textarea" rows={2} value={closureNotes} onChange={(event) => setClosureNotes(event.target.value)} />
            </Field>
          </div>
          <div className="mt-2 flex justify-end">
            <button
              className="btn btn-primary"
              disabled={busy || capaNotes.trim().length < 20 || closureNotes.trim().length < 20}
              onClick={() =>
                onClose_deviation({
                  capa_action: capaAction,
                  capa_notes: capaNotes.trim(),
                  closure_notes: closureNotes.trim(),
                  retest_run_id: retest.trim() || null,
                })
              }
            >
              {t('إغلاق الانحراف', 'Close deviation')}
            </button>
          </div>
        </div>
      )}

      {deviation.status === 'CLOSED' && (
        <div className="rounded-lg p-3" style={{ background: 'var(--surface-3)' }}>
          <p className="text-[11px] font-bold">{t('قرار CAPA', 'CAPA decision')}</p>
          <p className="text-[12px]">{label(CAPA_ACTIONS, deviation.capa_action, lang)}</p>
          {deviation.capa_notes && <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed">{deviation.capa_notes}</p>}
          {deviation.retest_run_id && (
            <p className="mono mt-2 text-[11.5px]" style={{ color: 'var(--pass)' }}>
              {t('تشغيل إعادة الاختبار', 'Retest run')}: {deviation.retest_run_id}
            </p>
          )}
        </div>
      )}

      {deviation.status === 'OPEN' && (
        <div className="mt-3 border-t pt-3" style={{ borderColor: 'var(--border)' }}>
          <CancelRow busy={busy} onCancel={onCancel} />
        </div>
      )}
    </Modal>
  );
}

function CancelRow({ busy, onCancel }: { busy: boolean; onCancel: (reason: string) => void }) {
  const { t } = useApp();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  if (!open) {
    return (
      <button className="btn btn-ghost text-[11.5px]" onClick={() => setOpen(true)}>
        {t('إلغاء انحراف فُتح بالخطأ', 'Cancel a deviation raised in error')}
      </button>
    );
  }
  return (
    <div>
      <Field label={t('سبب الإلغاء', 'Reason for cancellation')}>
        <textarea className="textarea" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} />
      </Field>
      <div className="mt-2 flex justify-end gap-2">
        <button className="btn btn-ghost" onClick={() => setOpen(false)}>
          {t('تراجع', 'Back')}
        </button>
        <button className="btn btn-danger" disabled={busy || reason.trim().length < 20} onClick={() => onCancel(reason.trim())}>
          {t('تأكيد الإلغاء', 'Confirm cancellation')}
        </button>
      </div>
    </div>
  );
}
