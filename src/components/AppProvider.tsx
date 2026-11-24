'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { appendAudit, db } from '@/core/db/database';
import { seedIfEmpty, SEED_USERS } from '@/core/db/seed';
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
  setUser: (u: UserAccount | null) => void;
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
  const [user, setUserState] = useState<UserAccount | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await seedIfEmpty();
        const ls = await db().settings.get('lang');
        const ts = await db().settings.get('theme');
        const us = await db().settings.get('currentUser');
        if (cancelled) return;
        if (ls?.value === 'en' || ls?.value === 'ar') setLangState(ls.value);
        if (ts?.value === 'dark' || ts?.value === 'light') setThemeState(ts.value);
        const saved = us?.value as string | undefined;
        const found = saved ? await db().users.get(saved) : null;
        setUserState(found ?? (await db().users.get('usr-001')) ?? SEED_USERS[0]);
      } catch {
        setUserState(SEED_USERS[0]);
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

  const setUser = useCallback((u: UserAccount | null) => {
    setUserState(u);
    void db().settings.put({
      key: 'currentUser',
      value: u?.id ?? null,
      updatedAt: new Date().toISOString(),
    });
    if (u) {
      void appendAudit({
        actor: u.username,
        role: u.role,
        action: 'SESSION_START',
        entity: 'user',
        entityId: u.id,
        module: 'auth',
      });
    }
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

  const value = useMemo(
    () => ({ ready, lang, setLang, theme, setTheme, t, user, setUser, toasts, notify, dismiss }),
    [ready, lang, setLang, theme, setTheme, t, user, setUser, toasts, notify, dismiss],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
