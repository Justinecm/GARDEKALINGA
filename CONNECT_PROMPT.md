<!--
HOW TO USE THIS FILE
1. Save it in the root of the repo that Vercel deploys gardekalinga.vercel.app from, as
   CONNECT_PROMPT.md, next to BUILD_PROMPT.md. (Check Vercel > Project > Settings > Git.
   Justinecm/GARDEKALINGA was last pushed on 11 Nov 2026, before the build prompt, so the
   live site may come from another repo or a CLI deploy.)
2. Copy sketch_nov20a.ino to firmware/legacy/sketch_nov20a/sketch_nov20a.ino
   (Arduino needs the folder name to match the sketch name).
3. Fill in the "Confirmed" column of Part 0 at the bench (about 5 minutes). If you are not
   sure about a row, leave it empty. The agent will use the default and flag it.
4. Open the repo in Claude Code (or another coding agent) and say:
   "Read CONNECT_PROMPT.md and BUILD_PROMPT.md, then connect the ESP32 to the live site.
    Start with CONNECT_PLAN.md."
5. Have ready: the ESP32 on USB, the relay board powered, a bucket of water for the pump,
   and access to the Vercel project (env vars, logs, usage).
Prompt version 1.0, 21 Nov 2026. Pairs with BUILD_PROMPT.md v1.0 (CHAPTER 1,2,3 draft v2).
-->

# GARDEKALINGA: connect the live website and the ESP32 controller

<role>
You are a senior embedded and full-stack engineer. You have shipped ESP32 devices that talk
to serverless backends over HTTPS on weak Wi-Fi. You treat the relays as safety equipment:
the pump must stop on time even when the network, the server or your own code misbehaves.
You verify on real hardware, you read serial logs, and you do not invent requirements.
</role>

<mission>
Make the deployed site https://gardekalinga.vercel.app and the bench ESP32 work as one system.
The node authenticates with its own key, sends readings, polls for commands every 3 seconds,
waters when the dashboard or the decision engine tells it to, reports what it really did, and
keeps the garden safe when the internet or the server is gone.

"Connected" means every check in Part 7 passes on the real bench hardware, with evidence in
docs/TEST_EVIDENCE.md, and nothing secret is committed.
</mission>

<inputs>
- BUILD_PROMPT.md: the full system spec. It stays the source of truth for the device API
  (C-3), the decision engine (C-4), the firmware structure (C-6) and every value marked FIXED.
- firmware/legacy/sketch_nov20a/sketch_nov20a.ino: the sketch running on the bench today. It
  is the only code proven on the real wiring. Treat its pin numbers and raw readings as facts
  about the bench, and its control logic as a prototype to be replaced.
- The repo: the site deployed on Vercel. Checked from outside on 21 Nov 2026:
  - GET /api/health returns {"ok":true,"service":"gardekalinga-api","time":"...Z"}
  - GET /api/ready returns {"ok":true,"database":true,"demo":true,"weather_key":false}
  - GET /api/device/v1/poll without headers returns a 4xx (401 or 404; find out which).
  So an API runs on Vercel functions, it has a database, it is in demo mode, and the
  OpenWeatherMap key is not set.
</inputs>

---

## Part 0. Hardware facts (the group fills in "Confirmed")

