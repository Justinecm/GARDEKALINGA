// Reports (manager, leader): CSV exports and a printable page; TC4 ingestion and
// command latency; the Test bench for TC1, TC2, TC12, TC14 (FR-UI-11, FR-UI-12).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, qs } from "../api/client";
import { useAuth } from "../app/Auth";
import Icon from "../components/Icon";
import Segmented from "../components/Segmented";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/I18n";
import type { StringKey } from "../i18n/strings";
import { fmtSmart, isoDaysAgo, manilaDateInput, manilaDayStartIso } from "../lib/time";

const REPORTS: { name: string; label: StringKey }[] = [
  { name: "irrigation", label: "rep_irrigation" },
  { name: "power", label: "rep_power" },
  { name: "water-use", label: "rep_water_use" },
  { name: "prediction-accuracy", label: "rep_prediction" },
  { name: "ingestion", label: "rep_ingestion" },
  { name: "decisions", label: "rep_decisions" },
  { name: "readings", label: "rep_readings" },
  { name: "audit", label: "rep_audit" },
];

interface Ingestion {
  days: { day: string; by_source: Record<string, number>; total: number; expected: number }[];
  latency: { n: number; max_s: number | null; within_6s: number; mean_s: number | null };
}

export default function Reports() {
  const { t } = useI18n();
  const [fromDay, setFromDay] = useState(manilaDateInput(new Date(Date.now() - 30 * 86400000)));
  const [toDay, setToDay] = useState(manilaDateInput());
  const from = manilaDayStartIso(fromDay);
  const to = new Date(new Date(manilaDayStartIso(toDay)).getTime() + 86400000).toISOString();
  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("reports_title")}</h1>
        <p>{t("reports_lead")}</p>
      </div>
      <section className="panel stack" aria-labelledby="dl-h">
        <h2 id="dl-h" style={{ fontSize: "var(--fs-20)" }}>{t("download")}</h2>
        <div className="row no-print">
          <div><label className="label small" htmlFor="r-from">{t("from")}</label><input id="r-from" className="input" type="date" value={fromDay} max={toDay} onChange={(e) => setFromDay(e.target.value)} /></div>
          <div><label className="label small" htmlFor="r-to">{t("to")}</label><input id="r-to" className="input" type="date" value={toDay} min={fromDay} onChange={(e) => setToDay(e.target.value)} /></div>
          <button className="btn btn-quiet" style={{ alignSelf: "flex-end" }} onClick={() => window.print()}><Icon name="print" size={18} />{t("print")}</button>
        </div>
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
          {REPORTS.map((r) => (
            <li key={r.name}>
              <a className="btn btn-quiet" style={{ width: "100%", justifyContent: "space-between" }} href={`/api/v1/reports/${r.name}.csv${qs({ from, to })}`} download>
                <span>{t(r.label)}</span><Icon name="download" size={18} />
              </a>
            </li>
          ))}
        </ul>
      </section>
      <IngestionPanel />
      <TestBench />
    </div>
  );
}

