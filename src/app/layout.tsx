import type { Metadata, Viewport } from 'next';
import localFont from 'next/font/local';
import './globals.css';

/**
 * Cairo — the Arabic face the board asked for.
 *
 * Self-hosted rather than fetched from Google: the platform is deployed to a network the
 * laboratory does not control, and a font that arrives from a third party can arrive late
 * or not at all. `next/font/local` fingerprints the file, emits a preload and removes the
 * layout shift that a late webfont causes on a table of thirty inputs.
 *
 * `variable` puts the generated family name on :root, so globals.css can decide *when* it
 * applies: Arabic pages get Cairo, English pages keep the system sans they already had.
 */
const cairo = localFont({
  src: [
    { path: '../fonts/Cairo-Regular.ttf', weight: '400', style: 'normal' },
    { path: '../fonts/Cairo-SemiBold.ttf', weight: '600', style: 'normal' },
    { path: '../fonts/Cairo-Bold.ttf', weight: '700', style: 'normal' },
  ],
  display: 'swap',
  variable: '--font-cairo',
  fallback: ['Segoe UI', 'Tahoma', 'Arial', 'sans-serif'],
});
import { AppProvider } from '@/components/AppProvider';
import { Shell } from '@/components/Shell';
import { Toasts } from '@/components/ui';

export const metadata: Metadata = {
  title: 'SBDMA · نظام إدارة ومعايرة الأجهزة المخبرية',
  description:
    'Laboratory Calibration & OQ Intelligence Platform — Supreme Board of Drugs, ISO/IEC 17025 · 21 CFR Part 11',
  applicationName: 'SBDMA Calibration Platform',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#21695e',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl" className={cairo.variable}>
      <body>
        <AppProvider>
          <Shell>{children}</Shell>
          <Toasts />
        </AppProvider>
      </body>
    </html>
  );
}