| # | Fact | Default (from sketch_nov20a.ino) | Confirmed |
|---|---|---|---|
| H1 | GPIO that drives the pump relay | GPIO26 | |
| H2 | GPIO that drives the valve relay | GPIO27 | |
| H3 | Relay logic | Active LOW (ON = LOW); pins written HIGH before pinMode | |
| H4 | Probes wired | One capacitive probe on GPIO32 | |
| H5 | Paper ID of that probe | S3 (GPIO32 is S3 in the paper's pin map) | |
| H6 | Probe raw value, dry / wet (11 dB attenuation) | 1500 dry, 1300 wet | |
| H7 | Supply divider on GPIO33 (100 kΩ / 22 kΩ) fitted | No (the sketch never reads it) | |
| H8 | Power during bench work | 12 V 5 A adapter into Box B; Box A not built | |
| H9 | Wi-Fi the node will join | 2.4 GHz, with internet access | |
| H10 | Vercel plan | Hobby (free) | |
| H11 | Device IDs | gk-bench-01 (bench), gk-node-01 (garden), gk-sim-01 (simulator) | |

**H1 and H2 conflict with the paper.** BUILD_PROMPT FR-ACT-01 (FIXED) puts the valve (K1) on
GPIO26 and the pump (K2) on GPIO27. The sketch drives the pump on 26 and the valve on 27.
Never guess this. Keep the pins in config.h, run the relay identify test (Part 5, step 3)
before new code ever runs the pump, use what the bench shows, and write the result in
docs/DECISIONS.md with a note that either the wiring or the paper's pin table (Section 3.10)
must change before the final defense. A swapped pair turns valve-before-pump into
pump-against-a-closed-valve.

<rules>
1. Order of truth: values marked FIXED in BUILD_PROMPT.md, then this prompt, then the
   confirmed Part 0 table, then what the repo currently does, then the legacy sketch's logic.
2. Audit before you build (Part 2). Extend what the repo already has. Do not change the
   dashboard's visual design.
3. Do not change FIXED values: 3 s poll, 30 min readings at :00/:30, 64 samples, 500 ms valve
   lead, pump-off before valve-close, 205/3890 fault limits, 2 retries before fail-safe,
   command delivery within 6 s. Where Vercel makes one hard to meet, say so in
   CONNECT_PLAN.md and give options (Part 6). Do not change it quietly.
4. Safety beats connectivity. The node enforces the maximum watering time, the valve lead and
   the stop order on its own. No network call sits in that path.
5. Secrets live in Vercel environment variables and in the node's NVS (or, in Stage 1 only, a
   gitignored secrets.h). Never in git, serial logs, API responses or screenshots.
6. Record every builder default in docs/DECISIONS.md: one line each with the decision, the
   reason and how to change it.
7. Verify on hardware: compile with arduino-cli, flash, read the serial log, look at the
   dashboard, and paste the evidence.
8. Ask the group only when a choice would change a FIXED value, cost money, or touch
   production data. Otherwise take the default given here and keep going.
</rules>

---

## Part 1. Gaps between the bench sketch and the spec

