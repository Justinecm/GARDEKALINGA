// Title, legend, and the "Show as table" toggle every chart needs (NFR-USE-04).
import { useState, type ReactNode } from "react";
import { useI18n } from "../i18n/I18n";
import Icon from "../components/Icon";
import s from "./Chart.module.css";

export interface LegendItem { label: string; color: string; kind?: "line" | "dash" | "dot" | "box"; width?: number }

interface Props {
  title: string;
  subtitle?: ReactNode;
  legend?: LegendItem[];
  table: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  headingLevel?: 2 | 3;
}

export default function ChartFrame({ title, subtitle, legend, table, children, actions, headingLevel = 2 }: Props) {
  const { t } = useI18n();
  const [asTable, setAsTable] = useState(false);
  const H = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className={s.frame} aria-label={title}>
      <div className={s.head}>
        <div>
          <H className={s.title}>{title}</H>
          {subtitle && <p className={s.sub}>{subtitle}</p>}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {actions}
          <button type="button" className={`btn btn-quiet btn-sm ${s.toggle}`} onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
            <Icon name={asTable ? "chart" : "list"} size={16} />
            {asTable ? t("show_chart") : t("show_table")}
          </button>
        </div>
      </div>
      {legend && legend.length > 1 && !asTable && (
        <ul className={s.legend}>
          {legend.map((l) => (
            <li key={l.label}>
              <span
                aria-hidden="true"
                className={`${l.kind === "box" ? s.swatchBox : s.swatch} ${l.kind === "dash" ? s.swatchDash : ""} ${l.kind === "dot" ? s.swatchDot : ""}`}
                style={l.kind === "box" ? { background: l.color } : { borderTopColor: l.color, borderTopWidth: l.width ?? 3 }}
              />
              {l.label}
            </li>
          ))}
        </ul>
      )}
      {asTable ? <div className="table-wrap" style={{ maxHeight: 420 }}>{table}</div> : children}
    </section>
  );
}
