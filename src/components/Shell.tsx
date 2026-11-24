'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Activity,
  Beaker,
  ClipboardCheck,
  Cog,
  FileBarChart2,
  Gauge,
  Languages,
  LayoutDashboard,
  LogOut,
  Moon,
  ScrollText,
  ShieldCheck,
  Sun,
  UserCog,
  Wrench,
} from 'lucide-react';
import { useApp } from './AppProvider';
import { db } from '@/core/db/database';
import { ROLE_LABELS, type UserAccount } from '@/core/types';
import { DEV_CREDIT_AR, DEV_CREDIT_EN, DEV_CREDIT_URL } from '@/core/constants';

const NAV = [
  { href: '/', ar: 'لوحة المؤشرات', en: 'Dashboard', icon: LayoutDashboard, perm: 'instruments.view' as const },
  { href: '/lab', ar: 'لوحة المختبر والمعايرة', en: 'Laboratory', icon: Beaker, perm: 'calibration.run' as const },
  { href: '/qa', ar: 'ضمان الجودة والاعتماد', en: 'Quality Assurance', icon: ShieldCheck, perm: 'calibration.review' as const },
  { href: '/engineering', ar: 'الصيانة والهندسة', en: 'Engineering', icon: Wrench, perm: 'maintenance.manage' as const },
  { href: '/control', ar: 'الإدارة المركزية', en: 'Central Control', icon: Cog, perm: 'settings.manage' as const },
  { href: '/audit', ar: 'سجل التدقيق', en: 'Audit Trail', icon: ScrollText, perm: 'audit.view' as const },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { t, user, setUser, lang, setLang, theme, setTheme, ready } = useApp();
  const path = usePathname();
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [switchOpen, setSwitchOpen] = useState(false);

  useEffect(() => {
    if (!ready) return;
    void db()
      .users.toArray()
      .then(setUsers)
      .catch(() => setUsers([]));
  }, [ready]);

  const isLogin = path === '/login';
  if (isLogin) return <>{children}</>;

  return (
    <div className="flex min-h-screen" style={{ background: 'var(--surface-2)' }}>
      <aside
        className="sticky top-0 hidden h-screen w-[254px] shrink-0 flex-col justify-between border-e md:flex"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div>
          <div className="flex items-center gap-2.5 px-4 py-4">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-xl"
              style={{ background: 'var(--brand)', color: '#fff' }}
            >
              <Gauge size={20} strokeWidth={2.1} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[12.5px] font-extrabold leading-tight">
                {t('الهيئة العليا للأدوية', 'Supreme Board of Drugs')}
              </p>
              <p className="truncate text-[10.5px]" style={{ color: 'var(--text-muted)' }}>
                SBDMA · Calibration & OQ Platform
              </p>
            </div>
          </div>

          <nav className="mt-1 space-y-0.5 px-2">
            {NAV.map((item) => {
              const active = path === item.href || (item.href !== '/' && path.startsWith(item.href));
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[12.5px] font-semibold transition-colors"
                  style={{
                    background: active ? 'var(--brand-soft)' : 'transparent',
                    color: active ? 'var(--brand)' : 'var(--text)',
                  }}
                >
                  <Icon size={16} strokeWidth={2} />
                  {t(item.ar, item.en)}
                </Link>
              );
            })}
          </nav>

          <div className="mt-4 px-4">
            <div className="rounded-lg p-2.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
              <p className="text-[10.5px] font-bold" style={{ color: 'var(--text-muted)' }}>
                {t('البروتوكول المسجل', 'Registered protocol')}
              </p>
              <p className="mt-1 font-mono text-[10.5px] leading-snug" style={{ direction: 'ltr' }}>
                SHIMADZU-LC2050C-UV-CAL
                <br />
                <span style={{ color: 'var(--text-muted)' }}>v1.0.0 · 13 tests</span>
              </p>
            </div>
          </div>
        </div>

        <div className="px-4 py-3">
          <div className="flex items-center justify-between gap-1 rounded-lg p-1" style={{ background: 'var(--surface-2)' }}>
            <button
              onClick={() => setLang(lang === 'ar' ? 'en' : 'ar')}
              className="btn btn-ghost flex-1 justify-center px-2 py-1 text-[11px]"
              title={t('تبديل اللغة', 'Switch language')}
            >
              <Languages size={13} /> {lang === 'ar' ? 'EN' : 'ع'}
            </button>
            <button
              onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
              className="btn btn-ghost flex-1 justify-center px-2 py-1 text-[11px]"
              title={t('تبديل المظهر', 'Toggle theme')}
            >
              {theme === 'light' ? <Moon size={13} /> : <Sun size={13} />}
            </button>
          </div>
          <p className="mt-3 text-center text-[10px]" style={{ color: 'var(--text-muted)' }}>
            {t(DEV_CREDIT_AR, DEV_CREDIT_EN)}
          </p>
          <p className="mt-0.5 text-center text-[9.5px]" style={{ color: 'var(--text-muted)' }}>
            <a href={DEV_CREDIT_URL} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--brand)' }}>
              {t('إبداع للاستضافة', 'Ebda3 Hosting')}
            </a>
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b px-4 py-2.5 backdrop-blur"
          style={{ background: 'color-mix(in srgb, var(--surface) 88%, transparent)', borderColor: 'var(--border)' }}
        >
          <div className="flex min-w-0 items-center gap-2">
            <span className="hidden text-[12px] font-bold md:inline">
              {NAV.find((n) => n.href === path) ? t(NAV.find((n) => n.href === path)!.ar, NAV.find((n) => n.href === path)!.en) : t('النظام', 'Platform')}
            </span>
            <span className="hidden text-[11px] md:inline" style={{ color: 'var(--text-muted)' }}>
              / ISO/IEC 17025 · 21 CFR Part 11
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span
              className="chip hidden sm:inline-flex"
              style={{ background: 'var(--brand-soft)', color: 'var(--brand)' }}
              title={t('قاعدة البيانات المحلية في المتصفح متصلة', 'Browser-local database connected')}
            >
              <Activity size={11} /> {t('IndexedDB متصلة', 'IndexedDB online')}
            </span>

            <div className="relative">
              <button
                className="btn btn-ghost gap-2 px-2 py-1.5"
                onClick={() => setSwitchOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={switchOpen}
              >
                <span
                  className="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{ background: 'var(--brand)', color: '#fff' }}
                >
                  {(user?.fullNameAr ?? 'U').slice(0, 1)}
                </span>
                <span className="hidden text-[11.5px] font-bold sm:inline">
                  {user ? (lang === 'ar' ? user.fullNameAr : user.fullNameEn) : '—'}
                </span>
              </button>
              {switchOpen && (
                <div
                  className="card absolute z-40 mt-1 w-[280px] p-1.5 ltr:right-0 rtl:left-0"
                  role="menu"
                  style={{ boxShadow: '0 12px 32px rgba(16,24,40,.16)' }}
                >
                  <p className="px-2 py-1 text-[10.5px] font-bold" style={{ color: 'var(--text-muted)' }}>
                    {t('تبديل هوية المستخدم (لتجربة الأدوار والصلاحيات)', 'Switch user identity (role testing)')}
                  </p>
                  {users.map((u) => (
                    <button
                      key={u.id}
                      onClick={() => {
                        setUser(u);
                        setSwitchOpen(false);
                      }}
                      className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-start hover:bg-[var(--surface-3)]"
                      role="menuitem"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-[11.5px] font-semibold">
                          {lang === 'ar' ? u.fullNameAr : u.fullNameEn}
                        </span>
                        <span className="block text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          {ROLE_LABELS[u.role][lang]} · {u.departmentCode}
                        </span>
                      </span>
                      {user?.id === u.id && <ClipboardCheck size={13} style={{ color: 'var(--brand)' }} />}
                    </button>
                  ))}
                  <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                  <Link
                    href="/login"
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[11.5px] font-semibold"
                    onClick={() => setSwitchOpen(false)}
                  >
                    <LogOut size={13} /> {t('شاشة الدخول / تغيير الحساب', 'Sign-in screen')}
                  </Link>
                  <Link
                    href="/control"
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[11.5px] font-semibold"
                    onClick={() => setSwitchOpen(false)}
                  >
                    <UserCog size={13} /> {t('إدارة المستخدمين', 'User administration')}
                  </Link>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 p-4 lg:p-6">{children}</main>

        <footer className="mt-4 border-t px-4 py-3 text-center text-[10.5px]" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
          <span className="inline-flex items-center gap-1.5">
            <FileBarChart2 size={11} />
            {t('نظام إدارة ومعايرة الأجهزة المخبرية — الإصدار 1.0.0', 'Laboratory Calibration & OQ Platform — v1.0.0')}
            <span aria-hidden>·</span>
            {t('تطوير: ', 'Developed by: ')}
            <a href={DEV_CREDIT_URL} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--brand)', fontWeight: 700 }}>
              {t('إبداع للاستضافة', 'Ebda3 Hosting')}
            </a>
          </span>
        </footer>
      </div>

      <MobileNav />
    </div>
  );
}

function MobileNav() {
  const { t, lang } = useApp();
  const path = usePathname();
  return (
    <nav
      className="fixed bottom-0 z-30 flex w-full items-center justify-around border-t px-2 py-1.5 md:hidden"
      style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
    >
      {NAV.slice(0, 5).map((item) => {
        const Icon = item.icon;
        const active = path === item.href || (item.href !== '/' && path.startsWith(item.href));
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-label={t(item.ar, item.en)}
            className="flex flex-col items-center gap-0.5 px-2 py-1"
            style={{ color: active ? 'var(--brand)' : 'var(--text-muted)' }}
          >
            <Icon size={17} />
            <span className="text-[9px] font-semibold">{lang === 'ar' ? item.ar.split(' ')[0] : item.en.split(' ')[0]}</span>
          </Link>
        );
      })}
    </nav>
  );
}
