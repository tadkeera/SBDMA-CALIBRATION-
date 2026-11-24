'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ArrowRight, Gauge, Languages, Lock, ShieldCheck, User } from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { appendAudit, db } from '@/core/db/database';
import { ROLE_LABELS, type UserAccount } from '@/core/types';
import { DEV_CREDIT_URL } from '@/core/constants';

/**
 * Demo/local sign-in.
 * The production authentication path is Argon2id + JWT (HttpOnly, SameSite=Strict)
 * exposed by the FastAPI backend at POST /api/v1/auth/login. This screen binds the
 * browser-local identity used by the offline layer and never stores a password.
 */
export default function LoginPage() {
  const { t, lang, setLang, setUser, notify } = useApp();
  const router = useRouter();
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [username, setUsername] = useState('analyst');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void db()
      .users.toArray()
      .then((u) => {
        setUsers(u);
        if (u.length) setUsername(u[0].username);
      })
      .catch(() => setUsers([]));
  }, []);

  const submit = async () => {
    setErr(null);
    if (password.length < 4) {
      setErr(t('كلمة المرور مطلوبة (4 أحرف على الأقل في بيئة العرض المحلية).', 'Password required (min 4 characters in the local demo environment).'));
      return;
    }
    setBusy(true);
    try {
      const found = users.find((u) => u.username === username);
      if (!found) {
        setErr(t('المستخدم غير موجود.', 'User not found.'));
        return;
      }
      if (!found.isActive) {
        setErr(t('الحساب معطل — راجع مسؤول النظام.', 'Account disabled — contact the system administrator.'));
        return;
      }
      await db().users.put({ ...found, lastLoginAt: new Date().toISOString() });
      await appendAudit({
        actor: found.username,
        role: found.role,
        action: 'LOGIN_SUCCESS',
        entity: 'user',
        entityId: found.id,
        module: 'auth',
        reason: 'دخول ناجح إلى النظام',
      });
      setUser(found);
      notify('success', t('تم تسجيل الدخول', 'Signed in'), ROLE_LABELS[found.role][lang]);
      router.push(found.role === 'QA_APPROVER' ? '/qa' : found.role === 'ENGINEERING_SERVICE' ? '/engineering' : '/');
    } finally {
      setBusy(false);
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

          <label className="label">{t('المستخدم', 'Username')}</label>
          <div className="relative mb-3">
            <User size={14} className="absolute top-2.5 ltr:left-2.5 rtl:right-2.5" style={{ color: 'var(--text-muted)' }} />
            <select className="select ps-8" value={username} onChange={(e) => setUsername(e.target.value)}>
              {users.map((u) => (
                <option key={u.id} value={u.username}>
                  {u.username} — {ROLE_LABELS[u.role][lang]}
                </option>
              ))}
            </select>
          </div>

          <label className="label">{t('كلمة المرور', 'Password')}</label>
          <div className="relative mb-4">
            <Lock size={14} className="absolute top-2.5 ltr:left-2.5 rtl:right-2.5" style={{ color: 'var(--text-muted)' }} />
            <input
              type="password"
              className="input ps-8 mono"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="••••••••"
            />
          </div>

          {err && (
            <p className="mb-3 text-[11.5px] font-semibold" style={{ color: 'var(--fail)' }}>
              {err}
            </p>
          )}

          <button className="btn btn-primary w-full justify-center" onClick={submit} disabled={busy}>
            {busy ? t('جارٍ التحقق…', 'Verifying…') : t('دخول', 'Sign in')} <ArrowRight size={14} />
          </button>

          <p className="mt-4 rounded-lg px-3 py-2 text-[10.5px] leading-relaxed" style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
            {t(
              'بيئة العرض المحلية: أي كلمة مرور من 4 أحرف تعمل لربط هوية المستخدم بقاعدة البيانات المحلية. في بيئة الإنتاج تُتحقق كلمة المرور عبر Argon2id على الخادم مع JWT في كوكيز آمنة.',
              'Local demo: any 4-character password binds the identity to the browser database. In production the password is verified with Argon2id on the server and JWT in secure cookies.',
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
