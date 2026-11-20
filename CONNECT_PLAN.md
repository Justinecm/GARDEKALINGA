# CONNECT_PLAN: live site and ESP32 controller

Audit of 20 Nov 2026 (container clock), CONNECT_PROMPT.md Part 2 and Part 9. Source: `main` at
ef30914 merged into `claude/relaxed-davinci-wanx93`. Live site probed from outside without
credentials and without writing data. Nothing was run against production with a login.

**Verdict.** The repo is far ahead of what CONNECT_PROMPT assumed. The device API (C-3), HMAC
with a nonce table, Fernet-encrypted secrets, cron replacement, the "Not installed" UI and a
two-task firmware with provisioning, NVS, LittleFS buffer and watchdog all exist, and the tests pass
(pytest 51/51, firmware native 17/17). The blockers are **deployment configuration and four code
gaps**, not a rewrite. Three items need the group before any real node is registered (Section 6).

## 1. Audit findings (Part 2, items 1–10)

| # | Item | Finding | Where |
|---|---|---|---|
| 1 | API stack | Flask 3 + Pydantic 2 + SQLAlchemy 2, one Python function. `vercel.json` rewrites `/api/(.*)` → `/api/index`; Flask sees the **original path and query**, so HMAC verifies over the bytes the node sent (`request.path` + raw `query_string`). No trailing-slash redirects (`/poll/` → 404 JSON). React + Vite SPA in `frontend/` | `vercel.json`, `api/index.py`, `backend/device_auth.py:_path_with_query` |
| 2 | Database | MySQL 8.4 via PyMySQL (TiDB Cloud / Aiven suggested), Alembic migration `0001`. On Vercel the engine uses **NullPool**: a new DB connection, with TLS when `DATABASE_SSL=true`, on every invocation. **If `DATABASE_URL` is unset and demo is on, it falls back to SQLite in `/tmp`, separate per instance.** Production reports `demo:true`, which matches DEPLOY.md §1a ("demo mode, no database"), so **production is probably on per-instance SQLite**. A real node cannot work on that: the device row, nonces and commands exist only in the instance that wrote them. Confirm `DATABASE_URL` in Vercel | `backend/config.py`, `backend/db.py`, `docs/DEPLOY.md` |
| 3 | Device routes vs C-3 | All present: `readings`, `poll`, `commands/<int>/ack`, `events`, `sync`, `settings`. Headers `X-GK-Device/-Timestamp/-Nonce/-Signature`, signature string exactly C-3, 120 s window, `time_unsynced` (ts < 1.6e9 → accepted, `tu:1` in poll), 10-min nonce replay, constant-time compare, idempotent by UUID. Live poll without headers → **401** `device_auth_missing` in the C-3 error shape ✅. Poll response measured at **34 bytes** (≤ 300 ✅). Gaps: no `n` field; `installed` comes from presence in the reading, not a `calibration_json` flag (1.1) | `backend/blueprints/device.py`, `backend/services/device_service.py` |
| 3a | Legacy `/api/sensors/*` | Gated by `GK_LEGACY_DEVICE_API` (off in prod) and by `X-Device-Key`. My unauthenticated probe got 422 only because the body is validated before the gate; it cannot write. Fix: check the gate first (one-line reorder), then remove the route once `legacy_single_probe` is retired | `device.py:_legacy_device` |
| 4 | Demo mode | `GK_DEMO_MODE=true` makes a virtual node **inside the API** that writes the **same tables** under **`DEMO_DEVICE = "gk-node-01"`, the real garden node's ID**. It also publishes three demo logins (incl. **manager**) on `/api/v1/auth/me`. The dashboard targets `primary_device()` = the **first device ever created**, so with demo seeded, gk-bench-01 would never be shown or commanded. **Breaks K13 and blocks bench step 5** | `backend/services/demo.py:44`, `device_service.primary_device`, `blueprints/control.py` |
| 5 | Keys, nonces, rate limits | Nonces: `device_nonces` table with a unique key, purged by the opportunistic runner at most every 10 min ✅. Secrets: Fernet with `DEVICE_KEY_ENC_KEY` (derived from `SECRET_KEY` if unset, which produces a warning) ✅. No in-process state on the device path except the demo seed flag. Login rate limiting: not audited yet | `device_auth.py`, `security.py` |
| 6 | Worker jobs (C-5) | Already replaced: an **opportunistic runner** (`jobs.run_due`) runs due jobs from polls (`expire_commands`, `purge_nonces`) and from dashboard `/status` (all cheap jobs); a Vercel cron `GET /api/cron/due` once a day; `GET /api/cron/<job>` with `Bearer CRON_SECRET` for an external scheduler. `CRON_SECRET` is unset in prod (cron answers 404 "disabled"). **Gap:** offline periods are only written by `mark_offline`, which polls do not run. If nobody has the dashboard open during an outage, the gap is never recorded. Part 3.2 wants the poll after a gap > 15 s to write the offline period | `backend/services/jobs.py`, `blueprints/cron.py` |
| 7 | Firmware | `firmware/gardekalinga_node/` exists (1,034 lines): `controlTask`/`netTask` on separate cores, HTTPS with `setCACert(ISRG X1+X2)` and `setReuse(true)`, mbedTLS HMAC, 3 s poll, `/settings` fetch on newer `s`, POST retries then offline fail-safe, RAM ring + LittleFS (96 readings / 200 events), ESP-IDF 5 watchdog reconfigure, boot event, captive setup page, `GK_TEST_HANG`. Its pin map follows the **paper** (valve 26, pump 27). `firmware/legacy_single_probe/` follows the **original wiring**. Not compiled here (no arduino-cli/PlatformIO in this container). **Gaps:** no `v` relay-identify command; no `GK_BENCH_READING_S`; ignores `n`; HTTP timeout 6 s (prompt: 5 s); no `Accept-Encoding: identity`; HMAC not covered by native tests | `firmware/` |
| 8 | Env vars | No `.env.example` (names live in `docs/DEPLOY.md` §1b): `DATABASE_URL`, `DATABASE_SSL`, `SECRET_KEY`, `DEVICE_KEY_ENC_KEY`, **`OWM_API_KEY`** (not `OPENWEATHER_API_KEY` as the prompt says), `CRON_SECRET`, `GK_DEMO_MODE`, `GK_LEGACY_DEVICE_API`, optional `GK_COMMAND_TTL_S`, `GK_OFFLINE_AFTER_S`, `GK_AUTO_CREATE_TABLES`, `SESSION_COOKIE_SECURE`. Production as seen from outside: demo **on**, `OWM_API_KEY` **unset**, `CRON_SECRET` **unset**, `DATABASE_URL` probably unset (item 2) | `backend/config.py` |
| 9 | Region / protection | Functions in **iad1 (Washington, D.C.)**; no `regions` in vercel.json. Pick the DB region first, then set `"regions": ["sin1"]` next to a Singapore DB. No Deployment Protection, Firewall challenge or bot page on `/api/device/*` (curl gets JSON) | headers `x-vercel-id: iad1::iad1` |
| 10 | TLS chain | **Not observable from here** (sandbox egress proxy re-signs TLS). The firmware pins ISRG Root X1 + X2, which is right if Vercel serves a Let's Encrypt chain for `*.vercel.app`. **Run the `openssl s_client` command from the bench laptop before the first flash.** If the chain ends in another root (Vercel also uses other CAs for some domains), add that root to `certs.h` | `firmware/gardekalinga_node/certs.h` |

