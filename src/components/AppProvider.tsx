'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, OfflineError, api, toUserAccount, type ServerUser } from '@/core/api/client';
import { DATA_MODE, type DataMode, type SourceStamp } from '@/core/api/mode';
import { db } from '@/core/db/database';
import { seedIfEmpty } from '@/core/db/seed';
import type { Lang, UserAccount } from '@/core/types';

type ToastKind = 'success' | 'error' | 'info' | 'warn';
export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

interface AppCtx {
  ready: boolean;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: 'light' | 'dark';
  setTheme: (t: 'light' | 'dark') => void;
  t: (ar: string, en: string) => string;
  user: UserAccount | null;
  session: ServerUser | null;
  permissions: string[];
  can: (permission: string) => boolean;
  signIn: (username: string, password: string) => Promise<UserAccount>;
  signOut: () => Promise<void>;
  authError: string | null;
  working: boolean;
  mode: DataMode;
  source: SourceStamp | null;
  setSource: (s: SourceStamp | null) => void;
  /** Read from the server, falling back to the cached snapshot in `auto` mode. */
  readThrough: <T>(fetchLive: () => Promise<T>, cache: () => Promise<T>) => Promise<{ data: T; source: SourceStamp }>;
  toasts: Toast[];
  notify: (kind: ToastKind, title: string, detail?: string) => void;
  dismiss: (id: number) => void;
}

const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp must be used inside AppProvider');
  return v;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [lang, setLangState] = useState<Lang>('ar');
  const [theme, setThemeState] = useState<'light' | 'dark'>('light');
  const [session, setSession] = useState<ServerUser | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [source, setSource] = useState<SourceStamp | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // ── boot: preferences from the cache, identity from the server ────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await seedIfEmpty();
        const [ls, ts] = await Promise.all([db().settings.get('lang'), db().settings.get('theme')]);
        if (cancelled) return;
        if (ls?.value === 'en' || ls?.value === 'ar') setLangState(ls.value);
        if (ts?.value === 'dark' || ts?.value === 'light') setThemeState(ts.value);
      } catch {
        /* preferences are non-critical */
      }

      // A live httpOnly session survives a page reload — ask the server who we are.
      try {
        const me = await api.me();
        if (!cancelled) {
          setSession(me);
          await db().settings.put({
            key: 'lastUsername',
            value: me.username,
            updatedAt: new Date().toISOString(),
          });
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError || error instanceof OfflineError) setSession(null);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  }, [lang]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    void db().settings.put({ key: 'lang', value: l, updatedAt: new Date().toISOString() });
  }, []);

  const setTheme = useCallback((tv: 'light' | 'dark') => {
    setThemeState(tv);
    void db().settings.put({ key: 'theme', value: tv, updatedAt: new Date().toISOString() });
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const notify = useCallback((kind: ToastKind, title: string, detail?: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev, { id, kind, title, detail }]);
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 6000);
  }, []);

  const t = useCallback((ar: string, en: string) => (lang === 'ar' ? ar : en), [lang]);

  // ── authentication (server-authoritative) ─────────────────────────────────
  const signIn = useCallback(
    async (username: string, password: string): Promise<UserAccount> => {
      setAuthError(null);
      setWorking(true);
      try {
        const result = await api.login(username, password);
        setSession(result.user);
        const account = toUserAccount(result.user);
        await db().settings.put({
          key: 'lastUsername',
          value: result.user.username,
          updatedAt: new Date().toISOString(),
        });
        // mirror identity locally for offline display only
        await db().users.put(account);
        return account;
      } catch (error) {
        if (error instanceof ApiError) {
          setAuthError(error.text(lang));
        } else if (error instanceof OfflineError) {
          setAuthError(
            lang === 'ar'
              ? 'تعذر الوصول إلى خادم المعايرة — تسجيل الدخول يتطلب اتصالاً.'
              : 'The calibration server is unreachable — sign-in requires a connection.',
          );
        } else {
          setAuthError(lang === 'ar' ? 'خطأ غير متوقع' : 'Unexpected error');
        }
        throw error;
      } finally {
        setWorking(false);
      }
    },
    [lang],
  );

  const signOut = useCallback(async () => {
    setWorking(true);
    try {
      await api.logout();
    } catch {
      /* the session may already be gone; clearing locally is still correct */
    } finally {
      setSession(null);
      setSource(null);
      setWorking(false);
    }
  }, []);

  const permissions = useMemo(() => session?.permissions ?? [], [session]);
  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);

  const user = useMemo(() => (session ? toUserAccount(session) : null), [session]);

  const readThrough = useCallback(
    async <T,>(
      fetchLive: () => Promise<T>,
      cache: () => Promise<T>,
    ): Promise<{ data: T; source: SourceStamp }> => {
      try {
        const data = await fetchLive();
        const stamp: SourceStamp = { source: 'server', at: new Date().toISOString() };
        return { data, source: stamp };
      } catch (error) {
        const offline = error instanceof OfflineError;
        const serverError = error instanceof ApiError;
        if ((offline || (serverError && (error as ApiError).status >= 500)) && DATA_MODE === 'auto') {
          const data = await cache();
          return { data, source: { source: 'cache', at: new Date().toISOString() } };
        }
        throw error;
      }
    },
    [],
  );

  const value = useMemo(
    () => ({
      ready,
      lang,
      setLang,
      theme,
      setTheme,
      t,
      user,
      session,
      permissions,
      can,
      signIn,
      signOut,
      authError,
      working,
      mode: DATA_MODE,
      source,
      setSource,
      readThrough,
      toasts,
      notify,
      dismiss,
    }),
    [
      ready, lang, setLang, theme, setTheme, t, user, session, permissions, can, signIn, signOut,
      authError, working, source, readThrough, toasts, notify, dismiss,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
