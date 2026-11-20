// Forecast: next 24 h in 3-hour steps, rain pause explanation, next-hour estimate
// against the limit, and the model card in plain words (FR-UI-02, FR-UI-10).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import { useForecast, useModel, useStatus } from "../api/hooks";
import type { ModelInfo, Prediction } from "../api/types";
import { useAuth } from "../app/Auth";
import BarChart from "../charts/BarChart";
import ChartFrame from "../charts/ChartFrame";
import LineChart from "../charts/LineChart";
import Icon, { type IconName } from "../components/Icon";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/I18n";
import { fmtDateTime, fmtHour, fmtSmart, isoDaysAgo } from "../lib/time";
import { moistureDomain } from "../lib/chart";
import { wxLabel } from "./Garden";
import s from "./Forecast.module.css";

function wxIcon(c: string | null): IconName {
  if (c === "Rain" || c === "Drizzle") return "rain";
  if (c === "Thunderstorm") return "storm";
  if (c === "Clouds") return "cloud";
  if (c === "Clear") return "sun";
  return "haze";
}

export default function Forecast() {
  const { t, lang } = useI18n();
  const fc = useForecast();
  const st = useStatus();
  const rp = fc.data?.rain_pause;
  const steps = fc.data?.steps.filter((x) => new Date(x.for).getTime() >= Date.now() - 3 * 3600000).slice(0, 9) ?? [];
  const thr = st.data?.settings.moisture_threshold ?? 30;

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("forecast")}</h1>
        {fc.data && (
          <p>{fc.data.stale ? t("forecast_stale", { time: fmtSmart(fc.data.retrieved_at, lang) }) : t("forecast_updated", { time: fmtSmart(fc.data.retrieved_at, lang) })}</p>
        )}
      </div>

      {rp && (
        <section className={`${s.rain} ${rp.active ? s.rainOn : ""}`} aria-labelledby="rp-h">
          <Icon name={rp.active ? "pause" : "rain"} size={28} />
          <div className="stack" style={{ gap: 6 }}>
            <h2 id="rp-h" className={s.rainTitle}>{rp.active ? t("rain_pause_on", { hours: rp.window_h }) : t("rain_pause_off")}</h2>
            {!rp.stale && <p>{t("rain_pause_now", { hours: rp.window_h, pop: Math.round(rp.pop_max ?? 0), mm: (rp.rain_mm ?? 0).toFixed(1) })}</p>}
            <p className="muted small">{t("rain_pause_rule", { pop: rp.rule.pop_pct, mm: rp.rule.rain_mm, hours: rp.rule.window_h })}</p>
          </div>
        </section>
      )}

      <section aria-labelledby="steps-h" className="stack">
        <h2 id="steps-h">{t("next_24h")}</h2>
        {steps.length === 0 ? (
          <p className="muted">{t("forecast_none")}</p>
        ) : (
          <ol className={s.steps} tabIndex={0} aria-label={t("next_24h")}>
            {steps.map((x) => (
              <li key={x.id} className={s.step}>
                <span className={s.stepTime}>{fmtHour(x.for, lang)}</span>
                <Icon name={wxIcon(x.condition)} size={30} />
                <span className={s.stepCond}>{wxLabel(x.condition, t)}</span>
                <span className={s.stepTemp}>{x.temperature_c != null ? `${Math.round(x.temperature_c)}°` : "—"}</span>
                <dl className={s.stepKv}>
                  <dt><Icon name="drop" size={14} /><span className="visually-hidden">{t("chance_of_rain")}</span></dt><dd>{Math.round(x.pop_pct ?? 0)}%</dd>
                  <dt><Icon name="rain" size={14} /><span className="visually-hidden">{t("rain_amount")}</span></dt><dd>{x.rain_3h_mm.toFixed(1)} mm</dd>
                  <dt><Icon name="humidity" size={14} /><span className="visually-hidden">{t("humidity")}</span></dt><dd>{Math.round(x.humidity_pct ?? 0)}%</dd>
                </dl>
              </li>
            ))}
          </ol>
        )}
      </section>

      {steps.length > 0 && (
        <div className="grid-2">
          {/* Two small panels sharing the time axis, never a dual axis. */}
          <div className="panel">
            <ChartFrame headingLevel={3} title={t("chance_of_rain")}
              table={<StepsTable steps={steps} field="pop_pct" unit="%" />}>
              <BarChart ariaLabel={t("chance_of_rain")} unit="%" color="var(--series-1)" max={100} showValues="max"
                refLine={rp ? { value: rp.rule.pop_pct, label: `${rp.rule.pop_pct}%` } : undefined}
                bars={steps.map((x) => ({ key: x.for, label: fmtHour(x.for, lang), value: Math.round(x.pop_pct ?? 0), tip: fmtDateTime(x.for, lang) }))} />
            </ChartFrame>
          </div>
          <div className="panel">
            <ChartFrame headingLevel={3} title={`${t("rain_amount")} (mm / 3 h)`}
              table={<StepsTable steps={steps} field="rain_3h_mm" unit="mm" />}>
              <BarChart ariaLabel={t("rain_amount")} unit="mm" color="var(--series-1)" showValues="max" max={Math.max(5, ...steps.map((x) => x.rain_3h_mm * 1.15))}
                bars={steps.map((x) => ({ key: x.for, label: fmtHour(x.for, lang), value: Number(x.rain_3h_mm.toFixed(1)), tip: fmtDateTime(x.for, lang) }))} />
            </ChartFrame>
          </div>
        </div>
      )}

      <ModelSection threshold={thr} />
    </div>
  );
}

