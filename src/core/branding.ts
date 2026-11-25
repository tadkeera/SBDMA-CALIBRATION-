/**
 * The official report letterhead.
 *
 * One source of truth for the header text and the logo, shared by the sign-in
 * screen, the application shell, the print stylesheet and the reports settings
 * page. The server owns the values (see `branding_service`); the browser keeps a
 * copy in `localStorage` so a cold, offline start still shows the right letterhead
 * instead of a flash of defaults.
 */

import { useEffect, useState } from 'react';

import { API_BASE, OfflineError, api } from '@/core/api/client';

export const DEFAULT_HEADER_AR = [
  'الجمهورية اليمنية',
  'وزارة الصحة العامة والسكان',
  'الهيئة العليا للأدوية والمستلزمات الطبية',
  'المختبر الوطني للرقابة الدوائية - عدن',
] as const;

export const DEFAULT_HEADER_EN = [
  'Republic of Yemen',
  'Ministry of Public Health and Population',
  'Supreme Board for Drugs & Medical Appliances',
  'National Quality Control Laboratory - ADEN',
] as const;

export const HEADER_LINES = 4;

export interface BrandingLogo {
  filename: string;
  content_type: string;
  bytes: number;
  sha256: string;
  width: number | null;
  height: number | null;
  converted: boolean;
  original_type: string | null;
  updated_at: string | null;
  updated_by: string | null;
  url: string;
}

export interface Branding {
  header_ar: string[];
  header_en: string[];
  is_default: boolean;
  updated_at: string | null;
  updated_by: string | null;
  logo: BrandingLogo | null;
}

export const DEFAULT_BRANDING: Branding = {
  header_ar: [...DEFAULT_HEADER_AR],
  header_en: [...DEFAULT_HEADER_EN],
  is_default: true,
  updated_at: null,
  updated_by: null,
  logo: null,
};

const CACHE_KEY = 'sbdma.branding.v1';

/** The letterhead as last seen — defaults when nothing has been cached yet. */
export function cachedBranding(): Branding {
  if (typeof window === 'undefined') return DEFAULT_BRANDING;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return DEFAULT_BRANDING;
    const parsed = JSON.parse(raw) as Partial<Branding>;
    return {
      ...DEFAULT_BRANDING,
      ...parsed,
      header_ar: parsed.header_ar?.length === HEADER_LINES ? parsed.header_ar : [...DEFAULT_HEADER_AR],
      header_en: parsed.header_en?.length === HEADER_LINES ? parsed.header_en : [...DEFAULT_HEADER_EN],
    };
  } catch {
    return DEFAULT_BRANDING;
  }
}

export function cacheBranding(branding: Branding): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(branding));
  } catch {
    // a full or blocked quota must never break the sign-in screen
  }
}

/**
 * Read the letterhead from the server, falling back to the cache.
 *
 * The two public routes are what make this callable from the sign-in screen: no
 * session exists yet, and a login page that cannot render its own letterhead is
 * not acceptable.
 */
export async function loadBranding(): Promise<Branding> {
  try {
    const fresh = await api.branding();
    cacheBranding(fresh);
    return fresh;
  } catch (error) {
    if (error instanceof OfflineError) return cachedBranding();
    return cachedBranding();
  }
}

/** The logo URL, fingerprinted with its checksum so a re-upload is picked up. */
export function logoUrl(logo: BrandingLogo | null): string | null {
  if (!logo) return null;
  return `${API_BASE}/branding/logo?sha=${encodeURIComponent(logo.sha256.slice(0, 16))}`;
}

/** Subscribe to the letterhead; re-reads when the settings page saves. */
export function useBranding(): Branding {
  const [branding, setBranding] = useState<Branding>(DEFAULT_BRANDING);

  useEffect(() => {
    let cancelled = false;
    void loadBranding().then((value) => {
      if (!cancelled) setBranding(value);
    });
    const onChange = () => setBranding(cachedBranding());
    window.addEventListener('sbdma:branding', onChange);
    return () => {
      cancelled = true;
      window.removeEventListener('sbdma:branding', onChange);
    };
  }, []);

  return branding;
}

/** Announce that the letterhead changed, so every mounted copy re-renders. */
export function publishBranding(branding: Branding): void {
  cacheBranding(branding);
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('sbdma:branding'));
  }
}
