'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Building2,
  Database,
  FlaskConical,
  PlusCircle,
  RefreshCw,
  ShieldCheck,
  Users,
  Wrench,
} from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Field, Metric, Modal, Skeleton, StatusChip, Toolbar } from '@/components/ui';
import { appendAudit, db, exportDatabase } from '@/core/db/database';
import { resetDatabase } from '@/core/db/seed';
import { LIMITS, TESTS } from '@/core/protocol';
import {
  DEPARTMENTS,
  LIMIT_SOURCES,
  ROLE_LABELS,
  ROLE_PERMISSIONS,
  ROLES,
  SOURCE_LABELS,
  type Instrument,
  type ReferenceEquipment,
  type UserAccount,
} from '@/core/types';

type Tab = 'users' | 'instruments' | 'refs' | 'protocol' | 'system';

export default function ControlPage() {
  const { t, lang, ready, user, notify, session, setLang, setTheme, theme } = useApp();
  const [tab, setTab] = useState<Tab>('instruments');
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [refs, setRefs] = useState<ReferenceEquipment[]>([]);
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    assetCode: '',
    departmentCode: DEPARTMENTS[0].code,
    category: 'HPLC',
    manufacturer: 'Shimadzu',
    model: '',
    partNumber: '',
    serialNumber: '',
    softwareVersion: '',
    freq: '180',
    lastCal: '',
  });

  const canManage = user ? ROLE_PERMISSIONS[user.role].includes('settings.manage') : false;

  const load = async () => {
    const d = db();
    setInstruments(await d.instruments.toArray());
    setRefs(await d.referenceEquipment.toArray());
    setUsers(await d.users.toArray());
    setLoading(false);
  };

  useEffect(() => {
    if (!ready) return;
    void load();
  }, [ready]);

  const today = new Date();

  const createInstrument = async () => {
    if (!form.assetCode.trim() || !form.model.trim() || !form.serialNumber.trim()) {
      notify('error', t('بيانات ناقصة', 'Missing data'), t('رمز الأصل والموديل والرقم التسلسلي إلزامية.', 'Asset code, model and serial number are mandatory.'));
      return;
    }
    setBusy(true);
    try {
      const last = form.lastCal ? new Date(form.lastCal) : null;
      const due = last ? new Date(last.getTime() + Number(form.freq) * 86400000) : null;
      const inst: Instrument = {
        id: `ins-${Date.now()}`,
        assetCode: form.assetCode.trim(),
        departmentCode: form.departmentCode,
        category: form.category,
        manufacturer: form.manufacturer,
        model: form.model.trim(),
        partNumber: form.partNumber.trim(),
        serialNumber: form.serialNumber.trim(),
        softwareVersion: form.softwareVersion.trim(),
        calibrationFreqDays: Number(form.freq),
        lastCalibrationDate: last ? last.toISOString().slice(0, 10) : null,
        nextDueDate: due ? due.toISOString().slice(0, 10) : null,
        status: 'ACTIVE',
        d2LampHours: 0,
      };
      await db().instruments.put(inst);
      await appendAudit({
        actor: user?.username ?? 'unknown',
        role: user?.role ?? 'VIEWER',
        action: 'INSTRUMENT_CREATED',
        entity: 'instrument',
        entityId: inst.id,
        module: 'control',
        after: inst,
        reason: 'تسجيل جهاز جديد في سجل الأجهزة',
      });
      notify('success', t('تم تسجيل الجهاز', 'Instrument registered'), inst.assetCode);
      setOpen(false);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const reseed = async () => {
    setBusy(true);
    try {
      await resetDatabase();
      await appendAudit({
        actor: user?.username ?? 'unknown',
        role: user?.role ?? 'VIEWER',
        action: 'DATABASE_RESEEDED',
        entity: 'system',
        entityId: 'sbdma_calibration',
        module: 'control',
        reason: 'إعادة تهيئة البيانات المرجعية للبروتوكول والأقسام',
      });
      notify('success', t('تمت إعادة التهيئة', 'Database reseeded'));
      await load();
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    const dump = await exportDatabase();
    const blob = new Blob([dump], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sbdma-database-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const limitStats = useMemo(() => {
    const approved = LIMITS.filter((l) => l.approvalStatus === 'APPROVED').length;
    const conflict = LIMITS.filter((l) => l.approvalStatus !== 'APPROVED').length;
    return { approved, conflict };
  }, []);

  if (loading) return <Skeleton rows={10} />;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('أجهزة مسجلة', 'Registered instruments')} value={instruments.length} />
        <Metric label={t('أدوات مرجعية', 'Reference items')} value={refs.length} hint={`${refs.filter((r) => new Date(r.expiryDate) < today).length} ${t('منتهية', 'expired')}`} tone={refs.some((r) => new Date(r.expiryDate) < today) ? 'fail' : 'neutral'} />
        <Metric label={t('حدود معتمدة', 'Approved limits')} value={limitStats.approved} hint={`${limitStats.conflict} ${t('تحتاج قرار QA', 'need QA decision')}`} tone="pass" />
        <Metric label={t('اختبارات البروتوكول', 'Protocol tests')} value={TESTS.length} hint={t('جميعها إلزامية', 'All mandatory')} />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(
          [
            { k: 'instruments', ar: 'سجل الأجهزة', en: 'Instruments', icon: FlaskConical },
            { k: 'refs', ar: 'الأدوات المرجعية', en: 'Reference equipment', icon: Wrench },
            { k: 'users', ar: 'المستخدمون والصلاحيات', en: 'Users & RBAC', icon: Users },
            { k: 'protocol', ar: 'البروتوكول والحدود', en: 'Protocol & limits', icon: ShieldCheck },
            { k: 'system', ar: 'النظام والبيانات', en: 'System & data', icon: Database },
          ] as { k: Tab; ar: string; en: string; icon: typeof FlaskConical }[]
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

      {tab === 'instruments' && (
        <Card
          title={t('سجل الأجهزة', 'Instrument register')}
          subtitle={t('جميع أجهزة الهيئة مع دورية المعايرة والاستحقاق', 'All SBDMA instruments with calibration frequency and due dates')}
          actions={
            <button className="btn btn-primary" onClick={() => setOpen(true)} disabled={!canManage}>
              <PlusCircle size={14} /> {t('جهاز جديد', 'New instrument')}
            </button>
          }
          dense
        >
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('رمز الأصل', 'Asset')}</th>
                  <th>{t('الفئة', 'Category')}</th>
                  <th>{t('المصنع / الموديل', 'Make / Model')}</th>
                  <th>{t('الرقم التسلسلي', 'Serial')}</th>
                  <th>{t('القسم', 'Dept')}</th>
                  <th>{t('الدورية', 'Freq.')}</th>
                  <th>{t('الاستحقاق', 'Due')}</th>
                  <th>{t('الحالة', 'Status')}</th>
                </tr>
              </thead>
              <tbody>
                {instruments.map((i) => {
                  const overdue = i.nextDueDate ? new Date(i.nextDueDate) < today : false;
                  return (
                    <tr key={i.id}>
                      <td className="font-mono text-[11px] font-bold">{i.assetCode}</td>
                      <td className="text-[11.5px]">{i.category}</td>
                      <td className="text-[11.5px]">
                        {i.manufacturer}
                        <br />
                        <span style={{ color: 'var(--text-muted)' }}>{i.model}</span>
                      </td>
                      <td className="font-mono text-[10.5px]">{i.serialNumber}</td>
                      <td className="text-[11px]">{i.departmentCode}</td>
                      <td className="text-[11px]">{i.calibrationFreqDays}d</td>
                      <td className="font-mono text-[11px]" style={{ color: overdue ? 'var(--fail)' : 'var(--text)' }}>
                        {i.nextDueDate ?? '—'}
                      </td>
                      <td>
                        <StatusChip status={i.status} small />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {tab === 'refs' && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title={t('الأدوات المرجعية', 'Reference equipment')} subtitle={t('حاجز الصلاحية يمنع استخدام أي أداة منتهية', 'The expiry guard blocks any expired item')} dense>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('الرمز', 'Code')}</th>
                    <th>{t('الاسم', 'Name')}</th>
                    <th>{t('الشهادة', 'Certificate')}</th>
                    <th>{t('الانتهاء', 'Expiry')}</th>
                  </tr>
                </thead>
                <tbody>
                  {refs.map((r) => {
                    const expired = new Date(r.expiryDate) < today;
                    return (
                      <tr key={r.id}>
                        <td className="font-mono text-[11px]">{r.code}</td>
                        <td className="text-[11px]">{lang === 'ar' ? r.nameAr : r.nameEn}</td>
                        <td className="font-mono text-[10.5px]">{r.certificateNo}</td>
                        <td className="font-mono text-[11px]" style={{ color: expired ? 'var(--fail)' : 'var(--pass)', fontWeight: 700 }}>
                          {r.expiryDate} {expired && `· ${t('منتهية', 'EXPIRED')}`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title={t('الأقسام والمختبرات', 'Departments & laboratories')} dense>
            <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {DEPARTMENTS.map((d) => (
                <li key={d.code} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="flex items-center gap-2">
                    <Building2 size={13} style={{ color: 'var(--brand)' }} />
                    <span className="text-[11.5px] font-semibold">{lang === 'ar' ? d.nameAr : d.nameEn}</span>
                  </span>
                  <span className="font-mono text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                    {d.code} · {instruments.filter((i) => i.departmentCode === d.code).length}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}

      {tab === 'users' && (
        <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
          <Card title={t('المستخدمون والأدوار', 'Users & roles')} subtitle={t('النطاق مقيد بالقسم ولا يمكن منح صلاحيات أعلى من صلاحياتك', 'Scoped by department; no user may grant permissions above their own')} dense>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('المستخدم', 'User')}</th>
                    <th>{t('الدور', 'Role')}</th>
                    <th>{t('القسم', 'Dept')}</th>
                    <th>{t('الصلاحيات', 'Permissions')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td className="text-[11.5px] font-semibold">
                        {lang === 'ar' ? u.fullNameAr : u.fullNameEn}
                        <br />
                        <span className="font-mono text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          {u.username}
                        </span>
                      </td>
                      <td className="text-[11px]">{ROLE_LABELS[u.role][lang]}</td>
                      <td className="text-[11px]">{u.departmentCode}</td>
                      <td className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        {ROLE_PERMISSIONS[u.role].length} {t('صلاحية', 'perms')}
                      </td>
                      <td>
                        <span
                          className="text-[10px]"
                          style={{ color: user?.id === u.id ? 'var(--brand)' : 'var(--text-muted)' }}
                          title={t('الهوية تُدار على الخادم فقط — يلزم تسجيل دخول', 'Identity is server-issued only — sign in as that user')}
                        >
                          {user?.id === u.id
                            ? t('الجلسة الحالية', 'Current session')
                            : t('يلزم دخول', 'Sign in to use')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title={t('مصفوفة الصلاحيات', 'Permission matrix')} dense>
            <div className="max-h-[480px] overflow-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('الدور', 'Role')}</th>
                    <th>{t('العدد', 'Count')}</th>
                  </tr>
                </thead>
                <tbody>
                  {ROLES.map((r) => (
                    <tr key={r}>
                      <td className="text-[11px]">{ROLE_LABELS[r][lang]}</td>
                      <td className="font-mono text-[11px]">{ROLE_PERMISSIONS[r].length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {tab === 'protocol' && (
        <div className="space-y-3">
          <Card title={t('البروتوكول المعتمد', 'Approved protocol')} subtitle="SHIMADZU-LC2050C-UV-CAL · v1.0.0" dense>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t('الاختبار', 'Test')}</th>
                    <th>{t('الوحدة', 'Module')}</th>
                    <th>{t('المرجع', 'Standard')}</th>
                    <th>{t('المعادلات', 'Formulas')}</th>
                    <th>{t('المقاييس', 'Metrics')}</th>
                  </tr>
                </thead>
                <tbody>
                  {TESTS.map((x) => (
                    <tr key={x.code}>
                      <td className="font-mono text-[11px] font-bold">{x.code}</td>
                      <td className="text-[11.5px]">{lang === 'ar' ? x.nameAr : x.nameEn}</td>
                      <td>
                        <span className="chip" style={{ background: 'var(--surface-3)' }}>
                          {x.module}
                        </span>
                      </td>
                      <td className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                        {x.standard}
                      </td>
                      <td className="font-mono text-[10.5px]">{x.formulas.length}</td>
                      <td className="text-[10.5px]">{x.metrics.join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title={t('حدود القبول من المصادر الخمسة', 'Acceptance limits from five sources')} dense>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('الاختبار', 'Test')}</th>
                    <th>{t('المقياس', 'Metric')}</th>
                    <th>{t('المصدر', 'Source')}</th>
                    <th>{t('الحد', 'Limit')}</th>
                    <th>{t('الاعتماد', 'Approval')}</th>
                  </tr>
                </thead>
                <tbody>
                  {LIMITS.map((l) => (
                    <tr key={l.id}>
                      <td className="font-mono text-[10.5px]">{l.testCode}</td>
                      <td className="font-mono text-[10.5px]">{l.metricKey}</td>
                      <td className="text-[10.5px]">{SOURCE_LABELS[l.sourceType][lang]}</td>
                      <td className="font-mono text-[10.5px]">
                        {l.operator === 'gte' ? '≥ ' : l.operator === 'lte' ? '≤ ' : ''}
                        {l.operator === 'gte' ? l.minValue : l.maxValue} {l.unit}
                      </td>
                      <td>
                        <StatusChip status={l.approvalStatus} small />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {tab === 'system' && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title={t('البيانات والإعدادات', 'Data & settings')}>
            <div className="space-y-3 text-[12px]">
              <div className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)' }}>
                <span>{t('اللغة', 'Language')}</span>
                <div className="flex gap-1">
                  <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => setLang('ar')} style={{ background: lang === 'ar' ? 'var(--brand-soft)' : undefined }}>
                    العربية
                  </button>
                  <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => setLang('en')} style={{ background: lang === 'en' ? 'var(--brand-soft)' : undefined }}>
                    English
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)' }}>
                <span>{t('المظهر', 'Theme')}</span>
                <div className="flex gap-1">
                  <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => setTheme('light')} style={{ background: theme === 'light' ? 'var(--brand-soft)' : undefined }}>
                    Light
                  </button>
                  <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => setTheme('dark')} style={{ background: theme === 'dark' ? 'var(--brand-soft)' : undefined }}>
                    Dark
                  </button>
                </div>
              </div>
              <Toolbar>
                <button className="btn btn-ghost" onClick={download}>
                  <Database size={14} /> {t('تصدير قاعدة البيانات', 'Export database')}
                </button>
                <button className="btn btn-ghost" onClick={reseed} disabled={busy || !canManage}>
                  <RefreshCw size={14} /> {t('إعادة تهيئة', 'Reseed')}
                </button>
              </Toolbar>
              <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                {t(
                  'قاعدة البيانات المحلية تعمل داخل المتصفح (IndexedDB) وتُحفظ تلقائياً بعد كل إجراء. يمكن تصدير نسخة JSON كاملة ومطابقتها مع مخطط PostgreSQL 16 للمزامنة مع الخادم.',
                  'The local database runs in the browser (IndexedDB) and persists every action automatically. A full JSON dump can be exported and mapped to the PostgreSQL 16 schema for server synchronisation.',
                )}
              </p>
            </div>
          </Card>

          <Card title={t('مصادر حدود القبول', 'Acceptance-limit sources')} dense>
            <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {LIMIT_SOURCES.map((s) => (
                <li key={s} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="text-[11.5px] font-semibold">{SOURCE_LABELS[s][lang]}</span>
                  <span className="flex gap-1">
                    <span className="chip" style={{ background: 'var(--surface-3)' }}>
                      {LIMITS.filter((l) => l.sourceType === s).length}
                    </span>
                    {LIMITS.some((l) => l.sourceType === s && l.approvalStatus !== 'APPROVED') && (
                      <span className="chip" style={{ background: 'rgba(181,71,8,.12)', color: 'var(--warn)' }}>
                        {t('تعارض', 'conflict')}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t('تسجيل جهاز جديد', 'Register new instrument')}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setOpen(false)}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button className="btn btn-primary" onClick={createInstrument} disabled={busy || !canManage}>
              {busy ? t('جارٍ الحفظ…', 'Saving…') : t('حفظ الجهاز', 'Save instrument')}
            </button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('رمز الأصل', 'Asset code')}>
            <input className="input mono" value={form.assetCode} onChange={(e) => setForm({ ...form, assetCode: e.target.value })} placeholder="SBDMA-CHEM-HPLC-003" />
          </Field>
          <Field label={t('القسم', 'Department')}>
            <select className="select" value={form.departmentCode} onChange={(e) => setForm({ ...form, departmentCode: e.target.value })}>
              {DEPARTMENTS.map((d) => (
                <option key={d.code} value={d.code}>
                  {lang === 'ar' ? d.nameAr : d.nameEn}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('الفئة', 'Category')}>
            <select className="select" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {['HPLC', 'GC', 'UV-Vis', 'FTIR', 'Karl Fischer', 'Dissolution', 'Disintegration', 'Hardness', 'Friability', 'Analytical Balance', 'pH Meter', 'Autoclave', 'Incubator', 'Stability Chamber'].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('المصنع', 'Manufacturer')}>
            <input className="input" value={form.manufacturer} onChange={(e) => setForm({ ...form, manufacturer: e.target.value })} />
          </Field>
          <Field label={t('الموديل', 'Model')}>
            <input className="input" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </Field>
          <Field label={t('رقم القطعة', 'Part number')}>
            <input className="input mono" value={form.partNumber} onChange={(e) => setForm({ ...form, partNumber: e.target.value })} />
          </Field>
          <Field label={t('الرقم التسلسلي', 'Serial number')}>
            <input className="input mono" value={form.serialNumber} onChange={(e) => setForm({ ...form, serialNumber: e.target.value })} />
          </Field>
          <Field label={t('إصدار البرمجية', 'Software version')}>
            <input className="input" value={form.softwareVersion} onChange={(e) => setForm({ ...form, softwareVersion: e.target.value })} />
          </Field>
          <Field label={t('دورية المعايرة (يوم)', 'Calibration frequency (days)')}>
            <input className="input mono" value={form.freq} onChange={(e) => setForm({ ...form, freq: e.target.value })} />
          </Field>
          <Field label={t('تاريخ آخر معايرة', 'Last calibration date')}>
            <input type="date" className="input mono" value={form.lastCal} onChange={(e) => setForm({ ...form, lastCal: e.target.value })} />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
