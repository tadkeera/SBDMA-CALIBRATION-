'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, PlusCircle, Wrench } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { AttachmentsPanel } from '@/components/AttachmentsPanel';
import { Card, EmptyState, Field, Metric, Modal, Skeleton, StatusChip, Toolbar } from '@/components/ui';
import { db } from '@/core/db/database';
import { ApiError, api, toInstrument, type ServerInstrument } from '@/core/api/client';
import { BREAKDOWN_MATRIX, TESTS, testsForComponent } from '@/core/protocol';
import { type Instrument, type MaintenanceTicket } from '@/core/types';

export default function EngineeringPage() {
  const { t, lang, ready, user, notify, can, readThrough, setSource } = useApp();
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [tickets, setTickets] = useState<MaintenanceTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [component, setComponent] = useState(BREAKDOWN_MATRIX[0].key);
  const [instrumentId, setInstrumentId] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [evidenceFor, setEvidenceFor] = useState('');

  const canManage = can('maintenance.manage');

  const load = async () => {
    try {
      const [inst, tk] = await Promise.all([
        readThrough(
          () => api.instruments(),
          async () =>
            (await db().instruments.toArray()).map(
              (c): ServerInstrument => ({
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
              }),
            ),
        ),
        readThrough(
          () => api.tickets(),
          async () =>
            (await db().tickets.toArray()).map((t) => ({
              id: t.id,
              instrument_id: t.instrumentId,
              component_affected: t.component,
              description: t.description,
              required_tests: t.requiredTests,
              status: t.status,
              resolved_at: t.resolvedAt ?? null,
            })),
        ),
      ]);
      setSource(inst.source);
      const mapped = inst.data.map((row) => toInstrument(row));
      setInstruments(mapped);
      setTickets(
        tk.data.map((x) => {
          const inst2 = mapped.find((i) => i.id === x.instrument_id);
          const comp = BREAKDOWN_MATRIX.find((b) => b.key === x.component_affected);
          return {
            id: x.id,
            instrumentId: x.instrument_id,
            instrumentName: inst2 ? `${inst2.manufacturer} ${inst2.model}` : x.instrument_id,
            component: x.component_affected as MaintenanceTicket['component'],
            componentAr: comp?.ar ?? x.component_affected,
            description: x.description,
            requiredTests: x.required_tests,
            status: x.status as MaintenanceTicket['status'],
            reportedBy: '',
            reportedAt: x.status === 'RESOLVED' ? (x.resolved_at ?? '') : '',
          };
        }),
      );
    } catch (error) {
      notify('error', t('تعذر تحميل بيانات الصيانة', 'Maintenance data could not be loaded'), error instanceof ApiError ? error.text(lang) : String(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!ready) return;
    void load();
  }, [ready]);

  const requiredTests = useMemo(() => testsForComponent(component), [component]);

  const createTicket = async () => {
    if (!instrumentId || description.trim().length < 8) {
      notify('error', t('بيانات ناقصة', 'Missing data'), t('اختر الجهاز واكتب وصفاً لا يقل عن 8 أحرف.', 'Select an instrument and write at least 8 characters.'));
      return;
    }
    setBusy(true);
    try {
      const ticket = await api.createTicket(instrumentId, component, description.trim());
      notify(
        'success',
        t('تم فتح تذكرة صيانة', 'Maintenance ticket opened'),
        `${ticket.id.slice(0, 8)} · ${ticket.required_tests.join(' / ')}`,
      );
      setOpen(false);
      setDescription('');
      await load();
    } catch (error) {
      notify(
        'error',
        t('تعذر فتح التذكرة', 'Ticket could not be opened'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const closeTicket = async (ticket: MaintenanceTicket) => {
    setBusy(true);
    try {
      await api.resolveTicket(ticket.id);
      notify('success', t('تم إنجاز التذكرة', 'Ticket resolved'), t('أُعيد الجهاز إلى الخدمة ويجب تنفيذ اختبارات ما بعد الأعطال.', 'The instrument is back in service; the post-breakdown retests are now due.'));
      await load();
    } catch (error) {
      notify(
        'error',
        t('تعذر إنجاز التذكرة', 'Ticket could not be resolved'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Skeleton rows={8} />;

  const openTickets = tickets.filter((x) => x.status === 'OPEN' || x.status === 'IN_PROGRESS');

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('تذاكر مفتوحة', 'Open tickets')} value={openTickets.length} tone={openTickets.length ? 'warn' : 'neutral'} />
        <Metric label={t('تذاكر منجزة', 'Resolved tickets')} value={tickets.filter((x) => x.status === 'RESOLVED').length} tone="pass" />
        <Metric label={t('أجهزة تحت الصيانة', 'Instruments under maintenance')} value={instruments.filter((i) => i.status === 'UNDER_MAINTENANCE').length} tone="warn" />
        <Metric
          label={t('لمبة D2 قاربت الحد', 'D2 lamps near limit')}
          value={instruments.filter((i) => i.d2LampHours >= 1800).length}
          hint={t('حد الاستبدال 2000 ساعة', 'Replacement at 2000 h')}
          tone={instruments.some((i) => i.d2LampHours >= 1800) ? 'fail' : 'neutral'}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_360px]">
        <Card
          title={t('تذاكر الصيانة والأعطال', 'Maintenance tickets')}
          actions={
            <button className="btn btn-primary" onClick={() => setOpen(true)} disabled={!canManage}>
              <PlusCircle size={14} /> {t('تذكرة جديدة', 'New ticket')}
            </button>
          }
          dense
        >
          {tickets.length === 0 ? (
            <EmptyState
              title={t('لا توجد تذاكر صيانة', 'No maintenance tickets')}
              detail={t('سجّل الأعطال لتفعيل مصفوفة الاختبارات الإلزامية بعد الصيانة.', 'Log breakdowns to activate the post-maintenance mandatory test matrix.')}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('المعرّف', 'ID')}</th>
                    <th>{t('الجهاز', 'Instrument')}</th>
                    <th>{t('المكوّن', 'Component')}</th>
                    <th>{t('الاختبارات الإلزامية', 'Mandatory tests')}</th>
                    <th>{t('الحالة', 'Status')}</th>
                    <th>{t('المسؤول', 'Owner')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {tickets
                    .slice()
                    .sort((a, b) => new Date(b.reportedAt).getTime() - new Date(a.reportedAt).getTime())
                    .map((tk) => (
                      <tr key={tk.id}>
                        <td className="font-mono text-[10.5px]">{tk.id.slice(-8)}</td>
                        <td className="text-[11.5px]">{tk.instrumentName}</td>
                        <td className="text-[11.5px]">{lang === 'ar' ? tk.componentAr : tk.component}</td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            {tk.requiredTests.map((c) => (
                              <span key={c} className="chip" style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }} title={TESTS.find((x) => x.code === c)?.nameAr}>
                                {c}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td>
                          <StatusChip status={tk.status} small />
                        </td>
                        <td className="text-[11px]">{tk.reportedBy}</td>
                        <td>
                          {tk.status !== 'RESOLVED' && (
                            <button className="btn btn-ghost px-2 py-1 text-[10.5px]" onClick={() => closeTicket(tk)} disabled={!canManage || busy}>
                              <CheckCircle2 size={12} /> {t('إنجاز', 'Resolve')}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title={t('مصفوفة ما بعد الأعطال', 'Post-breakdown matrix')} subtitle={t('يحددها النظام تلقائياً حسب المكوّن', 'Auto-derived from the failed component')} dense>
          <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {BREAKDOWN_MATRIX.map((b) => (
              <li key={b.key} className="px-3 py-2">
                <p className="text-[11.5px] font-bold">{lang === 'ar' ? b.ar : b.en}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {b.tests.map((c) => (
                    <span key={c} className="chip" style={{ background: 'var(--surface-3)' }} title={TESTS.find((x) => x.code === c)?.nameAr}>
                      {c}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          <div className="p-3">
            <Link href="/lab/units" className="btn btn-ghost w-full justify-center">
              <Wrench size={13} /> {t('فتح تشغيل ما بعد العطل', 'Open post-breakdown run')}
            </Link>
          </div>
        </Card>
      </div>

      <div className="mt-3">
        <Card
          title={t('ملف أدلة الجهاز', 'Instrument evidence file')}
          subtitle={t('اختر جهازاً لعرض أدلته المخبرية أو إرفاق دليل جديد ببصمة موثقة', 'Pick an instrument to review its evidence or file a new document under a verified checksum')}
        >
          <Field label={t('الجهاز', 'Instrument')}>
            <select
              className="select"
              data-testid="evidence-instrument"
              value={evidenceFor}
              onChange={(e) => setEvidenceFor(e.target.value)}
            >
              <option value="">{t('— اختر جهازاً —', '— select an instrument —')}</option>
              {instruments.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.assetCode} · {i.model}
                </option>
              ))}
            </select>
          </Field>
        </Card>
        {evidenceFor ? (
          <div className="mt-3">
            <AttachmentsPanel
              instrumentId={evidenceFor}
              instrumentLabel={instruments.find((i) => i.id === evidenceFor)?.assetCode}
            />
          </div>
        ) : null}
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t('فتح تذكرة صيانة جديدة', 'Open a maintenance ticket')}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setOpen(false)}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button className="btn btn-primary" onClick={createTicket} disabled={busy || !canManage}>
              {busy ? t('جارٍ الحفظ…', 'Saving…') : t('فتح التذكرة', 'Open ticket')}
            </button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t('الجهاز', 'Instrument')}>
            <select className="select" value={instrumentId} onChange={(e) => setInstrumentId(e.target.value)}>
              <option value="">{t('— اختر —', '— select —')}</option>
              {instruments.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.assetCode} · {i.model}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('المكوّن المتعطل', 'Failed component')}>
            <select className="select" value={component} onChange={(e) => setComponent(e.target.value)}>
              {BREAKDOWN_MATRIX.map((b) => (
                <option key={b.key} value={b.key}>
                  {lang === 'ar' ? b.ar : b.en}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('وصف العطل والإجراء المنفذ', 'Fault description & action taken')}>
            <textarea className="textarea" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="rounded-lg px-3 py-2" style={{ background: 'var(--brand-soft)' }}>
            <p className="text-[11px] font-bold" style={{ color: 'var(--brand)' }}>
              {t('الاختبارات الإلزامية قبل إعادة الجهاز للعمل', 'Mandatory retests before return to service')}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {requiredTests.map((c) => (
                <span key={c} className="chip" style={{ background: 'var(--surface)', color: 'var(--brand)' }}>
                  {c} · {lang === 'ar' ? TESTS.find((x) => x.code === c)?.nameAr : TESTS.find((x) => x.code === c)?.nameEn}
                </span>
              ))}
            </div>
          </div>
        </div>
      </Modal>
    </div>
  );
}
