'use client';

import { useEffect, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { useApp } from './AppProvider';

/**
 * Apache ECharts wrapper.
 * Registered lazily on the client so the bundle stays server-renderable and the
 * chart library never blocks first paint (Skeleton shows until init completes).
 */
export function Chart({ option, height = 300 }: { option: EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<import('echarts').ECharts | null>(null);
  const { theme } = useApp();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!ref.current) return;
      const echarts = await import('echarts');
      if (cancelled || !ref.current) return;
      if (!inst.current) {
        inst.current = echarts.init(ref.current, undefined, { renderer: 'canvas' });
      }
      inst.current.setOption(
        {
          animationDuration: 420,
          textStyle: { fontFamily: 'system-ui, Segoe UI, Tahoma, sans-serif' },
          backgroundColor: 'transparent',
          ...option,
        },
        true,
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [option, theme]);

  // A chart can be created while its card is still 0 px wide (hidden tab, or a
  // card that mounts before layout settles). Re-measure whenever the box
  // changes so the canvas is never left blank.
  useEffect(() => {
    if (!ref.current) return;
    const box = ref.current;
    const observer = new ResizeObserver(() => {
      if (box.clientWidth > 0) inst.current?.resize();
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onResize = () => inst.current?.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      inst.current?.dispose();
      inst.current = null;
    };
  }, []);

  return <div ref={ref} style={{ width: '100%', height }} role="img" aria-label="Scientific chart" />;
}

export function chartThemeColors(theme: 'light' | 'dark') {
  const dark = theme === 'dark';
  return {
    axis: dark ? '#99a2b0' : '#697488',
    split: dark ? '#2b323a' : '#eceef2',
    text: dark ? '#e8ebef' : '#1d2127',
    brand: dark ? '#4d9e91' : '#21695e',
    accent: '#b45309',
    fail: dark ? '#f87171' : '#b42318',
    pass: dark ? '#4ade80' : '#16794f',
    grid: dark ? '#3a424c' : '#dfe4ea',
  };
}

export const baseAxis = (c: ReturnType<typeof chartThemeColors>) => ({
  axisLine: { lineStyle: { color: c.grid } },
  axisTick: { lineStyle: { color: c.grid } },
  axisLabel: { color: c.axis, fontSize: 10.5 },
  splitLine: { lineStyle: { color: c.split, type: 'dashed' as const } },
});

export const baseTooltip = {
  backgroundColor: 'rgba(24,28,33,.94)',
  borderWidth: 0,
  textStyle: { color: '#fff', fontSize: 11 },
  confine: true,
};
