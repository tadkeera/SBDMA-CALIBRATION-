'use client';

import { useEffect, useMemo, useState } from 'react';
import { Download, Lock, Search, ShieldCheck, ShieldX } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Metric, Skeleton, Toolbar } from '@/components/ui';
import { exportDatabase, verifyAuditChain, db } from '@/core/db/database';
import type { AuditEntry } from '@/core/types';

export default function AuditPage() {
  const { t, lang, ready, notify } = useApp();
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [chain, setChain] = useState<{ ok: boolean; brokenAt?: number; total: number } | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    if (!ready) return;
    void (async () => {
      setRows(await db().audit.orderBy('id').reverse().toArray());
      setLoading(false);
    })();
  }, [ready]);

  const filtered = useMemo(() => {
    if (!q.trim()) return rows;
    const s = q.toLowerCase();
    return rows.filter(
      (r) =>
        r.actor.toLowerCase().includes(s) ||
        r.action.toLowerCase().includes(s) ||
        r.entity.toLowerCase().includes(s) ||
        r.entityId.toLowerCase().includes(s) ||
        (r.reason ?? '').toLowerCase().includes(s),
    );
  }, [rows, q]);

  const verify = async () => {
    setVerifying(true);
    try {
      const res = await verifyAuditChain();
      setChain(res);
      notify(
        res.ok ? 'success' : 'error',
        res.ok ? t('سلسلة التدقيق سليمة', 'Audit chain intact') : t('كسر في سلسلة التدقيق', 'Audit chain broken'),
        res.ok
          ? t(`${res.total} سجلاً متصلاً ببصمات SHA-256`, `${res.total} chained SHA-256 records`)
          : t(`الكسر عند السجل ${res.brokenAt}`, `Break at record ${res.brokenAt}`),
      );
    } finally {
      setVerifying(false);
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
    notify('success', t('تم تصدير قاعدة البيانات المحلية', 'Local database exported'), undefined);
  };

  if (loading) return <Skeleton rows={10} />;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('إجمالي سجلات التدقيق', 'Total audit records')} value={rows.length} />
        <Metric
          label={t('سلامة السلسلة', 'Chain integrity')}
          value={chain ? (chain.ok ? t('سليمة', 'Intact') : t('مكسورة', 'Broken')) : '—'}
          hint={t('تحقق SHA-256 متسلسل', 'Sequential SHA-256 verification')}
          tone={chain ? (chain.ok ? 'pass' : 'fail') : 'neutral'}
        />
        <Metric label={t('سجلات معدّلة', 'Mutable records')} value={0} hint={t('السجل مُلحق فقط (Append-only)', 'Append-only by design')} tone="pass" />
        <Metric label={t('مستخدمون نشطون', 'Distinct actors')} value={new Set(rows.map((r) => r.actor)).size} />
      </div>

      <Card
        title={t('سجل التدقيق غير القابل للتعديل', 'Immutable audit trail')}
        subtitle={t('كل سجل مرتبط بالسجل السابق ببصمة SHA-256 — أي تعديل يكسر السلسلة', 'Each record is chained to its predecessor by SHA-256 — any mutation breaks the chain')}
        actions={
          <span className="chip" style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }}>
            <Lock size={11} /> ALCOA+
          </span>
        }
        dense
      >
        <div className="flex flex-wrap items-center gap-2 px-3 py-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={13} className="absolute top-2.5 ltr:left-2.5 rtl:right-2.5" style={{ color: 'var(--text-muted)' }} />
            <input
              className="input ps-8"
              placeholder={t('بحث بالمستخدم أو الإجراء أو الكيان', 'Search actor, action, entity')}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <Toolbar>
            <button className="btn btn-ghost" onClick={verify} disabled={verifying}>
              {chain?.ok ? <ShieldCheck size={14} style={{ color: 'var(--pass)' }} /> : <ShieldX size={14} />}
              {verifying ? t('جارٍ التحقق…', 'Verifying…') : t('التحقق من السلسلة', 'Verify chain')}
            </button>
            <button className="btn btn-ghost" onClick={download}>
              <Download size={14} /> {t('تصدير قاعدة البيانات', 'Export database')}
            </button>
          </Toolbar>
        </div>

        {filtered.length === 0 ? (
          <EmptyState title={t('لا توجد سجلات مطابقة', 'No matching records')} />
        ) : (
          <div className="max-h-[600px] overflow-auto">
            <table className="table">
              <thead className="sticky top-0">
                <tr>
                  <th>#</th>
                  <th>{t('الوقت', 'Timestamp')}</th>
                  <th>{t('المستخدم', 'Actor')}</th>
                  <th>{t('الدور', 'Role')}</th>
                  <th>{t('الإجراء', 'Action')}</th>
                  <th>{t('الكيان', 'Entity')}</th>
                  <th>{t('السبب', 'Reason')}</th>
                  <th>{t('البصمة', 'Hash')}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id}>
                    <td className="font-mono text-[10px]">{r.id}</td>
                    <td className="whitespace-nowrap font-mono text-[10.5px]">
                      {new Date(r.at).toLocaleString(lang === 'ar' ? 'ar-YE' : 'en-GB')}
                    </td>
                    <td className="text-[11px] font-semibold">{r.actor}</td>
                    <td className="text-[10.5px]">{r.role}</td>
                    <td>
                      <span className="chip" style={{ background: 'var(--surface-3)' }}>
                        {r.action}
                      </span>
                    </td>
                    <td className="font-mono text-[10px]">
                      {r.entity}
                      <br />
                      <span style={{ color: 'var(--text-muted)' }}>{r.entityId.slice(0, 12)}</span>
                    </td>
                    <td className="max-w-[220px] text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                      {r.reason ?? '—'}
                    </td>
                    <td className="font-mono text-[9.5px]" title={r.hash} style={{ color: 'var(--text-muted)' }}>
                      {r.hash.slice(0, 10)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
