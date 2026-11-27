'use client';

/**
 * One unit's shelf of tests.
 *
 * Opening **HPLC (2)** shows that unit's twenty tests as tiles, one per test, each
 * carrying its code, its name and — when the unit has been measured today — the verdict
 * of its most recent result. The list is read from the *approved protocol on the server*,
 * so a test disabled by QA in the Control Center is not offered here, and a test added to
 * the protocol appears without a frontend release. The tile is a link, not a form: the
 * entry of readings happens on the test's own page, where the acceptance comparison and
 * the charts live.
 *
 * Unit numbering is the laboratory's: every unit of the same category is entitled to the
 * same twenty tests because the tests belong to the protocol, not to the unit. What a unit
 * owns is its own runs and its own certificates.
 */

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, ChevronLeft, ClipboardList, Loader2, Search, ShieldCheck } from 'lucide-react';

import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, StatusChip } from '@/components/ui';
import { ApiError, api, type ServerInstrument, type ServerRunSummary } from '@/core/api/client';
import { TESTS } from '@/core/protocol';

export default function UnitPage() {
  const { t, lang, can } = useApp();
  // The shelf is readable by QA and the administrators, but the readings and the run stay
  // with the bench — the page says so instead of leaving a visitor to discover it by
  // pressing a disabled button.
  const readOnly = !can('calibration.run');
  const routeParams = useParams<{ unitId: string }>();
  const params = { unitId: String(routeParams?.unitId ?? '') };
  const [unit, setUnit] = useState<ServerInstrument | null>(null);
  const [disabled, setDisabled] = useState<string[]>([]);
  const [latest, setLatest] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    setError(null);
    try {
      const [units, statuses, runs] = await Promise.all([
        api.instruments(),
        api.testStatuses().catch(() => ({ items: [], can_manage: false, protocol_code: '', enabled: 0, total: 0 })),
        api.runs({ page: 1, page_size: 25 }).catch(() => [] as ServerRunSummary[]),
      ]);
      const found = units.find((row) => row.id === params.unitId) ?? null;
      setUnit(found);
      setDisabled(statuses.items.filter((item) => !item.is_active).map((item) => item.test_code));

      // The chip on a tile is the verdict of the unit's most recent *executed* run that
      // contains the test. It is a convenience, not a record: the authoritative status
      // lives on the run itself, which the tile opens.
      const verdicts = new Map<string, string>();
      for (const run of runs.filter((row) => row.instrument_id === params.unitId)) {
        try {
          const detail = await api.run(run.id);
          for (const result of detail.results) {
            if (!verdicts.has(result.test_code) && result.status !== 'INCOMPLETE') {
              verdicts.set(result.test_code, result.status);
            }
          }
        } catch {
          /* one unreadable run must not hide the shelf */
        }
      }
      setLatest(verdicts);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.text(lang)
          : t('تعذر تحميل اختبارات الجهاز.', 'The unit’s tests could not be loaded.'),
      );
    } finally {
      setLoading(false);
    }
  }, [params.unitId, lang, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const enabled = TESTS.filter((test) => !disabled.includes(test.code));
    const needle = query.trim().toLowerCase();
    if (!needle) return enabled;
    return enabled.filter(
      (test) =>
        test.code.toLowerCase().includes(needle) ||
        test.nameEn.toLowerCase().includes(needle) ||
        test.nameAr.includes(query.trim()),
    );
  }, [disabled, query]);

  const label = unit ? ((lang === 'ar' ? unit.label_ar : unit.label_en) ?? unit.asset_code) : '';

  if (loading) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-[13px]" style={{ color: 'var(--text-muted)' }}>
          <Loader2 size={16} className="animate-spin" /> {t('جارٍ تحميل اختبارات الجهاز…', 'Loading the unit’s tests…')}
        </div>
      </Card>
    );
  }

  if (error || !unit) {
    return (
      <Card title={t('تعذر فتح الجهاز', 'The unit could not be opened')}>
        <p className="text-[12.5px]" style={{ color: 'var(--fail)' }}>
          {error ?? t('الجهاز غير موجود أو خارج نطاق صلاحيتك.', 'The unit does not exist or is outside your scope.')}
        </p>
        <Link href="/lab/units" className="btn btn-ghost mt-3">
          <ArrowLeft size={15} /> {t('أجهزة المختبر', 'Laboratory units')}
        </Link>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Link href="/lab/units" className="btn btn-ghost px-2 py-1" title={t('أجهزة المختبر', 'Laboratory units')}>
            <ArrowLeft size={15} />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[17px] font-bold">{label}</h2>
              <span
                className="inline-flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-extrabold"
                style={{
                  background: 'rgba(180,35,24,.10)',
                  color: 'var(--fail)',
                  border: '2px solid var(--fail)',
                  lineHeight: 1,
                }}
              >
                {unit.device_number ?? '—'}
              </span>
            </div>
            <p className="text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
              {unit.manufacturer} {unit.model} · S/N {unit.serial_number} · {unit.asset_code}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute start-2 top-2 opacity-50" />
            <input
              className="input ps-7 text-[11.5px]"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('بحث في الاختبارات', 'Search tests')}
            />
          </div>
          <span
            className="chip chip-quiet"
            data-testid="test-count"
            aria-label={t('عدد الاختبارات الظاهرة', 'tests shown')}
          >
            <ClipboardList size={11} /> {visible.length} / {TESTS.length}
          </span>
        </div>
      </div>

      <div
        className="flex items-start gap-2 rounded-lg px-3 py-2 text-[11px]"
        style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
      >
        <ShieldCheck size={13} className="mt-0.5 shrink-0" />
        {readOnly
          ? t(
              'أنت تفتح الوحدة للقراءة فقط: الاختبارات العشرون وحدودها ونتائجها ظاهرة، وإدخال القراءات وتشغيل المعايرة من عمل المنضدة (محلل/مشرف).',
              'You are opening this unit read-only: the twenty tests, their limits and their results are visible, while entering readings and running the calibration belong to the bench (analyst/supervisor).',
            )
          : t(
              'الاختبارات والعناوين والحدود تأتي من البروتوكول المعتمد؛ الحساب يجري على الخادم بعد «تشغيل المعايرة»، والحفظ يسجّل تشغيلاً لهذه الوحدة وحده.',
              'Tests, wording and limits come from the approved protocol; the calculation runs on the server when you press Run Calibration, and Save records a run for this unit alone.',
            )}
      </div>

      {visible.length === 0 ? (
        <EmptyState
          title={t('لا يوجد اختبار مطابق', 'No test matches')}
          detail={t('امسح خانة البحث أو تحقق من الاختبارات المعطلة في الإدارة المركزية.', 'Clear the search, or check the disabled tests in the Control Center.')}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((test) => {
            const verdict = latest.get(test.code);
            return (
              <Link
                key={test.code}
                href={`/lab/${unit.id}/${test.code}`}
                className="group card flex flex-col gap-1.5 p-3 transition-shadow hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-2">
                  <span
                    className="rounded-lg px-2 py-1 font-mono text-[11px] font-bold"
                    style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }}
                  >
                    {test.code}
                  </span>
                  <div className="flex items-center gap-1">
                    {verdict ? <StatusChip status={verdict} small /> : null}
                    <ChevronLeft size={15} className="opacity-40 transition-opacity group-hover:opacity-100" />
                  </div>
                </div>
                <p className="text-[12.5px] font-semibold leading-snug">
                  {lang === 'ar' ? test.nameAr : test.nameEn}
                </p>
                <p className="truncate text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                  {test.standard}
                </p>
                <div className="mt-0.5 flex flex-wrap gap-1 text-[10px]">
                  <span className="chip chip-quiet">{test.module}</span>
                  <span className="chip chip-quiet">
                    {test.fields.length} {t('حقول', 'fields')}
                  </span>
                  <span className="chip chip-quiet">
                    {test.metrics.length} {t('حدود', 'limits')}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {disabled.length > 0 && (
        <p className="flex items-center gap-1.5 text-[10.5px]" style={{ color: 'var(--warn)' }}>
          <AlertTriangle size={12} />
          {t(
            `${disabled.length} اختباراً معطّلاً في الإدارة المركزية ولا يظهر في القائمة، والخادم يرفض تنفيذه.`,
            `${disabled.length} test(s) are disabled in the Control Center, are hidden here, and are refused by the server.`,
          )}
        </p>
      )}
    </div>
  );
}
