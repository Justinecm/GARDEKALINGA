// Settings (manager): grouped forms with unit, range and current value; every
// save is a new version pushed to the node (FR-UI-08, NFR-MAIN-02, NFR-PORT-03).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useSettings, useStatus } from "../api/hooks";
import type { Calibration, DeviceInfo, FieldSpec, ProbeId, SettingsData } from "../api/types";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/I18n";
import type { StringKey } from "../i18n/strings";
import { fmtSmart } from "../lib/time";
import s from "./Settings.module.css";

const GROUPS: { id: string; title: StringKey; fields: string[] }[] = [
  { id: "watering", title: "grp_watering", fields: ["moisture_threshold", "probe_min_vwc", "max_actuation_sec", "soak_interval_sec", "valve_close_gap_ms"] },
  { id: "rain", title: "grp_rain", fields: ["rain_pop_pct", "rain_mm", "rain_window_h"] },
  { id: "phase", title: "grp_phase", fields: ["cold_start_days", "deployment_started_at"] },
  { id: "fault", title: "grp_fault", fields: ["flow_rate_lpm", "daily_water_mode", "daily_water_l", "fault_am_time", "fault_pm_time", "fault_am_share"] },
  { id: "power", title: "grp_power", fields: ["power_setup"] },
  { id: "location", title: "grp_location", fields: ["garden_lat", "garden_lon"] },
];
const PROBES: ProbeId[] = ["S1", "S2", "S3"];

type Draft = Record<string, string>;

/** ISO (UTC) -> "YYYY-MM-DDTHH:mm" in Asia/Manila for <input type=datetime-local>. */
function manilaLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

function toDraft(st: SettingsData): Draft {
  const d: Draft = {};
  for (const g of GROUPS) for (const f of g.fields) {
    const v = st[f];
    d[f] = v == null ? "" : f === "deployment_started_at" ? manilaLocalInput(String(v)) : String(v);
  }
  for (const p of PROBES) {
    const c = st.calibration[p];
    d[`${p}.adc_dry`] = String(c.adc_dry);
    d[`${p}.adc_sat`] = String(c.adc_sat);
    d[`${p}.vwc_dry`] = String(c.vwc_dry);
    d[`${p}.vwc_sat`] = String(c.vwc_sat);
  }
  return d;
}

export default function Settings() {
  const { t, lang } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useSettings();
  const [draft, setDraft] = useState<Draft>({});
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (data) setDraft(toDraft(data.settings));
  }, [data]);

  const changes = useMemo(() => {
    if (!data) return {};
    const base = toDraft(data.settings);
    const out: Record<string, unknown> = {};
    const cal: Record<string, Calibration> = {};
    for (const [k, v] of Object.entries(draft)) {
      if (v === base[k]) continue;
      if (k.includes(".")) {
        const [p] = k.split(".");
        const c = data.settings.calibration[p as ProbeId];
        cal[p] = {
          adc_dry: Number(draft[`${p}.adc_dry`]), adc_sat: Number(draft[`${p}.adc_sat`]),
          vwc_dry: Number(draft[`${p}.vwc_dry`]), vwc_sat: Number(draft[`${p}.vwc_sat`]), calibrated_at: c.calibrated_at,
        };
      } else {
        const spec = data.fields[k];
        out[k] = spec?.type === "number" || spec?.type === "integer" ? Number(v) : k === "deployment_started_at" ? (v ? new Date(v + ":00+08:00").toISOString() : null) : v;
      }
    }
    if (Object.keys(cal).length) out.calibration = cal;
    return out;
  }, [draft, data]);

  const save = useMutation({
    mutationFn: () => api.post<{ settings: SettingsData; changed: string[] }>("/api/v1/settings", { ...changes, note: note || undefined }),
    onSuccess: (r) => {
      setErrors({});
      setNote("");
      toast(r.changed.length ? t("saved", { v: r.settings.version }) : t("no_changes"), "good");
      void qc.invalidateQueries({ queryKey: ["settings"] });
      void qc.invalidateQueries({ queryKey: ["settings-history"] });
      void qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        setErrors(e.fields);
        toast(e.message, "critical");
      }
    },
  });

  if (!data) return <div className="page"><p>{t("loading")}</p></div>;
  const n = Object.keys(changes).length;

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("settings_title")}</h1>
        <p>{t("settings_lead")}</p>
        <p className="small muted">{t("version_n", { v: data.settings.version })} · {fmtSmart(data.settings.updated_at, lang)}</p>
        <div className="row"><Link to="/users" className="btn btn-quiet btn-sm"><Icon name="users" size={16} />{t("nav_users")}</Link><Link to="/reports" className="btn btn-quiet btn-sm"><Icon name="download" size={16} />{t("nav_reports")}</Link></div>
      </div>

      <form className={s.form} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {GROUPS.map((g) => (
          <fieldset key={g.id} className={s.group}>
            <legend className={s.legend}>{t(g.title)}</legend>
            <div className={s.fields}>
              {g.fields.map((f) => (
                <Field key={f} name={f} spec={data.fields[f]} value={draft[f] ?? ""} current={data.settings[f]} error={errors[f]}
                  onChange={(v) => setDraft((d) => ({ ...d, [f]: v }))} />
              ))}
            </div>
            {g.id === "power" && <p className="hint">{t("help_power_body")}</p>}
          </fieldset>
        ))}

        <Calibration draft={draft} setDraft={setDraft} cal={data.settings.calibration} errors={errors} />

        <div className={s.saveBar}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label className="label small" htmlFor="note">{t("note_optional")}</label>
            <input id="note" className="input" value={note} maxLength={255} onChange={(e) => setNote(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-water" disabled={!n || save.isPending}>
            {save.isPending ? t("saving") : `${t("save_changes")}${n ? ` (${n})` : ""}`}
          </button>
        </div>
      </form>

      <Devices />
      <History />
    </div>
  );
}

