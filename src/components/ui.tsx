'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Status } from '@/core/types';
import { useApp } from './AppProvider';

/* ---------------------------------- shell --------------------------------- */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
  dense = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  dense?: boolean;
}) {
  return (
    <section className={`card fade-in ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b px-4 py-3" style={{ borderColor: 'var(--border)' }}>
          <div className="min-w-0">
            {title && <h3 className="text-[14px] font-bold leading-tight">{title}</h3>}
            {subtitle && (
              <p className="mt-0.5 text-[11.5px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                {subtitle}
              </p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={dense ? 'p-0' : 'p-4'}>{children}</div>
    </section>
  );
}

export function StatusChip({ status, small = false }: { status: Status | string; small?: boolean }) {
  const { lang } = useApp();
  const map: Record<string, { bg: string; fg: string; ar: string; en: string }> = {
    PASS: { bg: 'rgba(22,121,79,.12)', fg: 'var(--pass)', ar: 'مطابق', en: 'PASS' },
    FAIL: { bg: 'rgba(180,35,24,.12)', fg: 'var(--fail)', ar: 'غير مطابق', en: 'FAIL' },
    UNDER_REVIEW: { bg: 'rgba(29,78,216,.12)', fg: 'var(--review)', ar: 'قيد المراجعة', en: 'UNDER REVIEW' },
    INCOMPLETE: { bg: 'rgba(181,71,8,.12)', fg: 'var(--warn)', ar: 'غير مكتمل', en: 'INCOMPLETE' },
    APPROVED: { bg: 'rgba(22,121,79,.12)', fg: 'var(--pass)', ar: 'معتمد', en: 'APPROVED' },
    UNAPPROVED: { bg: 'rgba(107,116,136,.14)', fg: 'var(--text-muted)', ar: 'غير معتمد', en: 'UNAPPROVED' },
    CONFLICT_REQUIRES_QA: { bg: 'rgba(181,71,8,.12)', fg: 'var(--warn)', ar: 'تعارض — يلزم QA', en: 'CONFLICT / QA' },
    REJECTED: { bg: 'rgba(180,35,24,.12)', fg: 'var(--fail)', ar: 'مرفوض', en: 'REJECTED' },
    ACTIVE: { bg: 'rgba(22,121,79,.12)', fg: 'var(--pass)', ar: 'قيد التشغيل', en: 'ACTIVE' },
    OUT_OF_SERVICE: { bg: 'rgba(180,35,24,.12)', fg: 'var(--fail)', ar: 'خارج الخدمة', en: 'OUT OF SERVICE' },
    UNDER_MAINTENANCE: { bg: 'rgba(181,71,8,.12)', fg: 'var(--warn)', ar: 'تحت الصيانة', en: 'MAINTENANCE' },
    OPEN: { bg: 'rgba(181,71,8,.12)', fg: 'var(--warn)', ar: 'مفتوحة', en: 'OPEN' },
    IN_PROGRESS: { bg: 'rgba(29,78,216,.12)', fg: 'var(--review)', ar: 'جارية', en: 'IN PROGRESS' },
    RESOLVED: { bg: 'rgba(22,121,79,.12)', fg: 'var(--pass)', ar: 'منجزة', en: 'RESOLVED' },
    CLOSED: { bg: 'rgba(107,116,136,.14)', fg: 'var(--text-muted)', ar: 'مغلقة', en: 'CLOSED' },
  };
  const c = map[status] ?? { bg: 'var(--surface-3)', fg: 'var(--text-muted)', ar: String(status), en: String(status) };
  return (
    <span
      className="chip"
      style={{
        background: c.bg,
        color: c.fg,
        fontSize: small ? 10 : 11,
        padding: small ? '.1rem .4rem' : undefined,
      }}
    >
      <span
        aria-hidden
        style={{ width: 6, height: 6, borderRadius: 999, background: c.fg, display: 'inline-block' }}
      />
      {lang === 'ar' ? c.ar : c.en}
    </span>
  );
}

export function Metric({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: 'pass' | 'fail' | 'warn' | 'neutral' }) {
  const color =
    tone === 'pass' ? 'var(--pass)' : tone === 'fail' ? 'var(--fail)' : tone === 'warn' ? 'var(--warn)' : 'var(--text)';
  return (
    <div className="card px-4 py-3">
      <p className="text-[11.5px] font-semibold" style={{ color: 'var(--text-muted)' }}>
        {label}
      </p>
      <p className="mt-1 text-[clamp(15px,1.55vw,21px)] font-extrabold leading-tight tabular-nums" style={{ color, wordBreak: 'break-word' }}>
        {value}
      </p>
      {hint && (
        <p className="mt-1.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {hint}
        </p>
      )}
    </div>
  );
}

export function EmptyState({ title, detail, action }: { title: string; detail?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div
        className="mb-1 flex h-12 w-12 items-center justify-center rounded-full"
        style={{ background: 'var(--surface-3)' }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.6">
          <path d="M4 7h16M4 12h10M4 17h7" strokeLinecap="round" />
        </svg>
      </div>
      <p className="text-[13px] font-bold">{title}</p>
      {detail && (
        <p className="max-w-md text-[12px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {detail}
        </p>
      )}
      {action}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skel" style={{ height: 14, width: `${90 - i * 7}%` }} />
      ))}
    </div>
  );
}

export function Toasts() {
  const { toasts, dismiss } = useApp();
  if (!toasts.length) return null;
  return (
    <div className="pointer-events-none fixed bottom-5 z-50 flex w-[340px] flex-col gap-2 ltr:right-5 rtl:left-5">
      {toasts.map((t) => {
        const color =
          t.kind === 'success' ? 'var(--pass)' : t.kind === 'error' ? 'var(--fail)' : t.kind === 'warn' ? 'var(--warn)' : 'var(--review)';
        return (
          <div
            key={t.id}
            className="pointer-events-auto card fade-in flex items-start gap-2 px-3 py-2.5"
            style={{ borderInlineStart: `3px solid ${color}` }}
            role="status"
          >
            <div className="min-w-0 flex-1">
              <p className="text-[12.5px] font-bold" style={{ color }}>
                {t.title}
              </p>
              {t.detail && (
                <p className="mt-0.5 text-[11.5px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                  {t.detail}
                </p>
              )}
            </div>
            <button onClick={() => dismiss(t.id)} className="text-[15px] leading-none" style={{ color: 'var(--text-muted)' }} aria-label="إغلاق">
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------- modal / dialog ---------------------------- */

export function Modal({
  open,
  title,
  children,
  onClose,
  footer,
  width = 720,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  width?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/45 p-4 pt-10" onClick={onClose}>
      <div
        ref={ref}
        className="card w-full fade-in"
        style={{ maxWidth: width, boxShadow: 'var(--tw-shadow-pop, 0 12px 32px rgba(16,24,40,.14))' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="flex items-center justify-between border-b px-4 py-3" style={{ borderColor: 'var(--border)' }}>
          <h3 className="text-[14px] font-bold">{title}</h3>
          <button onClick={onClose} className="btn btn-ghost px-2 py-1 text-[15px]" aria-label="إغلاق">
            ×
          </button>
        </header>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && (
          <footer className="flex items-center justify-end gap-2 border-t px-4 py-3" style={{ borderColor: 'var(--border)' }}>
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

/** 21 CFR Part 11 style signature gate — reason is mandatory. */
export function SignatureDialog({
  open,
  title,
  description,
  onClose,
  onConfirm,
  busy,
}: {
  open: boolean;
  title: string;
  description: string;
  onClose: () => void;
  onConfirm: (reason: string, password: string) => void;
  busy?: boolean;
}) {
  const { t } = useApp();
  const [reason, setReason] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setReason('');
      setPassword('');
      setErr(null);
    }
  }, [open]);

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      width={560}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
            {t('إلغاء', 'Cancel')}
          </button>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => {
              if (reason.trim().length < 8) {
                setErr(t('سبب التوقيع مطلوب ولا يقل عن 8 أحرف (ALCOA+).', 'A reason of at least 8 characters is required (ALCOA+).'));
                return;
              }
              if (password.length < 4) {
                setErr(t('يلزم تأكيد كلمة المرور للتوقيع الإلكتروني.', 'Password confirmation is required for the e-signature.'));
                return;
              }
              onConfirm(reason.trim(), password);
            }}
          >
            {busy ? t('جارٍ التوقيع…', 'Signing…') : t('توقيع واعتماد', 'Sign & approve')}
          </button>
        </>
      }
    >
      <p className="mb-3 text-[12px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        {description}
      </p>
      <label className="label">{t('سبب الإجراء (إلزامي)', 'Reason for action (mandatory)')}</label>
      <textarea
        className="textarea mb-3"
        rows={3}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={t('مثال: مراجعة نتائج المعايرة النصف سنوية لجهاز HPLC بعد استكمال جميع القراءات الخام', 'e.g. Semi-annual review of HPLC calibration after completing all raw data')}
      />
      <label className="label">{t('تأكيد كلمة المرور', 'Confirm password')}</label>
      <input className="input mono" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
      <p className="mt-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
        {t(
          'يُسجَّل التوقيع مع اسمك ودورك وختم زمني وبصمة SHA-256 في سجل تدقيق غير قابل للتعديل.',
          'The signature is recorded with your name, role, timestamp and SHA-256 hash in an immutable audit trail.',
        )}
      </p>
      {err && (
        <p className="mt-2 text-[11.5px] font-semibold" style={{ color: 'var(--fail)' }}>
          {err}
        </p>
      )}
    </Modal>
  );
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && (
        <p className="mt-1 text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
          {hint}
        </p>
      )}
    </div>
  );
}