| Area | Sketch today | Target | What to do |
|---|---|---|---|
| Transport | Plain HTTP to 192.168.1.10:3000, blocking, inside loop() | HTTPS to Vercel; network task on core 0, control task on core 1 | Rewrite networking. The control loop never waits on the network |
| Auth | Static X-Device-Key header | HMAC-SHA256 headers with timestamp and nonce (C-3) | Implement C-3 exactly, proven by a shared test vector |
| Endpoints | POST /api/sensors/readings every 15 s | POST /api/device/v1/readings at :00/:30, GET /poll every 3 s, acks, events, sync | Use the C-3 routes. Remove or disable any old /api/sensors/* route in the repo |
| Commands | Serial only ('1', '0', 'a') | Dashboard via poll, plus Serial as a bench console | Keep Serial; log its starts as manual with source "serial" |
| Probes | One probe, map() to 0–100 % | Three probe slots, Eq. 1 VWC with per-sensor calibration | Report S3; S1 and S2 are "not installed" (1.1) |
| Fault limits | Below 200 or above 4000 | Below 205 or above 3890 (FIXED) | Use the FIXED limits |
| Calibration | DRY 1500 / WET 1300 in code | ADCdry, ADCsat, θdry, θsat per sensor from settings | Seed S3 with 1500/1300 as STARTING VALUES; flag the span (1.2) |
| Control | Start below 40 %, stop above 60 %, 30 s max, 60 s cooldown | Server decides (cold-start threshold, fixed run of max_actuation_sec, then soak); node runs the offline fail-safe | Drop the 40/60 hysteresis. For bench demos set max_actuation_sec = 30 and soak = 60 from the dashboard, not in code |
| Auto lock after 3 timeouts | Present | Not in the paper. Paper cycles always end at max time by design, so it would lock every third cycle | Remove it. Note it in DECISIONS.md as a possible future "probe out of soil" check |
| Supply voltage | Not read | GPIO33 divider, hysteresis 11.6 / 12.8 V | Only if H7 is yes. Otherwise send sv = null, src = unknown, and let power_setup = adapter_only label it "Wall socket (not measured)" |
| Watchdog, offline buffer, NTP, cycle events, reset reason | None | FR-ACT-05, FR-FS-02, FR-FS-05, FR-ACT-06, FR-PWR-05 | Stage 2 |

### 1.1 "Not installed" is not "faulty"
Add a per-sensor `installed` flag inside system_settings.calibration_json (no new ERD column).
- Node: reads only installed pins. Uninstalled probes are sent as
  `{"id":"S1","installed":false}`. Document this in docs/openapi.yaml.
- Server: active_probe_count counts probes that are installed and not faulty. "All probes
  faulty" in FR-FS-03 and C-4 means all installed probes are faulty.
- Dashboard: an uninstalled plot is plain gray with "Not installed" / "Walang sensor". It
  never uses the hatched "Sensor problem" look or the critical status color. The scene's
  aria-label and the text summary say it too.
- Settings: managers tick which probes are installed (NFR-PORT-02).

### 1.2 Calibration warning
A 200-count gap between dry (1500) and wet (1300) is very small for a Capacitive Soil
Moisture Sensor v2.0 at 11 dB; dry air usually reads much higher. Before TC1, re-measure
with the "Read now" helper: probe in dry air, in dry soil, in water up to the line, and in
saturated soil. Enter the new numbers in Settings. Until then, mark readings as bench-only.

---

## Part 2. Audit first (write CONNECT_PLAN.md before changing code)

Find and write down, with file paths:
1. The API stack (Node/TypeScript or Python functions, framework, how /api routes map to
   files, vercel.json rewrites, the trailingSlash setting).
2. The database provider and region, the ORM and migrations, and whether connections are
   pooled for serverless.
3. Which device routes exist and how closely they match C-3 (readings, poll, ack, events,
   sync, read_now, settings). Call the production poll URL without headers. It must answer
   401 with the C-3 JSON error shape, not 404, not a 308 redirect, not an HTML challenge page.
4. What "demo" mode does (a built-in simulator? fake rows in the main tables?) and how it is
   switched on and off.
5. Where device keys, nonces and rate-limit counters are kept. Anything kept in process
   memory is a bug on serverless: instances do not share memory and are recycled.
6. What replaced the BUILD_PROMPT worker jobs (C-5) on Vercel, if anything.
7. Whether firmware/gardekalinga_node/ already exists and compiles. If yes, extend it and port
   only the bench facts from the legacy sketch. If not, grow it from the sketch in the stages
   of Part 4.
8. The env var names in .env.example and which are set in the Vercel production environment
   (names only, never values).
9. The function region against the database region, and whether Deployment Protection, a
   Firewall challenge or bot protection would block a non-browser client on the production
   domain.
10. The TLS chain served for gardekalinga.vercel.app:
    `openssl s_client -connect gardekalinga.vercel.app:443 -servername gardekalinga.vercel.app -showcerts`
    Note which root CA it ends in.

Then list what already works, what is missing, the stages you will run, the budget
arithmetic (Part 6) and the risks.

---

## Part 3. Server side on Vercel

### 3.1 Device API
Implement or finish BUILD_PROMPT C-3 exactly: headers, signature string, 120 s clock window
with `time_unsynced`, 10-minute nonce replay window, idempotent writes by UUID, poll
response of 300 bytes or less, one error shape.

Vercel-specific rules:
- Verify the signature against the path and query exactly as the device sent them, byte for
  byte, not a path rewritten by vercel.json or the framework router. Test it through the real
  routing, not by calling the handler directly.
- No redirects on device routes (ESP32 HTTPClient does not follow a 308 on POST) and no
  trailing slashes.
- Nonces without Redis: a `device_nonces` table (device_id, nonce, seen_at) with a unique
  index on (device_id, nonce). Purge rows older than 10 minutes lazily inside the poll
  handler, at most once a minute. List it in DECISIONS.md as a supporting table.
- Device secrets encrypted at rest with DEVICE_KEY_ENC_KEY (Fernet or AES-GCM, whichever the
  stack already uses).
- Add `GET /api/device/v1/settings` if it is missing. The node calls it when the poll's `s`
  is newer than its own settings version, so a change reaches the node in seconds instead of
  at the next 30-minute reading. Builder addition; record it.
- read_now: the node answers with `POST /api/device/v1/events`, type `read_now`, carrying raw
  and VWC per probe. It creates no sensor_logs row and does not run the decision engine.
- Add an optional `n` field to the poll response: the next poll interval in seconds. It is
  always 3 unless the group changes the paper (Part 6). The node accepts 1–60 and falls back
  to 3 when the field is missing or out of range.
- Keep the poll path small: verify the signature, insert the nonce, one UPDATE of
  devices.last_seen_at and last_state_json, one SELECT of pending commands (marked delivered
  in the same statement or transaction), respond. Aim for 10 ms of CPU or less per poll and
  measure it.

### 3.2 Replacing the worker jobs
Vercel Hobby cron runs at most once a day, and only somewhere within the scheduled hour, so
the 5-second, 10-second and hourly jobs from C-5 cannot be Vercel crons. Replace them:

| C-5 job | On Vercel |
|---|---|
| Mark node offline (every 5 s) | Compute on read: online when now − last_seen_at ≤ 15 s. When a poll arrives after a gap over 15 s, close the online period and write the offline period [last_seen_at + 15 s, now] |
| Expire commands (every 10 s) | Expire on read: pending commands older than 60 s become `expired` when the poll or GET /commands/{id} touches them |
| Fetch forecast hourly at :50 | External scheduler (cron-job.org or a GitHub Actions schedule) calls `POST /api/cron/forecast` with `Authorization: Bearer $CRON_SECRET`. Also refresh lazily when a reading arrives and the stored forecast is older than 70 minutes |
| Fault-schedule watchdog 06:20 / 16:20 | Same external scheduler, `/api/cron/fault-watch` |
| Daily water use, nightly cleanup | A Vercel cron once a day is fine |
| Database backup | Use the database provider's backups; document the restore steps in docs/OPERATIONS.md |
| ML retrain | Out of scope here. The decision engine must still fall back with reason `prediction_unavailable` when no model is available |

Every /api/cron/* route rejects calls without the secret and is safe to run twice.

### 3.3 Device registration, demo mode and environments
- A `register-device` script (npm or python, whichever the repo uses) that runs against the
  production DATABASE_URL, creates the device row and prints the 32-byte secret once, in hex.
  Keep POST /devices on the manager dashboard working too, if it exists.
- Register gk-bench-01 for bench work and gk-node-01 for the garden; the simulator uses
  gk-sim-01. Two clients must never share an ID.
- Demo mode must never write into the rows the real devices use in production. If demo and
  real data share tables, separate them by device_id, and show a "Demo data" banner whenever
  the dashboard is showing simulated data. Production runs with demo off during the cold
  start and the evaluation.
- Set power_setup = adapter_only while Box A is not built.
- Set OPENWEATHER_API_KEY in Vercel (weather_key is false today). Without it the forecast,
  rain pause and TC8 cannot pass.
- Put the function region next to the database (for a Manila deployment, a Singapore
  database with the sin1 region is the usual pairing). Measure the poll round trip from the
  bench before and after.

### 3.4 Dashboard changes (keep the existing design)
- "Not installed" plots (1.1).
- A device panel: device ID, firmware version, last seen, RSSI, uptime, last reset reason,
  and settings version on the node against the server.
- The command flow exactly as BUILD_PROMPT C-7: "Sending to the controller…", "Watering"
  only once the poll reports v = 1, "Still waiting" at 6 s, "Not delivered" at 60 s.
- Per-command latency (created → acked) on the ingestion page, for TC4.
- A "Bench device" tag on any device whose ID starts with gk-bench.

---

## Part 4. Firmware: grow the sketch into the connected node

Arduino-ESP32 core 3.x, Arduino IDE compatible, module layout from BUILD_PROMPT C-6. Keep from
the sketch: active-LOW relays written HIGH before pinMode, the IDLE → VALVE_OPENING →
RUNNING → PUMP_STOPPING state machine, sample averaging (raised to 64 per FR-SEN-03), and
the Serial console.

### Stage 1: talks (the bench waters from the dashboard)
- config.h: pins from Part 0, the FIXED constants, GK_DEVICE_ID. secrets.h (gitignored, with
  a committed secrets.example.h): Wi-Fi SSID and password, base URL
  `https://gardekalinga.vercel.app`, device secret. Stage 3 replaces secrets.h with the
  provisioning page.
- Two FreeRTOS tasks. `controlTask` on core 1: sensors, state machine, max-time guard, 1 s
  tick. `netTask` on core 0: Wi-Fi, time, HTTPS. They share a state snapshot under a mutex
  and pass commands through a queue. The control task never blocks on the network.
- Time: NTP (pool.ntp.org, time.google.com). UTC everywhere; Asia/Manila (`<+08>-8`) only for
  the fault schedule. Before the first sync, send requests anyway and adopt `server_time`
  from the responses.
- HTTPS: one NetworkClientSecure (WiFiClientSecure) reused with keep-alive
  (`http.setReuse(true)`), with the CA pinned to the root(s) found in Part 2, item 10. Keep
  ISRG Root X1 and X2 plus whatever root Vercel actually serves, as PEM in ca_certs.h. Never
  call setInsecure(). Send `Accept-Encoding: identity`. Connect timeout 5 s, response
  timeout 5 s.
- HMAC-SHA256 with mbedTLS over the exact C-3 string. Hash the exact body bytes sent; a GET
  hashes the empty string.
- Poll every 3 s with the C-3 query (p, v, src, sv, m, w, rem, s). Commands:
  `start` (clamp d to max_actuation_sec; reject with reason `already_watering` if busy),
  `stop` (always accepted), `read_now`. Ack each command once: `executed` when the valve
  opens, or `rejected` with a reason.
- Readings: 64 samples per installed probe, fault filter 205/3890, Eq. 1 VWC, spatial mean,
  POST at :00 and :30 with a reading_uuid. Act on the decision in the response (water for
  duration_s, trigger_source auto, with decision_id).
- Bench only: the compile flag `GK_BENCH_READING_S` (for example 60) sends readings faster
  for demos. It refuses to build together with `GK_RELEASE`, and only gk-bench-* devices
  use it.
- Serial console: `1` manual start for max_actuation_sec, `0` stop, `s` print status, `v`
  relay identify (pulses only the pin config.h calls the valve, for 2 s, with the pump
  locked off, and prints which GPIO it pulsed). No code path turns the pump on before the
  valve has been open for 500 ms.

### Stage 2: safe
- An event for every cycle with millisecond times: valve_open_at, pump_on_at, pump_off_at,
  valve_closed_at, interlock_ms, close_gap_ms, ended_reason, trigger_source, and decision_id
  or command_id. The same values on Serial as CSV lines with millis().
- Retries: 2 retries per POST, then the offline fail-safe (FR-FS-01) with the settings stored
  in NVS. Polling keeps trying in the background. On success: upload the buffer through
  /sync, take the current settings, resume server control.
- Buffer: a RAM ring mirrored to LittleFS, holding at least 96 readings and 200 events,
  idempotent by UUID.
- Watchdog with the ESP-IDF 5 API (esp_task_wdt_config_t; reconfigure it if the core already
  started it), with both tasks subscribed. A boot event with the reset reason and firmware
  version.
- Settings: a versioned copy in NVS (Preferences), fetched from /settings when the poll's
  `s` is newer.

### Stage 3: complete
- Captive provisioning page (button held at boot) for Wi-Fi, server URL, device ID and secret,
  stored in NVS. Release builds stop using secrets.h.
- The rest of FR-SEN, FR-PWR (only if H7 is yes), FR-FS-03/04/05 (fault schedule and time
  fallback), and the `GK_TEST_HANG` flag for TC13.
- PlatformIO `env:native` + Unity tests for the pure logic: calibration, fault filter,
  interlock timing, fail-safe decisions, fault schedule, power hysteresis, and the HMAC
  string and signature.

---

## Part 5. Bench bring-up (write it as docs/BENCH_BRINGUP.md and follow it)

1. Golden HMAC vector: create docs/hmac_test_vector.json with a fixed secret, method, path
   with query, timestamp, nonce, body and the expected signature. The server test, the
   simulator test and the firmware native test must all produce that signature.
2. Run the simulator (gk-sim-01) against a Vercel preview deployment that uses its own
   database or a dev branch, never production data. Then run it against production. Fix
   everything there before touching hardware.
3. Relay identify: flash Stage 1 with the pump's 12 V lead disconnected. Send `v`. Note which
   relay clicks and whether the valve opens. Correct config.h if needed and record it.
   Reconnect the pump only after this step.
4. Register gk-bench-01, put its secret in secrets.h, flash, and open Serial at 115200.
   Expect, in order: Wi-Fi connected with RSSI, time synced, first poll 200, boot event
   accepted.
5. On the dashboard: device Online within 6 s, the boot event in Logs, S1 and S2 "Not
   installed", an S3 reading after the first reading cycle.
6. Fill the bucket. Press Water now. The valve clicks, the pump starts about 500 ms later, the
   dashboard turns to "Watering" only after that, and at the end the pump stops before the
   valve closes.
7. Run every check in Part 7 and paste the evidence.

---

## Part 6. Vercel budget (do the arithmetic in CONNECT_PLAN.md, then measure)

- The 3 s poll alone is 86,400 ÷ 3 = 28,800 calls a day, about 864,000 in 30 days.
- Readings add about 1,440 calls a month. The dashboard's 5 s /status refresh adds 720 calls
  an hour for every open tab.
- Vercel Hobby includes 1,000,000 function invocations a month plus fixed Active CPU and
  memory allowances. On Hobby, going over usually means waiting until 30 days have passed.
  That would take the system down in the middle of the 14-day cold start or the evaluation.
- After 24 hours with the bench node, read invocations per hour and CPU ms per poll from
  Vercel Observability and the Usage tab, project the month, and write the numbers and the
  remaining headroom in CONNECT_PLAN.md.
- If any projection is above 80 % of its allowance, stop and give the group these options
  without implementing them:
  a. Vercel Pro for the deployment and evaluation period.
  b. Move only the device API to a host without per-call caps; keep the dashboard on Vercel.
  c. The on-site profile from BUILD_PROMPT C-10.
  d. Ask the adviser to approve an adaptive poll (3 s while someone has the dashboard open or
     water is running, slower otherwise). This changes FR-COM-02 and the wording of TC4 in
     the paper. The `n` field from 3.1 makes it a settings change instead of a reflash, but
     `n` stays at 3 until the group decides.

---

## Part 7. Acceptance checks for "connected" (record each in docs/TEST_EVIDENCE.md)

| # | Check | Passes when | Paper link |
|---|---|---|---|
| K1 | Bad requests | Unsigned or wrongly signed: 401 JSON error. Replayed nonce: rejected. Timestamp more than 120 s off after time sync: rejected | FR-SEC-05 |
| K2 | Golden vector | Same signature from server, simulator and firmware native test | C-3 |
| K3 | Online / offline | Online within 6 s of boot. Offline shown within 20 s of unplugging the router, with the last known state and its time | FR-COM-07 |
| K4 | Readings | 24 h on the adapter with 30-minute readings: at least 46 of 48 stored (fast bench mode is for demos only) | TC4 |
| K5 | Command latency | 20 starts and 20 stops from the dashboard, each acked within 6 s; median and max recorded | TC4 |
| K6 | Valve and pump order | interlock_ms within 450–550 and pump off before valve close in 20 cycles, matching the serial log | TC6 |
| K7 | Maximum time | Pump stops at max_actuation_sec for auto, dashboard and serial starts; a longer duration forced through the API is clamped; ended_reason = max_cutoff | TC5, TC7 |
| K8 | Network lost while watering | Router unplugged mid-cycle: the pump still stops on time | FR-ACT-04 |
| K9 | Offline fail-safe and sync | After 2 failed retries, control_mode = offline_failsafe. With the probe in dry air the node waters on its own. After reconnection, buffered readings and events appear once (a repeated sync adds no duplicates), with synced_offline = true | TC10 |
| K10 | Settings push | max_actuation_sec changed on the dashboard; the node reports the new settings version within 6 s and uses it on the next start | FR-UI-08 |
| K11 | Manual log | Every dashboard start and stop shows user and time; serial starts show source "serial" | TC7 |
| K12 | Installed vs faulty | S1 and S2 show "Not installed". Pulling the S3 lead shows "Sensor problem". The fault schedule starts only when all installed probes are faulty | TC3, FR-FS-03 |
| K13 | Demo separation | Production shows no demo rows for gk-bench-01 or gk-node-01; the demo banner shows whenever demo data is on screen | — |
| K14 | Budget | Measured numbers and the monthly projection written down; under 80 %, or the options handed to the group | — |

---

## Part 8. Skills to load (if your environment has them)
embedded-systems and cpp-pro (firmware), secure-code-guardian (HMAC, secrets),
api-designer (openapi.yaml), test-master (golden vector and native tests), debugging-wizard
(bench problems), devops-engineer (Vercel env vars, cron replacement, region). Dashboard
changes follow the existing design and the front-end skills listed in BUILD_PROMPT C-12.

## Part 9. Output format
Write CONNECT_PLAN.md first: audit findings, stages, budget arithmetic, risks, and open
questions for the group. After each stage, report in five lines or fewer: what changed, test
results, hardware evidence, decisions recorded, what is next. Finish with the Part 7 table
filled in.
