"""ORM models.

The six core tables keep the ERD (paper Fig. 5) names and columns exactly; extra
columns are only added, never renamed (BUILD_PROMPT A-5). Supporting tables are
listed in docs/DECISIONS.md. All times are stored as naive UTC datetimes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# BIGINT on MySQL, plain INTEGER on SQLite so autoincrement works there.
BigId = BigInteger().with_variant(Integer(), "sqlite")
LongBlob = LargeBinary().with_variant(mysql.LONGBLOB(), "mysql")
LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")
# Millisecond precision on MySQL (TC6 timing); SQLite keeps microseconds anyway.
DT = DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")

ROLES = ("caretaker", "manager", "leader")
CONTROL_MODES = ("online", "offline_failsafe", "sensor_fault")
PHASES = ("cold_start", "predictive")
TRIGGER_SOURCES = ("auto", "manual", "offline_failsafe", "sensor_fault_schedule")
ENDED_REASONS = ("completed", "max_cutoff", "manual_stop", "power_loss", "watchdog")
POWER_SOURCES = ("solar", "adapter", "unknown")


# --------------------------------------------------------------------------- core (ERD)
class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DT)
    # extras
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    theme: Mapped[str] = mapped_column(String(8), default="auto")
    last_login_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)


class SystemSettings(Base):
    """Insert-only. The newest row is current; setting_id is the settings version."""

    __tablename__ = "system_settings"
    setting_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moisture_threshold: Mapped[float] = mapped_column(Float)
    max_actuation_sec: Mapped[int] = mapped_column(Integer)
    soak_interval_sec: Mapped[int] = mapped_column(Integer)
    operating_phase: Mapped[str] = mapped_column(String(16))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DT, index=True)
    # extras
    probe_min_vwc: Mapped[float] = mapped_column(Float)
    rain_pop_pct: Mapped[float] = mapped_column(Float)
    rain_mm: Mapped[float] = mapped_column(Float)
    rain_window_h: Mapped[int] = mapped_column(Integer)
    cold_start_days: Mapped[int] = mapped_column(Integer)
    deployment_started_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    flow_rate_lpm: Mapped[float] = mapped_column(Float)
    daily_water_l: Mapped[float] = mapped_column(Float)
    daily_water_mode: Mapped[str] = mapped_column(String(8))
    fault_am_time: Mapped[str] = mapped_column(String(5))
    fault_pm_time: Mapped[str] = mapped_column(String(5))
    fault_am_share: Mapped[float] = mapped_column(Float)
    valve_close_gap_ms: Mapped[int] = mapped_column(Integer)
    calibration_json: Mapped[dict] = mapped_column(JSON)
    power_setup: Mapped[str] = mapped_column(String(16))
    garden_lat: Mapped[float] = mapped_column(Float)
    garden_lon: Mapped[float] = mapped_column(Float)
    change_note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SensorLog(Base):
    __tablename__ = "sensor_logs"
    log_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DT, index=True)
    spatial_mean_vwc: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_probe_count: Mapped[int] = mapped_column(Integer)
    raw_adc_values: Mapped[dict] = mapped_column(JSON)
    control_mode: Mapped[str] = mapped_column(String(20))
    # extras
    device_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    reading_uuid: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    probe_vwc_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    probe_fault_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    supply_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DT, nullable=True, index=True)
    synced_offline: Mapped[bool] = mapped_column(Boolean, default=False)


class WeatherForecast(Base):
    __tablename__ = "weather_forecasts"
    forecast_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    retrieved_at: Mapped[datetime] = mapped_column(DT, index=True)
    forecast_for: Mapped[datetime] = mapped_column(DT, index=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rain_3h_mm: Mapped[float] = mapped_column(Float, default=0.0)
    weather_condition: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # extras
    pop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class MLPrediction(Base):
    __tablename__ = "ml_predictions"
    prediction_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("sensor_logs.log_id"), index=True)
    forecast_id: Mapped[int | None] = mapped_column(ForeignKey("weather_forecasts.forecast_id"), nullable=True)
    predicted_vwc: Mapped[float] = mapped_column(Float)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DT, index=True)
    # extras
    target_at: Mapped[datetime | None] = mapped_column(DT, nullable=True, index=True)
    actual_vwc: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_vwc: Mapped[float | None] = mapped_column(Float, nullable=True)


class ActuationEvent(Base):
    __tablename__ = "actuation_events"
    event_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("ml_predictions.prediction_id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    trigger_source: Mapped[str] = mapped_column(String(24))
    valve_open_at: Mapped[datetime | None] = mapped_column(DT, nullable=True, index=True)
    pump_on_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    pump_off_at: Mapped[datetime | None] = mapped_column(DT, nullable=True, index=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    # extras
    event_uuid: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    command_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valve_closed_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    interlock_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    close_gap_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)


class PowerStateTransition(Base):
    __tablename__ = "power_state_transitions"
    transition_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DT, index=True)
    from_source: Mapped[str] = mapped_column(String(10))
    to_source: Mapped[str] = mapped_column(String(10))
    battery_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    # extras
    event_uuid: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


# --------------------------------------------------------------------------- supporting
class Device(Base):
    __tablename__ = "devices"
    device_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    key_encrypted: Mapped[str] = mapped_column(Text)
    key_rotated_at: Mapped[datetime] = mapped_column(DT)
    last_seen_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    fw_version: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DT)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    command_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(40), index=True)
    op: Mapped[str] = mapped_column(String(12))  # start | stop | read_now | test_hang
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DT, index=True)
    expires_at: Mapped[datetime] = mapped_column(DT)
    delivered_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending | delivered | executed | rejected | expired
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ControlDecision(Base):
    __tablename__ = "control_decisions"
    decision_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    log_id: Mapped[int | None] = mapped_column(ForeignKey("sensor_logs.log_id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(8))  # water | none
    reason_code: Mapped[str] = mapped_column(String(32))
    phase: Mapped[str] = mapped_column(String(16))
    inputs_json: Mapped[dict] = mapped_column(JSON)
    settings_version: Mapped[int] = mapped_column(Integer)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DT, index=True)


class MLModel(Base):
    __tablename__ = "ml_models"
    model_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    trained_at: Mapped[datetime] = mapped_column(DT)
    rows: Mapped[int] = mapped_column(Integer)
    date_from: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    date_to: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    mae: Mapped[float] = mapped_column(Float)
    rmse: Mapped[float] = mapped_column(Float)
    baseline_mae: Mapped[float] = mapped_column(Float)
    baseline_rmse: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact: Mapped[bytes | None] = mapped_column(LongBlob, nullable=True)  # zlib JSON forest


class AuditLog(Base):
    """Append-only. There is no update or delete endpoint for this table."""

    __tablename__ = "audit_logs"
    audit_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str | None] = mapped_column(String(80), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(DT, index=True)


class TestRecord(Base):
    __tablename__ = "test_records"
    __test__ = False  # not a pytest class
    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tc_number: Mapped[int] = mapped_column(Integer, index=True)
    trial_no: Mapped[int] = mapped_column(Integer)
    inputs_json: Mapped[dict] = mapped_column(JSON)
    result_json: Mapped[dict] = mapped_column(JSON)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DT)


class DeviceStatusPeriod(Base):
    __tablename__ = "device_status_periods"
    period_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(8))  # online | offline
    started_at: Mapped[datetime] = mapped_column(DT, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)


class DeviceEvent(Base):
    """Boot / reset-reason and other device events that have no ERD table."""

    __tablename__ = "device_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(String(40), unique=True)
    device_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DT, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)


class DeviceNonce(Base):
    __tablename__ = "device_nonces"
    __table_args__ = (UniqueConstraint("device_id", "nonce", name="uq_device_nonce"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(40))
    nonce: Mapped[str] = mapped_column(String(64))
    seen_at: Mapped[datetime] = mapped_column(DT, index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DT, index=True)


class DailyWaterUse(Base):
    __tablename__ = "daily_water_use"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD, Asia/Manila
    pump_seconds: Mapped[float] = mapped_column(Float)
    litres: Mapped[float] = mapped_column(Float)
    flow_rate_lpm: Mapped[float] = mapped_column(Float)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DT)


class JobRun(Base):
    """Bookkeeping for scheduled jobs (worker, Vercel Cron or opportunistic runner)."""

    __tablename__ = "job_runs"
    job_name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DT, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    last_message: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AppState(Base):
    """Small key/value store (demo simulator state, forecast fetch errors)."""

    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DT)


Index("ix_actuation_device_open", ActuationEvent.device_id, ActuationEvent.valve_open_at)
Index("ix_sensor_logs_device_time", SensorLog.device_id, SensorLog.recorded_at)
Index("ix_forecast_retrieved_for", WeatherForecast.retrieved_at, WeatherForecast.forecast_for)
