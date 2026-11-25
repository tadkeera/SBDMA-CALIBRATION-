'use client';

/**
 * إعداد الترويسة — the official report letterhead.
 *
 * One screen, because the letterhead is one artefact: the four Arabic lines, the
 * four English lines, the logo that sits between them, and a preview of exactly
 * what a printed report will carry. The preview *is* the report component, not a
 * mock-up, so what an approver sees here is what the certificate prints.
 *
 * Only `settings.manage` may write. The page says so plainly instead of hiding
 * itself: a QA officer shown a 403 with no explanation will file a support ticket.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Image as ImageIcon, RotateCcw, Save, Trash2, Upload } from 'lucide-react';

import { useApp } from '@/components/AppProvider';
import { Letterhead } from '@/components/Letterhead';
import { Card, Field, Skeleton, Toolbar } from '@/components/ui';
import { ApiError, api } from '@/core/api/client';
import {
  DEFAULT_HEADER_AR,
  DEFAULT_HEADER_EN,
  HEADER_LINES,
  publishBranding,
  type Branding,
} from '@/core/branding';

const ACCEPTED = 'image/png,image/jpeg,image/webp';

export default function SettingsPage() {
  const { t, lang, notify, can } = useApp();
  const allowed = can('settings.manage');

  const [branding, setBranding] = useState<Branding | null>(null);
  const [arabic, setArabic] = useState<string[]>([...DEFAULT_HEADER_AR]);
  const [english, setEnglish] = useState<string[]>([...DEFAULT_HEADER_EN]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'save' | 'logo' | 'reset' | 'remove' | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fresh = await api.branding();
      setBranding(fresh);
      setArabic(fresh.header_ar);
      setEnglish(fresh.header_en);
    } catch (error) {
      notify(
        'error',
        t('تعذّر تحميل إعداد الترويسة', 'Could not load the letterhead'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setLoading(false);
    }
  }, [lang, notify, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(() => {
    if (!branding) return false;
    return (
      branding.header_ar.join('\u0000') !== arabic.join('\u0000') ||
      branding.header_en.join('\u0000') !== english.join('\u0000')
    );
  }, [arabic, branding, english]);

  const preview: Branding = useMemo(
    () => ({
      header_ar: arabic,
      header_en: english,
      is_default: false,
      updated_at: branding?.updated_at ?? null,
      updated_by: branding?.updated_by ?? null,
      logo: branding?.logo ?? null,
    }),
    [arabic, branding, english],
  );

  const accept = (fresh: Branding, message_ar: string, message_en: string) => {
    setBranding(fresh);
    setArabic(fresh.header_ar);
    setEnglish(fresh.header_en);
    publishBranding(fresh);
    notify('success', message_ar, message_en);
  };

  const fail = (error: unknown, message_ar: string, message_en: string) =>
    notify(
      'error',
      message_ar,
      error instanceof ApiError ? error.text(lang) : message_en,
    );

  const save = async () => {
    if (arabic.some((line) => !line.trim()) || english.some((line) => !line.trim())) {
      notify(
        'error',
        'لا يجوز ترك سطر فارغ في الترويسة',
        'No line of the letterhead may be empty',
      );
      return;
    }
    setBusy('save');
    try {
      const fresh = await api.updateBrandingHeader(
        arabic.map((line) => line.trim()),
        english.map((line) => line.trim()),
      );
      accept(fresh, 'حُفظت الترويسة وأُدرجت في السجل', 'Letterhead saved and audited');
    } catch (error) {
      fail(error, 'تعذّر حفظ الترويسة', 'The letterhead could not be saved');
    } finally {
      setBusy(null);
    }
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy('logo');
    try {
      const fresh = await api.uploadBrandingLogo(file);
      accept(fresh, 'رُفع الشعار وأصبح في جميع التقارير', 'Logo uploaded — every report now carries it');
      if (fresh.logo?.converted) {
        notify(
          'info',
          'حُوّل الشعار إلى PNG لضمان طباعته في PDF',
          'The logo was converted to PNG so the PDF can embed it',
        );
      }
    } catch (error) {
      fail(error, 'تعذّر رفع الشعار', 'The logo could not be uploaded');
    } finally {
      setBusy(null);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const removeLogo = async () => {
    setBusy('remove');
    try {
      accept(await api.deleteBrandingLogo(), 'أُزيل الشعار', 'Logo removed');
    } catch (error) {
      fail(error, 'تعذّر إزالة الشعار', 'The logo could not be removed');
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy('reset');
    try {
      accept(
        await api.resetBrandingHeader(),
        'استُعيدت الترويسة الرسمية الافتراضية',
        'The official default letterhead was restored',
      );
    } catch (error) {
      fail(error, 'تعذّرت استعادة الترويسة', 'The letterhead could not be reset');
    } finally {
      setBusy(null);
    }
  };

  const block = (lines: string[], setLines: (value: string[]) => void, side: 'ar' | 'en') => (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ fontWeight: 600, fontSize: '0.86rem' }}>
        {side === 'ar' ? 'السطور العربية (يمين الترويسة)' : 'English lines (left of the letterhead)'}
      </div>
      {Array.from({ length: HEADER_LINES }).map((_, index) => (
        <Field
          key={index}
          label={
            side === 'ar'
              ? `السطر ${index + 1}${index === 0 ? ' — الجهة' : ''}`
              : `Line ${index + 1}${index === 0 ? ' — the authority' : ''}`
          }
        >
          <input
            className="input"
            dir={side === 'ar' ? 'rtl' : 'ltr'}
            maxLength={120}
            value={lines[index] ?? ''}
            disabled={!allowed || busy !== null}
            onChange={(event) => {
              const next = [...lines];
              next[index] = event.target.value;
              setLines(next);
            }}
            aria-label={side === 'ar' ? `السطر العربي ${index + 1}` : `English line ${index + 1}`}
          />
        </Field>
      ))}
    </div>
  );

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: '1.25rem' }}>إعداد الترويسة</h1>
        <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '0.84rem' }}>
          {t(
            'الترويسة الرسمية التي تُطبع أعلى جميع التقارير والشهادات: السطور العربية على اليمين، والإنجليزية على اليسار، والشعار في المنتصف تماماً.',
            'The official letterhead printed atop every report and certificate: Arabic lines on the right, English on the left, the logo exactly between them.',
          )}
        </p>
      </div>

      <Card
        title={t('معاينة الترويسة', 'Letterhead preview')}
        subtitle={t(
          'هذه هي الصورة المطبوعة نفسها التي ستظهر أعلى الشهادة والتقرير',
          'This is the exact component the certificate and the reports print',
        )}
      >
        {loading ? (
          <Skeleton rows={3} />
        ) : (
          <div
            style={{
              border: '1px solid var(--border)',
              borderRadius: 10,
              padding: '6px 14px 12px',
              background: 'var(--surface)',
            }}
          >
            <Letterhead variant="report" branding={preview} />
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', paddingTop: 8 }}>
              {branding?.updated_at
                ? t(
                    `آخر تعديل: ${new Date(branding.updated_at).toLocaleString('ar')} — ${branding.updated_by ?? ''}`,
                    `Last change: ${new Date(branding.updated_at).toLocaleString('en')} — ${branding.updated_by ?? ''}`,
                  )
                : t('لم تعدّل الترويسة بعد — تُستخدم النسخة الرسمية', 'Unchanged — the official defaults are in force')}
            </div>
          </div>
        )}
      </Card>

      <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
        <Card title={t('نصوص الترويسة', 'Letterhead text')}>
          <div style={{ display: 'grid', gap: 18 }}>
            {block(arabic, setArabic, 'ar')}
            {block(english, setEnglish, 'en')}
          </div>
        </Card>

        <div style={{ display: 'grid', gap: 18, alignContent: 'start' }}>
          <Card
            title={t('الشعار الرسمي', 'Official logo')}
            subtitle={t(
              'PNG أو JPEG أو WEBP — حتى 2 ميغابايت. يُحفظ ويظهر في الواجهة وشاشة الدخول وجميع التقارير.',
              'PNG, JPEG or WEBP up to 2 MB. Stored once and shown in the app, on the sign-in screen and on every report.',
            )}
          >
            <div style={{ display: 'grid', gap: 12 }}>
              <div
                style={{
                  display: 'grid',
                  placeItems: 'center',
                  minHeight: 96,
                  border: '1px dashed var(--border)',
                  borderRadius: 10,
                  background: 'var(--surface-2)',
                  padding: 12,
                }}
              >
                <Letterhead variant="logo" branding={preview} style={{ height: 64 }} />
              </div>

              {branding?.logo ? (
                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', display: 'grid', gap: 2 }}>
                  <div>{branding.logo.filename}</div>
                  <div>
                    {branding.logo.content_type} · {(branding.logo.bytes / 1024).toFixed(1)} KB
                    {branding.logo.width ? ` · ${branding.logo.width}×${branding.logo.height}` : ''}
                  </div>
                  <div style={{ wordBreak: 'break-all' }}>
                    SHA-256: {branding.logo.sha256.slice(0, 32)}…
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  {t('لم يُرفع شعار بعد', 'No logo uploaded yet')}
                </div>
              )}

              <input
                ref={fileInput}
                type="file"
                accept={ACCEPTED}
                disabled={!allowed || busy !== null}
                onChange={(event) => void upload(event.target.files?.[0])}
                data-testid="logo-input"
                style={{ display: 'none' }}
              />
              <Toolbar>
                <button
                  className="btn"
                  type="button"
                  disabled={!allowed || busy !== null}
                  onClick={() => fileInput.current?.click()}
                >
                  <Upload size={15} />
                  {busy === 'logo' ? t('جارٍ الرفع…', 'Uploading…') : t('رفع الشعار', 'Upload logo')}
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={!allowed || busy !== null || !branding?.logo}
                  onClick={() => void removeLogo()}
                >
                  <Trash2 size={15} />
                  {t('إزالة', 'Remove')}
                </button>
              </Toolbar>
            </div>
          </Card>

          <Card title={t('الإجراءات', 'Actions')}>
            <Toolbar>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!allowed || busy !== null || !dirty}
                onClick={() => void save()}
              >
                <Save size={15} />
                {busy === 'save' ? t('جارٍ الحفظ…', 'Saving…') : t('حفظ الترويسة', 'Save letterhead')}
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                disabled={!allowed || busy !== null}
                onClick={() => void reset()}
              >
                <RotateCcw size={15} />
                {t('استعادة الافتراضي', 'Restore defaults')}
              </button>
            </Toolbar>
            {!allowed ? (
              <p style={{ marginTop: 10, color: 'var(--warn)', fontSize: '0.8rem' }}>
                <ImageIcon size={13} style={{ verticalAlign: '-2px' }} />{' '}
                {t(
                  'تعديل الترويسة يتطلب صلاحية «إعدادات النظام».',
                  'Editing the letterhead requires the “system settings” permission.',
                )}
              </p>
            ) : (
              <p style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                {t(
                  'كل تعديل يُسجَّل في سجل التدقيق باسمك ووقته، ويُطبَّق فوراً على التقارير التالية.',
                  'Every change is recorded in the audit trail with your name and time, and applies to the next report generated.',
                )}
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
