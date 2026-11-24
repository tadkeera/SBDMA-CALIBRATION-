'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, Lock, Search, ShieldCheck, ShieldX } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Metric, Skeleton, Toolbar } from '@/components/ui';
import { exportDatabase, db } from '@/core/db/database';
import { SOURCE_LABEL } from '@/core/api/mode';
import type { AuditEntry } from '@/core/types';
import { ApiError, api, downloadReport } from '@/core/api/client';

const PAGE_SIZE = 100;

export default function AuditPage() {
  const { t, lang, ready, notify, can, source, setSource } = useApp();
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [chain, setChain] = useState<{ ok: boolean; brokenAt?: number | string | null; total: number } | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [serverTotal, setServerTotal] = useState<number | null>(null);
  const [page, setPage] = useState(1);

  const load = useCallback(
    async (pageNo: number) => {
      try {
        const data = await api.audit({ page: pageNo, page_size: PAGE_SIZE });
        setRows(
          data.map((r) => ({
            id: r.id as unknown as number,
            at: r.at,
            actor: r.actor_label,
            role: (r.role_label ?? '') as AuditEntry['role'],
            action: r.action,
            entity: r.entity_type,
            entityId: r.entity_id,
            reason: r.reason ?? undefined,
            hash: r.hash,
            prevHash: r.prev_hash,
            module: 'server',
          })),
        );
        setServerTotal(data.length === PAGE_SIZE ? (pageNo * PAGE_SIZE) + 1 : (pageNo - 1) * PAGE_SIZE + data.length);
        setSource({ source: 'server', at: new Date().toISOString() });
      } catch (error) {
        // the server trail is the authority; the local chain is only a fallback view
        const cached = await db().audit.orderBy('id').reverse().toArray();
        setRows(cached);
        setServerTotal(null);
        setSource({ source: 'cache', at: new Date().toISOString() });
        notify(
          'warn',
          t('تُعرض سلسلة المتصفح المحلية', 'Showing the browser-local chain'),
          error instanceof ApiError ? error.text(lang) : String(error),
        );
      } finally {
        setLoading(false);
      }
    },
    [lang, notify, setSource, t],
  );

  useEffect(() => {
    if (!ready) return;
    void load(page);
  }, [ready, page, load]);

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

  /** Server-side chain verification: recomputes every hash from the stored rows. */
  const verify = async () => {
    setVerifying(true);
    try {
      const res = await api.verifyAudit();
      setChain({ ok: res.ok, brokenAt: res.broken_at ?? null, total: res.total });
      notify(
        res.ok ? 'success' : 'error',
        res.ok ? t('سلسلة التدقيق سليمة', 'Audit chain intact') : t('كسر في سلسلة التدقيق', 'Audit chain broken'),
        res.ok
          ? t(`${res.total} سجلاً متصلاً ببصمات SHA-256 · الرأس ${res.head.slice(0, 12)}…`, `${res.total} chained SHA-256 records · head ${res.head.slice(0, 12)}…`)
          : t(`الكسر عند ${res.broken_at ?? '—'}`, `Break at ${res.broken_at ?? '—'}`),
      );
    } catch (error) {
      notify('error', t('تعذر التحقق', 'Verification failed'), error instanceof ApiError ? error.text(lang) : String(error));
    } finally {
      setVerifying(false);
    }
  };

  /** Excel export straight from PostgreSQL — not from the browser cache. */
  const downloadExcel = async () => {
    try {
      await downloadReport('/reports/audit.xlsx', 'SBDMA-audit-trail.xlsx');
      notify('success', t('تم تصدير سجل التدقيق من الخادم', 'Audit trail exported from the server'), undefined);
    } catch (error) {
      notify('error', t('تعذر التصدير', 'Export failed'), error instanceof ApiError ? error.text(lang) : String(error));
    }
  };

  const downloadLocalDump = async () => {
    const dump = await exportDatabase();
    const blob = new Blob([dump], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sbdma-local-cache-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    notify('info', t('تم تصدير نسخة المتصفح المحلية', 'Browser cache exported'), undefined);
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
            <button className="btn btn-ghost" onClick={downloadExcel} disabled={!can('audit.view')}>
              <Download size={14} /> {t('تصدير Excel', 'Export Excel')}
            </button>
            <button className="btn btn-ghost" onClick={downloadLocalDump}>
              <Download size={14} /> {t('نسخة المتصفح', 'Browser copy')}
            </button>
            {serverTotal !== null && (
              <div className="flex items-center gap-1">
                <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
                  ‹
                </button>
                <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {t('صفحة', 'Page')} {page}
                </span>
                <button
                  className="btn btn-ghost px-2 py-1 text-[11px]"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={rows.length < PAGE_SIZE}
                >
                  ›
                </button>
              </div>
            )}
            {source && (
              <span className="chip" style={{ background: 'var(--surface-3)', color: 'var(--text-muted)' }}>
                {SOURCE_LABEL[source.source][lang]}
              </span>
            )}
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
