# Changelog

## Unreleased

### Removed
- Demo mode (`GK_DEMO_MODE`): the virtual Box B, the 17 days of simulated history, the demo accounts
  and the **Demo** controls. The dashboard now shows only what the ESP32 sends.
- Synthetic weather: without `OWM_API_KEY` there is no forecast (the Forecast screen says so) instead of invented weather.
- The bundled demo model trained on simulated data (`demo_model.json.z`, `tools/make_demo_model.py`). The first model is
  trained on the garden's own readings after the 14-day learning period.
- The device simulator (`tools/device_simulator.py`) and the `demo-model`, `simulate` and `seed-demo` commands.

### Changed
- On Vercel the API no longer falls back to a throwaway SQLite file: `DATABASE_URL` and `SECRET_KEY` are required.
- `make dev-api` runs against a plain local database with no seeded garden.

## 1.0.0 (2026-11-20)

First complete build from BUILD_PROMPT.md (paper draft v2).

### Added
- Flask API with the six ERD tables plus supporting tables, Alembic migration `0001`.
- Sign-in with Argon2id, CSRF, rate limit and lockout, roles (caretaker, manager, leader), re-authentication for managers, append-only audit trail.
- HMAC-signed device API (readings, 3-second poll, commands and acks, events, offline sync), replay protection.
- Decision engine with cold start, Random Forest phase, probe minimum, soak and rain pause; every decision logged.
- OpenWeatherMap client; Random Forest training with the persistence-baseline gate; pure-Python inference.
- Reports (CSV), daily water use (Eq. 8), ingestion and command latency stats, test bench (Eq. 5, 6, 7).
- React dashboard: live garden scene, Langit sky theme with Auto / Light / Dark, English and Filipino, Garden, History, Forecast, Records, Settings, Users, Reports, Help.
- Demo mode with a virtual controller and demo controls; bundled demo model.
- Vercel configuration (static dashboard + Python function, cron, security headers).
- ESP32 firmware for Box B and native unit tests; bridge version of the original 1-probe sketch.
- Device simulator; Docker Compose with Caddy, worker, MySQL and backups; CI and retraining workflows.
- Documentation: decisions, deployment, API, test evidence, operations, user guides in English and Filipino.
