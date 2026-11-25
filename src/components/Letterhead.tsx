'use client';

/**
 * The official letterhead: Arabic on the right, English on the left, the logo
 * centred exactly between them, ruled off with a formal divider.
 *
 * Three sizes, one design:
 *   * `report` — the full band, for the sign-in screen and every printed page;
 *   * `compact` — logo plus the first and last line, for the application shell
 *     where a four-line block twice over would crowd out the work;
 *   * `logo` — the mark alone, for tight corners.
 *
 * The same component renders all three so the proportions cannot drift apart.
 */

import type { CSSProperties } from 'react';

import {
  DEFAULT_HEADER_AR,
  DEFAULT_HEADER_EN,
  logoUrl,
  useBranding,
  type Branding,
} from '@/core/branding';

type Variant = 'report' | 'compact' | 'logo';

export function Letterhead({
  variant = 'report',
  branding,
  onLight = false,
  style,
}: {
  variant?: Variant;
  /** Pass a value to render a specific letterhead (settings preview, tests). */
  branding?: Branding;
  /** For dark backgrounds: the English block clears to white, Arabic stays upright. */
  onLight?: boolean;
  style?: CSSProperties;
}) {
  const live = useBranding();
  const data = branding ?? live;
  const src = logoUrl(data.logo);

  const arabic = data.header_ar?.length ? data.header_ar : [...DEFAULT_HEADER_AR];
  const english = data.header_en?.length ? data.header_en : [...DEFAULT_HEADER_EN];

  const textColour = onLight ? 'rgba(255,255,255,0.92)' : 'var(--text)';
  const mutedColour = onLight ? 'rgba(255,255,255,0.72)' : 'var(--text-muted)';

  const line = (text: string, align: 'right' | 'left', index: number, total: number) => (
    <div
      key={`${align}-${index}`}
      style={{
        // the outermost line is the agency itself, so it carries the weight
        fontWeight: index === 0 ? 700 : 500,
        fontSize: index === 0 ? '0.86rem' : '0.78rem',
        lineHeight: 1.5,
        textAlign: align,
        color: index === total - 1 ? mutedColour : textColour,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        direction: align === 'right' ? 'rtl' : 'ltr',
      }}
      title={text}
    >
      {text}
    </div>
  );

  if (variant === 'logo') {
    if (!src) {
      return (
        <div
          aria-label="SBDMA"
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: 'var(--brand)',
            color: '#fff',
            display: 'grid',
            placeItems: 'center',
            fontWeight: 700,
            fontSize: '0.7rem',
            letterSpacing: '0.02em',
            ...style,
          }}
        >
          SBDMA
        </div>
      );
    }
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <img
        src={src}
        alt="شعار المختبر — Laboratory logo"
        style={{ height: 38, width: 'auto', objectFit: 'contain', ...style }}
      />
    );
  }

  if (variant === 'compact') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, ...style }}>
        <Letterhead variant="logo" branding={data} onLight={onLight} />
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: '0.74rem',
              fontWeight: 600,
              color: textColour,
              direction: 'rtl',
              whiteSpace: 'nowrap',
            }}
          >
            {arabic[0]}
          </div>
          <div
            style={{
              fontSize: '0.66rem',
              color: mutedColour,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: 190,
            }}
            title={english.join(' · ')}
          >
            {english[0]}
          </div>
        </div>
      </div>
    );
  }

  return (
    <header
      className="letterhead"
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) auto minmax(0, 1fr)',
        alignItems: 'center',
        gap: 14,
        padding: '10px 2px 8px',
        ...style,
      }}
    >
      {/* right: the Arabic block */}
      <div style={{ display: 'grid', gap: 1, justifyItems: 'end', minWidth: 0 }}>
        {arabic.map((text, index) => line(text, 'right', index, arabic.length))}
      </div>

      {/* centre: the mark, exactly between the two blocks */}
      <div style={{ display: 'grid', placeItems: 'center', minWidth: 64 }}>
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt="شعار المختبر — Laboratory logo"
            style={{ maxHeight: 58, maxWidth: 92, objectFit: 'contain' }}
          />
        ) : (
          <div
            aria-label="لم يُرفع شعار بعد"
            style={{
              width: 60,
              height: 44,
              borderRadius: 10,
              border: `1px dashed ${onLight ? 'rgba(255,255,255,0.35)' : 'var(--border)'}`,
            }}
          />
        )}
      </div>

      {/* left: the English block */}
      <div style={{ display: 'grid', gap: 1, justifyItems: 'start', minWidth: 0 }}>
        {english.map((text, index) => line(text, 'left', index, english.length))}
      </div>

      {/* the divider: a brand rule with a hairline beneath it */}
      <div style={{ gridColumn: '1 / -1', marginTop: 8 }}>
        <div style={{ height: 2, background: 'var(--brand)', opacity: onLight ? 0.85 : 1 }} />
        <div
          style={{
            height: 1,
            background: onLight ? 'rgba(255,255,255,0.25)' : 'var(--border)',
            marginTop: 2,
          }}
        />
      </div>
    </header>
  );
}

/**
 * The letterhead that printing uses.
 *
 * It lives in the shell, so every page prints on agency stationery without each
 * screen having to remember to render a header — and it is hidden on screen, where
 * the page already carries the logo in its own chrome.
 */
export function PrintLetterhead() {
  return (
    <div className="print-only">
      <Letterhead variant="report" />
    </div>
  );
}
