'use client';

/**
 * Due-date notices and the background jobs that produce them.
 *
 * Two panels with very different audiences on one page, because they answer the
 * same operational question — "is the schedule actually running, and what did it
 * say?" A notice that was never generated looks identical to a notice that was
 * generated and ignored, unless you can see both sides.
 *
 * The page never implies delivery. Notices are stored in-app and `sent_at` stays
 * NULL until a mail provider exists; the page says so rather than showing a
 * "delivered" column that would be a lie.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BellRing, CheckCheck, Clock, PlayCircle, RefreshCw, Server } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Metric, Skeleton, Toolbar } from '@/components/ui';
import {
  ApiError,
  api,
  type ServerKpiReportResult,
  type ServerNotification,
  type ServerWorkerStatus,
} from '@/core/api/client';

const SEVERITY = {
  critical: { bg: 'rgba(180,35,24,.12)', fg: 'var(--fail)', ar: 'حرج', en: 'Critical' },
  warning: { bg: 'rgba(181,71,8,.12)', fg: 'var(--warn)', ar: 'تحذير', en: 'Warning' },
  info: { bg: 'rgba(29,78,216,.12)', fg: 'var(--review)', ar: 'معلومة', en: 'Info' },
} as const;

export default function NotificationsPage() {
  const { t, lang, notify, can } = useApp();

  const [rows, setRows] = useState<ServerNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [worker, setWorker] = useState<ServerWorkerStatus | null>(null);
  const [report, setReport] = useState<ServerKpiReportResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.notifications({ unreadOnly, limit: 100 }));
    } catch (error) {
      notify(
        'error',
        t('تعذّر تحميل الإشعارات', 'Could not load notifications'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setLoading(false);
    }
  }, [unreadOnly, lang, notify, t]);

  useEffect(() => {
    void load();
  }, [load]);

  // the worker view requires audit.view; ask only if the shell says we may
  useEffect(() => {
    if (!can('audit.view')) return;
    api
      .workerStatus()
      .then(setWorker)
      .catch(() => setWorker(null));
  }, [can]);

  const stats = useMemo(() => {
    const unread = rows.filter((row) => !row.read_at).length;
    const critical = rows.filter((row) => row.severity === 'critical' && !row.read_at).length;
    return { total: rows.length, unread, critical };
  }, [rows]);

  const markRead = async (id: string) => {
    try {
      await api.markNotificationRead(id);
      await load();
    } catch (error) {
      notify(
        'error',
        t('تعذّر التعليم', 'Could not mark as read'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    }
  };

  const generate = async () => {
    setBusy(true);
    try {
      const summary = await api.generateNotifications();
      notify(
        'success',
        t('اكتمل التوليد', 'Generation finished'),
        t(
          `أُنشئ ${summary.created} إشعاراً · تُخطّي ${summary.skipped_duplicates} مكرراً`,
          `${summary.created} created · ${summary.skipped_duplicates} duplicates skipped`,
        ),
      );
      await load();
    } catch (error) {
      notify(
        'error',
        t('تعذّر التوليد', 'Generation failed'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const runReport = async () => {
    setBusy(true);
    try {
      const result = await api.runKpiReport();
      setReport(result);
      notify(
        'success',
        t('أُنشئ تقرير مؤشرات الأداء', 'KPI report generated'),
        `${result.period} · ${result.documents.length} ${t('مستنداً', 'documents')}`,
      );
    } catch (error) {
      notify(
        'error',
        t('تعذّر إنشاء التقرير', 'Report generation failed'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('الإشعارات', 'Notices')} value={stats.total} />
        <Metric
          label={t('غير مقروءة', 'Unread')}
          value={stats.unread}
          tone={stats.unread ? 'warn' : 'neutral'}
        />
        <Metric
          label={t('حرجة غير مقروءة', 'Unread critical')}
          value={stats.critical}
          tone={stats.critical ? 'fail' : 'pass'}
        />
        <Metric
          label={t('المزوّد', 'Transport')}
          value={t('داخل التطبيق', 'In-app')}
          hint={t('لا بريد مُعدّ بعد', 'No mail provider yet')}
        />
      </div>

      <Card
        title={t('إشعارات الانتهاء والمعايرة', 'Due-date notices')}
        subtitle={t(
          'كل إشعار يحمل سبب إرساله: نوع المادة، الموعد، والأيام المتبقية. لا يُكرَّر الإشعار لنفس الحالة مهما أُعيد تشغيل المهمة.',
          'Every notice carries its reason: the item, the date and the days remaining. The same condition is never announced twice, however often the job runs.',
        )}
        dense
        actions={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-[11.5px]">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(event) => setUnreadOnly(event.target.checked)}
              />
              <span>{t('غير المقروءة فقط', 'Unread only')}</span>
            </label>
            <button className="btn btn-ghost px-2 py-1" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={14} />
            </button>
          </div>
        }
      >
        {loading ? (
          <Skeleton rows={4} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={t('لا توجد إشعارات', 'No notices')}
            detail={t(
              'لا شيء مستحق خلال النطاق المتابَع (حتى 60 يوماً)، أو لم تُشغَّل مهمة التوليد بعد.',
              'Nothing is due within the tracked horizon (up to 60 days), or the generator has not run yet.',
            )}
          />
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {rows.map((row) => {
              const tone = SEVERITY[(row.severity as keyof typeof SEVERITY) ?? 'info'] ?? SEVERITY.info;
              const days = row.payload?.days_remaining;
              return (
                <li key={row.id} className="flex items-start gap-3 px-4 py-2.5">
                  <span
                    className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                    style={{ background: tone.bg, color: tone.fg }}
                  >
                    <BellRing size={13} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[12.5px] font-bold">
                      {lang === 'ar' ? row.title_ar : (row.title_en ?? row.title_ar)}
                    </p>
                    {row.body_ar && (
                      <p className="mt-0.5 text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
                        {row.body_ar}
                      </p>
                    )}
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                      <span className="chip" style={{ background: tone.bg, color: tone.fg }}>
                        {lang === 'ar' ? tone.ar : tone.en}
                      </span>
                      {typeof days === 'number' && (
                        <span>
                          {days < 0
                            ? t(`متأخر ${Math.abs(days)} يوماً`, `${Math.abs(days)} days overdue`)
                            : days === 0
                              ? t('مستحق اليوم', 'Due today')
                              : t(`يتبقى ${days} يوماً`, `${days} days left`)}
                        </span>
                      )}
                      {row.payload?.due_date && <span className="mono">{row.payload.due_date}</span>}
                      {row.payload?.code && <span className="mono">{row.payload.code}</span>}
                    </p>
                  </div>
                  {row.read_at ? (
                    <span className="chip shrink-0" style={{ background: 'var(--surface-3)', color: 'var(--text-muted)' }}>
                      <CheckCheck size={11} /> {t('مقروء', 'Read')}
                    </span>
                  ) : (
                    <button
                      className="btn btn-ghost shrink-0 px-2 py-1 text-[11px]"
                      onClick={() => void markRead(row.id)}
                    >
                      {t('تعليم كمقروء', 'Mark read')}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {worker && (
        <Card
          title={t('المهام المجدولة والعامل', 'Scheduled jobs and the worker')}
          subtitle={t(
            'الجَدولة مقروءة من التطبيق نفسه لا من التوثيق، فما يظهر هنا هو ما يعمل فعلاً.',
            'The schedule is read from the running app, not from documentation — what is listed here is what runs.',
          )}
          actions={
            <span
              className="chip"
              style={
                worker.broker_configured
                  ? { background: 'rgba(22,121,79,.12)', color: 'var(--pass)' }
                  : { background: 'var(--surface-3)', color: 'var(--text-muted)' }
              }
            >
              <Server size={11} />
              {worker.broker_configured ? t('الوسيط مُعدّ', 'Broker configured') : t('بلا وسيط', 'No broker')}
            </span>
          }
        >
          <div className="space-y-1.5">
            {worker.scheduled.map((job) => (
              <div
                key={job.name}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5"
                style={{ borderColor: 'var(--border)' }}
              >
                <span className="mono text-[11px]">{job.task}</span>
                <span className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  <Clock size={12} />
                  {job.schedule}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
            {lang === 'ar' ? worker.note_ar : worker.note_en}
          </p>

          <Toolbar>
            {can('calibration.approve') && (
              <button className="btn btn-ghost" onClick={() => void generate()} disabled={busy}>
                <PlayCircle size={14} /> {t('تشغيل توليد الإشعارات الآن', 'Run notice generation now')}
              </button>
            )}
            {can('reports.export') && (
              <button className="btn btn-ghost" onClick={() => void runReport()} disabled={busy}>
                <PlayCircle size={14} /> {t('توليد تقرير مؤشرات الأداء', 'Generate KPI report')}
              </button>
            )}
          </Toolbar>

          {report && (
            <div className="mt-2 rounded-lg p-2.5" style={{ background: 'var(--surface-3)' }}>
              <p className="text-[11.5px] font-bold">
                {t('تقرير', 'Report')} {report.period}
              </p>
              <ul className="mt-1 space-y-0.5">
                {report.documents.map((doc) => (
                  <li key={doc.document_id} className="mono text-[10.5px]" style={{ direction: 'ltr' }}>
                    {doc.scope} · {doc.bytes.toLocaleString()} B · {doc.sha256.slice(0, 16)}…
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

      {stats.critical > 0 && (
        <p className="flex items-center gap-1.5 px-1 text-[11.5px]" style={{ color: 'var(--fail)' }}>
          <AlertTriangle size={13} />
          {t(
            `لديك ${stats.critical} إشعاراً حرجاً غير مقروء — عناصر مستحقة أو منتهية تحتاج إجراءً.`,
            `${stats.critical} unread critical notice(s) — due or expired items needing action.`,
          )}
        </p>
      )}
    </div>
  );
}
