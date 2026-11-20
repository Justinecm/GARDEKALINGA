// Records: watering, power, decisions, online/offline periods and the audit
// trail, with date and type filters and CSV export (FR-UI-07, FR-UI-03, TC6/TC7).
import { useMemo, useState } from "react";
import { qs } from "../api/client";
import { useList, useReadings } from "../api/hooks";
import type { AuditItem, Decision, Period, PowerEvent, ReadingPoint, WateringEvent } from "../api/types";
import { useAuth } from "../app/Auth";
import ChartFrame from "../charts/ChartFrame";
import LineChart from "../charts/LineChart";
import { useWidth } from "../charts/useWidth";
import Icon from "../components/Icon";
import Segmented from "../components/Segmented";
import { useI18n } from "../i18n/I18n";
import type { StringKey } from "../i18n/strings";
import { fmtDateTime, fmtDuration, isoDaysAgo } from "../lib/time";

type Tab = "watering" | "power" | "decisions" | "device" | "audit";
type Range = "1" | "7" | "30";

export default function Records() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("watering");
  const [range, setRange] = useState<Range>("7");
  const from = useMemo(() => isoDaysAgo(Number(range)), [range]);
  const tabs: { id: Tab; label: StringKey }[] = [
    { id: "watering", label: "tab_watering" },
    { id: "power", label: "tab_power" },
    { id: "decisions", label: "tab_decisions" },
    { id: "device", label: "tab_device" },
    ...(can("audit") ? [{ id: "audit" as Tab, label: "tab_audit" as StringKey }] : []),
  ];

  return (
    <div className="page">
      <div className="page-head"><h1>{t("logs_title")}</h1></div>
      <div className="tabs" role="tablist" aria-label={t("logs_title")}>
        {tabs.map((x) => (
          <button key={x.id} id={`tab-${x.id}`} role="tab" className="tab" aria-selected={tab === x.id} aria-controls={`panel-${x.id}`} onClick={() => setTab(x.id)}>
            {t(x.label)}
          </button>
        ))}
      </div>
      <Segmented label={t("time")} hideLabel value={range} onChange={setRange}
        options={[{ value: "1", label: t("range_24h") }, { value: "7", label: t("range_7d") }, { value: "30", label: t("range_30d") }]} />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "watering" && <WateringTab from={from} />}
        {tab === "power" && <PowerTab from={from} range={range} />}
        {tab === "decisions" && <DecisionsTab from={from} />}
        {tab === "device" && <DeviceTab from={from} />}
        {tab === "audit" && <AuditTab from={from} />}
      </div>
    </div>
  );
}

function Csv({ name, from }: { name: string; from: string }) {
  const { t } = useI18n();
  const { can } = useAuth();
  if (!can("export")) return null;
  return (
    <a className="btn btn-quiet btn-sm" href={`/api/v1/reports/${name}.csv${qs({ from })}`} download>
      <Icon name="download" size={16} />{t("export_csv")}
    </a>
  );
}

function Empty() {
  const { t } = useI18n();
  return <p className="muted" style={{ padding: "24px 4px" }}>{t("no_records")}</p>;
}