### Poll cost (measured locally, SQLite, warm)
Signed poll: **3.8 ms CPU, 9 SQL statements**, 34-byte response. The Part 3.1 target is about 5
statements. The extras come from `run_due` (a `job_runs` read, and writes when due),
`current_settings()`, the status-period lookup in `touch_device`, and the device lookup. On Vercel
with MySQL, add one TCP + TLS connection per invocation (NullPool) and a cross-region round
trip per statement if the DB is not in the function's region. That will dominate both wall time and
Active CPU. Re-measure on the real stack (K14).

### Facts that differ from CONNECT_PROMPT
- **H6 calibration:** the committed `firmware/original/sketch_nov20a.ino` has `DRY_VALUE = 3000`, `WET_VALUE = 1300` (span 1,700), not 1500/1300. The Part 1.2 warning about a 200-count span probably came from another copy of the sketch. Still re-measure before TC1.
- **Original sketch has `ENABLE_WIFI false`** and a 10-sample average. It is preserved unchanged; the connected path is `legacy_single_probe/` (original wiring) or `gardekalinga_node/` (paper wiring).
- **Weather env var** is `OWM_API_KEY`.
- **Cron routes are GET + Bearer** (what Vercel Cron sends), not POST.

## 2. What works and what is missing

Works: everything in item 3 and 5; cron/opportunistic jobs; dashboard command flow and
"Not installed"/"Sensor problem" rendering; simulator `tools/device_simulator.py` that signs real
requests; firmware feature set in item 7; 51 backend tests and 17 native firmware tests passing.

Missing, in priority order:
1. **Production configuration**: a real `DATABASE_URL` (+ `alembic upgrade head`), `DEVICE_KEY_ENC_KEY`, `SECRET_KEY`, `OWM_API_KEY`, `CRON_SECRET`, `GK_DEMO_MODE=false`, function region next to the DB. *(Group / Vercel owner.)*
2. **Demo separation**: demo device ID `gk-node-01` → a demo-only ID (proposed `gk-demo-01`), plus a "Demo data" banner whenever that device is on screen.
3. **Device selection**: dashboard and Water now act on `primary_device()` (oldest device). Needs an explicit active device (setting) so gk-bench-01 and later gk-node-01 can be chosen. Show the "Bench device" tag.
4. **Offline-on-read**: in `touch_device`, when the previous `last_seen_at` is more than 15 s old, close the online period at `last_seen_at + 15 s` and record the offline period up to now.
5. **Poll `n` field** (always 3), firmware accepts 1–60, falls back to 3.
6. **Golden HMAC vector** `docs/hmac_test_vector.json` checked by pytest, by the simulator, and by a native firmware test (needs the signing-string builder and HMAC moved into `gk_logic.h` behind a portable SHA-256 for native builds).
7. **Firmware bench items**: `v` relay identify (valve pin only, pump locked off, prints the GPIO), `GK_BENCH_READING_S` (refuses `GK_RELEASE`), 5 s timeouts, `Accept-Encoding: identity`, `n`.
8. **`installed` flag** in `calibration_json`, editable in Settings, used by the node and by `active_probe_count` (1.1).
9. Smaller: legacy route gate order; `.env.example`; device panel fields (fw, RSSI, uptime, reset reason, settings version node vs server); per-command latency on the ingestion page.