function StepsTable({ steps, field, unit }: { steps: { id: number; for: string; pop_pct: number | null; rain_3h_mm: number }[]; field: "pop_pct" | "rain_3h_mm"; unit: string }) {
  const { t, lang } = useI18n();
  return (
    <table className="data">
      <thead><tr><th>{t("time")}</th><th className="num">{unit}</th></tr></thead>
      <tbody>{steps.map((x) => <tr key={x.id}><td>{fmtDateTime(x.for, lang)}</td><td className="num">{(x[field] ?? 0).toFixed(field === "pop_pct" ? 0 : 1)}</td></tr>)}</tbody>
    </table>
  );
}

function ModelSection({ threshold }: { threshold: number }) {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const model = useModel();
  const [from] = useState(() => isoDaysAgo(2));
  const preds = useQuery({ queryKey: ["predictions", from], queryFn: () => api.get<{ items: Prediction[] }>(`/api/v1/predictions?from=${encodeURIComponent(from)}`) });
  const retrain = useMutation({
    mutationFn: () => api.post<{ queued?: boolean; model?: ModelInfo }>("/api/v1/model/retrain"),
    onSuccess: (r) => {
      toast(r.queued ? t("retrain_queued") : t("retrained"), "good");
      void qc.invalidateQueries({ queryKey: ["model"] });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("error_generic"), "critical"),
  });
  const m = model.data;
  const a = m?.active ?? m?.versions[0] ?? null;
  const items = preds.data?.items ?? [];

  return (
    <section className="grid-2" aria-labelledby="model-h">
      <div className={`panel ${s.model}`}>
        <h2 id="model-h">{t("model_card")}</h2>
        {!m ? (
          <p className="muted">{t("loading")}</p>
        ) : !a ? (
          <>
            <p>{t("model_none")}</p>
            <p className="muted small">{m.phase.day > 0 ? t("phase_cold_start", { day: m.phase.day, of: m.phase.of }) : t("phase_not_started")}</p>
          </>
        ) : (
          <>
            <StatusBadge level={a.is_active ? "good" : "none"} label={a.is_active ? t("model_active") : t("model_inactive")} />
            <p className={s.plain}>{t("model_plain", { mae: a.mae.toFixed(1), base: a.baseline_mae.toFixed(1) })}</p>
            {!a.is_active && <p>{t("model_inactive_why")}</p>}
            <dl className={s.kv}>
              <dt>MAE</dt><dd>{a.mae.toFixed(2)} <span className="muted">/ {a.baseline_mae.toFixed(2)}</span></dd>
              <dt>RMSE</dt><dd>{a.rmse.toFixed(2)} <span className="muted">/ {a.baseline_rmse.toFixed(2)}</span></dd>
              <dt>{t("version_n", { v: "" }).trim()}</dt><dd>{a.version}</dd>
            </dl>
            <p className="muted small">{t("model_trained", { time: fmtSmart(a.trained_at, lang), rows: a.rows })}</p>
            {m.live && m.live.n > 0 && <p className="small">{t("model_live", { mae: m.live.mae?.toFixed(1), n: m.live.n })}</p>}
          </>
        )}
        {can("retrain") && (
          <div className="row">
            <button className="btn btn-quiet" onClick={() => retrain.mutate()} disabled={retrain.isPending}>
              <Icon name="refresh" size={18} />{t("retrain")}
            </button>
          </div>
        )}
      </div>
      <div className="panel">
        <ChartFrame headingLevel={3} title={t("prediction_chart")}
          legend={[{ label: t("actual"), color: "var(--ink)" }, { label: t("estimate"), color: "var(--series-1)", kind: "dash" }]}
          table={
            <table className="data">
              <thead><tr><th>{t("time")}</th><th className="num">{t("estimate")}</th><th className="num">{t("actual")}</th></tr></thead>
              <tbody>{[...items].reverse().map((p) => <tr key={p.id}><td>{fmtDateTime(p.target_at, lang)}</td><td className="num">{p.predicted_vwc.toFixed(1)}</td><td className="num">{p.actual_vwc?.toFixed(1) ?? "—"}</td></tr>)}</tbody>
            </table>
          }>
          {items.length === 0 ? (
            <p className="muted">{t("no_data_range")}</p>
          ) : (
            <LineChart ariaLabel={t("prediction_chart")} x={items.map((p) => new Date(p.target_at))} unit="%" height={220}
              yDomain={moistureDomain(items.map((p) => ({ mean: p.actual_vwc, S1: p.predicted_vwc, S2: null, S3: null })), threshold, threshold)}
              series={[
                { key: "actual", label: t("actual"), color: "var(--ink)", values: items.map((p) => p.actual_vwc) },
                { key: "pred", label: t("estimate"), color: "var(--series-1)", dash: "6 4", values: items.map((p) => p.predicted_vwc) },
              ]}
              refs={[{ value: threshold, label: t("limit_line", { v: threshold }), dash: "dashed" }]} />
          )}
        </ChartFrame>
      </div>
    </section>
  );
}
