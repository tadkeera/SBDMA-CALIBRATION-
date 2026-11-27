'use client';

/**
 * The laboratory, entered by unit.
 *
 * The bench does not think in categories ("the HPLC"), it thinks in units ("HPLC (2) is
 * on the third bench"). This screen is that shelf: one tile per registered unit, each
 * with its number in a red circle and a small ring showing how much of its cycle is left.
 *
 * Adding a unit is a governance act, not a formality — the number is assigned by the
 * server (never by the browser), the action is audited, and the new unit inherits the
 * twenty tests of the approved protocol for its category. That inheritance is a property
 * of the *protocol*, not a copy: one approved limit table governs every unit of the same
 * category, so a limit approved today is not silently re-approved per unit tomorrow and
 * the two copies cannot drift.
 */

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronLeft,
  CircleDot,
  Clock3,
  Loader2,
  Plus,
  RefreshCw,
  ShieldQuestion,
} from 'lucide-react';

import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Field, Modal, Skeleton } from '@/components/ui';
import { ApiError, api, type ServerInstrument } from '@/core/api/client';
import { TESTS } from '@/core/protocol';

interface UnitForm {
  label_ar: string;
  label_en: string;
  model: string;
  manufacturer: string;
  serial_number: string;
  part_number: string;
  software_version: string;
  calibration_freq_days: string;
}

const EMPTY: UnitForm = {
  label_ar: '',
  label_en: '',
  model: '',
  manufacturer: 'SHIMADZU',
  serial_number: '',
  part_number: '',
  software_version: '',
  calibration_freq_days: '180',
};

/** Days until the next due date; null when no cycle has been recorded. */
function daysLeft(nextDue: string | null): number | null {
  if (!nextDue) return null;
  const due = new Date(nextDue).getTime();
  if (Number.isNaN(due)) return null;
  return Math.round((due - Date.now()) / 86_400_000);
}

function dueTone(days: number | null): { color: string; labelAr: string; labelEn: string } {
  if (days === null) return { color: 'var(--text-muted)', labelAr: 'لم تُسجَّل دورة', labelEn: 'No cycle recorded' };
  if (days < 0) return { color: 'var(--fail)', labelAr: 'متأخرة', labelEn: 'Overdue' };
  if (days <= 30) return { color: 'var(--warn)', labelAr: 'قريبة', labelEn: 'Due soon' };
  return { color: 'var(--pass)', labelAr: 'سارية', labelEn: 'In date' };
}

