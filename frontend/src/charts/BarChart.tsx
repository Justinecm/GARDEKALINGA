// Columns: <= 24 px wide, 4 px rounded data-end, square at the baseline, single baseline.
import { scaleBand, scaleLinear } from "d3-scale";
import { useState } from "react";
import s from "./Chart.module.css";
import { useWidth } from "./useWidth";

export interface Bar { key: string; label: string; value: number | null; tip?: string }

interface Props {
  bars: Bar[];
  unit: string;
  color: string;
  height?: number;
  ariaLabel: string;
  max?: number;
  refLine?: { value: number; label: string };
  showValues?: "last" | "max" | "none";
}

const M = { top: 20, right: 12, bottom: 24, left: 34 };

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  if (h <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

export default function BarChart({ bars, unit, color, height = 180, ariaLabel, max, refLine, showValues = "max" }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const iw = Math.max(60, width - M.left - M.right);
  const ih = height - M.top - M.bottom;
  const x = scaleBand<string>().domain(bars.map((b) => b.key)).range([0, iw]).paddingInner(0.25);
  const top = max ?? Math.max(1, ...bars.map((b) => b.value ?? 0), refLine?.value ?? 0) * 1.12;
  const y = scaleLinear().domain([0, top]).range([ih, 0]).nice();
  const bw = Math.min(24, x.bandwidth());
  const maxIdx = bars.reduce((best, b, i) => ((b.value ?? -1) > (bars[best]?.value ?? -1) ? i : best), 0);
  const labelEvery = Math.ceil(bars.length / Math.max(2, Math.floor(iw / 46)));

  return (
    <div ref={ref} className={s.plot} role="group" aria-label={ariaLabel} aria-roledescription="chart" tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") setHover((h) => Math.min(bars.length - 1, (h ?? -1) + 1));
        if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? bars.length) - 1));
        if (e.key === "Escape") setHover(null);
      }}
      onBlur={() => setHover(null)}>
      <svg width={width} height={height} className={s.svg} aria-hidden="true">
        <g transform={`translate(${M.left},${M.top})`}>
          <g className={s.grid}>
            {y.ticks(4).map((v) => <line key={v} x1={0} x2={iw} y1={y(v)} y2={y(v)} />)}
          </g>
          <g className={s.axis}>
            {y.ticks(4).map((v) => <text key={v} x={-8} y={y(v)} dy="0.32em" textAnchor="end">{v}</text>)}
            <text x={-8} y={-10} textAnchor="end">{unit}</text>
            {bars.map((b, i) => (i % labelEvery === 0 || i === bars.length - 1) && (
              <text key={b.key} x={(x(b.key) ?? 0) + x.bandwidth() / 2} y={ih + 17} textAnchor="middle">{b.label}</text>
            ))}
          </g>
          {refLine && (
            <g>
              <line x1={0} x2={iw} y1={y(refLine.value)} y2={y(refLine.value)} className={s.ref} strokeDasharray="6 4" />
              <text x={4} y={y(refLine.value) - 5} className={s.refLabel}>{refLine.label}</text>
            </g>
          )}
          {bars.map((b, i) => {
            const bx = (x(b.key) ?? 0) + (x.bandwidth() - bw) / 2;
            const v = b.value ?? 0;
            const by = y(v);
            const show = (showValues === "max" && i === maxIdx && v > 0) || (showValues === "last" && i === bars.length - 1) || hover === i;
            return (
              <g key={b.key}>
                <path d={roundedTop(bx, by, bw, ih - by, 4)} fill={color} opacity={hover == null || hover === i ? 1 : 0.55} />
                {show && b.value != null && (
                  <text x={bx + bw / 2} y={by - 5} textAnchor="middle" className={s.endLabel}>{Number(b.value.toFixed(1))}</text>
                )}
                <rect x={x(b.key)} y={0} width={x.bandwidth()} height={ih} fill="transparent"
                  onPointerEnter={() => setHover(i)} onPointerDown={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                  <title>{b.tip ?? `${b.label}: ${b.value ?? "—"} ${unit}`}</title>
                </rect>
              </g>
            );
          })}
          <line x1={0} x2={iw} y1={ih} y2={ih} stroke="var(--hairline)" />
        </g>
      </svg>
      {hover != null && bars[hover] && (
        <div className={s.tooltip} role="status" style={{ left: Math.min(Math.max(0, (x(bars[hover].key) ?? 0) + M.left - 60), width - 170) }}>
          <strong>{bars[hover].label}</strong>
          <div className={s.tipRow}><span>{bars[hover].tip ?? ""}</span><span>{bars[hover].value ?? "—"} {unit}</span></div>
        </div>
      )}
    </div>
  );
}