function Field({ name, spec, value, current, error, onChange }: { name: string; spec?: FieldSpec; value: string; current: unknown; error?: string; onChange: (v: string) => void }) {
  const { t, lang } = useI18n();
  if (!spec) return null;
  const id = `f-${name}`;
  const label = t(`f_${name}` as StringKey);
  const unit = spec.unit;
  const hintId = `${id}-hint`;
  const fixed = !!spec.fixed;
  let control;
  if (spec.type === "enum") {
    control = (
      <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hintId}>
        {spec.options?.map((o) => <option key={o} value={o}>{t(`opt_${o}` as StringKey)}</option>)}
      </select>
    );
  } else if (spec.type === "time") {
    control = <input id={id} className="input" type="time" value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hintId} />;
  } else if (spec.type === "datetime") {
    control = <input id={id} className="input" type="datetime-local" value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hintId} />;
  } else {
    control = (
      <div className={s.withUnit}>
        <input id={id} className="input num" type="number" inputMode="decimal" min={spec.min} max={spec.max} step={spec.step} value={value} disabled={fixed}
          onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} aria-describedby={hintId} />
        {unit && <span className={s.unit}>{unit}</span>}
      </div>
    );
  }
  const cur = name === "deployment_started_at" ? fmtSmart(current as string, lang) : current == null ? "—" : `${current}${unit && spec.type !== "enum" ? " " + unit : ""}`;
  return (
    <div className={s.field}>
      <label className="label" htmlFor={id}>{label}</label>
      {control}
      <p id={hintId} className="hint">
        {fixed ? t("fixed_hint") : spec.min != null ? t("range_hint", { min: spec.min, max: spec.max, unit }) : ""}{" "}
        {!fixed && <span>· {t("current_value", { v: spec.type === "enum" ? t(`opt_${current}` as StringKey) : cur })}</span>}
      </p>
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

function Calibration({ draft, setDraft, cal, errors }: { draft: Draft; setDraft: (f: (d: Draft) => Draft) => void; cal: Record<ProbeId, Calibration>; errors: Record<string, string> }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const status = useStatus();
  const [waiting, setWaiting] = useState(false);
  const readNow = status.data?.device?.read_now;
  const devId = status.data?.device?.id;

  async function capture() {
    if (!devId) return;
    try {
      await api.post(`/api/v1/devices/${devId}/read-now`);
      setWaiting(true);
      window.setTimeout(() => setWaiting(false), 8000);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "critical");
    }
  }

  return (
    <fieldset className={s.group}>
      <legend className={s.legend}>{t("grp_calibration")}</legend>
      <p className="hint">θ = θdry + (ADCdry − ADC) / (ADCdry − ADCsat) × (θsat − θdry)</p>
      <div className="row">
        <button type="button" className="btn btn-quiet" onClick={capture} disabled={!devId || waiting}>
          <Icon name="refresh" size={18} />{t("cal_capture")}
        </button>
        <span className="hint">{t("cal_capture_hint")}</span>
      </div>
      {readNow && (
        <div className="well small" role="status">
          <strong>{t("cal_captured", { time: fmtSmart(readNow.at, lang) })}</strong>
          <div className="row" style={{ marginTop: 6 }}>
            {readNow.probes.map((p) => (
              <span key={p.id} className={s.capture}>
                {p.id}: <b className="num">{p.raw ?? "—"}</b>
                <button type="button" className="btn btn-link btn-sm" onClick={() => setDraft((d) => ({ ...d, [`${p.id}.adc_dry`]: String(p.raw ?? "") }))}>{t("cal_use_dry")}</button>
                <button type="button" className="btn btn-link btn-sm" onClick={() => setDraft((d) => ({ ...d, [`${p.id}.adc_sat`]: String(p.raw ?? "") }))}>{t("cal_use_wet")}</button>
              </span>
            ))}
          </div>
        </div>
      )}
      <div className={s.calGrid}>
        {PROBES.map((p, i) => (
          <div key={p} className={s.calCard}>
            <h3 className={s.calTitle}>{t("plot_n", { n: i + 1 })} ({p})</h3>
            <p className="hint">{t("last_calibration")}: {cal[p].calibrated_at ? fmtSmart(cal[p].calibrated_at, lang) : t("never")}</p>
            {(["adc_dry", "adc_sat", "vwc_dry", "vwc_sat"] as const).map((k) => (
              <div key={k} className={s.calRow}>
                <label htmlFor={`${p}-${k}`} className="small">{t(`cal_${k}` as StringKey)}</label>
                <input id={`${p}-${k}`} className="input num" type="number" inputMode="decimal" step={k.startsWith("adc") ? 1 : 0.1}
                  min={0} max={k.startsWith("adc") ? 4095 : 100} value={draft[`${p}.${k}`] ?? ""}
                  aria-invalid={!!errors[`calibration.${p}.${k}`] || !!errors[`calibration.${p}`]}
                  onChange={(e) => setDraft((d) => ({ ...d, [`${p}.${k}`]: e.target.value }))} />
              </div>
            ))}
            {(errors[`calibration.${p}.adc_dry`] || errors[`calibration.${p}.vwc_sat`] || errors[`calibration.${p}`]) && (
              <p className="error-text">{errors[`calibration.${p}.adc_dry`] ?? errors[`calibration.${p}.vwc_sat`] ?? errors[`calibration.${p}`]}</p>
            )}
          </div>
        ))}
      </div>
    </fieldset>
  );
}

