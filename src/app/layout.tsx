import type { Metadata, Viewport } from 'next';
import './globals.css';
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
    <html lang="ar" dir="rtl">
      <body>
        <AppProvider>
          <Shell>{children}</Shell>
          <Toasts />
        </AppProvider>
      </body>
    </html>
  );
}
