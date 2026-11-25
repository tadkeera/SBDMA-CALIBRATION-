'use client';

import { useCallback, useEffect, useState } from 'react';
import { Copy, KeyRound, QrCode, ShieldCheck, ShieldAlert, Check } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Field } from '@/components/ui';
import { ApiError, API_BASE, api } from '@/core/api/client';

/**
 * Second-factor enrolment (21 CFR Part 11.200(a)(1)(i)).
 *
 * Shown in two situations: when a role mandates a factor and the account has
 * none, and voluntarily from the account page. The secret is displayed once —
 * there is no "show me again", because the server only stores its ciphertext.
 */
export function MfaEnrolment() {
  const { t, lang, session, signOut, notify } = useApp();
  const [secret, setSecret] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const begin = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.mfaEnrol();
      setSecret(result.secret);
    } catch (err) {
      setError(err instanceof ApiError ? err.text(lang) : String(err));
    } finally {
      setBusy(false);
    }
  }, [lang]);

  useEffect(() => {
    void begin();
  }, [begin]);

  const activate = async () => {
    if (!/^\d{6}$/.test(value)) {
      setError(t('الرمز ستة أرقام.', 'The code is six digits.'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.mfaActivate(value);
      setCodes(result.recovery_codes);
      notify('success', t('فُعّل التحقق بخطوتين', 'Two-step verification is active'));
    } catch (err) {
      setError(err instanceof ApiError ? err.text(lang) : String(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard access can be denied; the value is visible anyway */
    }
  };

  // ── recovery codes: shown once, after activation ──────────────────────────
  if (codes) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-lg space-y-4 rounded-xl border p-6" style={{ background: 'var(--surface)' }}>
          <div className="flex items-center gap-2">
            <ShieldCheck size={20} style={{ color: 'var(--pass)' }} />
            <h1 className="text-[15px] font-bold">{t('أكواد الاسترداد', 'Recovery codes')}</h1>
          </div>
          <p className="text-[11.5px] leading-5" style={{ color: 'var(--text-muted)' }}>
            {t(
              'اطبع هذه الأكواد واحفظها في مكان آمن. كل كود يُستخدم مرة واحدة، وهي الطريقة الوحيدة للدخول إذا فقدت الهاتف. لن تُعرض مرة أخرى.',
              'Print these codes and keep them somewhere safe. Each works once, and they are the only way in if you lose your phone. They will not be shown again.',
            )}
          </p>
          <div className="grid grid-cols-2 gap-2 rounded-lg p-3" style={{ background: 'var(--surface-2)' }}>
            {codes.map((code) => (
              <code key={code} className="font-mono text-[12.5px] tracking-wider">
                {code}
              </code>
            ))}
          </div>
          <button className="btn btn-primary w-full justify-center" onClick={() => window.print()}>
            {t('طباعة', 'Print')}
          </button>
          <button className="btn w-full justify-center" onClick={() => void signOut()}>
            {t('تم — سجّل الدخول من جديد', 'Done — sign in again')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4 rounded-xl border p-6" style={{ background: 'var(--surface)' }}>
        <div className="flex items-center gap-2">
          <ShieldAlert size={20} style={{ color: 'var(--warn)' }} />
          <h1 className="text-[15px] font-bold">{t('التحقق بخطوتين', 'Two-step verification')}</h1>
        </div>

        <p className="text-[11.5px] leading-5" style={{ color: 'var(--text-muted)' }}>
          {t(
            'دورك يتطلب مكوّني تحقق متميزين قبل توقيع أي سجل (21 CFR Part 11). امسح الرمز بتطبيق مصادقة، ثم أدخل الرمز الظاهر لإتمام التسجيل.',
            'Your role requires two distinct identification components before signing any record (21 CFR Part 11). Scan the code with an authenticator app, then enter the code it shows.',
          )}
        </p>

        {session?.username && (
          <p className="text-[11.5px] font-semibold">
            {lang === 'ar' ? session.full_name_ar : session.full_name_en}{' '}
            <span className="font-mono" style={{ color: 'var(--text-muted)' }}>
              ({session.username})
            </span>
          </p>
        )}

        {secret ? (
          <>
            {/* The QR is rendered by the server from the same pending secret. */}
            <div className="flex justify-center rounded-lg p-3" style={{ background: '#fff' }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${API_BASE}/auth/mfa/qr.svg`}
                alt={t('رمز QR لتسجيل تطبيق المصادقة', 'QR code for authenticator enrolment')}
                width={180}
                height={180}
              />
            </div>

            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded-lg px-2 py-1.5 font-mono text-[11px]" style={{ background: 'var(--surface-2)' }}>
                {secret}
              </code>
              <button className="btn btn-ghost" onClick={() => void copy()} title={t('نسخ', 'Copy')}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
            <p className="text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
              {t('أو أدخل هذا المفتاح يدوياً في التطبيق.', 'Or enter this key manually in the app.')}
            </p>

            <Field label={t('الرمز الظاهر في التطبيق', 'Code shown in the app')}>
              <input
                className="input mono tracking-[0.4em]"
                inputMode="numeric"
                maxLength={6}
                value={value}
                onChange={(e) => setValue(e.target.value.replace(/\D/g, ''))}
                onKeyDown={(e) => e.key === 'Enter' && void activate()}
                placeholder="000000"
                autoFocus
              />
            </Field>
          </>
        ) : (
          <p className="text-[11.5px]">{busy ? t('جارٍ تحضير التسجيل…', 'Preparing enrolment…') : error}</p>
        )}

        {error && secret && (
          <p className="rounded-lg px-3 py-2 text-[11.5px] font-semibold" style={{ color: 'var(--fail)', background: 'rgba(180,35,24,.08)' }}>
            {error}
          </p>
        )}

        <div className="flex justify-between gap-2">
          <button className="btn btn-ghost" onClick={() => void signOut()}>
            {t('خروج', 'Sign out')}
          </button>
          <button className="btn btn-primary" disabled={busy || !secret} onClick={() => void activate()}>
            <QrCode size={15} />
            {t('تفعيل', 'Activate')}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Voluntary disable from the account page: password **and** a code are required. */
export function MfaDisablePanel({ onDone }: { onDone: () => void }) {
  const { t, lang, notify } = useApp();
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api.mfaDisable(password, code);
      notify('success', t('أُوقف التحقق بخطوتين', 'Two-step verification disabled'));
      setPassword('');
      setCode('');
      onDone();
    } catch (err) {
      notify('error', t('رُفض الطلب', 'Request refused'), err instanceof ApiError ? err.text(lang) : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-[11.5px]" style={{ color: 'var(--text-muted)' }}>
        {t(
          'إيقاف التحقق بخطوتين يتطلب كلمة المرور ورمزاً صحيحاً — لأن هذا أول ما يفعله من سرق كلمة مرورك.',
          'Disabling two-step verification requires your password and a valid code — it is the first thing someone holding a stolen password would try.',
        )}
      </p>
      <Field label={t('كلمة المرور', 'Password')}>
        <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
      </Field>
      <Field label={t('الرمز الحالي', 'Current code')}>
        <input
          className="input mono tracking-[0.4em]"
          inputMode="numeric"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          dir="ltr"
        />
      </Field>
      <button className="btn btn-danger" disabled={busy || !password || code.length !== 6} onClick={() => void submit()}>
        <KeyRound size={15} />
        {t('إيقاف', 'Disable')}
      </button>
    </div>
  );
}
