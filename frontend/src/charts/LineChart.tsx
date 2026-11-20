// Line chart drawn as React SVG with d3-scale/d3-shape. One y-axis only. 2 px lines,
// average 2.5 px, labelled reference lines, drop markers on the baseline, crosshair
// tooltip, keyboard stepping through points (arrow keys), direct end labels.
import { extent } from "d3-array";
import { scaleLinear, scaleTime } from "d3-scale";
import { line as d3line } from "d3-shape";
import { useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { useI18n } from "../i18n/I18n";
import { fmtDateTime, fmtHour, fmtTime } from "../lib/time";
import s from "./Chart.module.css";
import { useWidth } from "./useWidth";

export interface Series {
  key: string;
  label: string;
  color: string;
  width?: number;
  dash?: string;
  values: (number | null)[];
  endLabel?: boolean;
}
export interface RefLine { value: number; label: string; dash: "dashed" | "dotted" }
export interface Marker { t: Date; label: string }

interface Props {
  x: Date[];
  series: Series[];
  unit: string;
  yDomain?: [number, number];
  refs?: RefLine[];
  markers?: Marker[];
  height?: number;
  ariaLabel: string;
  decimals?: number;
}

const M = { top: 20, right: 54, bottom: 26, left: 36 };

export default function LineChart({ x, series, unit, yDomain, refs = [], markers = [], height = 240, ariaLabel, decimals = 1 }: Props) {
  const { lang } = useI18n();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const iw = Math.max(80, width - M.left - M.right);
  const ih = height - M.top - M.bottom;

  const xs = useMemo(() => {
    const [a, b] = extent(x) as [Date | undefined, Date | undefined];
    const now = new Date();
    return scaleTime()
      .domain([a ?? new Date(now.getTime() - 86400000), b ?? now])
      .range([0, iw]);
  }, [x, iw]);

  const ys = useMemo(() => {
    let dom = yDomain;
    if (!dom) {
      const vals = series.flatMap((s) => s.values).filter((v): v is number => v != null);
      refs.forEach((r) => vals.push(r.value));
      const lo = Math.min(...vals, 0);
      const hi = Math.max(...vals, 1);
      dom = [Math.floor(lo), Math.ceil(hi + (hi - lo) * 0.08)];
    }
    return scaleLinear().domain(dom).range([ih, 0]).nice();
  }, [series, refs, yDomain, ih]);

  const spanH = x.length > 1 ? (x[x.length - 1].getTime() - x[0].getTime()) / 3600000 : 24;
  const ticksX = xs.ticks(Math.max(2, Math.min(6, Math.floor(iw / 80))));
  const dayFmt = new Intl.DateTimeFormat(lang === "fil" ? "fil-PH" : "en-PH", { month: "short", day: "numeric", timeZone: "Asia/Manila" });
  // Hours for short spans; for longer spans the date at midnight and the hour otherwise.
  const fmtTick = (d: Date) => {
    if (spanH <= 36) return fmtHour(d, lang);
    if (spanH > 24 * 5) return dayFmt.format(d);
    const h = Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false, timeZone: "Asia/Manila" }).format(d)) % 24;
    return h === 0 ? dayFmt.format(d) : fmtHour(d, lang);
  };

  const paths = useMemo(
    () =>
      series.map((sr) => {
        const gen = d3line<number | null>()
          .defined((v) => v != null)
          .x((_v, i) => xs(x[i]))
          .y((v) => ys(v as number));
        return gen(sr.values) ?? "";
      }),
    [series, xs, ys, x],
  );

  function nearest(px: number): number | null {
    if (!x.length) return null;
    const t = xs.invert(px).getTime();
    let best = 0;
    let bd = Infinity;
    for (let i = 0; i < x.length; i++) {
      const d = Math.abs(x[i].getTime() - t);
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    return best;
  }

  function onMove(e: PointerEvent<SVGRectElement>) {
    const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    setHover(nearest(e.clientX - rect.left));
  }

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!x.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      setHover((h) => {
        const cur = h ?? (e.key === "ArrowLeft" ? x.length : -1);
        return Math.max(0, Math.min(x.length - 1, cur + (e.key === "ArrowRight" ? 1 : -1)));
      });
    } else if (e.key === "Home") setHover(0);
    else if (e.key === "End") setHover(x.length - 1);
    else if (e.key === "Escape") setHover(null);
  }

  // End labels: last defined value of each series, nudged apart so they never overlap.
  const ends = useMemo(() => {
    const out = series
      .filter((s) => s.endLabel !== false)
      .map((sr) => {
        let i = sr.values.length - 1;
        while (i >= 0 && sr.values[i] == null) i--;
        return i < 0 ? null : { key: sr.key, label: sr.label, v: sr.values[i] as number, y: ys(sr.values[i] as number), x: xs(x[i]) };
      })
      .filter((e): e is NonNullable<typeof e> => e !== null)
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < out.length; i++) if (out[i].y - out[i - 1].y < 14) out[i].y = out[i - 1].y + 14;
    return out;
  }, [series, xs, ys, x]);

  const hx = hover != null ? xs(x[hover]) : null;
  const tipLeft = hx != null ? Math.min(Math.max(0, hx + M.left - 80), width - 170) : 0;

  return (
    <div
      ref={ref}
      className={s.plot}
      tabIndex={0}
      role="group"
      aria-label={ariaLabel}
      aria-roledescription="chart"
      onKeyDown={onKey}
      onBlur={() => setHover(null)}
    >
      <svg width={width} height={height} className={s.svg} aria-hidden="true">
        <g transform={`translate(${M.left},${M.top})`}>
          <g className={s.grid}>
            {ys.ticks(5).map((v) => (
              <line key={v} x1={0} x2={iw} y1={ys(v)} y2={ys(v)} />
            ))}
          </g>
          <g className={s.axis}>
            {ys.ticks(5).map((v) => (
              <text key={v} x={-8} y={ys(v)} dy="0.32em" textAnchor="end">
                {v}
              </text>
            ))}
            <text x={-8} y={-10} textAnchor="end" className={s.tick}>{unit}</text>
            {ticksX.map((d) => (
              <text key={d.getTime()} x={xs(d)} y={ih + 18} textAnchor="middle">
                {fmtTick(d)}
              </text>
            ))}
          </g>
          {refs.map((r) => (
            <g key={r.label}>
              <line x1={0} x2={iw} y1={ys(r.value)} y2={ys(r.value)} className={s.ref} strokeDasharray={r.dash === "dashed" ? "6 4" : "1.5 4"} strokeLinecap="round" />
              <text x={4} y={ys(r.value) - 5} className={s.refLabel}>{r.label}</text>
            </g>
          ))}
          {series.map((sr, i) => (
            <path key={sr.key} d={paths[i]} fill="none" stroke={sr.color} strokeWidth={sr.width ?? 2} strokeDasharray={sr.dash} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {markers.map((m, i) => {
            const mx = xs(m.t);
            if (mx < -4 || mx > iw + 4) return null;
            return (
              <path key={i} className={s.marker} transform={`translate(${mx},${ih - 2})`} d="M0 -9 C3 -5 4.5 -3 4.5 -1.2 A4.5 4.5 0 0 1 -4.5 -1.2 C-4.5 -3 -3 -5 0 -9Z">
                <title>{m.label}</title>
              </path>
            );
          })}
          {ends.map((e) => (
            <text key={e.key} x={iw + 6} y={e.y} dy="0.32em" className={s.endLabel}>
              {e.v.toFixed(0)}
              {unit === "%" ? "%" : ""}
            </text>
          ))}
          {hx != null && hover != null && (
            <g>
              <line x1={hx} x2={hx} y1={0} y2={ih} className={s.cross} />
              {series.map((sr) =>
                sr.values[hover] == null ? null : (
                  <circle key={sr.key} cx={hx} cy={ys(sr.values[hover] as number)} r={4.5} fill={sr.color} className={s.dot} />
                ),
              )}
            </g>
          )}
          {/* hit target larger than the marks */}
          <rect x={0} y={0} width={iw} height={ih + M.bottom} fill="transparent" onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
        </g>
      </svg>
      {hover != null && x[hover] && (
        <div className={s.tooltip} style={{ left: tipLeft }} role="status">
          <strong>{spanH <= 36 ? fmtTime(x[hover].toISOString(), lang) : fmtDateTime(x[hover].toISOString(), lang)}</strong>
          {series.map((sr) => (
            <div key={sr.key} className={s.tipRow}>
              <span>
                <i aria-hidden="true" style={{ width: 10, height: 3, background: sr.color, display: "inline-block", borderRadius: 2 }} />
                {sr.label}
              </span>
              <span>{sr.values[hover] == null ? "—" : `${(sr.values[hover] as number).toFixed(decimals)}${unit === "%" ? "%" : " " + unit}`}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
