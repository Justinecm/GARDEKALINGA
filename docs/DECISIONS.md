# Decisions

Every builder default used where the paper (CHAPTER 1, 2, 3 draft v2) is silent, plus
the inconsistencies from BUILD_PROMPT A-9. One line each: **decision**, reason, how to change it.

## From the paper's inconsistencies (A-9)

| # | Decision | Reason | How to change |
|---|---|---|---|
| A9-1 | Node polls every 3 s **on either power source**. | 1.3.2, the 3.8 timing paragraph, Fig. 9 and TC4 say "either source". | `POLL_PERIOD_MS` in `firmware/gardekalinga_node/gk_logic.h`. Fix the two sentences in 3.8 / Ch. 2. |
| A9-2 | `weather_forecasts.pop_pct` added. | Rain pause needs chance of rain; Fig. 5 omits it. | Extra column, never renamed. |
| A9-3 | `sensor_logs` gets `probe_vwc_json`, `probe_fault_json`, `supply_voltage`, `power_source`. | TC15 shows per-sensor VWC and supply voltage. | Extra columns. |
| A9-4 | `actuation_events.valve_closed_at` and `close_gap_ms` added. | TC6 "pump stops before the valve closes". | Extra columns. |
| A9-5 | STARTING VALUES: threshold 30 % VWC, probe minimum 22 %, max watering 180 s, soak 30 min. | No numbers in the paper. | Settings screen (manager); every save is a new version. |
| A9-6 | Daily water before 3 days of data = 2 × max watering × flow rate / 60 (9 L at the starting values). | FR-FS-04. | Settings > Sensor problem schedule; `daily_water_mode` manual/auto. |
| A9-7 | Leaders get read-only Garden, History and Forecast. | Table 4 asks leaders to judge readings and forecast. | `MATRIX` in `frontend/src/app/Auth.tsx` and role checks in `backend/blueprints/*`. Update Fig. 6. |
| A9-8 | Dashboard = React + TypeScript built with Vite (compiles to HTML, CSS, JS). | Table 5 lists HTML/CSS/JS. | Table 5 wording. |
| A9-9 | Node detects return to solar above 12.8 V while the XH-M609 returns at 13.2 V. | By design (adapter never reaches 12.8 V); explained in Help. | — |

## Builder defaults