function IngestionPanel() {
  const { t, lang } = useI18n();
  const [from] = useState(() => isoDaysAgo(7));
  const { data } = useQuery({ queryKey: ["ingestion", from], queryFn: () => api.get<Ingestion>("/api/v1/stats/ingestion" + qs({ from })) });
  if (!data) return null;
  return (
    <section className="grid-2">
      <div className="panel stack">
        <h2 style={{ fontSize: "var(--fs-20)" }}>{t("ingestion_title")}</h2>
        <p className="hint">{t("ingestion_note")}</p>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>{t("time")}</th><th className="num">{t("power_solar")}</th><th className="num">{t("power_adapter")}</th><th className="num">Total</th></tr></thead>
            <tbody>{[...data.days].reverse().map((d) => (
              <tr key={d.day}><td>{d.day}</td><td className="num">{d.by_source.solar ?? 0}</td><td className="num">{d.by_source.adapter ?? 0}</td>
                <td className="num"><strong>{d.total}</strong> / 48</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
      <div className="panel stack">
        <h2 style={{ fontSize: "var(--fs-20)" }}>{t("latency_title")}</h2>
        {data.latency.n > 0 ? (
          <>
            <StatusBadge level={data.latency.within_6s === data.latency.n ? "good" : "warning"}
              label={t("latency_note", { within: data.latency.within_6s, n: data.latency.n, max: data.latency.max_s })} />
            <p className="muted small">mean {data.latency.mean_s} s · {fmtSmart(new Date().toISOString(), lang)}</p>
          </>
        ) : <p className="muted">{t("no_records")}</p>}
      </div>
    </section>
  );
}

type TC = "1" | "2" | "12" | "14";
interface TestItem { id: number; tc: number; trial: number; inputs: Record<string, unknown>; result: Record<string, unknown>; recorded_at: string }

function TestBench() {
  const { t } = useI18n();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [tc, setTc] = useState<TC>("14");
  const { data } = useQuery({ queryKey: ["tests", tc], queryFn: () => api.get<{ items: TestItem[]; summary: Record<string, Record<string, unknown>> }>(`/api/v1/test-records?tc=${tc}`) });
  const [inputs, setInputs] = useState<Record<string, string>>({ sensor: "S1", state: "dry", direction: "solar_to_adapter", expected_v: "11.6" });
  const fields: Record<TC, { key: string; label: StringKey; type?: "select"; options?: { v: string; l: StringKey | string }[] }[]> = {
    "1": [
      { key: "sensor", label: "tb_sensor", type: "select", options: ["S1", "S2", "S3"].map((v) => ({ v, l: v })) },
      { key: "state", label: "tb_state", type: "select", options: [{ v: "dry", l: "tb_dry" }, { v: "moist", l: "tb_moist" }, { v: "saturated", l: "tb_saturated" }] },
      { key: "sensor_vwc", label: "tb_sensor_vwc" },
      { key: "reference_vwc", label: "tb_reference_vwc" },
    ],
    "2": [
      { key: "sensor", label: "tb_sensor", type: "select", options: ["S1", "S2", "S3"].map((v) => ({ v, l: v })) },
      { key: "state", label: "tb_state", type: "select", options: [{ v: "dry", l: "tb_dry" }, { v: "moist", l: "tb_moist" }, { v: "saturated", l: "tb_saturated" }] },
      { key: "long_cable_vwc", label: "tb_long" },
      { key: "short_lead_vwc", label: "tb_short" },
    ],
    "12": [
      { key: "direction", label: "tb_direction", type: "select", options: [{ v: "solar_to_adapter", l: "Solar → wall (11.6 V)" }, { v: "adapter_to_solar", l: "Wall → solar (13.2 V)" }] },
      { key: "expected_v", label: "tb_expected_v" },
      { key: "switched_at_v", label: "tb_switched_v" },
      { key: "latency_ms", label: "tb_latency" },
    ],
    "14": [
      { key: "volume_l", label: "tb_volume" },
      { key: "time_s", label: "tb_time" },
    ],
  };
  const summary = data?.summary[tc] as Record<string, unknown> | undefined;
  const flowMean = summary?.mean_flow_lpm as number | undefined;

  async function addTrial(e: React.FormEvent) {
    e.preventDefault();
    const payload: Record<string, unknown> = {};
    for (const f of fields[tc]) payload[f.key] = f.type === "select" ? inputs[f.key] : Number(inputs[f.key]);
    try {
      await api.post("/api/v1/test-records", { tc_number: Number(tc), inputs: payload });
      void qc.invalidateQueries({ queryKey: ["tests", tc] });
      setInputs((x) => ({ ...x, ...Object.fromEntries(fields[tc].filter((f) => !f.type).map((f) => [f.key, f.key === "expected_v" ? x.expected_v : ""])) }));
    } catch (x) {
      toast(x instanceof ApiError ? x.message : t("error_generic"), "critical");
    }
  }

  async function applyFlow() {
    if (!flowMean) return;
    try {
      await api.post("/api/v1/settings", { flow_rate_lpm: Number(flowMean.toFixed(2)), note: "TC14 flow rate" });
      toast(t("saved", { v: "" }), "good");
    } catch (x) {
      toast(x instanceof ApiError ? x.message : t("error_generic"), "critical");
    }
  }

  const keys = fields[tc].map((f) => f.key);

  return (
    <section className="panel stack" aria-labelledby="tb-h">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 id="tb-h" style={{ fontSize: "var(--fs-20)" }}><Icon name="flask" size={20} style={{ display: "inline", verticalAlign: "-3px" }} /> {t("test_bench")}</h2>
        <a className="btn btn-quiet btn-sm" href={`/api/v1/test-records/${tc}.csv`} download><Icon name="download" size={16} />{t("export_csv")}</a>
      </div>
      <p className="hint">{t("tb_lead")}</p>
      <Segmented label="TC" hideLabel value={tc} onChange={setTc}
        options={[{ value: "1", label: t("tb_tc1") }, { value: "2", label: t("tb_tc2") }, { value: "12", label: t("tb_tc12") }, { value: "14", label: t("tb_tc14") }]} />

      {summary && (
        <div className="well stack" style={{ gap: 6 }}>
          {(tc === "1" || tc === "2") && ((summary.groups as Record<string, unknown>[]) ?? []).map((g, i) => (
            <StatusBadge key={i} level={g.pass ? "good" : "warning"} compact
              label={`${g.sensor} · ${g.state}: ${t("tb_mad", { v: g.mean_abs_diff as number })} (≤ ${g.limit}) · ${t("tb_trials", { n: g.pairs as number })} · ${g.pass ? t("tb_pass") : t("tb_fail")}`} />
          ))}
          {tc === "12" && <span className="small">{t("tb_trials", { n: summary.trials as number })} · {t("tb_latency")}: {String(summary.mean_latency_ms ?? "—")} · ±0.1 V: {summary.all_within_0_1v ? t("tb_pass") : t("tb_fail")}</span>}
          {tc === "14" && flowMean != null && (
            <div className="row">
              <StatusBadge level={summary.within_10pct && summary.enough_trials ? "good" : "warning"} compact
                label={t("tb_flow_mean", { v: flowMean, s: summary.spread_pct as number })} />
              {can("testbench_write") && <button className="btn btn-quiet btn-sm" onClick={applyFlow}>{t("tb_apply_flow")}</button>}
            </div>
          )}
        </div>
      )}

      {can("testbench_write") && (
        <form className="row" style={{ alignItems: "flex-end" }} onSubmit={addTrial}>
          {fields[tc].map((f) => (
            <div key={f.key} style={{ minWidth: 140, flex: "1 1 140px" }}>
              <label className="label small" htmlFor={`tb-${f.key}`}>{f.label.startsWith("tb_") ? t(f.label) : f.label}</label>
              {f.type === "select" ? (
                <select id={`tb-${f.key}`} className="select" value={inputs[f.key] ?? ""} onChange={(e) => setInputs({ ...inputs, [f.key]: e.target.value })}>
                  {f.options?.map((o) => <option key={o.v} value={o.v}>{o.l.startsWith("tb_") ? t(o.l as StringKey) : o.l}</option>)}
                </select>
              ) : (
                <input id={`tb-${f.key}`} className="input num" type="number" step="any" inputMode="decimal" required value={inputs[f.key] ?? ""} onChange={(e) => setInputs({ ...inputs, [f.key]: e.target.value })} />
              )}
            </div>
          ))}
          <button className="btn btn-water" type="submit">{t("tb_add")}</button>
        </form>
      )}

      {data && data.items.length > 0 && (
        <div className="table-wrap" style={{ maxHeight: 360 }}>
          <table className="data">
            <thead><tr><th className="num">#</th>{keys.map((k) => <th key={k}>{k}</th>)}<th>result</th></tr></thead>
            <tbody>{[...data.items].reverse().map((r) => (
              <tr key={r.id}><td className="num">{r.trial}</td>{keys.map((k) => <td key={k}>{String(r.inputs[k] ?? "—")}</td>)}
                <td className="small">{Object.entries(r.result).map(([k, v]) => `${k}: ${v}`).join(", ")}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}
