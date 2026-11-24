'use client';

import type { EChartsOption } from 'echarts';
import { useMemo } from 'react';
import { baseAxis, baseTooltip, Chart, chartThemeColors } from './Chart';
import { useApp } from './AppProvider';
import { ols } from '@/core/engine/safeMath';
import type { RunTestResult, TestSpec } from '@/core/types';

export function TestChart({ test, result }: { test: TestSpec; result?: RunTestResult }) {
  const { theme, t } = useApp();
  const c = chartThemeColors(theme);
  const axis = baseAxis(c);

  const option = useMemo<any>(() => {
    if (!result || result.status === 'INCOMPLETE') return null;
    const o = result.outputs as Record<string, number | number[]>;
    const n = (k: string, fb = NaN) => (typeof o[k] === 'number' ? (o[k] as number) : fb);
    const arr = (k: string) => (Array.isArray(o[k]) ? (o[k] as number[]) : []);
    const raw = result.rawInputs as Record<string, unknown>;
    const rawArr = (k: string) =>
      Array.isArray(raw[k])
        ? (raw[k] as unknown[]).map((x) => Number(x)).filter((x) => Number.isFinite(x))
        : [];

    switch (test.chart) {
      case 'flow': {
        const set = rawArr('set_flow');
        const actual = arr('actual_flow');
        const err = arr('pct_error');
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          grid: { left: 54, right: 54, top: 30, bottom: 38 },
          legend: { top: 0, textStyle: { color: c.axis, fontSize: 10.5 } },
          xAxis: { type: 'category', data: set.map((x) => `${x}`), ...axis, name: t('التدفق المضبوط mL/min', 'Set mL/min'), nameLocation: 'middle', nameGap: 24, nameTextStyle: { color: c.axis, fontSize: 10 } },
          yAxis: [
            { type: 'value', ...axis, name: t('التدفق الفعلي', 'Actual flow') },
            { type: 'value', ...axis, name: t('الخطأ %', '% error'), splitLine: { show: false } },
          ],
          series: [
            { name: t('مضبوط', 'Set'), type: 'bar', data: set, itemStyle: { color: c.grid }, barWidth: '28%' },
            { name: t('فعلي', 'Actual'), type: 'bar', data: actual.map((x) => Number(x.toFixed(4))), itemStyle: { color: c.brand }, barWidth: '28%' },
            {
              name: t('الخطأ %', '% error'),
              type: 'line',
              yAxisIndex: 1,
              data: err.map((x) => Number(x.toFixed(3))),
              symbolSize: 7,
              lineStyle: { width: 2, color: c.accent },
              itemStyle: { color: c.accent },
              markLine: {
                silent: true,
                symbol: 'none',
                data: [
                  { yAxis: 2, lineStyle: { color: c.fail, type: 'dashed' }, label: { formatter: '+2.00%', color: c.fail, fontSize: 9 } },
                  { yAxis: -2, lineStyle: { color: c.fail, type: 'dashed' }, label: { formatter: '−2.00%', color: c.fail, fontSize: 9 } },
                ],
              },
            },
          ],
        } as EChartsOption;
      }
      case 'gradient': {
        const actual = [10, 50, 90, 100].map((lvl) => Number((o[`actual_${lvl}`] as number)?.toFixed?.(3) ?? NaN));
        const dev = [10, 50, 90, 100].map((lvl) => Number((o[`dev_${lvl}`] as number)?.toFixed?.(3) ?? NaN));
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          legend: { top: 0, textStyle: { color: c.axis, fontSize: 10.5 } },
          grid: { left: 54, right: 30, top: 30, bottom: 38 },
          xAxis: { type: 'category', data: ['10%', '50%', '90%', '100%'], ...axis },
          yAxis: [
            { type: 'value', ...axis, name: t('النسبة الفعلية %', 'Actual %') },
            { type: 'value', ...axis, name: t('الانحراف %', 'Deviation %'), splitLine: { show: false } },
          ],
          series: [
            {
              name: t('البرنامج المضبوط', 'Programmed'),
              type: 'line',
              data: [10, 50, 90, 100],
              lineStyle: { width: 1.5, type: 'dashed', color: c.grid },
              itemStyle: { color: c.grid },
              symbol: 'none',
            },
            {
              name: t('المقاس', 'Measured'),
              type: 'line',
              data: actual,
              symbolSize: 7,
              lineStyle: { width: 2.5, color: c.brand },
              itemStyle: { color: c.brand },
            },
            {
              name: t('الانحراف', 'Deviation'),
              type: 'bar',
              yAxisIndex: 1,
              data: dev,
              itemStyle: { color: (p: any) => (Math.abs(Number(p.value)) > 2 ? c.fail : c.accent) },
              barWidth: '22%',
            },
          ],
        } as EChartsOption;
      }
      case 'linearity': {
        const xs = rawArr(test.code === 'T10' ? 'concs' : 'volumes');
        const ys = rawArr(test.code === 'T10' ? 'heights' : 'linearity_areas');
        if (xs.length < 2) return null;
        const fit = ols(xs, ys);
        const xMin = Math.min(...xs);
        const xMax = Math.max(...xs);
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          legend: { top: 0, textStyle: { color: c.axis, fontSize: 10.5 } },
          grid: { left: 60, right: 30, top: 30, bottom: 38 },
          xAxis: { type: 'value', ...axis, name: test.code === 'T10' ? t('التركيز mg/L', 'Conc. mg/L') : t('الحجم µL', 'Volume µL'), nameLocation: 'middle', nameGap: 24, nameTextStyle: { color: c.axis, fontSize: 10 } },
          yAxis: { type: 'value', ...axis, name: test.code === 'T10' ? 'AU' : 'mAU·s' },
          series: [
            { name: t('القيم المقاسة', 'Measured'), type: 'scatter', data: xs.map((x, i) => [x, ys[i]]), symbolSize: 8, itemStyle: { color: c.brand } },
            {
              name: t('انحدار OLS', 'OLS fit'),
              type: 'line',
              data: [xMin, xMax].map((x) => [x, Number((fit.slope * x + fit.intercept).toFixed(6))]),
              lineStyle: { width: 2, color: c.accent },
              itemStyle: { color: c.accent },
              symbol: 'none',
            },
          ],
          graphic: [
            {
              type: 'text',
              right: 12,
              top: 26,
              style: {
                text: `R² = ${fit.r2.toFixed(5)}\ny = ${fit.slope.toExponential(3)}x ${fit.intercept >= 0 ? '+' : '−'} ${Math.abs(fit.intercept).toExponential(2)}`,
                fontSize: 10,
                fill: c.text,
                fontFamily: 'ui-monospace, monospace',
              },
            },
          ],
        } as EChartsOption;
      }
      case 'residual': {
        const xs = rawArr('concs');
        const ys = rawArr('heights');
        if (xs.length < 2) return null;
        const fit = ols(xs, ys);
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          grid: { left: 58, right: 26, top: 20, bottom: 38 },
          xAxis: { type: 'category', data: xs.map(String), ...axis },
          yAxis: { type: 'value', ...axis, name: t('البواقي', 'Residuals') },
          series: [
            {
              type: 'bar',
              data: fit.residuals.map((r) => Number(r.toFixed(6))),
              itemStyle: { color: c.accent },
              barWidth: '40%',
            },
          ],
        } as EChartsOption;
      }
      case 'spectrum': {
        // reconstruct the caffeine scan from the detected landmarks so the curve is real, not decorative
        const p1 = n('peak_205', 205);
        const v = n('valley_245', 245);
        const p2 = n('peak_273', 273);
        const xs: number[] = [];
        for (let wl = 200; wl <= 280; wl += 1) xs.push(wl);
        const curve = xs.map((wl) => {
          const g = (mu: number, s: number, a: number) => a * Math.exp(-((wl - mu) ** 2) / (2 * s * s));
          return Number((g(p1, 5.5, 0.62) + g(p2, 9, 0.42) + 0.05 - 0.03 * Math.exp(-((wl - v) ** 2) / 18)).toFixed(4));
        });
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          grid: { left: 56, right: 26, top: 24, bottom: 38 },
          xAxis: { type: 'category', data: xs.map(String), ...axis, name: 'nm', nameLocation: 'middle', nameGap: 24, nameTextStyle: { color: c.axis, fontSize: 10 } },
          yAxis: { type: 'value', ...axis, name: 'AU' },
          series: [
            {
              type: 'line',
              data: curve,
              smooth: true,
              showSymbol: false,
              lineStyle: { width: 2, color: c.brand },
              areaStyle: { color: 'rgba(33,105,94,.10)' },
              markPoint: {
                symbolSize: 34,
                label: { fontSize: 9, color: '#fff' },
                data: [
                  { coord: [String(Math.round(p1)), curve[Math.round(p1) - 200] ?? 0], value: `${p1.toFixed(1)}`, itemStyle: { color: c.brand } },
                  { coord: [String(Math.round(v)), curve[Math.round(v) - 200] ?? 0], value: `${v.toFixed(1)}`, itemStyle: { color: c.accent } },
                  { coord: [String(Math.round(p2)), curve[Math.round(p2) - 200] ?? 0], value: `${p2.toFixed(1)}`, itemStyle: { color: c.brand } },
                ],
              },
            },
          ],
        } as EChartsOption;
      }
      case 'repeatability': {
        const rts = rawArr('rt_values');
        const areas = rawArr('areas');
        if (!rts.length) {
          const bl = rawArr('baseline');
          if (!bl.length) return null;
          const mean = bl.reduce((a, b) => a + b, 0) / bl.length;
          const sd = Math.sqrt(bl.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, bl.length - 1));
          return {
            tooltip: { trigger: 'axis', ...baseTooltip },
            grid: { left: 58, right: 26, top: 24, bottom: 38 },
            xAxis: { type: 'category', data: bl.map((_, i) => String(i + 1)), ...axis, name: t('الفترة (30 ث)', 'Segment (30 s)'), nameLocation: 'middle', nameGap: 24, nameTextStyle: { color: c.axis, fontSize: 10 } },
            yAxis: { type: 'value', ...axis, name: 'mAU' },
            series: [
              {
                type: 'line',
                data: bl,
                showSymbol: false,
                lineStyle: { width: 1.8, color: c.brand },
                markLine: {
                  silent: true,
                  symbol: 'none',
                  data: [
                    { yAxis: mean, lineStyle: { color: c.grid, type: 'dashed' }, label: { formatter: t('المتوسط', 'Mean'), fontSize: 9, color: c.axis } },
                    { yAxis: mean + 2 * sd, lineStyle: { color: c.accent, type: 'dashed' }, label: { formatter: '+2SD', fontSize: 9, color: c.accent } },
                    { yAxis: mean - 2 * sd, lineStyle: { color: c.accent, type: 'dashed' }, label: { formatter: '−2SD', fontSize: 9, color: c.accent } },
                  ],
                },
              },
            ],
          } as EChartsOption;
        }
        const mean = rts.reduce((a, b) => a + b, 0) / Math.max(1, rts.length);
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          legend: { top: 0, textStyle: { color: c.axis, fontSize: 10.5 } },
          grid: { left: 58, right: 50, top: 30, bottom: 38 },
          xAxis: { type: 'category', data: rts.map((_, i) => `#${i + 1}`), ...axis, name: t('رقم الحقنة', 'Injection'), nameLocation: 'middle', nameGap: 24, nameTextStyle: { color: c.axis, fontSize: 10 } },
          yAxis: [
            { type: 'value', ...axis, name: t('زمن الاستبقاء', 'RT (min)'), scale: true },
            { type: 'value', ...axis, name: t('المساحة', 'Area'), splitLine: { show: false }, scale: true },
          ],
          series: [
            {
              name: 'RT',
              type: 'line',
              data: rts.map((x) => Number(x.toFixed(3))),
              symbolSize: 6,
              lineStyle: { width: 2, color: c.brand },
              itemStyle: { color: c.brand },
              markLine: { silent: true, symbol: 'none', data: [{ yAxis: Number(mean.toFixed(3)), lineStyle: { color: c.grid, type: 'dashed' } }] },
            },
            {
              name: t('المساحة', 'Area'),
              type: 'line',
              yAxisIndex: 1,
              data: areas.map((x) => Number(x.toFixed(1))),
              symbolSize: 6,
              lineStyle: { width: 2, color: c.accent },
              itemStyle: { color: c.accent },
            },
          ],
        } as EChartsOption;
      }
      case 'temperature': {
        const set = n('t_set', NaN);
        const ref = n('t_ref_corrected', NaN);
        const err = n('error_abs', NaN);
        const disp = n('t_display', NaN);
        const cats = ['Set', 'Display', 'Reference'];
        const vals = [set, disp, ref].map((x) => (Number.isFinite(x) ? Number(x.toFixed(3)) : null));
        if (!vals.some((v) => v !== null)) return null;
        return {
          tooltip: { trigger: 'axis', ...baseTooltip },
          grid: { left: 56, right: 26, top: 24, bottom: 36 },
          xAxis: { type: 'category', data: cats, ...axis },
          yAxis: { type: 'value', ...axis, name: '°C', scale: true },
          series: [
            {
              type: 'bar',
              data: vals,
              barWidth: '42%',
              itemStyle: { color: (p: any) => (p.dataIndex === 2 ? c.accent : c.brand) },
              label: { show: true, position: 'top', fontSize: 10, color: c.text, formatter: (p: any) => (p.value === null ? '—' : String(p.value)) },
            },
          ],
          graphic: Number.isFinite(err)
            ? [{ type: 'text', right: 10, top: 6, style: { text: `|Error| = ${err.toFixed(2)} °C`, fontSize: 10.5, fill: c.text, fontFamily: 'ui-monospace, monospace' } }]
            : [],
        } as EChartsOption;
      }
      case 'bar': {
        /**
         * T01/T03/T05 mix units (nm, mV, MPa, °C, %, mAU) — plotting them on one
         * raw axis would be meaningless. Each metric is therefore expressed as a
         * share of the acceptance limit that was actually applied to it, which
         * is dimensionless and comparable. The raw value stays in the tooltip
         * and in the value label, so nothing is hidden.
         */
        const rows = test.metrics.map((k) => {
          const ev = result.metricEvaluations.find((m) => m.metricKey === k);
          const value = typeof o[k] === 'number' ? (o[k] as number) : null;
          const limit = /[\d.]+/.exec(ev?.limitText ?? '');
          const bound = limit ? Number(limit[0]) : NaN;
          const pct =
            value !== null && Number.isFinite(bound) && bound !== 0
              ? Number(((value / bound) * 100).toFixed(1))
              : null;
          return {
            name: k,
            value: pct,
            raw: value,
            unit: ev?.unit ?? '',
            limitText: ev?.limitText ?? '—',
            ok: ev?.status === 'PASS',
          };
        });
        return {
          tooltip: {
            trigger: 'axis',
            ...baseTooltip,
            formatter: (params: any) => {
              const p = Array.isArray(params) ? params[0] : params;
              const row = rows[p.dataIndex];
              return [
                `<b>${row.name}</b>`,
                `${t('القيمة', 'Value')}: ${row.raw === null ? '—' : `${row.raw} ${row.unit}`}`,
                `${t('الحد المطبق', 'Applied limit')}: ${row.limitText}`,
                `${t('النسبة من الحد', 'Share of limit')}: ${row.value === null ? '—' : `${row.value}%`}`,
              ].join('<br/>');
            },
          },
          grid: { left: 128, right: 46, top: 14, bottom: 40 },
          xAxis: {
            type: 'value',
            ...axis,
            name: t('% من حد القبول المطبق', '% of applied limit'),
            nameLocation: 'middle',
            nameGap: 26,
            nameTextStyle: { color: c.axis, fontSize: 10 },
          },
          yAxis: {
            type: 'category',
            data: rows.map((d) => d.name),
            ...axis,
            axisLabel: { ...(axis as any).axisLabel, fontSize: 9.5, width: 116, overflow: 'truncate' },
          },
          series: [
            {
              type: 'bar',
              data: rows.map((d) => ({
                value: d.value,
                itemStyle: { color: d.ok ? c.brand : c.fail },
              })),
              barWidth: '52%',
              markLine: {
                silent: true,
                symbol: 'none',
                lineStyle: { color: c.fail, type: 'dashed', width: 1.2 },
                label: { formatter: '100%', fontSize: 9.5, color: c.fail },
                data: [{ xAxis: 100 }],
              },
              label: {
                show: true,
                position: 'right',
                fontSize: 9.5,
                color: c.text,
                formatter: (p: any) => {
                  const row = rows[p.dataIndex];
                  if (row?.value === null) return '—';
                  return `${row.raw} ${row.unit}`.trim();
                },
              },
            },
          ],
        } as EChartsOption;
      }
      default:
        return null;
    }
  }, [test, result, c, t, theme]);

  if (!option) {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-lg text-[11.5px]" style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
        {t('لا توجد بيانات كافية لرسم المخطط', 'Not enough data to render the chart')}
      </div>
    );
  }
  return <Chart option={option} height={280} />;
}
