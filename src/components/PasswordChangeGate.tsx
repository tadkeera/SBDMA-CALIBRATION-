'use client';

import { useState } from 'react';
import { KeyRound, ShieldAlert } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Field } from '@/components/ui';
import { ApiError, api } from '@/core/api/client';

/**
 * Forced password change.
 *
 * The server refuses every non-identity endpoint while an account still holds an
 * administrator-issued password (403 PASSWORD_CHANGE_REQUIRED), so without this
 * screen a newly created or reset account would be stuck with no way forward.
 */
export function PasswordChangeGate() {
  const { t, lang, session, signOut, notify } = useApp();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const mismatch = confirm.length > 0 && next !== confirm;
  const canSubmit =
    current.length > 0 && next.length > 0 && next === confirm && reason.trim().length >= 8 && !busy;

  const submit = async () => {
    setBusy(true);
    setErrors([]);
    try {
      await api.changePassword(current, next, reason.trim());
      notify(
        'success',
        t('حُدّثت كلمة المرور', 'Password updated'),
        t('سجّل الدخول من جديد بكلمة مرورك', 'Sign in again with your new password'),
      );
      // the change revokes every session, so the tokens in the cookies are dead
      await signOut();
    } catch (error) {
      if (error instanceof ApiError) {
        const rules = error.details?.password_rules;
        if (Array.isArray(rules) && rules.length > 0) setErrors(rules.map(String));
        else setErrors([error.text(lang)]);
      } else {
        setErrors([String(error)]);
      }
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4 rounded-xl border p-6" style={{ background: 'var(--surface)' }}>
        <div className="flex items-center gap-2">
          <ShieldAlert size={20} style={{ color: 'var(--warn)' }} />
          <h1 className="text-[15px] font-bold">{t('تغيير كلمة المرور المؤقتة', 'Change your temporary password')}</h1>
        </div>

        <p className="text-[11.5px] leading-5" style={{ color: 'var(--text-muted)' }}>
          {t(
            `كلمة المرور الحالية أصدرها مسؤول الحسابات، ولا يمكن توقيع أي سجل بها. حدّد كلمة مرور شخصية للمتابعة.`,
            'Your current password was issued by an account administrator, so it cannot be used to sign any record. Set a personal password to continue.',
          )}
        </p>

        {session?.full_name_ar && (
          <p className="text-[11.5px] font-semibold">
            {lang === 'ar' ? session.full_name_ar : session.full_name_en}{' '}
            <span className="font-mono" style={{ color: 'var(--text-muted)' }}>
              ({session.username})
            </span>
          </p>
        )}

        <Field label={t('كلمة المرور الحالية', 'Current password')}>
          <input
            className="input"
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            dir="ltr"
            autoComplete="current-password"
          />
        </Field>

        <Field
          label={t('كلمة المرور الجديدة', 'New password')}
          hint={t(
            '12 حرفاً على الأقل، مع حرف كبير وصغير ورقم ورمز',
            'At least 12 characters with upper, lower, digit and symbol',
          )}
        >
          <input
            className="input"
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            dir="ltr"
            autoComplete="new-password"
          />
        </Field>

        <Field
          label={t('تأكيد كلمة المرور', 'Confirm password')}
          hint={mismatch ? t('الكلمتان غير متطابقتين', 'The two entries do not match') : undefined}
        >
          <input
            className="input"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            dir="ltr"
            autoComplete="new-password"
          />
        </Field>

        <Field label={t('سبب التغيير (يُسجَّل في التدقيق)', 'Reason (written to the audit trail)')}>
          <textarea
            className="textarea"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('استبدال كلمة المرور المؤقتة بكلمة شخصية', 'replacing the temporary password')}
          />
        </Field>

        {errors.length > 0 && (
          <ul className="space-y-1 rounded-lg p-3 text-[11.5px]" style={{ background: 'rgba(180,35,24,.08)', color: 'var(--fail)' }}>
            {errors.map((e, i) => (
              <li key={i}>• {e}</li>
            ))}
          </ul>
        )}

        <div className="flex justify-between gap-2">
          <button className="btn btn-ghost" onClick={() => void signOut()}>
            {t('خروج', 'Sign out')}
          </button>
          <button className="btn btn-primary" disabled={!canSubmit} onClick={() => void submit()}>
            <KeyRound size={15} />
            {t('تحديث كلمة المرور', 'Update password')}
          </button>
        </div>
      </div>
    </div>
  );
}
