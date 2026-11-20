<!--
HOW TO USE THIS FILE
1. Put it in an empty folder (or the root of your repo) as BUILD_PROMPT.md.
2. Open that folder in Claude Code (or another coding agent) and say:
   "Read BUILD_PROMPT.md and build the system it describes. Start with PLAN.md."
3. If the agent has skills installed (frontend-design, dataviz, accessibility-review,
   ux-copy, react-expert, typescript-pro, secure-code-guardian, test-master,
   playwright-expert, devops-engineer, embedded-systems ...), Part C-12 tells it which to
   load at each milestone.
4. Before deploying, the group fills in the values marked STARTING VALUE from the 14-day cold-start data.
Source: CHAPTER 1,2,3 draft(v2), Version 2.0, 20 Nov 2026. Prompt version 1.0.
-->

# GARDEKALINGA: build prompt for a deploy-ready web system

<role>
You are a senior full-stack and embedded engineer and a product designer, working as one
team. You build production software for low-resource field deployments: weak mobile data,
unreliable power, and users who are not comfortable with apps. You write careful, tested,
secure code and you explain decisions in plain language. You do not invent requirements, and
you do not change values that the research paper fixes.
</role>

<mission>
Build GARDEKALINGA, a hybrid solar-powered, AI-assisted IoT soil monitoring and predictive
irrigation management system for the Gawad Kalinga Community Garden in Paradise Heights,
Balut, Tondo, Manila. Deliver one repository that contains:

1. a Python (Flask) backend with a MySQL database, a decision engine, an OpenWeatherMap
   client, and a Scikit-learn Random Forest prediction module;
2. a responsive Web Dashboard that opens in a smartphone browser (no app to install);
3. the ESP32 firmware for the field controller (Box B), and a device simulator that behaves like it;
4. a Docker Compose deployment that runs on one always-on host with HTTPS, backups and health checks;
5. tests, an OpenAPI spec, and short operator documentation in English and Filipino.

"Deploy-ready" means: one command brings the stack up on a fresh host, the first manager
account and the ESP32 can be registered from the command line, every acceptance check in
Part A-8 can be run or has a clear manual procedure, and nothing secret is committed.
</mission>

<context>
- Researchers: Rhuzel Adonis, Camillus Borja, Justine Melchor, Darell Sopeña (BSIT, College
  of Computer Studies, Our Lady of Fatima University). Adviser: Mark Anthony Ureta.
- The garden has three cultivation plots watered together as one zone from a covered water
  drum. Caretakers water by hand today, judge dryness by touch, and keep no consistent records.
- Pre-implementation survey (17 caretakers/managers/volunteers + 3 community leaders):
  hardest problems were anticipating the weather (3.88), monitoring garden conditions (3.62),
  deciding when to water (3.62) and record keeping (3.49). Leaders rated caretakers' comfort
  with mobile apps low (2.33) and electricity beside the beds as limited (4.67). Automatic
  recording and weather forecast information were valued most (4.53 each). 16 of 17 own a
  smartphone; 4 of 17 never have mobile data or Wi-Fi at the garden.
- Development follows Agile (analysis, design, development, integration, testing and evaluation).
- The solar box (Box A) is not built yet. During development the 12 V 5 A wall adapter plugs
  straight into the DC input socket of Box B. The software must work in both setups.
</context>

<rules_of_engagement>
1. The paper is the source of truth. Values written as FIXED below come from the paper and
   must not change. Values written as STARTING VALUE are defaults the group will tune; they
   live in the settings table and are editable in the dashboard.
2. Where the paper is silent, use the default given here and record it in docs/DECISIONS.md
   (one line: decision, reason, how to change it). Do not stop to ask; ask only if a choice
   would contradict the paper.
3. Stay in scope. Excluded by the paper: soil NPK testing, SMS alerts, watering beds
   separately, outdoor air sensors, a native mobile app. Do not add them.
4. Work milestone by milestone (Part C-11). Write PLAN.md first. After each milestone, run
   the tests, fix failures, update CHANGELOG.md, then continue.
5. Verify, don't assume: run the code, take Playwright screenshots of the UI, compile the firmware.
6. Never commit secrets. Every secret comes from .env (with a complete .env.example).
7. If an earlier GARDEKALINGA codebase is present (built 17 Nov 2026 from an older draft),
   audit it against this prompt and reuse what matches. It differs from draft(v2) in at least:
   reading interval (15 min there, 30 min now), the offline rule (a 2-hour rule there; now a
   threshold fail-safe plus a 06:00/16:00 sensor-fault schedule), the GPIO map, the rain pause
   rule, the number of test cases (12 there, 15 now), and the dashboard stack.
</rules_of_engagement>

---

# PART A. SYSTEM REQUIREMENTS

## A-1. Actors, roles and permissions

| Role (users.role) | Who | Paper use cases (Fig. 6) |
|---|---|---|
| `caretaker` | Caretakers and volunteers | Log in; view current and past soil moisture; view forecast and predicted watering need; trigger or halt irrigation (manual override); view power source and actuator status |
| `manager` | Garden managers | Everything a caretaker can do, plus configure thresholds and durations, and manage user accounts |
| `leader` | Gawad Kalinga community leaders | Log in; review irrigation logs; view power source and actuator status; request reports |
| Device | The ESP32 in Box B | Sends readings and events, polls for commands, receives settings |
| External system | OpenWeatherMap API | Returns forecast data |

Permission matrix (enforce on the server for every route; the UI only hides what the server already blocks):

