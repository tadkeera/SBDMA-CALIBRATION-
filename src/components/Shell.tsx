'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Activity,
  Beaker,
  Cog,
  FileBarChart2,
  Languages,
  LayoutDashboard,
  LogOut,
  Moon,
  ScrollText,
  ShieldCheck,
  Sun,
  UserCog,
  Wrench,
  AlertTriangle,
  BellRing,
  Image as ImageIcon,
} from 'lucide-react';
import { useApp } from './AppProvider';
import { PasswordChangeGate } from './PasswordChangeGate';
import { MfaEnrolment } from './MfaEnrolment';
import { ROLE_LABELS } from '@/core/types';
import { Letterhead, PrintLetterhead } from '@/components/Letterhead';
import { PROTOCOL_VERSION, TESTS } from '@/core/protocol';
import { APP_VERSION, DEV_CREDIT_URL } from '@/core/constants';
import { api, ApiError } from '@/core/api/client';

const NAV = [
  { href: '/', ar: 'لوحة المؤشرات', en: 'Dashboard', icon: LayoutDashboard, perm: 'instruments.view' as const },
  // The laboratory is entered through its units: one tile per registered unit, each tile
  // holding the twenty tests. The former single-screen laboratory and the standalone
  // Flow Rate page are no longer navigation entries — Flow Rate is reached from the test
  // tile of a unit, where its readings and charts belong.
  //
  // ``instruments.view`` and not ``calibration.run``: the administrator who registers a
  // unit does not run calibrations, and hiding the shelf from the office that registers
  // units would leave the "Add unit" form reachable only by URL. What the page offers is
  // still decided by the server's permissions — the button appears only for a role that
  // may create, and the API refuses anyone else.
  { href: '/lab/units', ar: 'أجهزة المختبر', en: 'Laboratory units', icon: Beaker, perm: 'instruments.view' as const },
  { href: '/qa', ar: 'ضمان الجودة والاعتماد', en: 'Quality Assurance', icon: ShieldCheck, perm: 'calibration.review' as const },
  { href: '/engineering', ar: 'الصيانة والهندسة', en: 'Engineering', icon: Wrench, perm: 'maintenance.manage' as const },
  { href: '/control', ar: 'الإدارة المركزية', en: 'Central Control', icon: Cog, perm: 'settings.manage' as const },
  {
    href: '/deviations',
    ar: 'انحرافات OOS',
    en: 'Deviations',
    icon: AlertTriangle,
    perm: 'instruments.view' as const,
  },
  { href: '/users', ar: 'إدارة المستخدمين', en: 'Users', icon: UserCog, perm: 'users.manage' as const },
  {
    href: '/notifications',
    ar: 'الإشعارات والمهام',
    en: 'Notices & Jobs',
    icon: BellRing,
    perm: 'instruments.view' as const,
  },
  { href: '/audit', ar: 'سجل التدقيق', en: 'Audit Trail', icon: ScrollText, perm: 'audit.view' as const },
  {
    href: '/settings',
    ar: 'إعداد الترويسة',
    en: 'Report Header',
    icon: ImageIcon,
    perm: 'settings.manage' as const,
  },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { t, user, session, can, signOut, lang, setLang, theme, setTheme, ready, working } = useApp();
  const path = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [backend, setBackend] = useState<'checking' | 'up' | 'down'>('checking');
  const [unread, setUnread] = useState(0);

  // the navigation is filtered by the permissions the server granted, not by a
  // client-side role table
  const allowed = NAV.filter((item) => can(item.perm));
  const isLogin = path === '/login';

  // Unread notices, polled. A due-date warning that only exists behind a menu is a
  // warning most people will not read, so the count is part of the header.
  useEffect(() => {
    if (!user) {
      setUnread(0);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const { unread: count } = await api.unreadNotificationCount();
        if (!cancelled) setUnread(count);
      } catch {
        if (!cancelled) setUnread(0);
      }
    };
    void tick();
    const timer = setInterval(tick, 120_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [user, path]);

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      try {
        await api.health();
        if (!cancelled) setBackend('up');
      } catch {
        if (!cancelled) setBackend('down');
      }
    };
    void probe();
    const timer = setInterval(probe, 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // an unauthenticated visitor never sees a protected page
  useEffect(() => {
    if (ready && !isLogin && !session) router.replace('/login');
  }, [ready, isLogin, session, router]);

  /**
   * The laboratory screens belong to the bench.
   *
   * QA and the administrators hold ``calibration.run`` too (the super administrator holds
   * every permission), but they do not enter readings on a unit — QA reads results on the
   * approval screen. Rather than hiding a menu entry and leaving a page reachable by URL,
   * a principal who is not an operator is sent to its own landing screen. The server
   * still refuses anything this does not cover.
   */
  const operator =
    session?.roles.some((role) => role === 'ANALYST' || role === 'SUPERVISOR') ?? false;
  // Registration of a unit is an administrative act; the administrator is therefore
  // allowed onto the shelf to perform it, but nowhere else in the laboratory — the
  // reading, the run and the approval stay with the bench and with QA.
  const registersUnits = can('instruments.create');
  const inLaboratory = path.startsWith('/lab');
  const unitShelf = path === '/lab/units';
  useEffect(() => {
    if (!ready || !session || inLaboratory === false) return;
    if (operator) return;
    if (unitShelf && registersUnits) return;
    router.replace(session.roles.includes('QA_APPROVER') ? '/qa' : '/');
  }, [ready, session, operator, registersUnits, unitShelf, inLaboratory, router]);

  if (isLogin) return <>{children}</>;

  // The server blocks everything but identity + password change for an account
  // still holding an administrator-issued password. Showing the gate here keeps
  // the user from wandering into 403s with no way forward.
  if (session?.must_change_password) return <PasswordChangeGate />;

  // A role that mandates a second factor cannot reach the app until it is
  // enrolled: the server refuses everything but the enrolment routes.
  if (session?.mfa_enrolment_required) return <MfaEnrolment />;

  return (
    <div className="flex min-h-screen" style={{ background: 'var(--surface-2)' }}>
      <aside
        className="sticky top-0 hidden h-screen w-[254px] shrink-0 flex-col justify-between border-e md:flex"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div>
          {/* the official logo, as uploaded in إعداد الترويسة */}
          <div className="px-4 py-4">
            <Letterhead variant="compact" />
            <p className="mt-1 truncate text-[10px] font-semibold" style={{ color: 'var(--text-muted)' }}>
              SBDMA · Calibration &amp; OQ Platform
            </p>
          </div>

          <nav className="mt-1 space-y-0.5 px-2">
            {allowed.map((item) => {
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
                <span style={{ color: 'var(--text-muted)' }}>
                  {`v${PROTOCOL_VERSION} · ${TESTS.length} tests`}
                </span>
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
          <p className="mt-3 text-center text-[9.5px]" style={{ color: 'var(--text-muted)' }}>
            <a href={DEV_CREDIT_URL} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--brand)', fontWeight: 700 }}>
              {t('تذكرة للحلول البرمجية والأنظمة', 'Tadkrah Software Solutions')}
            </a>
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* every printed page carries the official letterhead, not just the reports */}
        <PrintLetterhead />
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
              style={
                backend === 'up'
                  ? { background: 'rgba(22,121,79,.12)', color: 'var(--pass)' }
                  : backend === 'down'
                    ? { background: 'rgba(180,35,24,.12)', color: 'var(--fail)' }
                    : { background: 'var(--surface-3)', color: 'var(--text-muted)' }
              }
              title={t('حالة خادم المعايرة (فحص كل دقيقة)', 'Calibration server status (probed every minute)')}
            >
              <Activity size={11} />
              {backend === 'up'
                ? t('الخادم متاح', 'Server online')
                : backend === 'down'
                  ? t('الخادم غير متاح', 'Server offline')
                  : t('جارٍ الفحص', 'Checking')}
            </span>

            <button
              className="btn btn-ghost relative px-2 py-1.5"
              onClick={() => router.push('/notifications')}
              title={t('الإشعارات غير المقروءة', 'Unread notices')}
              aria-label={t('الإشعارات غير المقروءة', 'Unread notices')}
            >
              <BellRing size={15} />
              {unread > 0 && (
                <span
                  className="absolute -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9.5px] font-bold"
                  style={{ background: 'var(--fail)', color: '#fff' }}
                >
                  {unread > 99 ? '99+' : unread}
                </span>
              )}
            </button>

            <div className="relative">
              <button
                className="btn btn-ghost gap-2 px-2 py-1.5"
                onClick={() => setMenuOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
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
              {menuOpen && (
                <div
                  className="card absolute z-40 mt-1 w-[286px] p-1.5 ltr:right-0 rtl:left-0"
                  role="menu"
                  style={{ boxShadow: '0 12px 32px rgba(16,24,40,.16)' }}
                >
                  <div className="px-2 py-1.5">
                    <p className="text-[11.5px] font-bold">
                      {user ? (lang === 'ar' ? user.fullNameAr : user.fullNameEn) : '—'}
                    </p>
                    <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                      {user ? ROLE_LABELS[user.role][lang] : ''} · {user?.departmentCode ?? '—'}
                    </p>
                    <p className="mt-1 font-mono text-[9.5px]" style={{ color: 'var(--text-muted)' }}>
                      {session?.email ?? ''}
                    </p>
                  </div>
                  <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                  <p className="px-2 py-1 text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>
                    {t('الصلاحيات الممنوحة من الخادم', 'Permissions granted by the server')} (
                    {(session?.permissions ?? []).length})
                  </p>
                  <div className="max-h-[130px] overflow-y-auto px-2 pb-1">
                    <p className="font-mono text-[9.5px] leading-relaxed" style={{ color: 'var(--text-muted)', direction: 'ltr' }}>
                      {(session?.permissions ?? []).join(' · ') || '—'}
                    </p>
                  </div>
                  <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                  <button
                    onClick={async () => {
                      setMenuOpen(false);
                      await signOut();
                      router.replace('/login');
                    }}
                    disabled={working}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start text-[11.5px] font-semibold"
                    role="menuitem"
                  >
                    <LogOut size={13} /> {t('تسجيل الخروج', 'Sign out')}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 p-4 lg:p-6">{children}</main>

        <footer className="mt-4 border-t px-4 py-3 text-center text-[10.5px]" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
          <span className="inline-flex items-center gap-1.5">
            <FileBarChart2 size={11} />
            {t(
              `نظام إدارة ومعايرة الأجهزة المخبرية — الإصدار ${APP_VERSION}`,
              `Laboratory Calibration & OQ Platform — v${APP_VERSION}`,
            )}
            <span aria-hidden>·</span>
            {t('تطوير: ', 'Developed by: ')}
            <a href={DEV_CREDIT_URL} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--brand)', fontWeight: 700 }}>
              {t('تذكرة للحلول البرمجية والأنظمة', 'Tadkrah Software Solutions')}
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
