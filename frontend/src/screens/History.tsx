// History: soil moisture per plot and average, threshold, watering events,
// 24 h / 7 days / 30 days / custom, a table view of the same data (FR-UI-04).
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import { useReadings } from "../api/hooks";
import type { WaterUseDay } from "../api/types";
import { useAuth } from "../app/Auth";
import BarChart from "../charts/BarChart";
import ChartFrame from "../charts/ChartFrame";
import LineChart from "../charts/LineChart";
import Icon from "../components/Icon";
import Segmented from "../components/Segmented";
import { useI18n } from "../i18n/I18n";
import { moistureDomain } from "../lib/chart";
import { fmtDateTime, fmtDay, fmtTime, isoDaysAgo, manilaDateInput, manilaDayStartIso } from "../lib/time";

type Range = "24h" | "7d" | "30d" | "custom";


export default function History() {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const [range, setRange] = useState<Range>("24h");
  const [cFrom, setCFrom] = useState(manilaDateInput(new Date(Date.now() - 3 * 86400000)));
  const [cTo, setCTo] = useState(manilaDateInput());
  const [from, to] = useMemo(() => {
    if (range === "custom") return [manilaDayStartIso(cFrom), new Date(new Date(manilaDayStartIso(cTo)).getTime() + 86400000).toISOString()];
    return [isoDaysAgo(range === "24h" ? 1 : range === "7d" ? 7 : 30), undefined];
  }, [range, cFrom, cTo]);
  const { data, isLoading } = useReadings(from, to);
  const water = useQuery({
    queryKey: ["water-use"],
    queryFn: () => api.get<{ items: WaterUseDay[]; daily_water_l: number }>("/api/v1/reports/water-use?days=30"),
    staleTime: 5 * 60_000,
  });

  const x = data?.points.map((p) => new Date(p.t)) ?? [];
  const series = data
    ? [
        { key: "mean", label: t("average"), color: "var(--ink)", width: 2.5, values: data.points.map((p) => p.mean) },
        { key: "S1", label: t("plot_n", { n: 1 }), color: "var(--series-1)", values: data.points.map((p) => p.S1) },
        { key: "S2", label: t("plot_n", { n: 2 }), color: "var(--series-2)", values: data.points.map((p) => p.S2) },
        { key: "S3", label: t("plot_n", { n: 3 }), color: "var(--series-3)", values: data.points.map((p) => p.S3) },
      ]
    : [];
  const fmtT = (iso: string) => (data?.bucket === "day" ? fmtDay(iso, lang) : fmtDateTime(iso, lang));
  const exportHref = "/api/v1/reports/readings.csv" + qs({ from, to });

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("history_title")}</h1>
      </div>
      <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
        <Segmented label={t("time")} hideLabel value={range} onChange={setRange}
          options={[
            { value: "24h", label: t("range_24h") },
            { value: "7d", label: t("range_7d") },
            { value: "30d", label: t("range_30d") },
            { value: "custom", label: t("range_custom") },
          ]} />
        {range === "custom" && (
          <div className="row">
            <div>
              <label className="label small" htmlFor="h-from">{t("from")}</label>
              <input id="h-from" type="date" className="input" value={cFrom} max={cTo} onChange={(e) => setCFrom(e.target.value)} />
            </div>
            <div>
              <label className="label small" htmlFor="h-to">{t("to")}</label>
              <input id="h-to" type="date" className="input" value={cTo} min={cFrom} max={manilaDateInput()} onChange={(e) => setCTo(e.target.value)} />
            </div>
          </div>
        )}
      </div>

      <div className="panel">
        {isLoading || !data ? (
          <p className="muted">{t("loading")}</p>
        ) : (
          <ChartFrame
            title={t("soil_moisture")}
            subtitle={`${fmtDateTime(data.from, lang)} – ${fmtDateTime(data.to, lang)}`}
            legend={[
              ...series.map((sr) => ({ label: sr.label, color: sr.color, width: sr.width === 2.5 ? 3.5 : 3 })),
              { label: t("limit_line", { v: data.threshold }), color: "var(--chart-ref)", kind: "dash" as const },
              { label: t("min_line", { v: data.probe_min }), color: "var(--chart-ref)", kind: "dot" as const },
            ]}
            actions={can("export") ? <a className="btn btn-quiet btn-sm" href={exportHref} download><Icon name="download" size={16} />{t("export_csv")}</a> : undefined}
            table={
              <table className="data">
                <thead>
                  <tr><th>{t("time")}</th><th className="num">{t("average")}</th><th className="num">{t("plot_n", { n: 1 })}</th><th className="num">{t("plot_n", { n: 2 })}</th><th className="num">{t("plot_n", { n: 3 })}</th><th className="num">{t("supply_voltage")}</th></tr>
                </thead>
                <tbody>
                  {[...data.points].reverse().map((p) => (
                    <tr key={p.t}>
                      <td>{fmtT(p.t)}</td>
                      <td className="num">{p.mean?.toFixed(1) ?? "—"}</td>
                      <td className="num">{p.S1?.toFixed(1) ?? t("sensor_problem")}</td>
                      <td className="num">{p.S2?.toFixed(1) ?? t("sensor_problem")}</td>
                      <td className="num">{p.S3?.toFixed(1) ?? t("sensor_problem")}</td>
                      <td className="num">{p.supply_v?.toFixed(2) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          >
            {data.points.length === 0 ? (
              <p className="muted" style={{ padding: 24 }}>{t("no_data_range")}</p>
            ) : (
              <LineChart
                ariaLabel={`${t("soil_moisture")}: ${t("average")}, ${t("plot_n", { n: 1 })}, ${t("plot_n", { n: 2 })}, ${t("plot_n", { n: 3 })}`}
                x={x}
                unit="%"
                height={300}
                yDomain={moistureDomain(data.points, data.probe_min, data.threshold)}
                series={series}
                refs={[
                  { value: data.threshold, label: t("limit_line", { v: data.threshold }), dash: "dashed" },
                  { value: data.probe_min, label: t("min_line", { v: data.probe_min }), dash: "dotted" },
                ]}
                markers={data.watering.filter((e) => e.valve_open_at).map((e) => ({
                  t: new Date(e.valve_open_at as string),
                  label: `${t("watering_marks")}: ${fmtDateTime(e.valve_open_at, lang)}, ${t(`src_${e.source}` as never)}, ${Math.round((e.duration_s ?? 0) / 60 * 10) / 10} min`,
                }))}
              />
            )}
          </ChartFrame>
        )}
        {data && data.watering.length > 0 && (
          <p className="muted small" style={{ marginTop: 8 }}>
            <Icon name="drop" size={14} style={{ display: "inline", verticalAlign: "-2px", color: "var(--drum)" }} /> {t("watering_marks")}: {data.watering.length} · {fmtTime(data.watering[data.watering.length - 1].valve_open_at, lang)}
          </p>
        )}
      </div>

      <div className="panel">
        {water.data ? (
          <ChartFrame
            title={t("water_use")}
            subtitle={`${t("range_30d")} · ${t("f_flow_rate_lpm")} ${water.data.items[0]?.flow_rate_lpm ?? "—"} L/min`}
            legend={[
              { label: t("litres"), color: "var(--series-1)", kind: "box" },
              { label: `${t("f_daily_water_l")}: ${water.data.daily_water_l} L`, color: "var(--chart-ref)", kind: "dash" },
            ]}
            table={
              <table className="data">
                <thead><tr><th>{t("time")}</th><th className="num">{t("litres")}</th><th className="num">{t("col_duration")}</th></tr></thead>
                <tbody>
                  {[...water.data.items].reverse().map((d) => (
                    <tr key={d.day}><td>{fmtDay(d.day + "T00:00:00+08:00", lang)}</td><td className="num">{d.litres.toFixed(1)}</td><td className="num">{Math.round(d.pump_seconds / 60)} min</td></tr>
                  ))}
                </tbody>
              </table>
            }
          >
            <BarChart
              ariaLabel={t("water_use")}
              unit="L"
              color="var(--series-1)"
              bars={water.data.items.map((d) => ({ key: d.day, label: d.day.slice(8), value: d.litres, tip: fmtDay(d.day + "T00:00:00+08:00", lang) }))}
              refLine={{ value: water.data.daily_water_l, label: "" }}
            />
          </ChartFrame>
        ) : (
          <p className="muted">{t("loading")}</p>
        )}
      </div>
    </div>
  );
}