export default function UnitsPage() {
  const { t, lang, notify, can } = useApp();
  const [units, setUnits] = useState<ServerInstrument[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<UnitForm>(EMPTY);
  const [category, setCategory] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const canCreate = can('instruments.create');

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await api.instruments();
      setUnits(rows);
      const distinct = Array.from(new Set(rows.map((row) => row.category))).sort();
      setCategories(distinct);
      setCategory((current) => current || distinct[0] || 'HPLC');
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.text(lang)
          : t('تعذر تحميل سجل الأجهزة من الخادم.', 'The instrument register could not be loaded.'),
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [lang, t]);

  useEffect(() => {
    void load();
  }, [load]);

  /** The next number the server will hand out — shown as a preview, never submitted. */
  const nextNumber = useMemo(
    () =>
      units.reduce((highest, unit) => Math.max(highest, unit.device_number ?? 0), 0) + 1,
    [units],
  );

  /**
   * The register's own category is what the units are filed under (``HPLC-UV``), while
   * the bench calls them by the short name (``HPLC``). Both labels therefore use the
   * short name, so the new tile matches the units already on the shelf.
   */
  const shortName = category.split('-')[0] || category;

  const openDialog = () => {
    setForm({
      ...EMPTY,
      label_ar: `${shortName} (${nextNumber})`,
      label_en: `${shortName} (${nextNumber})`,
    });
    setFormError(null);
    setOpen(true);
  };

  const submit = async () => {
    if (saving) return; // no double submission: the button is disabled too, this is the guard
    setFormError(null);
    if (!form.model.trim() || !form.serial_number.trim()) {
      setFormError(t('اسم الطراز والرقم التسلسلي مطلوبان.', 'Model and serial number are required.'));
      return;
    }
    setSaving(true);
    try {
      const createdUnit = await api.createInstrument({
        // The register code is not sent: the server composes it from the category and the
        // number it has just issued. An identifier invented in the browser is exactly the
        // kind of value a register must never accept.
        //
        // The department *is* sent, and only because the administrator is not attached to
        // the laboratory: the page shows the shelf it is adding to, so it names that
        // department explicitly. A department-scoped principal (an analyst, a supervisor)
        // has nothing to send — the server derives the department from the principal — and
        // must not be able to name someone else's.
        department_id: units[0]?.department_id,
        category,
        manufacturer: form.manufacturer.trim() || 'SHIMADZU',
        model: form.model.trim(),
        serial_number: form.serial_number.trim(),
        part_number: form.part_number.trim() || null,
        software_version: form.software_version.trim() || null,
        calibration_freq_days: Number(form.calibration_freq_days) || 180,
        label_ar: form.label_ar.trim() || null,
        label_en: form.label_en.trim() || null,
      });
      notify(
        'success',
        t('تم تسجيل الجهاز', 'Unit registered'),
        `${createdUnit.label_en ?? createdUnit.asset_code} · ${t(
          'استنسخ الاختبارات من البروتوكول المعتمد',
          'tests inherited from the approved protocol',
        )}`,
      );
      setOpen(false);
      setRefreshing(true);
      await load();
    } catch (cause) {
      setFormError(cause instanceof ApiError ? cause.text(lang) : String(cause));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[17px] font-bold">{t('أجهزة المختبر', 'Laboratory units')}</h2>
          <p className="text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
            {t(
              `كل جهاز مسجل له أيقونته، وداخلها اختبارات البروتوكول الـ ${TESTS.length}. افتح الجهاز لتدخل اختباراً بعينه.`,
              `Every registered unit has its own tile, and inside it the ${TESTS.length} protocol tests. Open a unit to work on one test.`,
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-ghost" onClick={() => { setRefreshing(true); void load(); }} disabled={refreshing}>
            {refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {t('تحديث', 'Refresh')}
          </button>
          {canCreate && (
            <button className="btn btn-primary" onClick={openDialog}>
              <Plus size={15} /> {t('إضافة جهاز HPLC', 'Add HPLC unit')}
            </button>
          )}
        </div>
      </div>

      {error && (
        <Card>
          <p className="flex items-start gap-2 text-[12px]" style={{ color: 'var(--fail)' }}>
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {error}
          </p>
        </Card>
      )}

      {loading ? (
        <Skeleton rows={4} />
      ) : units.length === 0 ? (
        <EmptyState
          // The register is department-scoped for the bench: a QA officer sees the units of
          // its own department, which may legitimately be none while the laboratory holds
          // instruments. Saying "nothing is registered yet" would be untrue there, so the
          // empty state states the scope it is empty in.
          title={t('لا يوجد جهاز في نطاقك', 'No unit in your scope')}
          detail={t(
            'الأجهزة تُعرض في نطاق قسمك. سجّل أول جهاز HPLC؛ سيحمل الرقم 1 وتُضاف إليه اختبارات البروتوكول المعتمد.',
            'Units are listed within your own department. Register the first HPLC unit; it takes number 1 and inherits the approved protocol’s tests.',
          )}
          action={
            canCreate ? (
              <button className="btn btn-primary" onClick={openDialog}>
                <Plus size={15} /> {t('إضافة جهاز HPLC', 'Add HPLC unit')}
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {units.map((unit) => {
            const days = daysLeft(unit.next_due_date);
            const tone = dueTone(days);
            const label = (lang === 'ar' ? unit.label_ar : unit.label_en) ?? unit.label_en ?? unit.asset_code;
            return (
              <Link
                key={unit.id}
                href={`/lab/${unit.id}`}
                className="group card flex flex-col gap-2 p-3 transition-shadow hover:shadow-md"
                style={{ borderColor: 'var(--border)' }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="text-[15px] font-bold leading-tight" style={{ color: 'var(--brand)' }}>
                      {label}
                    </span>
                    <span
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-extrabold"
                      style={{
                        background: 'rgba(180,35,24,.10)',
                        color: 'var(--fail)',
                        border: '2px solid var(--fail)',
                        lineHeight: 1,
                      }}
                      aria-label={`unit ${unit.device_number}`}
                    >
                      {unit.device_number ?? '—'}
                    </span>
                  </div>
                  <ChevronLeft size={16} className="mt-1 shrink-0 opacity-40 transition-opacity group-hover:opacity-100" />
                </div>

                <p className="truncate text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
                  {unit.manufacturer} {unit.model}
                </p>
                <p className="font-mono text-[10.5px]" style={{ color: 'var(--text-muted)', direction: 'ltr' }}>
                  S/N {unit.serial_number} · {unit.asset_code}
                </p>

                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px]">
                  <span className="chip chip-quiet">
                    <CircleDot size={10} /> {TESTS.length} {t('اختباراً', 'tests')}
                  </span>
                  <span className="chip" style={{ background: 'transparent', color: tone.color, border: `1px solid ${tone.color}` }}>
                    <Clock3 size={10} />{' '}
                    {days === null
                      ? t(tone.labelAr, tone.labelEn)
                      : t(`${days} يوماً`, `${days} days`)}
                  </span>
                  {unit.status !== 'ACTIVE' && (
                    <span className="chip" style={{ background: 'rgba(180,35,24,.10)', color: 'var(--fail)' }}>
                      {unit.status}
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <Modal
        open={open}
        title={t('إضافة جهاز HPLC جديد', 'Register a new HPLC unit')}
        onClose={() => (saving ? undefined : setOpen(false))}
        width={620}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setOpen(false)} disabled={saving}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button className="btn btn-primary" onClick={() => void submit()} disabled={saving}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
              {saving ? t('جارٍ الحفظ…', 'Saving…') : t('حفظ', 'Save')}
            </button>
          </>
        }
      >
        <div className="space-y-2.5">
          <div
            className="flex items-start gap-2 rounded-lg px-3 py-2 text-[11px]"
            style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }}
          >
            <ShieldQuestion size={14} className="mt-0.5 shrink-0" />
            {t(
              'الرقم التسلسلي للجهاز (داخل الدائرة الحمراء) يعيينه الخادم ولا يُعاد استخدامه، ثم تُستنسخ له اختبارات البروتوكول المعتمد.',
              'The number in the red circle is assigned by the server and never reused; the approved protocol’s tests are then inherited by the unit.',
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[12px] font-bold">
              {t('الرقم الذي ستحمله الوحدة', 'Number the unit will carry')}
            </span>
            <span
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-extrabold"
              style={{ background: 'rgba(180,35,24,.10)', color: 'var(--fail)', border: '2px solid var(--fail)', lineHeight: 1 }}
            >
              {nextNumber}
            </span>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <Field label={t('اسم الجهاز (عربي)', 'Unit name (Arabic)')}>
              <input
                className="input"
                value={form.label_ar}
                onChange={(event) => setForm({ ...form, label_ar: event.target.value })}
                placeholder={`${shortName} (${nextNumber})`}
              />
            </Field>
            <Field label={t('اسم الجهاز (إنجليزي)', 'Unit name (English)')}>
              <input
                className="input"
                dir="ltr"
                value={form.label_en}
                onChange={(event) => setForm({ ...form, label_en: event.target.value })}
                placeholder={`${shortName} (${nextNumber})`}
              />
            </Field>
            <Field label={t('الفئة', 'Category')}>
              <input
                className="input"
                dir="ltr"
                value={category}
                onChange={(event) => setCategory(event.target.value.toUpperCase())}
                list="unit-categories"
              />
              <datalist id="unit-categories">
                {categories.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
            </Field>
            <Field label={t('الشركة المصنعة', 'Manufacturer')}>
              <input className="input" dir="ltr" value={form.manufacturer} onChange={(event) => setForm({ ...form, manufacturer: event.target.value })} />
            </Field>
            <Field label={t('الطراز', 'Model')}>
              <input className="input" dir="ltr" value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} placeholder="LC-2050C" />
            </Field>
            <Field label={t('الرقم التسلسلي', 'Serial number')}>
              <input className="input" dir="ltr" value={form.serial_number} onChange={(event) => setForm({ ...form, serial_number: event.target.value })} />
            </Field>
            <Field label={t('رقم القطعة', 'Part number')}>
              <input className="input" dir="ltr" value={form.part_number} onChange={(event) => setForm({ ...form, part_number: event.target.value })} />
            </Field>
            <Field label={t('إصدار البرنامج', 'Software version')}>
              <input className="input" dir="ltr" value={form.software_version} onChange={(event) => setForm({ ...form, software_version: event.target.value })} />
            </Field>
            <Field label={t('دورة المعايرة (يوم)', 'Calibration cycle (days)')}>
              <input
                className="input mono"
                inputMode="numeric"
                value={form.calibration_freq_days}
                onChange={(event) => setForm({ ...form, calibration_freq_days: event.target.value })}
              />
            </Field>
          </div>

          {formError && (
            <p className="rounded-lg px-3 py-2 text-[11.5px]" style={{ background: 'rgba(180,35,24,.09)', color: 'var(--fail)' }}>
              {formError}
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}
