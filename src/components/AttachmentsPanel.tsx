'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Download, FileCheck2, Paperclip, ShieldCheck, Upload } from 'lucide-react';
import { ApiError, OfflineError, api, downloadReport, type ServerAttachment } from '@/core/api/client';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Field, Skeleton } from '@/components/ui';

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * Evidence attachments for one instrument.
 *
 * The platform never lets the browser decide what a file's checksum is: the
 * server hashes the bytes it actually received, re-reads them from disk, and
 * records that. This panel therefore shows the hash it was *given* and offers a
 * verified download that re-checks it — it never computes or asserts a hash of
 * its own, because a client-side hash would be a claim, not evidence.
 */
export function AttachmentsPanel({
  instrumentId,
  instrumentLabel,
}: {
  instrumentId: string;
  instrumentLabel?: string;
}) {
  const { t, lang, notify, can, ready } = useApp();
  const [rows, setRows] = useState<ServerAttachment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [supersedes, setSupersedes] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const canManage = can('attachments.manage');

  const load = useCallback(async () => {
    if (!instrumentId) return;
    try {
      setRows(await api.attachments(instrumentId));
      setError(null);
    } catch (e) {
      setRows([]);
      setError(
        e instanceof ApiError ? e.text(lang) : e instanceof OfflineError
          ? t('غير متصل بالخادم — المرفقات تحتاج اتصالاً', 'Server unreachable — attachments need a connection')
          : String(e),
      );
    }
  }, [instrumentId, lang, t]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  const upload = async () => {
    if (!file) {
      notify('warn', t('اختر ملفاً أولاً', 'Choose a file first'));
      return;
    }
    if (description.trim().length < 8) {
      notify('warn', t('سبب الإرفاق مطلوب (8 أحرف على الأقل)', 'A reason of 8+ characters is required'));
      return;
    }
    setBusy(true);
    try {
      const saved = await api.uploadAttachment(instrumentId, file, description.trim(), supersedes || null);
      notify(
        'success',
        t('تم إرفاق الدليل وبصمته محفوظة', 'Evidence filed with its checksum'),
        `${saved.file_name} · SHA-256 ${saved.sha256_checksum.slice(0, 16)}…`,
      );
      setFile(null);
      setDescription('');
      setSupersedes('');
      await load();
    } catch (e) {
      notify(
        'error',
        t('تعذر إرفاق الملف', 'The file could not be filed'),
        e instanceof ApiError ? e.text(lang) : String(e),
      );
    } finally {
      setBusy(false);
    }
  };

  const download = (row: ServerAttachment) =>
    downloadReport(row.download_url.replace('/api/v1', ''), row.file_name).catch((e: unknown) =>
      notify(
        'error',
        t('تعذر تنزيل المرفق', 'Attachment download failed'),
        e instanceof ApiError ? e.text(lang) : String(e),
      ),
    );

  return (
    <Card
      title={t('المرفقات والأدلة المخبرية', 'Evidence attachments')}
      subtitle={
        instrumentLabel
          ? t(`${instrumentLabel} — كل ملف يُخزَّن ببصمة SHA-256 ولا يُعدَّل أو يُحذف`, `${instrumentLabel} — every file is stored under its SHA-256 and can never be edited or deleted`)
          : t('كل ملف يُخزَّن ببصمة SHA-256 ولا يُعدَّل أو يُحذف', 'Every file is stored under its SHA-256 and can never be edited or deleted')
      }
      actions={
        <span className="chip" style={{ background: 'var(--surface-3)' }}>
          <ShieldCheck size={11} /> ALCOA+ · {rows?.length ?? 0}
        </span>
      }
    >
      {rows === null ? (
        <Skeleton rows={3} />
      ) : (
        <div className="space-y-3">
          {error && (
            <p className="flex items-start gap-1.5 rounded-lg px-2.5 py-2 text-[11px]" style={{ background: 'rgba(180,35,24,.08)', color: 'var(--fail)' }}>
              <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
            </p>
          )}

          {rows.length === 0 ? (
            <EmptyState
              title={t('لا توجد مرفقات لهذا الجهاز', 'No evidence filed for this instrument')}
              detail={t('أرفق مخططاً كروماتوغرافياً أو تقرير معايرة أو صورة شاشة الجهاز.', 'File a chromatogram, a calibration report, or a photograph of the instrument display.')}
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {rows.map((row) => (
                <li key={row.id} className="flex flex-wrap items-start justify-between gap-2 px-1 py-2">
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 truncate text-[11.5px] font-bold">
                      <Paperclip size={12} /> {row.file_name}
                      {row.supersedes_id && (
                        <span className="chip" style={{ background: 'rgba(29,78,216,.12)', color: 'var(--review)' }}>
                          {t('يُحل محل مرفق سابق', 'supersedes')}
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                      {row.description_ar ?? '—'} · {humanSize(row.size_bytes)} ·{' '}
                      {new Date(row.created_at).toLocaleDateString(lang === 'ar' ? 'ar-YE' : 'en-GB')}
                    </p>
                    <p
                      className="mt-0.5 break-all font-mono text-[9.5px]"
                      style={{ color: 'var(--text-muted)', direction: 'ltr' }}
                      title={row.sha256_checksum}
                    >
                      SHA-256 {row.sha256_checksum}
                    </p>
                  </div>
                  <button className="btn btn-ghost px-2 py-1 text-[10.5px]" onClick={() => void download(row)}>
                    <Download size={12} /> {t('تنزيل موثّق', 'Verified download')}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {canManage ? (
            <div className="rounded-lg p-2.5" style={{ background: 'var(--surface-2)' }}>
              <div className="grid gap-2 sm:grid-cols-2">
                <Field label={t('الملف', 'File')} hint={t('PDF · XLSX · CSV · PNG · JPG · TXT · حتى 25 ميجابايت', 'PDF · XLSX · CSV · PNG · JPG · TXT · up to 25 MB')}>
                  <input
                    type="file"
                    className="input py-1 text-[11px]"
                    accept=".pdf,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg,.tif,.zip"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </Field>
                <Field label={t('المرفق السابق (اختياري)', 'Supersedes (optional)')} hint={t('التصحيح مرفق جديد، لا تعديل للسابق', 'A correction is a new attachment, never an edit')}>
                  <select className="select py-1 text-[11px]" value={supersedes} onChange={(e) => setSupersedes(e.target.value)}>
                    <option value="">{t('— لا شيء —', '— none —')}</option>
                    {rows.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.file_name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="mt-2">
                <Field label={t('سبب الإرفاق (إلزامي)', 'Reason for filing (required)')} hint={t('8 أحرف على الأقل — يُسجَّل في سلسلة التدقيق', '8+ characters — written to the audit chain')}>
                  <textarea
                    className="input min-h-[54px] py-1 text-[11px]"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t('مثال: مخطط كروماتوغرافي لاختبار التكرارية مأخوذ من LabSolutions', 'e.g. chromatogram for the repeatability test exported from LabSolutions')}
                  />
                </Field>
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <p className="flex items-center gap-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  <FileCheck2 size={11} /> {t('تُحسب البصمة على الخادم ويُعاد التحقق منها بعد الكتابة', 'The hash is computed server-side and re-verified after writing')}
                </p>
                <button className="btn btn-primary px-3 py-1.5 text-[11px]" disabled={busy} onClick={() => void upload()}>
                  <Upload size={12} /> {busy ? t('جارٍ الإرفاق…', 'Filing…') : t('إرفاق الدليل', 'File evidence')}
                </button>
              </div>
            </div>
          ) : (
            <p className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
              {t('الإرفاق متاح لأدوار التحليل والصيانة والإدارة.', 'Filing is limited to analyst, engineering service and admin roles.')}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