function WateringTab({ from }: { from: string }) {
  const { t, lang } = useI18n();
  const [source, setSource] = useState("");
  const { data } = useList<WateringEvent>("watering", "/api/v1/events/watering" + qs({ from, source }));
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div style={{ minWidth: 220 }}>
          <label className="label small" htmlFor="w-src">{t("col_source")}</label>
          <select id="w-src" className="select" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t("filter_all")}</option>
            {["auto", "manual", "offline_failsafe", "sensor_fault_schedule"].map((v) => <option key={v} value={v}>{t(`src_${v}` as StringKey)}</option>)}
          </select>
        </div>
        <Csv name="irrigation" from={from} />
      </div>
      {!data ? <p className="muted">{t("loading")}</p> : data.items.length === 0 ? <Empty /> : (
        <div className="table-wrap">
          <table className="data stack-sm">
            <thead><tr><th>{t("col_start")}</th><th>{t("col_source")}</th><th>{t("col_who")}</th><th className="num">{t("col_duration")}</th><th className="num">{t("col_interlock")}</th><th className="num">{t("col_gap")}</th><th>{t("col_end")}</th></tr></thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id}>
                  <td data-label={t("col_start")}><strong>{fmtDateTime(e.valve_open_at, lang)}</strong></td>
                  <td data-label={t("col_source")}>{t(`src_${e.source}` as StringKey)}</td>
                  <td data-label={t("col_who")}>{e.user ?? "—"}</td>
                  <td data-label={t("col_duration")} className="num">{fmtDuration(e.duration_s, lang)}</td>
                  <td data-label={t("col_interlock")} className="num">{e.interlock_ms != null ? `${e.interlock_ms} ms` : "—"}</td>
                  <td data-label={t("col_gap")} className="num">{e.close_gap_ms != null ? `${e.close_gap_ms} ms` : "—"}</td>
                  <td data-label={t("col_end")}>{e.ended_reason ? t(`end_${e.ended_reason}` as StringKey) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SourceBand({ points }: { points: ReadingPoint[] }) {
  const { t } = useI18n();
  const [ref, width] = useWidth<HTMLDivElement>();
  if (points.length < 2) return null;
  const t0 = new Date(points[0].t).getTime();
  const t1 = new Date(points[points.length - 1].t).getTime();
  const left = 36;
  const iw = Math.max(40, width - 36 - 54);
  const xOf = (iso: string) => left + ((new Date(iso).getTime() - t0) / Math.max(1, t1 - t0)) * iw;
  return (
    <div ref={ref}>
      <svg width={width} height={22} aria-hidden="true">
        {points.slice(0, -1).map((p, i) => (
          <rect key={p.t} x={xOf(p.t)} y={4} width={Math.max(1, xOf(points[i + 1].t) - xOf(p.t))} height={12}
            fill={p.source === "solar" ? "var(--paint)" : p.source === "adapter" ? "var(--ink-muted)" : "var(--hairline)"} />
        ))}
        <text x={left - 6} y={14} textAnchor="end" style={{ fill: "var(--ink-muted)", font: "600 11px var(--font)" }}>{t("power")}</text>
      </svg>
    </div>
  );
}

function PowerTab({ from, range }: { from: string; range: Range }) {
  const { t, lang } = useI18n();
  const { data } = useList<PowerEvent>("power", "/api/v1/events/power" + qs({ from }));
  const readings = useReadings(from, undefined, range === "30" ? "hour" : "raw");
  const pts = (readings.data?.points ?? []).filter((p) => p.supply_v != null);
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="panel">
        <ChartFrame title={t("voltage_chart")} subtitle={t("volt_lines")}
          legend={[{ label: t("power_solar"), color: "var(--paint)", kind: "box" }, { label: t("power_adapter"), color: "var(--ink-muted)", kind: "box" }]}
          table={
            <table className="data">
              <thead><tr><th>{t("time")}</th><th className="num">{t("col_voltage")}</th><th>{t("power")}</th></tr></thead>
              <tbody>{[...pts].reverse().map((p) => <tr key={p.t}><td>{fmtDateTime(p.t, lang)}</td><td className="num">{p.supply_v?.toFixed(2)} V</td><td>{p.source ? t(`power_${p.source}` as StringKey) : "—"}</td></tr>)}</tbody>
            </table>
          }>
          {pts.length === 0 ? <Empty /> : (
            <div>
              {range !== "30" && <SourceBand points={pts} />}
              <LineChart ariaLabel={t("voltage_chart")} x={pts.map((p) => new Date(p.t))} unit="V" yDomain={[11, 14]} height={220} decimals={2}
                series={[{ key: "v", label: t("supply_voltage"), color: "var(--series-1)", values: pts.map((p) => p.supply_v), endLabel: false }]}
                refs={[{ value: 11.6, label: "11.6 V", dash: "dashed" }, { value: 12.8, label: "12.8 V", dash: "dotted" }]} />
            </div>
          )}
        </ChartFrame>
      </div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ fontSize: "var(--fs-20)" }}>{t("tab_power")}</h2>
        <Csv name="power" from={from} />
      </div>
      {!data ? <p className="muted">{t("loading")}</p> : data.items.length === 0 ? <Empty /> : (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>{t("time")}</th><th>{t("col_from")}</th><th>{t("col_to")}</th><th className="num">{t("col_voltage")}</th></tr></thead>
            <tbody>{data.items.map((p) => (
              <tr key={p.id}><td>{fmtDateTime(p.at, lang)}</td><td>{t(`power_${p.from}` as StringKey)}</td><td>{t(`power_${p.to}` as StringKey)}</td><td className="num">{p.v?.toFixed(2) ?? "—"} V</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DecisionsTab({ from }: { from: string }) {
  const { t, lang } = useI18n();
  const [reason, setReason] = useState("");
  const { data } = useList<Decision>("decisions", "/api/v1/decisions" + qs({ from, reason, limit: 1000 }));
  const reasons = ["moist_enough", "cold_start_threshold", "predicted_below_threshold", "probe_below_min", "rain_pause", "soak", "already_watering", "sensor_fault_schedule", "prediction_unavailable", "forecast_stale"];
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div style={{ minWidth: 240 }}>
          <label className="label small" htmlFor="d-r">{t("col_reason")}</label>
          <select id="d-r" className="select" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">{t("filter_all")}</option>
            {reasons.map((r) => <option key={r} value={r}>{t(`r_${r}` as StringKey)}</option>)}
          </select>
        </div>
        <Csv name="decisions" from={from} />
      </div>
      {!data ? <p className="muted">{t("loading")}</p> : data.items.length === 0 ? <Empty /> : (
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="data">
            <thead><tr><th>{t("time")}</th><th>{t("col_action")}</th><th>{t("col_reason")}</th><th className="num">{t("col_mean")}</th><th className="num">{t("estimate")}</th><th className="num">{t("chance_of_rain")}</th><th className="num">{t("rain_amount")}</th><th>{t("col_phase")}</th></tr></thead>
            <tbody>
              {data.items.map((d) => (
                <tr key={d.id}>
                  <td>{fmtDateTime(d.at, lang)}</td>
                  <td>{d.action === "water" ? <strong>{t("act_water")} {d.duration_s ? `(${fmtDuration(d.duration_s, lang)})` : ""}</strong> : t("act_none")}</td>
                  <td>{t(`r_${d.reason}` as StringKey)}</td>
                  <td className="num">{d.inputs.mean_vwc != null ? `${Number(d.inputs.mean_vwc).toFixed(1)}%` : "—"}</td>
                  <td className="num">{d.inputs.predicted_vwc != null ? `${Number(d.inputs.predicted_vwc).toFixed(1)}%` : "—"}</td>
                  <td className="num">{d.inputs.rain?.pop_max != null ? `${Math.round(d.inputs.rain.pop_max)}%` : "—"}</td>
                  <td className="num">{d.inputs.rain?.rain_mm != null ? `${d.inputs.rain.rain_mm.toFixed(1)} mm` : "—"}</td>
                  <td>{d.phase === "predictive" ? t("phase_label_pred") : t("phase_label_cold")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DeviceTab({ from }: { from: string }) {
  const { t, lang } = useI18n();
  const { data } = useList<Period>("periods", "/api/v1/device/periods" + qs({ from }));
  return !data ? <p className="muted">{t("loading")}</p> : data.items.length === 0 ? <Empty /> : (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th>{t("col_status")}</th><th>{t("col_start")}</th><th>{t("col_ended")}</th><th className="num">{t("col_duration")}</th></tr></thead>
        <tbody>{data.items.map((p) => (
          <tr key={p.id}>
            <td><span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 600 }}>
              <span className="status-dot" style={{ background: p.status === "online" ? "var(--good)" : "var(--critical)" }} aria-hidden="true" />
              {p.status === "online" ? t("online") : t("offline")}</span></td>
            <td>{fmtDateTime(p.started_at, lang)}</td>
            <td>{p.ended_at ? fmtDateTime(p.ended_at, lang) : t("now")}</td>
            <td className="num">{p.duration_s >= 3600 ? `${(p.duration_s / 3600).toFixed(1)} h` : fmtDuration(p.duration_s, lang)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function AuditTab({ from }: { from: string }) {
  const { t, lang } = useI18n();
  const { data } = useList<AuditItem>("audit", "/api/v1/audit" + qs({ from }));
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}><Csv name="audit" from={from} /></div>
      {!data ? <p className="muted">{t("loading")}</p> : data.items.length === 0 ? <Empty /> : (
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="data">
            <thead><tr><th>{t("time")}</th><th>{t("col_who")}</th><th>{t("col_what")}</th><th>{t("col_target")}</th><th>{t("details")}</th></tr></thead>
            <tbody>{data.items.map((a) => (
              <tr key={a.id}>
                <td>{fmtDateTime(a.at, lang)}</td><td>{a.user ?? t("system")}</td><td>{a.action}</td><td>{a.target ?? "—"}</td>
                <td style={{ whiteSpace: "normal", minWidth: 220, maxWidth: 420 }} className="small">{a.after ? JSON.stringify(a.after) : ""}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
