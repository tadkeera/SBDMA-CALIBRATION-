/**
 * Data-source mode.
 *
 * `auto`  — use the server; if it is unreachable fall back to the browser cache.
 * `server` — the server is mandatory; being offline is surfaced as an error.
 *
 * The mode never changes what a user may do: authorisation is enforced by the
 * backend. The browser cache is a read-only snapshot.
 */
export type DataMode = 'auto' | 'server';

export const DATA_MODE: DataMode =
  (process.env.NEXT_PUBLIC_DATA_MODE as DataMode | undefined) ?? 'auto';

export interface SourceStamp {
  source: 'server' | 'cache';
  at: string;
}

export const SOURCE_LABEL: Record<SourceStamp['source'], { ar: string; en: string }> = {
  server: { ar: 'بيانات الخادم', en: 'Live server data' },
  cache: { ar: 'نسخة مخزّنة — الخادم غير متاح', en: 'Cached copy — server unavailable' },
};
