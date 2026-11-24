// Shapes returned by the Flask API (docs/openapi.yaml).
export type Role = "caretaker" | "manager" | "leader";
export type Lang = "en" | "fil";
export type ThemePref = "auto" | "light" | "dark";
export type Level = "good" | "warning" | "serious" | "critical" | "none";
export type ProbeId = "S1" | "S2" | "S3";

export interface User {
  id: number;
  full_name: string;
  username: string;
  role: Role;
  language: Lang | null;
  theme: ThemePref;
  last_login_at: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface Me {
  user: User | null;
  csrf: string | null;
}

export interface Probe {
  id: ProbeId;
  installed: boolean;
  vwc: number | null;
  raw: number | null;
  fault: boolean;
  level: Level;
  calibrated_at: string | null;
}

export interface CommandView {
  id: number;
  op: "start" | "stop" | "read_now";
  duration_s: number | null;
  status: string;
  phase: "sending" | "still_waiting" | "delivered" | "executed" | "rejected" | "expired" | "cancelled";
  created_at: string;
  delivered_at: string | null;
  acked_at: string | null;
  latency_s: number | null;
  reason: string | null;
}

export interface RainPause {
  active: boolean;
  stale: boolean;
  pop_max: number | null;
  rain_mm: number | null;
  window_h: number;
  retrieved_at: string | null;
  steps: { forecast_id: number; for: string; pop: number | null; rain_mm: number }[];
  rule: { pop_pct: number; rain_mm: number; window_h: number };
}

export type StatusCode = "no_readings" | "sensor_fault" | "below_minimum" | "getting_dry" | "moist_enough";
export type StartBlocked = null | "no_device" | "offline" | "fault_schedule" | "already_running" | "role";
export type WaterSource = "auto" | "manual" | "offline_failsafe" | "sensor_fault_schedule" | null;

export interface Status {
  server_time: string;
  status: { code: StatusCode; level: Level; offline: boolean };
  device: null | { id: string; name: string; online: boolean; last_seen_at: string | null; fw: string | null; mode: string | null;
    read_now: null | { at: string; probes: { id: ProbeId; raw: number | null; vwc: number | null; fault: boolean }[] } };
  reading: null | {
    log_id: number; recorded_at: string; mean: number | null; active_count: number; probes: Probe[]; supply_v: number | null;
    power_source: string | null; control_mode: string; synced_offline: boolean;
  };
  next_check_at: string | null;
  phase: { name: "cold_start" | "predictive"; day: number; of: number; started_at: string | null; ends_at: string | null;
    cold_start_complete?: boolean; model_active: boolean };
  decision: null | { id: number; action: "water" | "none"; reason: string; created_at: string; duration_s: number | null; need_reason: string | null };
  rain_pause: RainPause;
  soak: { active: boolean; remaining_s: number; ends_at: string | null; last_watering_end: string | null };
  watering: {
    active: boolean; pump: boolean; valve: boolean; source: WaterSource; remaining_s: number; since: string | null;
    command: CommandView | null; start_blocked: StartBlocked; last_known: { pump: boolean; valve: boolean; at: string | null };
  };
  power: { source: "solar" | "adapter" | "unknown"; supply_v: number | null; setup: "adapter_only" | "hybrid";
    last_transition: null | { at: string; from: string; to: string; v: number | null } };
  prediction: null | { predicted_vwc: number; target_at: string; model_version: string; baseline_vwc: number | null };
  weather_now: null | { for: string; condition: string | null; temperature_c: number | null; humidity_pct: number | null; pop_pct: number | null; rain_3h_mm: number };
  forecast: { retrieved_at: string | null; status: { ok: boolean | null; retrieved_at: string | null; last_error?: string | null; source?: string } };
  settings: { version: number; moisture_threshold: number; probe_min_vwc: number; max_actuation_sec: number; soak_interval_sec: number; power_setup: string };
}

export interface ReadingPoint {
  t: string; mean: number | null; S1: number | null; S2: number | null; S3: number | null; supply_v: number | null;
  source?: string | null; synced?: boolean; n?: number;
}

export interface WateringEvent {
  id: number; source: string; user_id: number | null; user: string | null; valve_open_at: string | null; pump_on_at: string | null;
  pump_off_at: string | null; valve_closed_at: string | null; duration_s: number | null; interlock_ms: number | null;
  close_gap_ms: number | null; ended_reason: string | null; command_id: number | null; decision_id: number | null;
}

export interface Readings { from: string; to: string; bucket: string; points: ReadingPoint[]; watering: WateringEvent[]; threshold: number; probe_min: number }

export interface ForecastStep { id: number; for: string; condition: string | null; temperature_c: number | null; humidity_pct: number | null; pop_pct: number | null; rain_3h_mm: number }
export interface Forecast { retrieved_at: string | null; stale: boolean; status: Status["forecast"]["status"]; rain_pause: RainPause; steps: ForecastStep[] }

export interface ModelInfo {
  version: string; trained_at: string; rows: number; date_from: string | null; date_to: string | null; mae: number; rmse: number;
  baseline_mae: number; baseline_rmse: number; beats_baseline: boolean; is_active: boolean; notes: string | null;
  features: string[] | null; train_rows: number | null; test_rows: number | null;
  held_out?: { hour: string; actual: number; predicted: number; baseline: number }[];
}
export interface ModelCard {
  active: ModelInfo | null; versions: ModelInfo[]; live: null | { n: number; mae: number | null; rmse: number | null; baseline_mae: number | null; baseline_rmse: number | null };
  phase: Status["phase"]; trainer_available: boolean; retrain_requested_at: string | null;
}

export interface Prediction { id: number; target_at: string; predicted_vwc: number; actual_vwc: number | null; baseline_vwc: number | null; decision: string | null; model_version: string }

export interface FieldSpec { group: string; unit: string; min?: number; max?: number; step?: number; type: "number" | "integer" | "enum" | "time" | "datetime"; options?: string[]; fixed?: boolean }
export interface Calibration { adc_dry: number; adc_sat: number; vwc_dry: number; vwc_sat: number; calibrated_at: string | null }
export interface SettingsData {
  version: number; updated_at: string; updated_by: number | null; moisture_threshold: number; probe_min_vwc: number; max_actuation_sec: number;
  soak_interval_sec: number; operating_phase: string; rain_pop_pct: number; rain_mm: number; rain_window_h: number; cold_start_days: number;
  deployment_started_at: string | null; flow_rate_lpm: number; daily_water_l: number; daily_water_mode: "auto" | "manual"; fault_am_time: string;
  fault_pm_time: string; fault_am_share: number; valve_close_gap_ms: number; power_setup: "adapter_only" | "hybrid"; garden_lat: number; garden_lon: number;
  calibration: Record<ProbeId, Calibration>; change_note: string | null;
  [key: string]: unknown;
}
export interface SettingsResponse { settings: SettingsData; fields: Record<string, FieldSpec> }

export interface Decision { id: number; at: string; action: string; reason: string; phase: string; duration_s: number | null; settings_version: number;
  inputs: Record<string, unknown> & { mean_vwc?: number | null; predicted_vwc?: number | null; threshold?: number; rain?: { pop_max: number | null; rain_mm: number | null; stale: boolean } } }
export interface PowerEvent { id: number; at: string; from: string; to: string; v: number | null }
export interface Period { id: number; status: "online" | "offline"; started_at: string; ended_at: string | null; duration_s: number }
export interface AuditItem { id: number; at: string; user: string | null; action: string; target: string | null; before: unknown; after: unknown }
export interface DeviceInfo { id: string; name: string; fw: string | null; last_seen_at: string | null; key_rotated_at: string | null; online: boolean }
export interface WaterUseDay { day: string; litres: number; pump_seconds: number; runs: number; flow_rate_lpm: number }
