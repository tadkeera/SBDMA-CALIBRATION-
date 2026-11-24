'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ArrowRight, Gauge, Languages, Lock, ShieldCheck, User } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { db } from '@/core/db/database';
import { ROLE_LABELS } from '@/core/types';
import { DEV_CREDIT_URL } from '@/core/constants';

/**
 * Sign-in against POST /api/v1/auth/login.
 *
 * The password is verified with Argon2id on the server and never stored in the
 * browser: the session lives in httpOnly cookies. The username list is only a
 * convenience — any username may be typed, and the server answers uniformly for
 * unknown accounts and wrong passwords so account existence is not disclosed.
 */
export default function LoginPage() {
  const { t, lang, setLang, signIn, notify, session, authError, working } = useApp();
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);

  // remember the last successful username (never the password)
  useEffect(() => {
    void db()
      .settings.get('lastUsername')
      .then((row) => {
        const last = row?.value;
        if (typeof last === 'string' && last) setUsername(last);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (session) {
      const role = session.roles[0] ?? 'VIEWER';
      router.replace(role === 'QA_APPROVER' ? '/qa' : role === 'ENGINEERING_SERVICE' ? '/engineering' : '/');
    }
  }, [session, router]);

  const submit = async () => {
    setErr(null);
    if (!username.trim() || password.length === 0) {
      setErr(t('أدخل اسم المستخدم وكلمة المرور.', 'Enter your username and password.'));
      return;
    }
    try {
      const account = await signIn(username.trim(), password);
      setPassword('');
      notify('success', t('تم تسجيل الدخول', 'Signed in'), ROLE_LABELS[account.role][lang]);
      router.push(account.role === 'QA_APPROVER' ? '/qa' : account.role === 'ENGINEERING_SERVICE' ? '/engineering' : '/');
    } catch {
      setPassword('');
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4" style={{ background: 'var(--surface-2)' }}>
      <div className="grid w-full max-w-4xl overflow-hidden rounded-2xl md:grid-cols-2" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
        <div
          className="hidden flex-col justify-between p-7 md:flex"
          style={{
            background: 'linear-gradient(150deg, color-mix(in srgb, var(--brand) 92%, #000) 0%, color-mix(in srgb, var(--brand) 62%, #fff) 100%)',
            color: '#fff',
          }}
        >
          <div>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: 'rgba(255,255,255,.18)' }}>
              <Gauge size={22} />
            </div>
            <h1 className="mt-4 text-[17px] font-extrabold leading-snug">
              {t('نظام إدارة ومعايرة الأجهزة المخبرية', 'Laboratory Calibration & OQ Platform')}
            </h1>
            <p className="mt-1 text-[11.5px] opacity-90">
              {t('الهيئة العليا للأدوية والمستحضرات الطبية', 'Supreme Board of Drugs & Medical Devices')}
            </p>
            <ul className="mt-5 space-y-2 text-[11.5px] opacity-95">
              {[
                t('ISO/IEC 17025 — تأهيل تشغيلي موثق', 'ISO/IEC 17025 — documented OQ'),
                t('21 CFR Part 11 — توقيع إلكتروني وسجل تدقيق', '21 CFR Part 11 — e-signature & audit trail'),
                t('ALCOA+ — سلامة البيانات والقراءات الخام', 'ALCOA+ — raw data integrity'),
                t('بروتوكول Shimadzu LC-2050C UV — 13 اختباراً', 'Shimadzu LC-2050C UV — 13 tests'),
              ].map((x) => (
                <li key={x} className="flex items-start gap-1.5">
                  <ShieldCheck size={13} className="mt-0.5 shrink-0" /> {x}
                </li>
              ))}
            </ul>
          </div>
          <p className="mt-6 text-[10px] opacity-80">
            {t('تطوير: ', 'Developed by: ')}
            <a href={DEV_CREDIT_URL} target="_blank" rel="noopener noreferrer" style={{ color: '#fff', textDecoration: 'underline' }}>
              {t('إبداع للاستضافة', 'Ebda3 Hosting')}
            </a>
          </p>
        </div>

        <div className="p-6 md:p-8">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-[15px] font-extrabold">{t('تسجيل الدخول', 'Sign in')}</h2>
            <button className="btn btn-ghost px-2 py-1 text-[11px]" onClick={() => setLang(lang === 'ar' ? 'en' : 'ar')}>
              <Languages size={13} /> {lang === 'ar' ? 'EN' : 'ع'}
            </button>
          </div>

          <label className="label" htmlFor="username">{t('المستخدم', 'Username')}</label>
          <div className="relative mb-3">
            <User size={14} className="absolute top-2.5 ltr:left-2.5 rtl:right-2.5" style={{ color: 'var(--text-muted)' }} />
            <input
              id="username"
              className="input ps-8 mono"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t('اسم المستخدم', 'username')}
            />
          </div>

          <label className="label" htmlFor="password">{t('كلمة المرور', 'Password')}</label>
          <div className="relative mb-4">
            <Lock size={14} className="absolute top-2.5 ltr:left-2.5 rtl:right-2.5" style={{ color: 'var(--text-muted)' }} />
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              className="input ps-8 mono"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="••••••••"
            />
          </div>

          {(err ?? authError) && (
            <p className="mb-3 rounded-lg px-3 py-2 text-[11.5px] font-semibold" style={{ color: 'var(--fail)', background: 'rgba(180,35,24,.08)' }}>
              {err ?? authError}
            </p>
          )}

          <button className="btn btn-primary w-full justify-center" onClick={submit} disabled={working}>
            {working ? t('جارٍ التحقق…', 'Verifying…') : t('دخول', 'Sign in')} <ArrowRight size={14} />
          </button>

          <p className="mt-4 rounded-lg px-3 py-2 text-[10.5px] leading-relaxed" style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
            {t(
              'يُتحقق من كلمة المرور بـArgon2id على خادم المعايرة، وتُحفظ الجلسة في كوكيز httpOnly غير قابلة للقراءة من JavaScript. الحسابات المقفلة بعد 5 محاولات فاشلة تبقى مقفلة 15 دقيقة.',
              'The password is verified with Argon2id on the calibration server and the session is stored in httpOnly cookies that JavaScript cannot read. Accounts lock for 15 minutes after 5 failed attempts.',
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