| Area | Decision | Reason | How to change |
|---|---|---|---|
| Hosting | **Vercel-ready** in addition to the paper's Docker profile: static dashboard + one Python serverless function (`api/index.py`). | The group asked for a Vercel deployment. | `vercel.json`; Docker files in `deploy/`. |
| Hosting | No Redis. Login rate limits, lockouts and device nonces live in MySQL tables (`login_attempts`, `device_nonces`). | Serverless instances share no memory; one fewer service to run. | `backend/security.py`, `backend/device_auth.py`. |
| Hosting | Scheduled jobs run three ways: Docker worker (APScheduler), Vercel Cron (`/api/cron/due`, daily on Hobby), and an **opportunistic runner** on dashboard `/status` calls. | Vercel Hobby cron runs at most once a day. | `backend/services/jobs.py`; add an external cron to `/api/cron/due` with `CRON_SECRET` for hourly runs. |
| ML | Training needs scikit-learn and runs in the worker, `make train` or the `Retrain model` GitHub Action. Inference walks the exported trees in pure Python (`forest_runtime.py`, identical to `RandomForestRegressor.predict`, tested). | scikit-learn + SciPy do not fit a serverless bundle comfortably. | `requirements-ml.txt`, `.github/workflows/retrain.yml`. |
| ML | On Vercel, "Retrain now" queues a request (`app_state.retrain_request`) picked up by the worker or the Action. | Same reason. | — |
| ML | n_estimators = 300, min_samples_leaf = 2, random_state = 42 (demo model: 100 trees). | FR-ML-04 "e.g." values. | `train_model(n_estimators=...)`. |
| ML | The forecast step "for hour h+1" is the step from the latest batch retrieved before h whose time is closest to h+1 (within 3 h). | FR-ML-01 needs one step per hour. | `backend/services/ml/dataset.py`. |
| Cold start | The 14-day cold start begins with the **first live reading** (`deployment_started_at`), editable by a manager. | Paper says "first 14 days after deployment". | Settings > Learning period started. |
| Phase | `system_settings.operating_phase` is updated by a system row when the phase changes (model activated after day 14). | FR-CTL-08 "stored". | `jobs._phase_sync`. |
| Decision | When watering is needed but the forecast is older than 6 h, the decision is `water` with reason `forecast_stale` (the original reason is kept in `inputs_json.need_reason`). | FR-WX-02: rain pause not applied, reason logged. | `decision_engine.decide`. |
| Decision | Rain-pause window and thresholds are inclusive (exactly 70 % and exactly 2.0 mm pause). | "at least" in FR-CTL-05. | Tests in `test_decision_engine.py`. |
| Status words | "Getting dry" starts 3 points above the threshold; "Below minimum" = any plot below `probe_min_vwc`. | Plain-language status needs an early warning. | `GETTING_DRY_MARGIN` in `backend/services/status.py`. |
| Commands | Undelivered commands expire after 60 s; a Stop cancels a pending Start. | FR-COM-05. | `GK_COMMAND_TTL_S`. |
| Offline | Node shown offline after 15 s without a poll. | FR-COM-07. | `GK_OFFLINE_AFTER_S`. |
| Offline | Node also goes offline after 5 failed polls (15 s), not only after a failed POST. | A node that cannot poll also cannot receive commands. | `POLL_FAILS_OFFLINE` in `config.h`. |
| Firmware | `valve_close_gap_ms` default 100 ms (0–1000). | FR-ACT-03. | Settings. |
| Firmware | Fault schedule splits a share longer than the max watering time into several runs separated by the soak interval. | FR-FS-03. | `planFaultRuns` in `gk_logic.h`. |
| Firmware | Time unknown after a reboot with no connection: fault schedule runs at boot + 1 h (60 %) and 10 h later (40 %). | FR-FS-05. | `FaultScheduler::dueByBoot`. |
| Firmware | Calibration helper "read now" (FR-SEN-07) is a dashboard command; raw values can be applied as ADC dry / wet. | TC1/TC2. | Settings > Sensor calibration. |
| Firmware | Calibration STARTING VALUES: ADC dry 3000, ADC wet 1300 (from the original sketch), θdry 5 %, θsat 45 %. | No reference values yet. | Replace after TC1 with the reference meter. |
| Firmware | HTTPS pins ISRG Root X1 + X2 by default; the setup page accepts a custom root (Caddy `tls internal`) or plain HTTP for bench tests. | C-6 TLS pinning. | Setup page (hold BOOT at power-up). |
| Firmware | The original 1-probe sketch is kept as a **bridge** (`firmware/legacy_single_probe`), using `/api/sensors/*` with `X-Device-Key`; off unless `GK_LEGACY_DEVICE_API=true`. | Lets the group test the dashboard with today's hardware. | Env var; remove when Box B has three probes. |
| Power | With `power_setup = adapter_only` an UNKNOWN source is shown as the wall socket. | FR-PWR-02 dashboard labelling while Box A is not built. | Settings > Power. |
| Demo | `GK_DEMO_MODE=true` seeds 17 days of simulated history, three demo accounts and a virtual Box B so a Vercel preview works with no hardware. Turn it off for the real garden. | Thesis defense and beta testing. | Env var. |
| Security | Signed cookie sessions (stateless) with rotation at login, 7-day rolling / 30-day absolute; a password change ends older sessions. | Works on serverless without a session store. | `backend/security.py`. |
| Security | CSP allows inline *styles* (`style-src 'unsafe-inline'`) but no inline script. | React sets dynamic styles; C-9 forbids inline script only. | `vercel.json`, `deploy/Caddyfile`. |
| UI | Forms use controlled React state and server-side field specs (unit, range, step from `/settings`), not React Hook Form + Zod. | Smaller bundle; the server is the single source of ranges. | `frontend/src/screens/Settings.tsx`. |
| UI | Hand-written service worker instead of vite-plugin-pwa; last `/status` kept in `localStorage`. | Fewer dependencies; no push notifications. | `frontend/public/sw.js`. |
| UI | "Langit" sky preview chips (Morning / Midday / Afternoon / Night) in the menu show another time of day for 8 s. | Interactive theme requested by the group. | `ThemeProvider.previewPeriod`. |
| Data | Database: MySQL 8.4 (tested, including the full test suite). SQLite for development and the demo. | Paper. | `DATABASE_URL`. |

## Supporting tables (for the ERD note)

`devices`, `device_commands`, `control_decisions`, `ml_models`, `audit_logs`, `test_records`,
`device_status_periods`, plus `device_events` (boot / reset reasons, read-now), `device_nonces`
(replay protection), `login_attempts` (rate limit and lockout), `daily_water_use` (Equation 8),
`job_runs` (scheduler bookkeeping) and `app_state` (forecast status, retrain request, demo state).