function Devices() {
  const { t, lang } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["devices"], queryFn: () => api.get<{ items: DeviceInfo[] }>("/api/v1/devices") });
  const [secret, setSecret] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [newId, setNewId] = useState("gk-node-01");

  async function rotate(id: string) {
    setConfirm(null);
    try {
      const r = await api.post<{ secret: string }>(`/api/v1/devices/${id}/rotate-key`);
      setSecret(r.secret);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "critical");
    }
  }
  async function register() {
    try {
      const r = await api.post<{ secret: string }>("/api/v1/devices", { device_id: newId });
      setSecret(r.secret);
      void qc.invalidateQueries({ queryKey: ["devices"] });
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "critical");
    }
  }

  return (
    <section className={s.group} aria-labelledby="dev-h">
      <h2 id="dev-h" className={s.legend}>{t("grp_devices")}</h2>
      {data?.items.length ? (
        data.items.map((d) => (
          <div key={d.id} className={s.device}>
            <div>
              <strong>{d.name}</strong>
              <dl className={s.kv}>
                <dt>{t("device_id")}</dt><dd>{d.id}</dd>
                <dt>{t("device_fw")}</dt><dd>{d.fw ?? "—"}</dd>
                <dt>{t("last_seen", { time: "" }).trim()}</dt><dd>{fmtSmart(d.last_seen_at, lang)}</dd>
              </dl>
            </div>
            <button type="button" className="btn btn-quiet" onClick={() => setConfirm(d.id)}><Icon name="key" size={18} />{t("rotate_key")}</button>
          </div>
        ))
      ) : (
        <div className="row">
          <input className="input" style={{ maxWidth: 220 }} value={newId} onChange={(e) => setNewId(e.target.value)} aria-label={t("device_id")} />
          <button type="button" className="btn btn-water" onClick={register}>{t("register_device")}</button>
        </div>
      )}
      <Sheet open={!!confirm} title={t("rotate_key")} onClose={() => setConfirm(null)}
        actions={<><button className="btn btn-stop btn-big" onClick={() => confirm && rotate(confirm)}>{t("rotate_key")}</button><button className="btn btn-quiet btn-big" onClick={() => setConfirm(null)}>{t("cancel")}</button></>}>
        <p>{t("rotate_confirm")}</p>
      </Sheet>
      <Sheet open={!!secret} title={t("secret_once")} onClose={() => setSecret(null)}>
        <p className="hint">{t("secret_note")}</p>
        <code className={s.secret}>{secret}</code>
      </Sheet>
    </section>
  );
}

function History() {
  const { t, lang } = useI18n();
  const { data } = useQuery({
    queryKey: ["settings-history"],
    queryFn: () => api.get<{ items: { version: number; updated_at: string; updated_by: string | null; note: string | null; changed: Record<string, unknown> }[] }>("/api/v1/settings/history"),
  });
  return (
    <section className="stack" aria-labelledby="sh-h">
      <h2 id="sh-h">{t("grp_history")}</h2>
      <div className="table-wrap" style={{ maxHeight: 420 }}>
        <table className="data">
          <thead><tr><th>{t("version_n", { v: "" }).trim()}</th><th>{t("time")}</th><th>{t("col_who")}</th><th>{t("details")}</th></tr></thead>
          <tbody>
            {data?.items.map((h) => (
              <tr key={h.version}>
                <td className="num">{h.version}</td>
                <td>{fmtSmart(h.updated_at, lang)}</td>
                <td>{h.updated_by ?? t("system")}</td>
                <td style={{ whiteSpace: "normal" }} className="small">
                  {Object.entries(h.changed).map(([k, v]) => <span key={k} style={{ marginRight: 10 }}>{k.startsWith("calibration") ? t("grp_calibration") : t(`f_${k}` as StringKey)}: <b>{typeof v === "object" ? "…" : typeof v === "string" && ISO_RE.test(v) ? fmtSmart(v, lang) : String(v)}</b></span>)}
                  {h.note && <em className="muted"> “{h.note}”</em>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