## 3. Stages

| Stage | Work | Needs |
|---|---|---|
| S0 ✅ | This audit | — |
| S1 | Code gaps 2–6 and 9 on this branch, with tests. No production change | Nothing. Can start now |
| S2 | Preview deployment with its **own** DB (TiDB/Aiven dev DB or branch), simulator gk-sim-01 against it, then a short smoke test on production | Vercel access, a dev DB |
| S3 | Firmware gaps 7–8; compile with arduino-cli for `esp32dev` | Arduino core 3.x (CI or bench laptop) |
| S4 | Bench bring-up (Part 5): TLS chain, relay identify, register gk-bench-01, first poll, Water now | Bench hardware, decisions in Section 6 |
| S5 | K1–K14 into docs/TEST_EVIDENCE.md, 24 h run, budget measurement | Bench, Vercel Usage tab |

## 4. Vercel budget (Part 6)

| Source | Calls / month |
|---|---|
| Poll, 1 node, every 3 s | 864,000 |
| Readings at :00/:30 | 1,440 |
| Events, acks, settings, sync (estimate) | ~3,000 |
| Dashboard `/status` every 5 s, one tab 4 h/day | 86,400 |
| **One real node, light dashboard use** | **~954,840 = 95 % of 1,000,000** |
| + gk-sim-01 or a second node also polling at 3 s | **~182 %** |

The poll alone is **86.4 %** of the Hobby invocation allowance, above the 80 % line. Active CPU:
3.8 ms/poll measured locally on SQLite. On Vercel with a TLS DB connection per call, expect several
times that. 864,000 × 15 ms ≈ 3.6 CPU-hours a month, near the Hobby Active CPU allowance (check the
current figure on the Usage tab).

**Per Part 6, stopped. Options for the group (none implemented):**
- **a. Vercel Pro** for the deployment and evaluation months.
- **b. Move only `/api/device/v1/*`** to an uncapped host near the DB. The repo already has the Docker image (`deploy/`); the dashboard stays on Vercel.
- **c. On-site profile** (C-10, `deploy/docker-compose.yml`, Caddy `tls internal`). The repo's own DEPLOY.md calls this "recommended for the prototype", and it keeps working when the internet is down.
- **d. Adaptive poll** via `n`. Changes FR-COM-02 / TC4 wording; needs the adviser.

## 5. Risks

1. **Production DB is probably per-instance SQLite** → device auth fails at random, commands are lost. Must be fixed before any node connects.
2. **Demo writes as `gk-node-01`** and publishes a manager login. With demo on, anyone can command whatever `primary_device()` is.
3. **Budget** (Section 4).
4. **Relay pins**: `gardekalinga_node` = paper (valve 26 / pump 27); original sketch = valve 27 / pump 26. Flash the paper firmware on the original wiring and the pump runs against a closed valve. Settle it with the relay-identify test (pump 12 V lead disconnected), and fix either the wiring or the paper's Section 3.10.
5. **TLS root** not yet confirmed from the bench.
6. **NullPool + cross-region DB**: slow polls and high CPU; may push command latency toward the 6 s limit on weak Wi-Fi.
7. **Offline periods lost** when nobody is watching (gap 4), which weakens K3/TC10 evidence.

## 6. Questions for the group (blocking items marked ★)

1. ★ Budget: option a, b, c or d?
2. ★ Production config: may I write the exact Vercel env-var checklist, and who sets it? Which DB provider and region?
3. ★ Demo: turn `GK_DEMO_MODE` off in production now? Demo can live on a separate preview deployment with its own DB.
4. Part 0, H1–H11 at the bench, especially **H1/H2 (relay pins)** and which firmware will run (`legacy_single_probe` on the original wiring, or `gardekalinga_node` after rewiring).
5. Run the TLS `openssl` command from the bench laptop and paste the issuer lines.

## 7. Decisions (to merge into docs/DECISIONS.md with S1)

- D-01: Part 0 defaults apply until confirmed; relay pins settled only by the bench identify test.
- D-02: TLS roots stay ISRG X1 + X2 until the bench shows the chain; add any other root found.
- D-03: Budget decision handed to the group (Part 6); nothing changed.
- D-04: Cron stays GET + `Bearer CRON_SECRET` (deployed behaviour, what Vercel Cron sends).
- D-05 (proposed): demo device ID becomes `gk-demo-01`; gk-sim-01 stays reserved for the signed simulator; gk-bench-01 and gk-node-01 for hardware.
- D-06 (proposed): the dashboard controls an explicit `active_device_id` system setting, defaulting to the oldest non-demo device.
