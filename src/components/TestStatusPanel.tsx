'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, Power, Search } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Modal, Skeleton, Toolbar } from '@/components/ui';
import { ApiError, api, type ServerTestStatus } from '@/core/api/client';

/**
 * Enable / disable the twenty tests of the protocol.
 *
 * Three rules drive this screen:
 *
 * 1. **The server decides.** `can_manage` comes from the API, computed from the
 *    caller's permissions; the switch is disabled when it is false, but the PATCH is
 *    also refused server-side, so hiding the button is not the control.
 * 2. **A reason is mandatory.** Disabling a test removes it from what the laboratory
 *    may execute, which is a governance change; the audit trail stores who, what and
 *    why, in the same transaction.
 * 3. **No optimism.** The row is updated from the server's answer after the PATCH
 *    returns, and shows a spinner while it is in flight — a switch that flips before
 *    the server agrees is a lie the analyst only discovers later.
 */
export function TestStatusPanel() {
  const { t, lang, notify } = useApp();
  const [items, setItems] = useState<ServerTestStatus[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState<{ item: ServerTestStatus; next: boolean } | null>(null);
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const answer = await api.testStatuses();
      setItems(answer.items);
      setCanManage(answer.can_manage);
    } catch (err) {
      setError(err instanceof ApiError ? err.text(lang) : t('تعذر تحميل حالة الاختبارات', 'Test statuses could not be loaded'));
    } finally {
      setLoading(false);
    }
  }, [lang, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.test_code.toLowerCase().includes(q) ||
        item.name_en.toLowerCase().includes(q) ||
        item.name_ar.includes(query.trim()) ||
        item.module.toLowerCase().includes(q) ||
        item.standard_ref.toLowerCase().includes(q),
    );
  }, [items, query]);

  const enabled = items.filter((i) => i.is_active).length;

  const open = (item: ServerTestStatus) => {
    setPending({ item, next: !item.is_active });
    setReason(
      item.is_active
        ? ''
        : t('إعادة التفعيل بعد استكمال الإجراء التصحيحي', 'Re-enabled after the corrective action was completed'),
    );
  };

  const submit = async () => {
    if (!pending) return;
    const { item, next } = pending;
    setBusyCode(item.test_code);
    try {
      const result = await api.setTestStatus(item.test_code, next, reason.trim());
      setItems((prev) =>
        prev.map((row) =>
          row.test_code === item.test_code ? { ...row, is_active: result.is_active } : row,
        ),
      );
      notify(
        result.is_active ? 'success' : 'warn',
        result.is_active
          ? t(`تم تفعيل ${result.test_code}`, `${result.test_code} enabled`)
          : t(`تم تعطيل ${result.test_code}`, `${result.test_code} disabled`),
        t('سُجّل التغيير في سجل التدقيق', 'Change recorded in the audit trail'),
      );
      setPending(null);
    } catch (err) {
      notify(
        'error',
        t('لم يتم تغيير الحالة', 'Status not changed'),
        err instanceof ApiError ? err.text(lang) : String(err),
      );
    } finally {
      setBusyCode(null);
    }
  };

  if (loading) return <Skeleton rows={8} />;

  return (
    <div className="space-y-3">
      {error && (
        <Card title={t('تعذر التحميل', 'Could not load')}>
          <p className="text-[12px]" style={{ color: 'var(--fail)' }}>
            {error}
          </p>
          <button className="btn btn-ghost mt-2" onClick={() => void load()}>
            {t('إعادة المحاولة', 'Retry')}
          </button>
        </Card>
      )}

      <Card
        title={t('تفعيل وتعطيل الاختبارات', 'Enable and disable tests')}
        subtitle={t(
          `الاختبار المعطّل يختفي من شاشة المختبر ويُرفض تنفيذه على الخادم — ${enabled} من ${items.length} مفعّل`,
          `A disabled test disappears from the laboratory screen and is refused by the server — ${enabled} of ${items.length} enabled`,
        )}
        actions={
          <Toolbar>
            <div className="relative">
              <Search size={13} className="absolute top-1/2 -translate-y-1/2 opacity-60" style={{ insetInlineStart: 8 }} />
              <input
                className="input w-56 py-1 ps-7 text-[11.5px]"
                placeholder={t('بحث بالرمز أو الاسم أو المرجع', 'Search code, name or standard')}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <button className="btn btn-ghost" onClick={() => void load()}>
              {t('تحديث', 'Refresh')}
            </button>
          </Toolbar>
        }
        dense
      >
        {!canManage && (
          <div
            className="flex items-start gap-2 border-b px-4 py-2 text-[11.5px]"
            style={{ borderColor: 'var(--border)', background: 'rgba(154,106,18,.08)', color: 'var(--warn, #9a6a12)' }}
          >
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {t(
              'تغيير حالة الاختبار يتطلب صلاحية tests.manage_status — العرض فقط متاح لدورك.',
              'Changing a test status requires the tests.manage_status permission — your role can only review.',
            )}
          </div>
        )}
        {filtered.length === 0 ? (
          <EmptyState title={t('لا نتائج مطابقة', 'No matching test')} detail={query} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 44 }}>#</th>
                  <th>{t('الاختبار', 'Test')}</th>
                  <th>{t('الوحدة', 'Module')}</th>
                  <th>{t('الحدود', 'Limits')}</th>
                  <th>{t('الحالة', 'Status')}</th>
                  <th style={{ width: 120 }}>{t('التحكم', 'Control')}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.test_code} style={item.is_active ? undefined : { background: 'rgba(180,35,24,.05)' }}>
                    <td className="font-mono text-[11px] font-bold">{item.test_code}</td>
                    <td>
                      <div className="text-[11.5px] font-semibold">{lang === 'ar' ? item.name_ar : item.name_en}</div>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        {item.standard_ref}
                      </div>
                    </td>
                    <td>
                      <span className="chip" style={{ background: 'var(--surface-3)' }}>
                        {item.module}
                      </span>
                    </td>
                    <td className="font-mono text-[10.5px]">{item.limits_count}</td>
                    <td>
                      <span
                        className="chip"
                        style={
                          item.is_active
                            ? { background: 'rgba(22,121,79,.12)', color: 'var(--pass)' }
                            : { background: 'rgba(180,35,24,.12)', color: 'var(--fail)' }
                        }
                      >
                        {item.is_active ? (
                          <>
                            <CheckCircle2 size={11} /> {t('مفعّل', 'Enabled')}
                          </>
                        ) : (
                          <>
                            <AlertTriangle size={11} /> {t('معطّل', 'Disabled')}
                          </>
                        )}
                      </span>
                    </td>
                    <td>
                      {/* dir="ltr" pins the knob to a physical side: a switch that
                          slides one way in Arabic and the other in English reads as a
                          different control. */}
                      <button
                        role="switch"
                        dir="ltr"
                        aria-checked={item.is_active}
                        aria-label={`${item.test_code} — ${item.is_active ? 'enabled' : 'disabled'}`}
                        disabled={!canManage || busyCode === item.test_code}
                        onClick={() => open(item)}
                        className="inline-flex h-5 w-9 items-center rounded-full px-0.5 transition-colors disabled:opacity-40"
                        style={{ background: item.is_active ? 'var(--pass)' : 'var(--border)' }}
                        title={
                          canManage
                            ? t('تغيير حالة الاختبار', 'Change this test status')
                            : t('صلاحية غير كافية', 'Insufficient permission')
                        }
                      >
                        <span
                          className="block h-4 w-4 shrink-0 rounded-full bg-white shadow transition-transform"
                          style={{ transform: item.is_active ? 'translateX(16px)' : 'translateX(0)' }}
                        />
                        {busyCode === item.test_code && (
                          <Loader2 size={11} className="ms-2 animate-spin" />
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={pending !== null}
        title={
          pending?.next
            ? t(`تفعيل ${pending?.item.test_code}`, `Enable ${pending?.item.test_code}`)
            : t(`تعطيل ${pending?.item.test_code}`, `Disable ${pending?.item.test_code}`)
        }
        onClose={() => setPending(null)}
        width={560}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setPending(null)} disabled={busyCode !== null}>
              {t('إلغاء', 'Cancel')}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => void submit()}
              disabled={busyCode !== null || reason.trim().length < 8}
            >
              {busyCode ? <Loader2 size={13} className="animate-spin" /> : <Power size={13} />}
              {pending?.next ? t('تفعيل', 'Enable') : t('تعطيل', 'Disable')}
            </button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-[12px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {pending?.next
              ? t(
                  'سيعود الاختبار إلى شاشة المختبر ويصبح تنفيذه مسموحاً.',
                  'The test returns to the laboratory screen and may be executed again.',
                )
              : t(
                  'سيزول الاختبار من شاشة المختبر، وسيرفض الخادم تنفيذه حتى لو أُرسل رمزه مباشرة. التشغيلات السابقة لا تتأثر.',
                  'The test disappears from the laboratory screen and the server refuses to execute it even if its code is posted directly. Past runs are unaffected.',
                )}
          </p>
          <label className="block">
            <span className="mb-1 block text-[11px] font-bold">
              {t('السبب (إلزامي، 8 أحرف على الأقل)', 'Reason (mandatory, at least 8 characters)')}
            </span>
            <textarea
              className="input h-20 w-full py-2 text-[12px]"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t(
                'مثال: عطل في حساس التسريب — الجهاز تحت الإصلاح',
                'Example: leak sensor faulty — instrument under repair',
              )}
            />
          </label>
          <p className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
            {t(
              'يُسجَّل التغيير مع القيمة قبل وبعد وسبب التغيير في سلسلة التدقيق.',
              'The change is written to the hash-chained audit together with the before/after value and this reason.',
            )}
          </p>
        </div>
      </Modal>
    </div>
  );
}