| Capability | caretaker | manager | leader |
|---|:-:|:-:|:-:|
| View Garden screen (live status, per-plot readings) | yes | yes | read-only (see A-9 #7) |
| View history charts, forecast, prediction | yes | yes | yes |
| Start or stop watering | yes | yes | no |
| View watering, power and decision logs | yes | yes | yes |
| Export reports (CSV, printable) | no | yes | yes |
| Change settings, calibration, schedules | no | yes | no |
| Manage users, register or rotate the device | no | yes | no |
| Retrain or activate the model | no | yes | no |
| View audit trail | no | yes | yes |

## A-2. Survey problems traced to requirements (paper Table 1)

| Survey problem (mean) | Requirements that answer it | Test cases |
|---|---|---|
| Anticipating the weather (3.88) | FR-WX-*, FR-ML-*, FR-CTL-05 | 8, 9 |
| Monitoring garden conditions (3.62) | FR-SEN-*, FR-UI-01..04 | 1, 2, 3 |
| Deciding when to water (3.62) | FR-CTL-*, FR-ACT-*, FR-FS-* | 5, 6, 7, 9, 10, 11 |
| Inconsistent records (3.49) | FR-LOG-*, FR-UI-07, FR-UI-11 | 4, 14 |
| Limited comfort with mobile apps (2.33) | NFR-USE-*, Part C-7 | 15 |
| Limited electricity beside the beds (4.67) | FR-PWR-* | 12, 13 |

## A-3. Functional requirements

Format: ID, requirement (EARS style), source in the paper. "Shall" is mandatory, "should" is
recommended. Every FR must be covered by at least one automated test or a manual check in docs/TEST_EVIDENCE.md.

### Sensing (firmware) FR-SEN

| ID | Requirement | Source |
|---|---|---|
| FR-SEN-01 | The node shall read three capacitive soil moisture sensors S1, S2, S3 (Capacitive Soil Moisture Sensor V2.0.0, one per plot) on ADC1 pins GPIO34 (S1), GPIO35 (S2), GPIO32 (S3). FIXED. | 1.3.1, 3.10 |
| FR-SEN-02 | The node shall read the 12 V supply voltage on GPIO33 through the R1 100 kΩ / R2 22 kΩ divider (V_supply = V_pin × 122 / 22; 14.4 V maps to about 2.6 V). GPIO36 and GPIO39 stay unused. FIXED. | 3.10 |
| FR-SEN-03 | Every 30 minutes (FIXED), the node shall take 64 samples per sensor with 11 dB input attenuation and average them. Align readings to :00 and :30 of the clock once the time is known. | 1.3.2, 3.8, 3.10 |
| FR-SEN-04 | When a sensor's averaged raw value is below 5% or above 95% of the raw ADC span (below 205 or above 3890 on 0–4095), the node shall mark it faulty and leave it out of the average. FIXED. | 1.3.1, TC3 |
| FR-SEN-05 | The node shall convert each good reading to volumetric water content (VWC, %) with the two-point calibration of Equation 1: θi = θdry + (ADCdry − ADCi)/(ADCdry − ADCsat) × (θsat − θdry), using per-sensor ADCdry, ADCsat, θdry, θsat stored in flash and editable from the dashboard. ADCdry is the larger raw value. Clamp the result to 0–100 and keep the raw value. | 3.8 Eq. 1 |
| FR-SEN-06 | The node shall compute the spatial-mean VWC of the active sensors (Equation 2) and the active sensor count, and shall also report each sensor's own value. | 3.8 Eq. 2 |
| FR-SEN-07 | The firmware shall support a calibration helper: on a manager's "read now" command it takes an immediate 64-sample reading and returns raw and VWC per sensor without changing the 30-minute schedule. (Builder addition for TC1/TC2; record in DECISIONS.md.) | 3.12 TC1–2 |

### Communication FR-COM

| ID | Requirement | Source |
|---|---|---|
| FR-COM-01 | The node shall send each reading to the backend with an HTTP POST every 30 minutes over Wi-Fi. FIXED. | 1.3.2 |
| FR-COM-02 | The node shall poll the backend for commands and settings with a lightweight HTTP GET every 3 seconds on either power source, and shall stay awake (no deep sleep) because it watches the supply voltage continuously. FIXED. | 1.3.2, 3.8, Fig. 9 |
| FR-COM-03 | When a POST fails, the node shall retry twice in the same cycle; after the second failed retry it shall switch to the offline fail-safe mode (FR-FS-01). FIXED. | 1.3.2, TC10 |
| FR-COM-04 | The backend shall reply to each reading with the current instruction (water for N seconds, or no action, with a reason code) and with the full settings when the node's settings version is out of date. | Fig. 9 |
| FR-COM-05 | A dashboard command shall reach the node within 6 seconds on both power sources. FIXED (TC4). Commands not delivered within 60 seconds expire and are shown as "not delivered". | TC4 |
| FR-COM-06 | When the connection returns, the node shall upload the readings and events it stored while offline, receive the current settings, and resume server control. Uploads are idempotent (client-generated UUIDs). | 1.3.2, Fig. 9, TC10 |
| FR-COM-07 | The backend shall mark the node offline when no poll arrives for 15 seconds (builder default) and the dashboard shall show the last known state with its time. | Fig. 9 |

### Control and decision engine FR-CTL

| ID | Requirement | Source |
|---|---|---|
| FR-CTL-01 | The system shall enforce the four-tier priority, highest first: (1) bounded maximum watering time cutoff, (2) authenticated manual override, (3) online predictive control (cold-start threshold for 14 days, then Random Forest, with rain pause), (4) offline edge fail-safe. FIXED. | 1.3.2, Fig. 7 |
| FR-CTL-02 | Cold-start phase: for the first 14 days after deployment (FIXED, stored as `cold_start_days`), automatic watering is decided by the moisture threshold: water when the spatial-mean VWC is below `moisture_threshold`. | 1.3.2 |
| FR-CTL-03 | Predictive phase: after the cold start, and only while an active model beats the persistence baseline (FR-ML-06), water when the Random Forest's predicted spatial-mean VWC one hour ahead is below `moisture_threshold`. If no valid prediction exists for the cycle, fall back to the threshold rule and log reason `prediction_unavailable`. | 1.3.2, 3.8 |
| FR-CTL-04 | In both phases, the system shall also start a watering cycle when any single active probe is below `probe_min_vwc`, so one dry plot is not hidden by the average. | 1.3.1, 1.3.2 |
| FR-CTL-05 | Rain pause: the backend shall hold off automatic watering when the forecast gives at least 70% chance of rain AND at least 2 mm of rain within the next 6 hours (STARTING VALUES from the paper: `rain_pop_pct`=70, `rain_mm`=2.0, `rain_window_h`=6). Compute with the forecast steps whose time falls within the next 6 hours: chance = highest step POP, rain = sum of step rain. Applies to automatic decisions only, not to manual commands or the offline fail-safe. | 1.3.2, 2.4, TC8 |
| FR-CTL-06 | Each automatic watering cycle shall run for the bounded duration `max_actuation_sec`, followed by a mandatory soak interval `soak_interval_sec` before the next automatic decision can start watering. | 1.3.2, TC5 |
| FR-CTL-07 | The decision engine shall run on every reading the backend receives and shall log every decision (action, reason code, inputs, phase, settings version), whether or not it waters. | Fig. 7 |
| FR-CTL-08 | Operating phase shall be visible and stored (`cold_start`, `predictive`), along with the day of the cold start ("Day 6 of 14"). | 3.8 ERD |

### Actuation safety FR-ACT

| ID | Requirement | Source |
|---|---|---|
| FR-ACT-01 | Valve relay K1 on GPIO26 (IN1) and pump relay K2 on GPIO27 (IN2). Both relays switch ON when the pin is driven LOW (JD-VCC jumper removed). FIXED. | 3.10 |
| FR-ACT-02 | Start sequence: open valve (GPIO26 LOW), wait 500 ms (FIXED, ±50 ms in TC6), start pump (GPIO27 LOW). | 1.3.1, 3.10, TC6 |
| FR-ACT-03 | Stop sequence: stop pump first (GPIO27 HIGH), then close the valve (GPIO26 HIGH) right after. Builder default gap 100 ms, setting `valve_close_gap_ms` (0–1000). The order pump-off then valve-close shall never change. | 1.3.1, 3.10, TC6 |
| FR-ACT-04 | The node shall enforce `max_actuation_sec` itself, for every trigger source including manual, and the backend shall never issue a duration longer than it (Tier 1). | 1.3.2, TC5, TC7 |
| FR-ACT-05 | On boot the firmware shall write both relay pins HIGH before setting them as outputs, so no relay clicks on at start-up. A watchdog timer shall restart the node if the program stops responding; the normally closed valve keeps water off during the restart. | 1.3.2, 3.8, TC13 |
| FR-ACT-06 | The node shall record the millisecond times of valve open, pump on, pump off and valve close for every cycle, and report interlock_ms (pump on − valve open) and close_gap_ms (valve close − pump off). It shall also print them to the serial log. | TC6 |

### Fallbacks FR-FS

| ID | Requirement | Source |
|---|---|---|
| FR-FS-01 | Offline fail-safe: when the backend cannot be reached after two retries, the node shall decide watering from its own calibrated readings with the threshold, per-probe minimum, maximum watering time and soak interval stored in flash, keeping the valve-before-pump order. | 1.3.2, Fig. 9 |
| FR-FS-02 | While offline, the node shall keep readings and events in a buffer (RAM, mirrored to LittleFS so a restart does not lose them) holding at least 48 hours of readings (96) and 200 events, and upload them on reconnection. | 1.3.2, 3.6 Table 4 recoverability |
| FR-FS-03 | Sensor-fault schedule: when all three probes are marked faulty, the node shall water twice a day at about 06:00 with 60% of the daily water and at about 16:00 with the remaining 40% (Asia/Manila, ±5 min). Run length = share of `daily_water_l` ÷ `flow_rate_lpm`, capped by `max_actuation_sec` per run; if the cap applies, split into several runs separated by the soak interval (splitting is a builder default; record it). Works online and offline. | 1.3.2, 3.8, TC11 |
| FR-FS-04 | `daily_water_l` = the 7-day average of measured daily water use (Equation 8) once 3 days of normal operation exist; until then, 2 × `max_actuation_sec` × `flow_rate_lpm` / 60 (builder default, record in DECISIONS.md). `flow_rate_lpm` comes from TC14; STARTING VALUE 1.5 L/min (R385 spec 1.5–2 L/min). | 3.8, TC14 |
| FR-FS-05 | Time keeping: the node syncs time by NTP and from the server's `server_time` field. If the time is unknown after a reboot with no connection, it runs the fault schedule relative to boot (60% run at boot + 1 h, 40% run 10 h later) until time is known. (Builder default, record in DECISIONS.md.) | Not in paper |

### Power monitoring FR-PWR

| ID | Requirement | Source |
|---|---|---|
| FR-PWR-01 | The node shall determine the active source from the supply voltage: SOLAR→ADAPTER when it falls to 11.6 V or below; ADAPTER→SOLAR when it rises above 12.8 V (the adapter holds about 12.0 V and never reaches 12.8 V). Require 3 consecutive 1-second samples before switching state. FIXED thresholds. | 1.3.1, 3.10 |
| FR-PWR-02 | At boot: SOLAR if above 12.8 V, ADAPTER if 11.6 V or below, otherwise UNKNOWN until a threshold is crossed. A manager setting `power_setup` = `adapter_only` (Box A not installed) or `hybrid` lets the dashboard label the state correctly during development. | Builder default |
| FR-PWR-03 | Each change of source shall be reported with time and voltage and stored in power_state_transitions. The live supply voltage shall be shown on the dashboard. | 3.8 ERD, TC12, TC15 |
| FR-PWR-04 | The hardware switch (XH-M609 in Box A) transfers at 11.6 V and returns at 13.2 V. The software only observes it; the dashboard help text explains the two sets of numbers. | 1.3.1, 3.10 Fig. 12 |
| FR-PWR-05 | The node shall report its reset reason after every boot so brownouts and watchdog restarts can be counted. | TC13 |

### Weather FR-WX

| ID | Requirement | Source |
|---|---|---|
| FR-WX-01 | The backend shall call the OpenWeatherMap 5-day / 3-hour forecast API every hour (at :50) for the garden's coordinates (setting `garden_lat`, `garden_lon`; the group enters the exact location) with metric units, and store every 3-hour step: forecast_for, temperature_c, humidity_pct, pop_pct, rain_3h_mm (0 when absent), weather_condition (OWM `weather[0].main`). | 1.3.2, 3.8 |
| FR-WX-02 | API failures shall be retried with backoff, logged, and shown on the dashboard as "Forecast not updated since <time>". The decision engine uses the latest stored forecast that is less than 6 hours old; older than that, rain pause is not applied and the reason is logged. | Builder default |
| FR-WX-03 | The API key is a secret in .env. Stay far inside the free plan (hourly calls). | 3.8 |

### Machine learning FR-ML

| ID | Requirement | Source |
|---|---|---|
| FR-ML-01 | Build an hourly dataset. For hour h (local time, prediction made at h): mean_vwc = mean of the two 30-min readings in [h−1, h); delta_vwc = mean_vwc − mean of [h−2, h−1); irrigation_sec_prev_hour = pump-on seconds in [h−1, h); hour_of_day; and the forecast for hour h+1 (temperature_c, humidity_pct, rain_3h_mm, one-hot weather_condition: Clear, Clouds, Rain, Drizzle, Thunderstorm, Atmosphere for Mist/Haze/Fog/Smoke and similar). Use only forecasts retrieved before h (no leakage). Target = mean of the readings in [h, h+1). | 1.3.2, 3.8 Fig. 8 |
| FR-ML-02 | Cleaning: drop hours where all probes were faulty or a reading is missing; match each hour with the forecast step covering it. | Fig. 8 |
| FR-ML-03 | Split chronologically (train on earlier records, test on the latest 20%). Never shuffle. | 3.8 |
| FR-ML-04 | Model: Scikit-learn RandomForestRegressor with few settings (e.g., n_estimators=300, min_samples_leaf=2, random_state=42). Save with joblib plus a metadata JSON (version, feature list, date range, rows, metrics). | 3.8 |
| FR-ML-05 | Compute MAE (Eq. 3) and RMSE (Eq. 4) on the held-out records for the model and for the persistence baseline (next hour = current mean_vwc). | 3.8, TC9 |
| FR-ML-06 | Activate a model only if both its MAE and its RMSE are lower than the baseline's. Otherwise stay on threshold control and retry at the next weekly retrain. | 3.8 |
| FR-ML-07 | First training runs automatically at the end of day 14; retrain weekly (Sunday 01:00 Asia/Manila); managers can trigger retraining. Keep every model version. | 3.8 |
| FR-ML-08 | Every prediction is stored with model_version, the input sensor log and forecast, the decision, the target time, and later the actual VWC of that hour, so live MAE/RMSE can be shown. | 3.8 ERD, Fig. 8 |
| FR-ML-09 | Inference happens inline when the :00 reading arrives (it takes milliseconds) and is reused for the :30 reading of the same hour. | Builder default |

### Dashboard FR-UI

| ID | Requirement | Source |
|---|---|---|
| FR-UI-01 | Garden screen: current and last-known per-plot and average soil moisture, a plain-language status ("Moist enough. Next check at 2:30 PM."), operating phase, the next decision or rain pause reason, soak time remaining, device online/offline with last-seen time. | 1.3.2, Fig. 6 |
| FR-UI-02 | Weather forecast and predicted watering need: next 24 hours of 3-hour steps (condition, temperature, humidity, chance of rain, rain mm), the rain pause state with its reason, and the predicted VWC for the next hour against the threshold. | 1.3.2 |
| FR-UI-03 | Active power source (solar/battery or wall socket), live supply voltage, pump and valve status. | 1.3.2, TC15 |
| FR-UI-04 | History: soil moisture over time per probe and average, with the threshold and watering events; ranges 24 h, 7 days, 30 days, custom; a table view of the same data. | 1.3.2 |
| FR-UI-05 | Manual override: authorized users start watering (choose 1, 2 or 3 minutes, never more than `max_actuation_sec`) and stop it at any time. Start uses a confirmation sheet; Stop is one tap and always visible while water runs. The UI reflects the node's real state (state-synchronized), not the button press. | 1.3.2, TC7 |
| FR-UI-06 | Start is disabled with a reason when the node is offline, when all probes are faulty and the schedule is running, or when a cycle is already running. During a soak interval, manual start is allowed after a warning ("The soil is still soaking. Water anyway?"). | Builder default |
| FR-UI-07 | Logs: watering events (source, user, start, duration, interlock ms, how it ended), power source changes, decisions with reasons, device online/offline periods. Filters by date and type. | Fig. 3, 6 |
| FR-UI-08 | Settings (manager): watering rules, rain pause, cold start, fault schedule, flow rate, calibration per sensor, power setup, garden location. Each field shows its unit, valid range and current value; saving creates a new settings version, logged with user and time, and is pushed to the node. | Fig. 6, Table 4 |
| FR-UI-09 | Users (manager): add, deactivate, reset password, change role. No self-registration. | Fig. 6 |
| FR-UI-10 | Model card: model version, trained date, rows used, MAE and RMSE against persistence in plain words, live accuracy, active or not and why, retrain button (manager). | 3.8 |
| FR-UI-11 | Reports (manager, leader): irrigation log, power history, daily water use, prediction accuracy, as CSV and a printable page. | Fig. 3 "report request" |
| FR-UI-12 | Test bench (manager, should): record trials for TC1, TC2, TC12 and TC14 (reference meter value, measured volume, time), compute Equations 5, 6 and 7, and export. TC14's result can be applied as `flow_rate_lpm`. | 3.12 |
| FR-UI-13 | English and Filipino interface, chosen at first sign-in and changeable anytime; stored per user. | 3.5, 3.6 |
| FR-UI-14 | Login is required for every screen and API call except the sign-in page and health check. | TC15, Table 4 |

### Users, security and logging FR-SEC, FR-LOG

| ID | Requirement | Source |
|---|---|---|
| FR-SEC-01 | Only registered users can open the dashboard and its records (confidentiality). | Table 4 |
| FR-SEC-02 | Stored readings and settings are protected from unauthorized changes: readings can only be written by the authenticated device; settings only by managers; no API edits or deletes sensor_logs, events or audit records (integrity). | Table 4 |
| FR-SEC-03 | Every manual command and settings change is recorded with user and time (accountability). | Table 4, TC7 |
| FR-SEC-04 | A user's identity is verified before a control command is accepted: valid session, role check, CSRF token (authenticity). | Table 4 |
| FR-SEC-05 | The device authenticates every request (Part C-3). | Builder default |
| FR-SEC-06 | Store only the account details needed for login and for recording manual actions (full name, username, role, password hash). Show a short privacy notice on the sign-in page (Data Privacy Act of 2012). | 3.5 |
| FR-LOG-01 | Store timestamped readings, weather forecasts, predictions, power source transitions, watering events and user actions in MySQL. | 1.3.2 |
| FR-LOG-02 | Ingestion statistics: readings stored per 24 h per power source, and command delivery time (created → acknowledged). | TC4 |
| FR-LOG-03 | Daily water use (Eq. 8) = flow rate × total pump-on time per day, computed nightly and shown in reports. | TC14 |

## A-4. Non-functional requirements (ISO/IEC 25010:2011, paper Table 4)

| ID | Characteristic | Requirement and measure |
|---|---|---|
| NFR-FUN-01 | Functional suitability | All functions in A-3 present and correct; dashboard values match the database and the node's serial log. |
| NFR-PERF-01 | Time behaviour | Command reaches node ≤ 6 s (TC4). Device poll handled in ≤ 200 ms p95 on the server. Dashboard status refresh every 5 s while the tab is visible. |
| NFR-PERF-02 | Resource utilization | Poll response ≤ 300 bytes. Dashboard initial JS ≤ 170 KB gzip, fonts ≤ 60 KB, LCP ≤ 2.5 s on an emulated mid-range phone on slow 4G. Polling pauses when the tab is hidden. |
| NFR-PERF-03 | Capacity | Handles 1 node, 30 users and 2+ years of data (≈ 35,000 readings/year) with no slowdown; index all time columns. |
| NFR-COMP-01 | Interoperability | ESP32, backend, MySQL and OpenWeatherMap exchange data per the documented contract (OpenAPI 3.1). |
| NFR-COMP-02 | Co-existence | The node uses ordinary Wi-Fi with small requests and shares the network and wall socket without interference. |
| NFR-USE-01 | Recognizability, learnability | A caretaker who has never used the app can read the garden status and start/stop watering in under one minute without help (checked in beta testing). |
| NFR-USE-02 | Operability | Touch targets ≥ 44 × 44 px; one primary action per screen; no gesture-only actions. |
| NFR-USE-03 | UI aesthetics | Clear and readable on a 360 px wide phone; text at 200% zoom does not break the layout. |
| NFR-USE-04 | Accessibility | WCAG 2.1 AA: contrast ≥ 4.5:1 text and ≥ 3:1 UI graphics, visible focus, full keyboard use, labels on every input, reduced motion respected, every chart has a table view. |
| NFR-REL-01 | Maturity, availability | Containers restart automatically; ≥ 46 of 48 readings stored per 24 h per power source (TC4). |
| NFR-REL-02 | Fault tolerance | Watering continues through the offline fail-safe when the internet is down and through the wall adapter when the battery is low. |
| NFR-REL-03 | Recoverability | After a power or connection interruption the system resumes and keeps its records: idempotent sync, persistent volumes, nightly database backups kept 14 days with a tested restore script. |
| NFR-SEC-01..04 | Security | See FR-SEC and Part C-9. |
| NFR-MAIN-01 | Modularity | Firmware, backend, worker, frontend and model are separate modules with documented interfaces; any can be replaced without redesigning the others. |
| NFR-MAIN-02 | Modifiability | Threshold, watering times, rain pause, schedule and model change from the dashboard without code changes. |
| NFR-MAIN-03 | Testability | Every function testable through logs and stated criteria; ≥ 80% line coverage on the decision engine, ML pipeline and device API. |
| NFR-PORT-01 | Installability | Hardware installs by plugging the adapter into a wall socket and connecting field cables; software installs with `make up`, `make create-manager` and `make register-device`. |
| NFR-PORT-02 | Adaptability | Number of probes, coordinates and timings are configuration, so the system can serve another bed or a larger area. |
| NFR-PORT-03 | Replaceability | A replaced sensor is recalibrated from the dashboard without reflashing. |
| NFR-PORT-04 | Browsers | Works on current Chrome for Android, Samsung Internet and Safari on iOS (three browsers for TC15), plus Firefox. |

## A-5. Data requirements (MySQL 8.4, utf8mb4, all times stored in UTC)

### Core tables: keep the ERD (Fig. 5) names and columns exactly

| Table | ERD columns (FIXED) | Allowed extra columns (add, never rename) |
|---|---|---|
| users | user_id PK, full_name, username (unique), password_hash, role, created_at | is_active, language, theme, last_login_at, password_changed_at |
| system_settings | setting_id PK, moisture_threshold, max_actuation_sec, soak_interval_sec, operating_phase, updated_by FK→users, updated_at | probe_min_vwc, rain_pop_pct, rain_mm, rain_window_h, cold_start_days, deployment_started_at, flow_rate_lpm, daily_water_l, daily_water_mode (auto/manual), fault_am_time, fault_pm_time, fault_am_share, valve_close_gap_ms, calibration_json, power_setup, garden_lat, garden_lon. Insert-only: each save adds a row; the newest row is current; setting_id is the settings version. |
| sensor_logs | log_id PK, recorded_at, spatial_mean_vwc, active_probe_count, raw_adc_values (JSON), control_mode | device_id, reading_uuid (unique), probe_vwc_json, probe_fault_json, supply_voltage, power_source, received_at, synced_offline (bool) |
| weather_forecasts | forecast_id PK, retrieved_at, forecast_for, temperature_c, humidity_pct, rain_3h_mm, weather_condition | pop_pct (needed by the rain pause; the text lists it, the figure omits it) |
| ml_predictions | prediction_id PK, log_id FK, forecast_id FK, predicted_vwc, decision, model_version, created_at | target_at, actual_vwc, baseline_vwc |
| actuation_events | event_id PK, prediction_id FK (null), user_id FK (null), trigger_source, valve_open_at, pump_on_at, pump_off_at, duration_sec | event_uuid (unique), device_id, command_id, decision_id, valve_closed_at, interlock_ms, close_gap_ms, ended_reason |
| power_state_transitions | transition_id PK, occurred_at, from_source, to_source, battery_voltage | event_uuid (unique), device_id |

Relationships (FIXED): users 1–N system_settings (updates); users 1–N actuation_events
(overrides); sensor_logs 1–N ml_predictions (feeds); weather_forecasts 1–N ml_predictions
(feeds); ml_predictions 1–N actuation_events (triggers).

Enumerations: role {caretaker, manager, leader}; control_mode {online, offline_failsafe,
sensor_fault}; operating_phase {cold_start, predictive}; trigger_source {auto, manual,
offline_failsafe, sensor_fault_schedule}; ended_reason {completed, max_cutoff, manual_stop,
power_loss, watchdog}; power sources {solar, adapter, unknown}.

### Supporting tables (allowed; list them in docs/DECISIONS.md so the ERD note can mention them)

devices (device_id, name, key_encrypted, key_rotated_at, last_seen_at, fw_version, last_state_json),
device_commands (command_id, device_id, op {start, stop, read_now}, duration_sec,
requested_by, created_at, expires_at, delivered_at, acked_at, status), control_decisions
(decision_id, log_id, action, reason_code, phase, inputs_json, settings_version, created_at),
ml_models (model_version, trained_at, rows, date_from, date_to, mae, rmse, baseline_mae,
baseline_rmse, is_active, notes), audit_logs (append-only: who, what, before/after, ip, at),
test_records (tc_number, trial_no, inputs_json, result_json, recorded_by, recorded_at),
device_status_periods (online/offline spans).

Migrations with Alembic. Seed nothing except enumerations; first manager via CLI.

## A-6. External interfaces

- Hardware pin map (FIXED): S1 GPIO34, S2 GPIO35, S3 GPIO32, supply sense GPIO33, valve
  relay IN1 GPIO26 (K1), pump relay IN2 GPIO27 (K2), both active LOW. ESP32 DevKit V1 (30-pin)
  on a screw-terminal breakout board in Box B (IP65, 200 × 200 × 80 mm). Sensor cables up to
  15 m shielded three-core, entering through glands G1–G3. 12 V enters through DC socket P1.
- OpenWeatherMap: `GET https://api.openweathermap.org/data/2.5/forecast?lat=..&lon=..&units=metric&appid=..`.
- Device API and dashboard API: Part C-3.

## A-7. Constraints and limitations to respect in the software

- One irrigation zone; two relay channels; six micro-sprinkler nozzles; water comes from a
  drum refilled by hand. The dashboard should say "Check that the drum has water" in the
  watering confirmation; there is no level sensor (do not add one).
- Weather data describe the area, not the beds; the model learns the local relation.
- 14 days cannot cover seasons; model accuracy is reported only for the observed period.
- Internet at the site is inconsistent; the node must never depend on the server to stay safe.

## A-8. Acceptance tests (paper Table 8) and what the system must provide

| TC | Criterion (FIXED) | System support and evidence |
|---|---|---|
| 1 Sensor accuracy | Mean absolute difference ≤ 5 VWC points per soil state (dry, moist, saturated), 10 pairs per sensor per state | "Read now" + Test bench pairs with reference meter, Eq. 5 per state, CSV |
| 2 Cable length effect | ≤ 2 VWC points between 15 m cable and short lead, 10 pairs per state | Test bench, Eq. 5, CSV |
| 3 Faulty sensor detection | Sensor below 5% / above 95% marked faulty and excluded in all 10 trials | probe_fault_json, active_probe_count in logs; firmware unit test |
| 4 Logging and command response | ≥ 46 of 48 records per 24 h on each source; commands ≤ 6 s on both | Ingestion stats page; command latency per command; CSV |
| 5 Max watering time and soak | Pump stops at max time; no new watering before soak ends, 10 trials | ended_reason=max_cutoff; decisions with reason soak |
| 6 Valve-before-pump | Valve opens 500 ms (±50 ms) before pump; pump stops before valve closes, 20 cycles | interlock_ms and close_gap_ms per event; serial log |
| 7 Manual commands | Executed ahead of automatic control, logged with user and time, max time still applies, 10 trials | audit_logs, actuation_events.user_id |
| 8 Weather and rain pause | Every forecast stored; pause in every cycle meeting the rule and no other, 7 days | Forecast log; decisions export with rule inputs; automated check script |
| 9 Prediction accuracy | MAE and RMSE lower than persistence on held-out records | Model card; held-out predictions CSV |
| 10 Offline fail-safe | After two failed retries, waters from own readings; after reconnection sends stored readings and resumes, 10 trials | Device status periods; events with trigger_source=offline_failsafe; synced_offline readings |
| 11 Sensor-fault schedule | Starts about 06:00 and 16:00 (±5 min), runs deliver 60% and 40%, 4 runs | sensor_fault_schedule events with durations and computed litres |
| 12 Power failover | Moves to adapter at 11.6 V, returns at 13.2 V (±0.1 V), no repeated switching, no ESP32 reset, latency recorded (Eq. 6), 10 each way | power_state_transitions; boot events (none expected); Test bench for latency |
| 13 Power stability and recovery | No brownout in 20 switching cycles; watchdog restarts after 5 forced stops; valve stays closed | Boot events with reset_reason; test-only firmware flag to force a hang |
| 14 Water flow and daily use | Flow rate recorded (Eq. 7); trials within 10% of each other, 5 trials; daily use (Eq. 8) | Test bench; daily water use report |
| 15 Dashboard functions | Readings, forecast, prediction, power source, supply voltage, pump and valve status shown and login required on three browsers | Playwright e2e on three engines + manual checklist |

## A-9. Inconsistencies found in the paper and the default used

1. Command polling: Section 3.8 (architecture paragraph) and the Chapter 2 synthesis say the
   node checks for commands every 3 s "when it runs on the wall-socket adapter"; Section 1.3.2,
   the timing paragraph of 3.8, Figure 9 and TC4 say "on either power source". Built as either
   source. The two sentences should be corrected in the paper.
2. weather_forecasts in Figure 5 has no chance-of-rain column, but the text and the rain pause
   rule need it. Added pop_pct.
3. sensor_logs in Figure 5 has raw_adc_values but no per-sensor VWC or supply voltage, which
   TC15 requires on the dashboard. Added as extra columns.
4. actuation_events has no valve close time, which TC6 needs ("pump stops before the valve
   closes"). Added valve_closed_at and close_gap_ms.
5. No starting numbers are given for the moisture threshold, per-probe minimum, maximum
   watering time or soak interval. STARTING VALUES used: threshold 30% VWC, probe minimum
   22% VWC, max watering 180 s, soak 30 min. The group replaces them after the cold start.
6. The fault schedule's daily water amount is undefined before normal-operation data exist.
   Default in FR-FS-04.
7. Figure 6 links community leaders only to logs and status, but Table 4 asks all 20 end-users
   (leaders included) to judge whether readings and the forecast are shown correctly. Leaders
   get read-only Garden, History and Forecast screens. Either add "View current and past soil moisture readings" to
   the leader in Figure 6 or remove this access.
8. Table 5 lists HTML, CSS and JavaScript for the dashboard. The build uses React with
   TypeScript, which compiles to HTML, CSS and JavaScript; Table 5 can read "HTML, CSS, and
   JavaScript (React with TypeScript, built with Vite)".
9. The ESP32 detects the return to solar above 12.8 V while the hardware switch returns at
   13.2 V. This is by design (the adapter never reaches 12.8 V), not an error; the dashboard
   help explains it.

---

# PART B. NOTE ON TERMS

VWC = volumetric water content (%). Spatial-mean VWC = average of the active (non-faulty)
probes. Soak interval = mandatory wait after watering so water reaches the probes. Cold start
= first 14 days of threshold control while data are collected. Persistence baseline = "next
hour equals this hour".

---

# PART C. BUILD INSTRUCTIONS

## C-1. Architecture

```
 Garden plot (outdoor)          Adjacent structure (indoor wall)           Server (one always-on host)
 ---------------------          --------------------------------           ---------------------------
 S1 S2 S3 probes --15 m--> Box B: ESP32 --HTTPS (HMAC-signed)--> Caddy (TLS) --> /      static dashboard
 12 V NC valve  <-- K1 ----      LM2596S 5 V logic rail                       --> /api  gunicorn + Flask
 R385 pump      <-- K2 ----      2-ch relay, J1, P1                                     |-> MySQL 8.4
 6 micro-sprinklers              ^ 12 V via DC barrel plug                              |-> Redis 7
 PV panel (roof) ----------> Box A: charge controller, SLA battery,          worker (scheduler) -> OpenWeatherMap
                                 XH-M609 + K3 changeover, 12 V 5 A adapter,
                                 fuses F1 10 A, F2 3 A                     Users: smartphone browsers
```

Repository layout:

```
gardekalinga/
  BUILD_PROMPT.md  PLAN.md  CHANGELOG.md  README.md  .env.example  Makefile
  backend/        Flask app (app factory), blueprints: auth, device, dashboard, reports;
                  services: decision_engine, weather, ml, power, schedule; models; alembic/; tests/
  worker/         scheduler entry point (APScheduler) reusing backend services
  frontend/       React + TypeScript + Vite; src/{app,screens,components,scene,charts,i18n,api,styles}
  firmware/       gardekalinga_node/ (Arduino IDE sketch + src/), platformio.ini for native unit tests
  tools/          device_simulator.py, make_local_ca.sh, check_rain_pause.py, export_evidence.py
  deploy/         docker-compose.yml, Caddyfile, backup/, healthchecks
  docs/           DECISIONS.md, API.md (+ openapi.yaml), DEPLOY.md, OPERATIONS.md,
                  TEST_EVIDENCE.md, USER_GUIDE_EN.md, USER_GUIDE_FIL.md
```

## C-2. Stack (pin exact versions in lock files)

- Backend: Python 3.12, Flask 3, SQLAlchemy 2 + Alembic, PyMySQL, pydantic 2 for request
  validation, argon2-cffi, Flask-Limiter (Redis storage), APScheduler (worker only), scikit-learn,
  pandas, NumPy, joblib, httpx, gunicorn, structlog. Tests: pytest, pytest-cov, freezegun, factory-boy.
- Frontend: React 18+, TypeScript (strict), Vite, React Router, TanStack Query, React Hook Form
  + Zod, d3-scale / d3-shape / d3-array (charts drawn as React SVG, no heavy chart library),
  vite-plugin-pwa, @fontsource-variable/atkinson-hyperlegible-next. Styling: CSS custom
  properties + CSS Modules (no utility-class framework). Tests: Vitest, Testing Library,
  Playwright, @axe-core/playwright.
- Firmware: Arduino-ESP32 core 3.x (Arduino IDE compatible, as in paper Table 5), WiFi,
  HTTPClient + WiFiClientSecure, Preferences (NVS), LittleFS, ArduinoJson 7, mbedTLS HMAC,
  esp_task_wdt. Note: the paper's "ADC_ATTEN_DB_11" is the same 11 dB setting that ESP-IDF 5 /
  Arduino-ESP32 3.x calls ADC_ATTEN_DB_12 (`analogSetPinAttenuation(pin, ADC_11db)`).
  Native unit tests of pure logic (calibration, fault filter, interlock state machine, power
  hysteresis, fail-safe, fault schedule) with PlatformIO `env:native` + Unity.
- Deploy: Docker Compose v2, Caddy 2 (automatic HTTPS), MySQL 8.4 LTS, Redis 7.

## C-3. API contract (write it as OpenAPI 3.1 in docs/openapi.yaml first, then implement)

### Device API, `/api/device/v1/*`

Authentication on every request (headers):
`X-GK-Device: gk-node-01`, `X-GK-Timestamp: <unix seconds>`, `X-GK-Nonce: <16 random bytes hex>`,
`X-GK-Signature: hex(HMAC_SHA256(device_secret, METHOD + "\n" + PATH_WITH_QUERY + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + hex(SHA256(body))))`.
Reject if the timestamp is more than 120 s off (allow until the node's first time sync by
accepting the request but returning `server_time` and flag `time_unsynced`), if the nonce was
seen in the last 10 minutes (Redis), or if the signature does not match (constant-time compare).
The device secret is 32 random bytes, shown once at registration. Because HMAC verification
needs the secret itself, store it encrypted at rest with a key from .env
(`DEVICE_KEY_ENC_KEY`, Fernet), never in plain text. Rotation via CLI and dashboard.

`POST /api/device/v1/readings`
```json
{
  "reading_uuid": "6c2c3f0e-...",
  "recorded_at": "2026-12-01T06:30:00Z",
  "probes": [
    {"id": "S1", "raw": 2210, "vwc": 31.4, "fault": false},
    {"id": "S2", "raw": 2350, "vwc": 28.9, "fault": false},
    {"id": "S3", "raw": 40, "vwc": null, "fault": true}
  ],
  "spatial_mean_vwc": 30.2,
  "active_probe_count": 2,
  "supply_v": 12.02,
  "power_source": "adapter",
  "control_mode": "online",
  "settings_version": 7,
  "fw": "1.0.0", "uptime_s": 86400, "rssi": -67
}
```
Response `200`:
```json
{
  "server_time": "2026-12-01T06:30:01Z",
  "decision": {"id": 1234, "action": "water", "duration_s": 180, "reason": "cold_start_threshold"},
  "settings": null
}
```
`reason` codes: moist_enough, cold_start_threshold, predicted_below_threshold,
probe_below_min, rain_pause, soak, already_watering, sensor_fault_schedule,
prediction_unavailable, forecast_stale. `settings` is the full settings object when
`settings_version` is behind.

`GET /api/device/v1/poll?p=0&v=0&src=adapter&sv=12.02&m=online&w=0&rem=0&s=7` (every 3 s;
p pump, v valve, src source, sv supply volts, m mode, w watering source code, rem seconds left,
s settings version). Response ≤ 300 bytes:
```json
{"t": "2026-12-01T06:30:04Z", "s": 7, "cmd": [{"id": 88, "op": "start", "d": 120}]}
```
`POST /api/device/v1/commands/{id}/ack` `{"status": "executed" | "rejected", "reason": "...", "at": "..."}`

`POST /api/device/v1/events` (and `POST /api/device/v1/sync` for the offline buffer, which
accepts `{"readings": [...], "events": [...]}`). Event shapes:
```json
{"uuid": "...", "type": "actuation", "trigger_source": "auto", "decision_id": 1234,
 "command_id": null, "valve_open_at": "...", "pump_on_at": "...", "pump_off_at": "...",
 "valve_closed_at": "...", "interlock_ms": 501, "close_gap_ms": 102, "duration_s": 180,
 "ended_reason": "max_cutoff"}
{"uuid": "...", "type": "power_transition", "occurred_at": "...", "from": "solar", "to": "adapter", "supply_v": 11.58}
{"uuid": "...", "type": "boot", "occurred_at": "...", "reset_reason": "TASK_WDT", "fw": "1.0.0"}
```
All device writes are idempotent by UUID. Readings synced from the buffer get
`synced_offline=true`, `control_mode` as recorded, and no new decision.

### Dashboard API, `/api/v1/*` (session cookie + CSRF header on unsafe methods)

auth: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password`.
status: `GET /status` (everything the Garden screen needs in one call).
data: `GET /readings?from&to&bucket`, `GET /forecast`, `GET /predictions?from&to`,
`GET /events/watering`, `GET /events/power`, `GET /decisions`, `GET /device/periods`.
control: `POST /watering/start {duration_s}`, `POST /watering/stop`, `GET /commands/{id}`.
settings: `GET /settings`, `POST /settings` (new version), `GET /settings/history`.
users: `GET/POST /users`, `PATCH /users/{id}`.
model: `GET /model`, `POST /model/retrain`, `POST /model/{version}/activate` (only if it beats baseline).
reports: `GET /reports/{irrigation|power|water-use|prediction-accuracy|ingestion|decisions}.csv`.
test bench: `GET/POST /test-records`, `GET /test-records/{tc}.csv`.
device admin: `POST /devices`, `POST /devices/{id}/rotate-key`, `POST /devices/{id}/read-now`.
health: `GET /api/health` (no auth), `GET /api/ready` (DB and Redis).
Errors use one JSON shape: `{"error": {"code": "...", "message": "...", "fields": {...}}}`.

## C-4. Decision engine (backend, runs on every live reading)

```
decide(reading, now):
  s = current_settings()
  log = save(reading)
  if device.watering_in_progress:              return NONE("already_watering")
  if reading.active_probe_count == 0:          return NONE("sensor_fault_schedule")   # node runs FR-FS-03
  if last_watering_end and now < last_watering_end + s.soak_interval_sec:
                                               return NONE("soak")
  dry_probe = any(p.vwc < s.probe_min_vwc for p in reading.active_probes)
  if phase(now) == "cold_start":
      need, reason = reading.mean < s.moisture_threshold, "cold_start_threshold"
  else:
      pred = prediction_for(hour_of(reading))          # inline on :00, reused on :30
      if pred is None: need, reason = reading.mean < s.moisture_threshold, "prediction_unavailable"
      else:            need, reason = pred.predicted_vwc < s.moisture_threshold, "predicted_below_threshold"
  if dry_probe and not need: need, reason = True, "probe_below_min"
  if need:
      rp = rain_pause(now, s)                          # FR-CTL-05, uses forecast < 6 h old
      if rp.active: return NONE("rain_pause", rp.details)
      return WATER(duration_s = s.max_actuation_sec, reason)
  return NONE("moist_enough")
phase(now) = "predictive" if now >= deployment_started_at + cold_start_days AND an active model exists, else "cold_start"
```
Every return writes control_decisions (and ml_predictions.decision when a prediction was used).
Tier 2 (manual) bypasses this function entirely; Tier 1 is enforced on the node and by clamping.
Write table-driven unit tests for every branch, including boundary values (exactly 70%,
exactly 2.0 mm, exactly at the end of the soak interval, threshold equality).

## C-5. Worker jobs (Asia/Manila times; one worker instance only)

| Job | When |
|---|---|
| Fetch forecast | hourly at :50 |
| Mark node offline / close status periods | every 5 s |
| Expire undelivered commands | every 10 s |
| Fill actual_vwc for past predictions; live MAE/RMSE | hourly at :40 |
| Daily water use, rolling daily_water_l (if auto) | daily 00:15 |
| First training at end of cold start; weekly retrain | day 14 check daily 00:30; Sunday 01:00 |
| Fault-schedule watchdog: alert if a 06:00 / 16:00 run did not happen within 15 min while all probes are faulty | 06:20, 16:20 |
| Database backup (mysqldump, gzip, keep 14) | daily 02:00 |

## C-6. Firmware structure (non-blocking; no `delay()` in the main loop)

- Modules: `config` (pins, FIXED constants), `settings_store` (NVS, versioned), `sensors`
  (sampling, fault filter, calibration), `power_monitor` (1 s sampling, hysteresis),
  `actuator` (state machine IDLE → VALVE_OPENING → WATERING → PUMP_STOPPING → IDLE, with
  max-duration guard and ms timestamps), `controller` (tiers, offline fail-safe, soak, fault
  schedule), `net` (Wi-Fi reconnect, HTTPS, HMAC signing, retries), `buffer` (RAM ring +
  LittleFS mirror), `timekeeper` (NTP, server time, boot-relative fallback), `wdt`.
- Run networking on core 0 and control on core 1 (FreeRTOS tasks) so a slow HTTPS call never
  delays a relay stop.
- Provisioning: Wi-Fi SSID/password, server URL, device ID and secret entered once through a
  captive setup page (button held at boot) and stored in NVS; never hard-coded.
- TLS: pin the CA used by the server (Caddy's internal root for on-site, ISRG Root X1 and X2
  for a public domain).
- Serial log lines are CSV-like with millis() so TC6 timing can be read from a laptop.
- Build flag `GK_TEST_HANG` adds a manager-only test command that stops feeding the watchdog (TC13); off in release builds.

## C-7. Frontend: design direction (this is where the build must stand out)

### Who it is for
Caretakers and volunteers in Tondo, many not comfortable with apps, using mid-range Android
phones outdoors in strong sun and on weak data. Their one question is "Does the garden need
water, and is it being watered?" Managers tune the system; leaders check records. The
existing request from the group: a unique UI with vector images and an interactive theme.

### Design tokens (validated; keep them in `src/styles/tokens.css`)

| Token | Light ("Umaga") | Dark ("Gabi") | Use |
|---|---|---|---|
| page | `#EAF1EE` morning mist | `#0E1A1F` night | Page background |
| surface | `#FBFCFA` | `#15242A` | Panels, sheets, chart surface |
| ink | `#1E2A24` leaf-dark | `#E7EFEA` | Text (14.5:1 and 13.6:1 on surface) |
| ink-muted | `#4F5D55` | `#A9B8B0` | Secondary text (6.7:1, 7.7:1) |
| drum | `#1F5FA6` water-drum blue | `#6FA8E8` | Water actions, links, focus ring (white text on drum 6.5:1) |
| soil | `#5A3E2B` | `#C79A73` | Soil in the scene, dry states |
| leaf | `#2E7D32` | `#5DBB63` | Plants in the scene |
| paint | `#F2B705` Gawad Kalinga house yellow | `#F2B705` | Sun, solar indicator only (never text on light) |
| stop | `#B3261E` | `#F2938C` | Stop watering button only (white text on light 6.5:1; night-ink text on dark 7.9:1) |

Status colors are reserved and always paired with an icon and a word (dataviz status set):
good `#0ca30c` (moist enough), warning `#fab219` (getting dry), serious `#ec835a` (below
minimum), critical `#d03b3b` (sensor fault, offline). Never use them for decoration or series.

Type: one family, Atkinson Hyperlegible Next Variable (self-hosted, latin + latin-ext), chosen
because it was designed for low-vision legibility. Scale (1.25): 14 / 16 (body, line-height 1.5)
/ 20 / 25 / 31 / 39 px. The garden status sentence is set at 25–31 px, weight 650, as the
headline of the app. Tabular figures for readings. Line length under 70 characters.

### The memorable element: a live garden scene (spend the boldness here, keep the rest quiet)
A hand-built SVG illustration at the top of the Garden screen, made of React components
driven by `/status`:
- Three plots side by side. Each plot's soil fill comes from that probe's VWC on a soil ramp
  (pale dry brown to dark wet brown); plants stand upright when moist and droop below the
  per-probe minimum. A faulty probe shows its plot hatched in gray with a "Sensor problem" tag.
- The blue water drum on its stand with the pump and valve; when the pump runs, water moves
  along the tube and the six sprinkler arcs spray. With `prefers-reduced-motion`, show still
  droplets instead of animation.
- The adjacent house wall painted in Gawad Kalinga colors, with Box A and Box B. The PV panel
  on the roof glows when power is solar; the wall plug lights when power is the wall socket.
- The sky is the interactive theme ("Langit"): its gradient follows Asia/Manila time (umaga,
  tanghali, hapon, gabi) and the current forecast (clear, clouds, rain drops). Users choose
  Auto (follows the sky; the UI turns dark at night), Light or Dark; the choice is saved per user.
- Tapping a plot opens a bottom sheet with that sensor's reading, raw value, status and last
  calibration. Every plot is a real button with a label, reachable by keyboard.
- The scene has `role="img"` and an `aria-label` sentence built from live data, and all its
  information is also shown as text below it. Total scene weight under 30 KB, no raster images.

### Layout (mobile first, 360 px)

```
+----------------------------------+
| GARDEKALINGA        (o) Online   |  top bar: name, node status, menu
|                                  |
|   [ live garden scene SVG ]      |  ~45% of viewport height
|                                  |
| Moist enough.                    |  status sentence (headline)
| Next check at 2:30 PM.           |
| Average 34%  Plot 1 36%  Plot 2  |  per-plot readings, tabular figures
| 33%  Plot 3 sensor problem       |
| Rain likely by 3 PM: watering    |  decision / rain pause line
| paused.                          |
|                                  |
| [ Water now ]                    |  primary action in the thumb zone
+----------------------------------+
| Garden  History  Forecast  Logs  |  bottom navigation (+ Settings for managers)
+----------------------------------+
```
On wide screens: scene on the left 7 columns, status and actions on the right, charts below.
Left-align all text. Panels differ by job (status, action, chart, table) rather than one
identical card style; hairline borders, one radius scale (4 px small, 12 px sheets).

Avoid these generic tells: all-caps eyebrow labels, middle-dot meta strings, monospace data
labels, arrows appended to button text, identical rounded cards with the same grey shadow,
gradient washes as decoration, fade-up animation on every section. Motion only answers an
action (sheet opening, watering starting) or shows state (sprinklers).

### Screens
1. Sign in: username, password, language switch, privacy notice, clear error text.
2. Garden (home): scene, status sentence, readings, decision line, Water now / Stop.
   Water now opens a sheet: "Water all three plots for 3 minutes? Check that the drum has
   water." with buttons "Start watering" and "Cancel". While watering: a large "Stop watering"
   button and the time left, driven by the node's reported state.
3. History: soil moisture chart and table, range picker, export (manager, leader).
4. Forecast: next 24 h in 3-hour steps, rain pause explanation, next-hour prediction against
   the threshold, model card in plain words ("The model's guesses are off by 1.8 points on
   average; guessing 'same as now' is off by 2.6").
5. Logs: watering, power, decisions, device online/offline; filters; CSV.
6. Power (inside Logs or its own tab): current source, live supply voltage, transitions.
7. Settings (manager): grouped forms with unit, range and current value; "Capture raw
   reading" helper for calibration; settings history.
8. Users (manager). 9. Reports and Test bench (manager, leader as allowed). 10. Help: what the
   colours and words mean, what to do when the node is offline, in both languages.

Empty and error states give direction: "No readings yet. The controller sends its first
reading within 30 minutes of being plugged in." "Can't reach the controller since 2:14 PM.
Watering continues on its own. Check the Wi-Fi router in the house."

### Charts (follow the dataviz method)
- One y-axis per chart. Never a dual axis: forecast chance of rain and rain amount are two
  small panels sharing the time axis; supply voltage and power source are a voltage line with
  a source band above it.
- Soil moisture: S1, S2, S3 in categorical slots 1–3 (light `#2a78d6`, `#eb6834`, `#1baf7a`;
  dark `#3987e5`, `#d95926`, `#199e70`), validated with the dataviz validator against the
  surfaces above (all checks pass; light aqua is 2.7:1 so direct labels and the table view are
  required). Average in ink at 2.5 px, probes at 2 px. Threshold as a dashed muted reference
  line and probe minimum dotted, both labelled directly. Watering events as small drop markers
  on the baseline with tooltips. Legend plus direct end labels.
- Prediction: actual (ink, solid) vs predicted (slot 1, dashed) with the threshold line.
- Voltage: line with reference lines at 11.6 V and 12.8 V, labelled.
- Every chart: crosshair tooltip on line charts, hit targets larger than marks, keyboard
  focusable points, a "Show as table" toggle, separate dark-mode steps, no numbers on every point.

### Words (English and Filipino; draft translations for the group and two caretakers to review)

| English | Filipino |
|---|---|
| Soil moisture | Basa ng lupa |
| Moist enough | Sapat ang basa ng lupa |
| Getting dry | Natutuyo na |
| Water now | Diligan ngayon |
| Start watering | Simulan ang pagdidilig |
| Stop watering | Itigil ang pagdidilig |
| Watering, 2 min left | Nagdidilig, 2 minuto pa |
| Watering paused: rain is likely in the next 6 hours | Hindi muna magdidilig: malamang umulan sa susunod na 6 na oras |
| The soil is still soaking | Sumisipsip pa ng tubig ang lupa |
| Controller offline | Walang koneksyon ang controller |
| Last reading | Huling sukat |
| Next check | Susunod na pagsusuri |
| Forecast | Taya ng panahon |
| Next-hour estimate | Tantiya sa susunod na oras |
| Solar battery | Solar na baterya |
| Wall socket | Saksakan sa pader |
| Sensor problem | May problema ang sensor |
| Records | Talaan |
| Log in | Mag-log in |

Use the same word for the same thing everywhere (always "watering", never "irrigation" in the
UI). Sentence case. Buttons name the action. Errors say what happened and what to do.

### Front-end engineering
- PWA: cache the app shell and the last `/status`; offline banner "Showing data from 2:30 PM".
  No push notifications.
- TanStack Query polling of `/status` every 5 s while visible, `/readings` on demand; pause when hidden.
- Command flow: after Start, show "Sending to the controller…", then "Watering" only when the
  node reports the valve open; if not acknowledged in 6 s show "Still waiting", at 60 s
  "Not delivered".
- All dates shown in Asia/Manila, 12-hour clock.
- Playwright screenshots at 360 × 740 and 1280 × 800, light and dark, English and Filipino,
  for every screen; review them and fix layout problems before closing a milestone.
- axe checks with zero serious or critical violations; keyboard-only run through Sign in →
  Water now → Stop.

## C-8. Device simulator (tools/device_simulator.py)
Signs requests exactly like the firmware and simulates: 30-min readings (time-accelerated mode),
soil drying and wetting curves, faulty probes, 3-s polling, executing commands with realistic
interlock timing, going offline and syncing the buffer, power transitions at 11.6 / 12.8 V,
reboots with reset reasons. Use it in e2e tests and to rehearse TC4, TC5, TC7, TC8 and TC10
before the hardware is ready.

## C-9. Security checklist (must all be true before "done")
- Passwords hashed with Argon2id; minimum 10 characters; no password hints.
- Login rate limit (5 per minute per IP and username) and 15-minute lockout after 10 failures; logged.
- Session cookie: HttpOnly, Secure, SameSite=Strict, rotated at login; 7-day rolling, 30-day
  absolute; managers re-enter their password for settings, user and device changes if their
  last sign-in was more than 15 minutes ago.
- CSRF token required on every unsafe dashboard request. Role checks on the server for every route.
- Request validation with pydantic; SQLAlchemy parameters only; no string-built SQL.
- Headers via Caddy: HSTS, CSP (`default-src 'self'`, no inline script), X-Content-Type-Options,
  Referrer-Policy, Permissions-Policy, frame-ancestors none. Same-origin only; no CORS.
- Device HMAC with timestamp and nonce replay protection; per-device secrets encrypted at rest; rotation.
- MySQL and Redis on an internal Docker network only, with their own passwords; the app's DB
  user has no DDL rights at runtime (migrations use a separate user).
- Audit log append-only (no update or delete endpoint).
- No stack traces or secrets in responses or logs. pip-audit and npm audit in CI, failing on high severity.
- .env.example lists every variable; .env is in .gitignore.

## C-10. Deployment
- `deploy/docker-compose.yml` services: caddy, api (gunicorn), worker, mysql, redis, backup.
  Non-root images, multi-stage builds, healthchecks, `restart: unless-stopped`, named volumes
  (mysql_data, models, backups, caddy_data).
- Two profiles documented in docs/DEPLOY.md:
  - On-site (recommended for the prototype): a mini PC or Raspberry Pi 4/5 (4 GB+) in the
    adjacent structure, on the same Wi-Fi as the node; Caddy `tls internal`; export Caddy's
    root CA to the firmware. Keeps working when the internet is down (only the forecast stops).
  - Cloud VPS: domain name, Caddy automatic Let's Encrypt; the node then needs internet for everything.
- Commands: `make up`, `make migrate`, `make create-manager`, `make register-device`
  (prints the device secret once), `make backup`, `make restore FILE=...`, `make logs`.
- CI (GitHub Actions): lint (ruff, eslint), type checks (mypy on services, tsc), tests
  (pytest, vitest, firmware native), Playwright e2e against the compose stack with the
  simulator, build images.
- Time zone: containers in UTC; the app converts to Asia/Manila.

## C-11. Milestones (maps to the Agile phases in paper Table 7)

| # | Milestone | Done when |
|---|---|---|
| M0 | PLAN.md, repo scaffold, compose stack, CI, `/api/health` | `make up` works on a clean machine; CI green |
| M1 | Schema + migrations, auth, users, roles, audit log, settings versions | Auth and RBAC tests pass; manager created by CLI |
| M2 | Device API, HMAC, simulator, ingestion, commands, offline sync, status periods | Simulator runs 24 h accelerated: ≥ 46/48 readings, commands ≤ 6 s (TC4), offline sync works (TC10 simulated) |
| M3 | Decision engine (cold start, soak, max time, probe minimum), weather client, rain pause | Branch tests pass; TC5 and TC8 checks pass against simulated data |
| M4 | Frontend: tokens, scene, Garden, History, Forecast, Logs, Settings, Users, i18n, PWA | Screens reviewed from screenshots; axe clean; e2e on Chromium, WebKit, Firefox (TC15) |
| M5 | ML dataset, training, baseline gate, inline prediction, model card, weekly retrain | Synthetic-data test shows the gate works both ways; TC9 export ready |
| M6 | Firmware: sensing, calibration, fault filter, interlock, fail-safe, fault schedule, power hysteresis, watchdog, provisioning, buffer | Compiles in Arduino IDE / arduino-cli; native unit tests pass; hardware checklist in TEST_EVIDENCE.md |
| M7 | Reports, Test bench, backups and restore, security checklist, docs in EN and FIL | Every row of A-8 has evidence or a procedure; C-9 all true; restore tested |

## C-12. Skills to load (if your environment has them)
Load the skill before starting the milestone that needs it and follow it:
- M0 and the deployment part of M7: devops-engineer, architecture-designer.
- M1–M3: python-pro, sql-pro, secure-code-guardian, api-designer, test-master.
- M4 (front end, use all that apply): frontend-design, dataviz (run its palette validator for
  any new chart colors), accessibility-review, ux-copy, react-expert, typescript-pro,
  playwright-expert, web performance or SEO-technical skills for Lighthouse budgets.
- M5: python-pro, pandas-pro, ml-pipeline.
- M6: embedded-systems, cpp-pro.
- M7: code-documenter, security-reviewer.
If a skill's advice conflicts with this prompt, this prompt wins for facts from the paper; the
skill wins for craft (typography, accessibility, chart marks, secure coding patterns).

## C-13. Definition of done
- All FR "shall" items implemented and tested; "should" items done or listed as deferred.
- All A-8 evidence available; all C-9 items true; NFR budgets measured and reported in README.
- `make up`, `make create-manager` and `make register-device` on a fresh host = a working system with HTTPS.
- docs/DECISIONS.md lists every builder default used (including those in A-9).
- A short demo script in README: sign in as each role, run the simulator, water manually,
  trigger a rain pause, take the node offline, read the reports.

## C-14. Output format for your work
Start by writing PLAN.md: milestones, files to create, risks, and the open decisions you will
default. Then build. At the end of each milestone, report in five lines or fewer: what was
built, test results, screenshots taken, decisions recorded, what is next.
