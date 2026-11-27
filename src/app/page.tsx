'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  FlaskConical,
  ShieldCheck,
  Timer,
  TrendingUp,
} from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Metric, Skeleton, StatusChip } from '@/components/ui';
import { db } from '@/core/db/database';
import { api, toInstrument, type ServerKpis } from '@/core/api/client';
import { SOURCE_LABEL } from '@/core/api/mode';
import { BREAKDOWN_MATRIX, TESTS } from '@/core/protocol';
import type { Instrument, MaintenanceTicket, ReferenceEquipment, RunRecord } from '@/core/types';

const DAY = 86400000;
const daysBetween = (a: string, b = new Date()) =>
  Math.round((new Date(a).getTime() - new Date(b).toISOString().slice(0, 10).length ? new Date(a).getTime() - b.getTime() : 0) / DAY);

export default function DashboardPage() {
  const { t, lang, ready, readThrough, source, setSource } = useApp();
  const [loading, setLoading] = useState(true);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [refEq, setRefEq] = useState<ReferenceEquipment[]>([]);
  const [tickets, setTickets] = useState<MaintenanceTicket[]>([]);
  const [serverKpis, setServerKpis] = useState<ServerKpis | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    (async () => {
      try {
        // The KPI numbers come from GET /kpis (computed in SQL over real rows).
        // The lists below are used for the due-date table and the ledger.
        const [kpis, instrumentsResult, runsResult] = await Promise.all([
          readThrough(
            () => api.kpis(),
            async () => {
              const cached = await db().settings.get('kpis');
              return (cached?.value as ServerKpis) ?? null;
            },
          ),
          readThrough(
            () => api.instruments(),
            async () =>
              (await db().instruments.toArray()).map((c) => ({
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
              })),
          ),
          readThrough(
            () => api.runs({ page_size: 100 }),
            async () => [],
          ),
        ]);

        setSource(instrumentsResult.source);
        setServerKpis(kpis.data);
        if (kpis.source.source === 'server') {
          await db().settings.put({
            key: 'kpis',
            value: kpis.data,
            updatedAt: new Date().toISOString(),
          });
        }
        setInstruments(instrumentsResult.data.map((row) => toInstrument(row)));
        setRuns(
          runsResult.data.map((row) => ({
            id: row.id,
            executionCode: row.execution_code,
            instrumentId: row.instrument_id,
            instrumentName: row.instrument_id,
            protocolCode: 'SHIMADZU-LC2050C-UV-CAL',
            runType: row.run_type,
            ambientTempC: 0,
            ambientHumidity: 0,
            analyst: row.analyst_id,
            reviewer: null,
            qaApprover: row.is_locked ? row.analyst_id : null,
            overallStatus: row.overall_status,
            results: [],
            startedAt: row.started_at,
            completedAt: row.completed_at,
            isLocked: row.is_locked,
            certificateHash: null,
            revision: 1,
          })),
        );
        try {
          const [refs, tk] = await Promise.all([
            readThrough(
              () => api.referenceEquipment(),
              async () => [],
            ),
            readThrough(
              () => api.tickets(),
              async () => [],
            ),
          ]);
          setRefEq(
            refs.data.map((r) => ({
              id: r.id,
              departmentCode: '—',
              code: r.equipment_code,
              nameAr: r.name_ar,
              nameEn: r.name_en,
              serialNumber: r.serial_number,
              certificateNo: r.certificate_no,
              calibratedBy: r.calibrated_by,
              calibrationDate: r.calibration_date,
              expiryDate: r.expiry_date,
              isActive: r.is_active,
            })),
          );
          setTickets(
            tk.data.map((x) => ({
              id: x.id,
              instrumentId: x.instrument_id,
              instrumentName: x.instrument_id,
              component: x.component_affected as MaintenanceTicket['component'],
              componentAr: x.component_affected,
              description: x.description,
              requiredTests: x.required_tests,
              status: x.status as MaintenanceTicket['status'],
              reportedBy: '',
              reportedAt: '',
            })),
          );
        } catch {
          /* secondary panels degrade to their empty state */
        }
        setLoadError(null);
      } catch (error) {
        setLoadError(
          t(
            'تعذر تحميل المؤشرات من الخادم — تُعرض البيانات المتاحة فقط.',
            'KPIs could not be loaded from the server — showing only what is available.',
          ),
        );
        void error;
      } finally {
        setLoading(false);
      }
    })();
  }, [ready, readThrough, setSource, t]);

  const kpi = useMemo(() => {
    const today = new Date();
    const calibrated = instruments.filter(
      (i) => i.nextDueDate && new Date(i.nextDueDate).getTime() >= today.getTime(),
    ).length;
    const dueSoon = instruments.filter((i) => {
      if (!i.nextDueDate) return false;
      const d = Math.ceil((new Date(i.nextDueDate).getTime() - today.getTime()) / DAY);
      return d >= 0 && d <= 30;
    }).length;
    const overdue = instruments.filter(
      (i) => i.nextDueDate && new Date(i.nextDueDate).getTime() < today.getTime(),
    ).length;
    const completed = runs.filter((r) => r.overallStatus !== 'INCOMPLETE');
    const pass = runs.filter((r) => r.overallStatus === 'PASS').length;
    const fail = runs.filter((r) => r.overallStatus === 'FAIL').length;
    const pending = runs.filter((r) => r.overallStatus !== 'FAIL' && !r.qaApprover).length;
    const approvedRuns = runs.filter((r) => r.qaApprover && r.completedAt && r.qaApprover);
    const reviewTimes = approvedRuns
      .map((r) => (r.completedAt ? (new Date(r.completedAt).getTime() - new Date(r.startedAt).getTime()) / DAY : NaN))
      .filter((x) => Number.isFinite(x));
    const avgApprovalDays = reviewTimes.length
      ? (reviewTimes.reduce((a, b) => a + b, 0) / reviewTimes.length).toFixed(1)
      : '—';
    const expiredRef = refEq.filter((e) => new Date(e.expiryDate).getTime() < today.getTime()).length;
    const expiringRef = refEq.filter((e) => {
      const d = Math.ceil((new Date(e.expiryDate).getTime() - today.getTime()) / DAY);
      return d >= 0 && d <= 30;
    }).length;
    const openTickets = tickets.filter((x) => x.status === 'OPEN' || x.status === 'IN_PROGRESS').length;
    return {
      calibrated,
      dueSoon,
      overdue,
      completed: completed.length,
      passRate: completed.length ? Math.round((pass / completed.length) * 100) : null,
      fail,
      pending,
      avgApprovalDays,
      expiredRef,
      expiringRef,
      openTickets,
      total: instruments.length,
    };
  }, [instruments, runs, refEq, tickets]);

  /** Server-computed KPIs win over the client recomputation above. */
  const shown = useMemo(() => {
    if (!serverKpis) return kpi;
    return {
      ...kpi,
      calibrated: serverKpis.instruments.in_calibration,
      total: serverKpis.instruments.total,
      dueSoon: serverKpis.instruments.due_within_30_days,
      overdue: serverKpis.instruments.overdue,
      completed: serverKpis.runs.completed,
      passRate: serverKpis.runs.pass_rate_percent === null ? null : Math.round(serverKpis.runs.pass_rate_percent),
      pending: serverKpis.runs.pending_qa_approval,
      avgApprovalDays:
        serverKpis.runs.mean_approval_days === null ? '—' : String(serverKpis.runs.mean_approval_days),
      expiredRef: serverKpis.compliance.expired_reference_equipment,
      expiringRef: serverKpis.compliance.expired_reference_standards,
      openTickets: serverKpis.compliance.open_maintenance_tickets,
    };
  }, [kpi, serverKpis]);

  const dueList = useMemo(() => {
    const today = new Date();
    return instruments
      .filter((i) => i.nextDueDate)
      .map((i) => ({
        ...i,
        days: Math.ceil((new Date(i.nextDueDate!).getTime() - today.getTime()) / DAY),
      }))
      .sort((a, b) => a.days - b.days)
      .slice(0, 6);
  }, [instruments]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="card">
            <Skeleton rows={2} />
          </div>
        ))}
      </div>
    );
  }

  const hasRuns = runs.length > 0;

  return (
    <div className="space-y-4">
      <div className="card overflow-hidden p-0">
        <div
          className="flex flex-wrap items-center justify-between gap-4 px-5 py-5"
          style={{
            background:
              'linear-gradient(120deg, color-mix(in srgb, var(--brand) 92%, #000) 0%, color-mix(in srgb, var(--brand) 65%, #fff) 100%)',
            color: '#fff',
          }}
        >
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider opacity-85">
              {t('الهيئة العليا للأدوية والمستحضرات الطبية', 'Supreme Board of Drugs & Medical Devices')}
            </p>
            <h1 className="mt-1 text-[19px] font-extrabold leading-tight">
              {t('منصة إدارة ومعايرة الأجهزة المخبرية', 'Laboratory Calibration & OQ Intelligence Platform')}
            </h1>
            <p className="mt-1 text-[11.5px] opacity-90">
              {t(
                'ISO/IEC 17025 · 21 CFR Part 11 · ALCOA+ · بروتوكول Shimadzu LC-2050C UV',
                'ISO/IEC 17025 · 21 CFR Part 11 · ALCOA+ · Shimadzu LC-2050C UV protocol',
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <Link href="/lab/units" className="btn" style={{ background: '#fff', color: 'var(--brand)' }}>
              <FlaskConical size={15} /> {t('تشغيل معايرة', 'Run calibration')}
            </Link>
            <Link href="/qa" className="btn" style={{ background: 'rgba(255,255,255,.18)', color: '#fff', border: '1px solid rgba(255,255,255,.35)' }}>
              <ShieldCheck size={15} /> {t('مراجعة واعتماد', 'Review & approve')}
            </Link>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric
          label={t('أجهزة معايرة سارية', 'Instruments in calibration')}
          value={`${shown.calibrated} / ${shown.total}`}
          hint={t('محسوبة من تواريخ الاستحقاق الفعلية', 'Computed from actual due dates')}
          tone="pass"
        />
        <Metric
          label={t('مستحقة خلال 30 يوماً', 'Due within 30 days')}
          value={shown.dueSoon}
          hint={t('تنبيهات 30/15/7 أيام', '30/15/7-day alerts')}
          tone={shown.dueSoon ? 'warn' : 'neutral'}
        />
        <Metric
          label={t('أجهزة متأخرة الاستحقاق', 'Overdue instruments')}
          value={shown.overdue}
          hint={t('تتطلب إيقافاً تشغيلياً', 'Requires operational hold')}
          tone={shown.overdue ? 'fail' : 'neutral'}
        />
        <Metric
          label={t('معدل نجاح التشغيلات', 'Run pass rate')}
          value={shown.passRate === null ? '—' : `${shown.passRate}%`}
          hint={
            hasRuns
              ? t(`${shown.completed} تشغيل مكتمل`, `${shown.completed} completed runs`)
              : t('لا توجد تشغيلات بعد', 'No runs yet')
          }
          tone={shown.passRate === null ? 'neutral' : shown.passRate >= 90 ? 'pass' : shown.passRate >= 70 ? 'warn' : 'fail'}
        />
        <Metric
          label={t('قيد الاعتماد من QA', 'Awaiting QA approval')}
          value={shown.pending}
          hint={t('فصل المهام مُطبَّق على الخادم', 'Segregation of duties enforced')}
          tone={shown.pending ? 'warn' : 'neutral'}
        />
        <Metric
          label={t('متوسط زمن الاعتماد', 'Mean approval lead time')}
          value={shown.avgApprovalDays === '—' ? '—' : `${shown.avgApprovalDays} ${t('يوم', 'd')}`}
          hint={t('من بدء التشغيل إلى اعتماد QA', 'Start of run → QA sign-off')}
        />
        <Metric
          label={t('أدوات مرجعية منتهية', 'Expired reference items')}
          value={shown.expiredRef}
          hint={t(`${shown.expiringRef} تنتهي خلال 30 يوماً`, `${shown.expiringRef} expiring in 30 days`)}
          tone={shown.expiredRef ? 'fail' : 'neutral'}
        />
        <Metric
          label={t('تذاكر صيانة مفتوحة', 'Open maintenance tickets')}
          value={shown.openTickets}
          hint={t('تربط بمصفوفة ما بعد الأعطال', 'Linked to post-breakdown matrix')}
          tone={shown.openTickets ? 'warn' : 'neutral'}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={t('حالة استحقاق الأجهزة', 'Instrument due status')}
          subtitle={t('مرتبة حسب أقرب تاريخ استحقاق معايرة', 'Sorted by nearest calibration due date')}
          dense
        >
          {dueList.length === 0 ? (
            <EmptyState title={t('لا توجد أجهزة مسجلة', 'No instruments registered')} />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('رمز الأصل', 'Asset code')}</th>
                    <th>{t('الموديل', 'Model')}</th>
                    <th>{t('القسم', 'Department')}</th>
                    <th>{t('الاستحقاق', 'Due date')}</th>
                    <th>{t('المتبقي', 'Remaining')}</th>
                    <th>{t('الحالة', 'Status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {dueList.map((i) => (
                    <tr key={i.id}>
                      <td className="font-mono text-[11.5px]">{i.assetCode}</td>
                      <td className="text-[12px]">{i.model}</td>
                      <td className="text-[12px]">{i.departmentCode}</td>
                      <td className="font-mono text-[11.5px]">{i.nextDueDate}</td>
                      <td>
                        <span
                          className="text-[11.5px] font-bold"
                          style={{
                            color: i.days < 0 ? 'var(--fail)' : i.days <= 30 ? 'var(--warn)' : 'var(--pass)',
                          }}
                        >
                          {i.days < 0
                            ? t(`متأخر ${Math.abs(i.days)} يوم`, `${Math.abs(i.days)}d overdue`)
                            : t(`${i.days} يوم`, `${i.days} d`)}
                        </span>
                      </td>
                      <td>
                        <StatusChip status={i.status} small />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card
          title={t('آخر التشغيلات', 'Latest runs')}
          subtitle={t('سجل التشغيلات المحفوظة محلياً', 'Locally persisted runs')}
          dense
        >
          {runs.length === 0 ? (
            <EmptyState
              title={t('لم يتم تشغيل أي معايرة بعد', 'No calibration run yet')}
              detail={t(
                'انتقل إلى لوحة المختبر لبدء أول تشغيل معايرة للجهاز LC-2050C UV.',
                'Open the laboratory panel to start the first LC-2050C UV run.',
              )}
              action={
                <Link href="/lab/units" className="btn btn-primary mt-2">
                  {t('بدء المعايرة', 'Start calibration')} <ArrowUpRight size={14} />
                </Link>
              }
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {runs
                .slice()
                .sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())
                .slice(0, 6)
                .map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2 px-4 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-[11px] font-bold">{r.executionCode}</p>
                      <p className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                        {r.instrumentName} · {new Date(r.startedAt).toLocaleDateString(lang === 'ar' ? 'ar-YE' : 'en-GB')}
                      </p>
                    </div>
                    <StatusChip status={r.overallStatus} small />
                  </li>
                ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card
          title={t('مصفوفة ما بعد الأعطال', 'Post-breakdown matrix')}
          subtitle={t('الاختبارات الإلزامية قبل إعادة الجهاز للعمل', 'Mandatory retests before returning to service')}
          dense
        >
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('المكوّن', 'Component')}</th>
                  <th>{t('الاختبارات الإلزامية', 'Mandatory tests')}</th>
                </tr>
              </thead>
              <tbody>
                {BREAKDOWN_MATRIX.map((b) => (
                  <tr key={b.key}>
                    <td className="text-[12px] font-semibold">{lang === 'ar' ? b.ar : b.en}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {b.tests.map((code) => (
                          <span
                            key={code}
                            className="chip"
                            style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }}
                            title={TESTS.find((x) => x.code === code)?.nameAr}
                          >
                            {code}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card
          title={t('ملخص البروتوكول المعتمد', 'Approved protocol summary')}
          subtitle={t('مستخرج من التقرير العلمي المقارن', 'Derived from the comparative scientific report')}
          dense
        >
          <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {[
              { icon: CheckCircle2, ar: `${TESTS.length} اختباراً معتمداً لكل دورة معايرة نصف سنوية`, en: `${TESTS.length} mandated tests per semi-annual cycle` },
              { icon: CalendarClock, ar: 'دورية المعايرة: 180 يوماً أو بعد أي صيانة كبرى', en: 'Frequency: 180 days or after major service' },
              { icon: AlertTriangle, ar: 'وحدة الضجيج تُرفض تلقائياً عند إدخال AU/h (GAP-02)', en: 'Noise in AU/h rejected automatically (GAP-02)' },
              { icon: FlaskConical, ar: 'حساس حرارة المبرد يُثبَّت في الموقع 27 — لا فرن العمود (GAP-08)', en: 'Cooler sensor fixed at position 27 — not the oven (GAP-08)' },
              { icon: ShieldCheck, ar: 'لا حكم PASS على حد غير معتمد أو متعارض', en: 'No PASS on an unapproved or conflicted limit' },
              { icon: TrendingUp, ar: 'كل نتائج التقريب تُطبَّق في العرض فقط دون المساس بالقيم الخام', en: 'Rounding applied at presentation only; raw values preserved' },
            ].map(({ icon: Icon, ar, en }, idx) => (
              <li key={idx} className="flex items-start gap-2 px-4 py-2.5">
                <Icon size={14} className="mt-0.5 shrink-0" style={{ color: 'var(--brand)' }} />
                <span className="text-[11.5px] leading-relaxed">{t(ar, en)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
