// Garden (home): the live scene, the status sentence, readings, the decision line
// and the one primary action, Water now / Stop watering (FR-UI-01..06).
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { useReadings, useStatus } from "../api/hooks";
import type { CommandView, Level, Probe, Status } from "../api/types";
import { useAuth } from "../app/Auth";
import { useTheme } from "../app/Theme";
import LineChart from "../charts/LineChart";
import Icon, { type IconName } from "../components/Icon";
import Segmented from "../components/Segmented";
import Sheet from "../components/Sheet";
import StatusBadge, { levelColor } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/I18n";
import type { StringKey } from "../i18n/strings";
import GardenScene from "../scene/GardenScene";
import { fmtDuration, fmtSmart, fmtTime, isoDaysAgo } from "../lib/time";
import s from "./Garden.module.css";
import { moistureDomain } from "../lib/chart";

type T = ReturnType<typeof useI18n>["t"];

function leftText(sec: number, t: T): string {
  return sec >= 60 ? t("minutes_n", { n: Math.ceil(sec / 60) }) : `${Math.max(0, Math.round(sec))} s`;
}

function clock(sec: number): string {
  const s = Math.max(0, Math.ceil(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function headline(st: Status, t: T, lang: string, remaining: number): { title: string; sub?: string; help?: string; level: Level; icon: IconName } {
  const w = st.watering;
  if (!st.device || !st.reading) {
    return { title: t("st_no_readings"), help: t("no_readings_help"), level: "none", icon: "clock" };
  }
  if (w.active) {
    return {
      title: t("st_watering", { left: leftText(remaining, t) }),
      sub: w.source ? t(`src_${w.source}` as StringKey) : undefined,
      level: "good",
      icon: "drop",
    };
  }
  if (!st.device.online) {
    return {
      title: t("controller_offline") + ".",
      sub: t("offline_since", { time: fmtSmart(st.device.last_seen_at, lang) }),
      help: t("offline_help"),
      level: "critical",
      icon: "wifi-off",
    };
  }
  const code = st.status.code;
  const title = t(`st_${code}` as StringKey);
  if (code === "sensor_fault") return { title, help: t("fault_help", { am: "6:00 AM", pm: "4:00 PM" }), level: "critical", icon: "alert" };
  let sub: string | undefined;
  if (st.rain_pause.active && (code === "getting_dry" || code === "below_minimum")) sub = t("st_rain_pause", { hours: st.rain_pause.window_h });
  else if (st.soak.active) sub = `${t("st_soaking")} ${t("soak_detail", { time: fmtTime(st.soak.ends_at, lang) })}`;
  else if (code === "below_minimum") {
    const dry = st.reading.probes.find((p) => p.level === "serious");
    if (dry) sub = t("below_min_detail", { plot: t("plot_n", { n: Number(dry.id.slice(1)) }), value: `${Math.round(dry.vwc ?? 0)}%` });
  }
  const next = st.next_check_at ? t("next_check", { time: fmtTime(st.next_check_at, lang) }) : undefined;
  return { title, sub: sub ? `${sub}` : next, help: sub ? next : undefined, level: st.status.level, icon: st.status.level === "good" ? "check" : st.status.level === "warning" ? "drop" : "alert" };
}

function decisionText(st: Status, t: T, lang: string): { text: string; rain: boolean } {
  const d = st.decision;
  if (!d) return { text: t("dec_none_yet"), rain: false };
  const time = fmtTime(d.created_at, lang);
  const vars = {
    time,
    thr: st.settings.moisture_threshold,
    min: st.settings.probe_min_vwc,
    pred: st.prediction ? st.prediction.predicted_vwc.toFixed(1) : "—",
    pop: st.rain_pause.pop_max != null ? Math.round(st.rain_pause.pop_max) : "—",
    mm: st.rain_pause.rain_mm != null ? st.rain_pause.rain_mm.toFixed(1) : "—",
  };
  const key = `dec_${d.reason}` as StringKey;
  return { text: t(key, vars), rain: d.reason === "rain_pause" };
}

export default function Garden() {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const theme = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [cmd, setCmd] = useState<CommandView | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const fast = !!cmd;
  const { data: st, dataUpdatedAt, isLoading, isError, refetch } = useStatus(fast);
  const [now, setNow] = useState(Date.now());
  const [plotOpen, setPlotOpen] = useState<number | null>(null);
  const [waterOpen, setWaterOpen] = useState(false);
  const [soakOpen, setSoakOpen] = useState(false);
  const [minutes, setMinutes] = useState("3");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // Follow the command through the node's real state (state-synchronised UI).
  const live = st?.watering.command && cmd && st.watering.command.id === cmd.id ? st.watering.command : cmd;
  useEffect(() => {
    if (!cmd || !st) return;
    const c = st.watering.command?.id === cmd.id ? st.watering.command : null;
    if (!c) return;
    if (cmd.op === "start" && (st.watering.active || c.phase === "executed")) {
      if (st.watering.active) {
        toast(t("started_toast"), "good");
        setCmd(null);
      }
    } else if (cmd.op === "stop" && !st.watering.active && (c.phase === "executed" || c.phase === "delivered")) {
      toast(t("stopped"), "good");
      setCmd(null);
    }
    if (c.phase === "expired") {
      setFailed(t("not_delivered"));
      setCmd(null);
    } else if (c.phase === "rejected") {
      setFailed(t("rejected", { reason: c.reason ?? "—" }));
      setCmd(null);
    }
  }, [st, cmd, t, toast]);

  const remaining = useMemo(() => {
    if (!st?.watering.active) return 0;
    return Math.max(0, st.watering.remaining_s - (now - dataUpdatedAt) / 1000);
  }, [st, now, dataUpdatedAt]);

  if (isLoading && !st) return <div className="page"><p>{t("loading")}</p></div>;
  if (isError && !st)
    return (
      <div className="page">
        <p>{t("error_generic")}</p>
        <button className="btn btn-quiet" onClick={() => refetch()}>{t("try_again")}</button>
      </div>
    );
  if (!st) return null;

  const head = headline(st, t, lang, remaining);
  const dec = decisionText(st, t, lang);
  const maxMin = Math.max(1, Math.floor(st.settings.max_actuation_sec / 60));
  const durationOptions = [1, 2, 3].filter((m) => m <= maxMin).map((m) => ({ value: String(m), label: t("minutes_n", { n: m }) }));
  const chosenMin = Math.min(Number(minutes), maxMin);
  const blocked = st.watering.start_blocked;
  const canWater = can("water");

  async function start() {
    setBusy(true);
    setFailed(null);
    try {
      const r = await api.post<{ command: CommandView }>("/api/v1/watering/start", { duration_s: chosenMin * 60 });
      setCmd(r.command);
      setWaterOpen(false);
      setSoakOpen(false);
      void qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      setFailed(e instanceof ApiError ? e.message : t("error_generic"));
      setWaterOpen(false);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      const r = await api.post<{ command: CommandView }>("/api/v1/watering/stop");
      setCmd(r.command);
      void qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "critical");
    } finally {
      setBusy(false);
    }
  }

  const probes = st.reading?.probes ?? [];
  const selected: Probe | undefined = plotOpen != null ? probes[plotOpen] : undefined;

  return (
    <div className={s.layout}>
      <div className={s.sceneCol}>
        <GardenScene status={st} period={theme.period} hour={theme.hour} onPlot={setPlotOpen} />

        <div className={s.statusBlock} aria-live="polite">
          <div className={s.headRow}>
            <span className={s.statusIcon} style={{ background: levelColor(head.level) }} aria-hidden="true">
              <Icon name={head.icon} size={20} strokeWidth={2.4} />
            </span>
            <h1 className={s.headline}>{head.title}</h1>
          </div>
          {head.sub && <p className={s.headSub}>{head.sub}</p>}
          {head.help && <p className={s.headHelp}>{head.help}</p>}
        </div>

        {st.reading && (
          <div className={s.readings} role="group" aria-label={t("soil_moisture")}>
            <div className={`${s.reading} ${s.avg}`}>
              <span className={s.rLabel}>{t("average")}</span>
              <span className={s.rValue}>{st.reading.mean != null ? `${Math.round(st.reading.mean)}%` : "—"}</span>
              <span className={s.rBar} aria-hidden="true">
                <i style={{ width: `${Math.min(100, ((st.reading.mean ?? 0) / 50) * 100)}%`, background: "var(--ink)" }} />
              </span>
            </div>
            {probes.map((p, i) => (
              <button key={p.id} type="button" className={s.reading} onClick={() => setPlotOpen(i)}
                aria-label={`${t("plot_n", { n: i + 1 })}: ${p.fault ? t("sensor_problem") : p.installed ? `${Math.round(p.vwc ?? 0)}%, ${t(`lvl_${p.level}` as StringKey)}` : t("not_installed")}`}>
                <span className={s.rLabel}>{t("plot_n", { n: i + 1 })}</span>
                {!p.installed ? (
                  <span className={s.rValueSmall} style={{ color: "var(--ink-muted)" }}>{t("not_installed")}</span>
                ) : p.fault ? (
                  <span className={s.rValueSmall}>{t("sensor_problem")}</span>
                ) : (
                  <span className={s.rValue}>{Math.round(p.vwc ?? 0)}%</span>
                )}
                <span className={s.rBar} aria-hidden="true">
                  <i style={{ width: p.fault ? "100%" : `${Math.min(100, ((p.vwc ?? 0) / 50) * 100)}%`, background: levelColor(p.level) }} />
                </span>
              </button>
            ))}
          </div>
        )}

        <div className={`${s.decision} ${dec.rain ? s.decisionRain : ""}`}>
          <Icon name={dec.rain ? "rain" : "clock"} />
          <div>
            <p>{dec.text}</p>
            {st.reading && <p className="muted small">{t("last_reading_at", { time: fmtSmart(st.reading.recorded_at, lang) })}</p>}
          </div>
        </div>
      </div>

      <aside className={s.side}>
        {/* ---------------- primary action ---------------- */}
        <div className={s.action}>
          {!canWater ? (
            <p className={s.actionNote}>{t("blocked_role")}</p>
          ) : st.watering.active ? (
            <div className={s.wateringRow}>
              <div className={s.wateringInfo}>
                <Icon name="drop" size={24} />
                <span className={s.timeLeft} aria-live="off">{t("watering_left", { left: clock(remaining) })}</span>
              </div>
              <div className={s.ring} aria-hidden="true">
                <i style={{ width: `${Math.max(0, Math.min(100, (remaining / Math.max(1, st.settings.max_actuation_sec)) * 100))}%` }} />
              </div>
              <button type="button" className="btn btn-stop btn-big" onClick={stop} disabled={busy || (cmd?.op === "stop")}>
                <Icon name="stop" />
                {cmd?.op === "stop" ? t("stopping") : t("stop_watering")}
              </button>
            </div>
          ) : live && cmd?.op === "start" ? (
            <div className={s.progress} role="status">
              <span className={s.spinner} aria-hidden="true" />
              {live.phase === "still_waiting" ? t("still_waiting") : live.phase === "executed" ? t("st_watering_starting") : t("sending")}
            </div>
          ) : (
            <>
              <button
                type="button"
                className="btn btn-water btn-big"
                disabled={!!blocked}
                aria-describedby={blocked ? "start-blocked" : undefined}
                onClick={() => (st.soak.active ? setSoakOpen(true) : setWaterOpen(true))}
              >
                <Icon name="drop" />
                {t("water_now")}
              </button>
              {blocked && <p id="start-blocked" className={s.actionNote}>{t(`blocked_${blocked}` as StringKey)}</p>}
              {failed && <p className="error-text" role="alert" style={{ textAlign: "center" }}>{failed}</p>}
            </>
          )}
        </div>

        <div className={s.cards}>
          <PowerCard st={st} />
          <WeatherCard st={st} />
          <PhaseCard st={st} />
        </div>
      </aside>

      <div className={`${s.full} ${s.chartPanel}`}>
        <MiniHistory threshold={st.settings.moisture_threshold} pmin={st.settings.probe_min_vwc} />
      </div>

      {/* ---------------- sheets ---------------- */}
      <Sheet open={plotOpen != null} title={plotOpen != null ? t("plot_sheet_title", { n: plotOpen + 1, id: `S${plotOpen + 1}` }) : ""} onClose={() => setPlotOpen(null)}>
        {selected && (
          <div className={s.sheetGrid}>
            <div className={s.sheetBig}>{selected.fault || selected.vwc == null ? "—" : `${selected.vwc.toFixed(1)}%`}</div>
            <StatusBadge level={selected.installed ? selected.level : "none"} label={!selected.installed ? t("not_installed") : undefined} />
            <dl className={s.kv}>
              <dt>{t("raw_value")}</dt>
              <dd>{selected.raw ?? "—"}</dd>
              <dt>{t("last_reading")}</dt>
              <dd>{fmtSmart(st.reading?.recorded_at, lang)}</dd>
              <dt>{t("last_calibration")}</dt>
              <dd>{selected.calibrated_at ? fmtSmart(selected.calibrated_at, lang) : t("never")}</dd>
            </dl>
            <p className="hint">{t("raw_value_hint")}</p>
            <p className="hint">{t("probe_threshold_note", { thr: st.settings.moisture_threshold, min: st.settings.probe_min_vwc })}</p>
          </div>
        )}
      </Sheet>

      <Sheet
        open={soakOpen}
        title={t("soak_warning_title")}
        onClose={() => setSoakOpen(false)}
        actions={
          <>
            <button className="btn btn-water btn-big" onClick={() => { setSoakOpen(false); setWaterOpen(true); }}>{t("water_anyway")}</button>
            <button className="btn btn-quiet btn-big" onClick={() => setSoakOpen(false)}>{t("cancel")}</button>
          </>
        }
      >
        <p>{t("soak_warning")}</p>
        <p className="muted">{t("soak_detail", { time: fmtTime(st.soak.ends_at, lang) })}</p>
      </Sheet>

      <Sheet
        open={waterOpen}
        title={t("water_sheet_title", { min: t("minutes_n", { n: chosenMin }) })}
        onClose={() => setWaterOpen(false)}
        actions={
          <>
            <button className="btn btn-water btn-big" onClick={start} disabled={busy}>
              <Icon name="drop" />
              {t("start_watering")}
            </button>
            <button className="btn btn-quiet btn-big" onClick={() => setWaterOpen(false)}>{t("cancel")}</button>
          </>
        }
      >
        <div className={s.sheetGrid}>
          <div className={s.drumNote}>
            <Icon name="alert" />
            <span>{t("water_sheet_drum")}</span>
          </div>
          <div className={s.durations}>
            <Segmented label={t("how_long")} value={String(chosenMin)} onChange={setMinutes} options={durationOptions} />
          </div>
          <p className="hint">{t("water_sheet_max", { max: fmtDuration(st.settings.max_actuation_sec, lang) })}</p>
        </div>
      </Sheet>
    </div>
  );
}

/* --------------------------------------------------------------------- cards */

function PowerCard({ st }: { st: Status }) {
  const { t, lang } = useI18n();
  const src = st.power.source;
  const icon: IconName = src === "solar" ? "solar" : src === "adapter" ? "plug" : "bolt";
  const offline = !st.device?.online;
  const pump = offline ? st.watering.last_known.pump : st.watering.pump;
  const valve = offline ? st.watering.last_known.valve : st.watering.valve;
  return (
    <section className={s.card} aria-labelledby="power-h">
      <h2 id="power-h" className={s.cardTitle}><Icon name="bolt" />{t("power")}</h2>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Icon name={icon} size={30} className={src === "solar" ? s.solarIcon : undefined} />
        <div>
          <div style={{ fontWeight: 650 }}>{t(`power_${src}` as StringKey)}</div>
          <div className="muted small">{t(`power_setup_${st.power.setup}` as StringKey)}</div>
        </div>
      </div>
      <dl className={s.kv}>
        <dt>{t("supply_voltage")}</dt>
        <dd>{st.power.supply_v != null ? `${st.power.supply_v.toFixed(2)} V` : "—"}</dd>
        <dt>{t("pump")}</dt>
        <dd><span className={`${s.pill} ${pump ? s.pillOn : s.pillOff}`}>{pump ? t("on") : t("off")}</span></dd>
        <dt>{t("valve")}</dt>
        <dd><span className={`${s.pill} ${valve ? s.pillOn : s.pillOff}`}>{valve ? t("open") : t("closed")}</span></dd>
      </dl>
      {offline && <p className="muted small">{t("last_seen", { time: fmtSmart(st.device?.last_seen_at, lang) })}</p>}
    </section>
  );
}

function wxIcon(c: string | null | undefined): IconName {
  if (c === "Rain" || c === "Drizzle") return "rain";
  if (c === "Thunderstorm") return "storm";
  if (c === "Clouds") return "cloud";
  if (c === "Clear") return "sun";
  return "haze";
}

export function wxLabel(c: string | null | undefined, t: T): string {
  if (!c) return t("wx_unknown");
  const k = ["Clear", "Clouds", "Rain", "Drizzle", "Thunderstorm"].includes(c) ? c : "Atmosphere";
  return t(`wx_${k}` as StringKey);
}

function WeatherCard({ st }: { st: Status }) {
  const { t, lang } = useI18n();
  const w = st.weather_now;
  const rp = st.rain_pause;
  return (
    <section className={s.card} aria-labelledby="wx-h">
      <h2 id="wx-h" className={s.cardTitle}><Icon name="forecast" />{t("forecast")}</h2>
      {w ? (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Icon name={wxIcon(w.condition)} size={32} />
          <div>
            <div className={s.big}>{w.temperature_c != null ? `${Math.round(w.temperature_c)}°C` : "—"}</div>
            <div className="muted small">{wxLabel(w.condition, t)} · {t("chance_of_rain")} {Math.round(w.pop_pct ?? 0)}%</div>
          </div>
        </div>
      ) : (
        <p className="muted small">{t("forecast_none")}</p>
      )}
      <StatusBadge level={rp.active ? "warning" : rp.stale ? "none" : "good"} compact
        label={rp.active ? t("rain_pause_on", { hours: rp.window_h }) : rp.stale ? (rp.retrieved_at ? t("forecast_stale", { time: fmtSmart(rp.retrieved_at, lang) }) : t("forecast_none")) : t("rain_pause_off")} />
      {!rp.stale && (
        <p className="muted small">{t("rain_pause_now", { hours: rp.window_h, pop: Math.round(rp.pop_max ?? 0), mm: (rp.rain_mm ?? 0).toFixed(1) })}</p>
      )}
    </section>
  );
}

function PhaseCard({ st }: { st: Status }) {
  const { t } = useI18n();
  const ph = st.phase;
  const pred = st.prediction;
  const thr = st.settings.moisture_threshold;
  return (
    <section className={s.card} aria-labelledby="phase-h">
      <h2 id="phase-h" className={s.cardTitle}><Icon name="sparkle" />{t("next_hour_estimate")}</h2>
      <div style={{ fontWeight: 650 }}>
        {ph.name === "predictive" ? t("phase_predictive") : ph.day === 0 ? t("phase_not_started") : t("phase_cold_start", { day: ph.day, of: ph.of })}
      </div>
      {ph.name === "cold_start" && ph.day > 0 && (
        <div className={s.meter} aria-hidden="true"><i style={{ width: `${(Math.min(ph.day, ph.of) / ph.of) * 100}%`, background: "var(--leaf)" }} /></div>
      )}
      {pred ? (
        <div className={s.estimate}>
          <div className={s.big}>{pred.predicted_vwc.toFixed(1)}%</div>
          <div className={s.meter} aria-hidden="true">
            <i style={{ width: `${Math.min(100, (pred.predicted_vwc / 50) * 100)}%` }} />
            <b style={{ left: `${Math.min(100, (thr / 50) * 100)}%` }} />
          </div>
          <p className="muted small">{t("estimate_vs_limit", { pred: pred.predicted_vwc.toFixed(1), thr })}</p>
        </div>
      ) : (
        <p className="muted small">{ph.name === "cold_start" ? t("phase_explain_cold") : t("phase_explain_pred")}</p>
      )}
    </section>
  );
}

function MiniHistory({ threshold, pmin }: { threshold: number; pmin: number }) {
  const { t, lang } = useI18n();
  const [from] = useState(() => isoDaysAgo(1));
  const { data } = useReadings(from, undefined, "raw");
  if (!data) return <p className="muted">{t("loading")}</p>;
  const x = data.points.map((p) => new Date(p.t));
  return (
    <div className="stack">
      <h2 style={{ fontSize: "var(--fs-20)" }}>{t("soil_moisture")} · {t("range_24h")}</h2>
      {data.points.length === 0 ? (
        <p className="muted">{t("no_data_range")}</p>
      ) : (
        <LineChart
          ariaLabel={`${t("soil_moisture")}, ${t("range_24h")}`}
          x={x}
          unit="%"
          height={200}
          yDomain={moistureDomain(data.points, pmin, threshold)}
          series={[{ key: "mean", label: t("average"), color: "var(--ink)", width: 2.5, values: data.points.map((p) => p.mean) }]}
          refs={[
            { value: threshold, label: t("limit_line", { v: threshold }), dash: "dashed" },
            { value: pmin, label: t("min_line", { v: pmin }), dash: "dotted" },
          ]}
          markers={data.watering.filter((e) => e.valve_open_at).map((e) => ({ t: new Date(e.valve_open_at as string), label: `${t("watering_marks")} ${fmtTime(e.valve_open_at, lang)}` }))}
        />
      )}
    </div>
  );
}
