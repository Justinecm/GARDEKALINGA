# CONNECT_PLAN: live site and ESP32 controller

Audit date: 20 Nov 2026 (container clock). Follows CONNECT_PROMPT.md Part 2 and Part 9.

## 0. Status: blocked on inputs

This repository (`Justinecm/GARDEKALINGA`, branch `main`, one commit) contains only `README.md`.
The following inputs from CONNECT_PROMPT.md are **not present**:

| Input | Where it should be | Found |
|---|---|---|
| Source of the site deployed at gardekalinga.vercel.app | repo root | No. This repo is not the deployed one, as the prompt suspected |
| BUILD_PROMPT.md (C-3, C-4, C-6, FIXED values) | repo root | No |
| firmware/legacy/sketch_nov20a/sketch_nov20a.ino | firmware/legacy/ | No |
| Confirmed column of Part 0 | CONNECT_PROMPT.md | Empty (defaults apply, all flagged) |
| Vercel project access (env vars, logs, usage) | — | No (no Vercel token or connector in this session) |

Server work (Part 3), the firmware (Part 4) and the golden HMAC vector (Part 5.1) all depend on
the exact C-3 signature string and on the real source. I will not guess C-3. Everything below
comes from probing the live site from outside, without credentials and without writing any data.

## 1. Audit findings (from outside)

| # | Item | Finding | Evidence | Confidence |
|---|---|---|---|---|
| 1 | API stack | **Python, Flask (Werkzeug)** on Vercel Python functions. Frontend: React + Vite SPA (`/assets/index-*.js`, `react-*.js`, `query-*.js` = TanStack Query) | Unknown routes return Werkzeug's stock 404 text ("The requested URL was not found on the server. If you entered the URL manually…") and stock 405 text; `/api/ready` keys come back alphabetically sorted (Flask `jsonify` default) | High |
| 1a | Trailing slash | `/api/device/v1/poll/` → **404 JSON**, no redirect. Good: no 308 on device routes | curl | High |
| 1b | Rewrites | Unknown without vercel.json. `/docs/openapi.yaml` returns the SPA's index.html (SPA catch-all rewrite) | curl | Medium |
| 2 | Database | Connected (`"database":true`). Provider, region, ORM, pooling: **unknown, need source** | /api/ready | — |
| 3 | Device routes | `/api/device/v1/{poll, settings, readings, events, sync}` exist and answer **401 JSON** `{"error":{"code":"device_auth_missing","message":…}}` without headers. Poll is 401, not 404, so that check passes. `/api/device/v1/commands/x/ack` → 404, most likely because a UUID URL converter rejects `x`; the ack path still needs confirming in source. Sending `X-Device-Id/X-Timestamp/X-Nonce/X-Signature` still gives `device_auth_missing`, so **the real C-3 header names differ** from my guess (need BUILD_PROMPT) | curl | High / Medium |
| 3a | **Legacy route still live** | `POST /api/sensors/readings` with `{}` and no auth → **422 validation_error** (wants `device_id`, `readings`), not 401. Either it checks the body before auth or it has no auth. Not tested further, because a valid body could write to production | curl | High that it is live; auth status unknown |
| 4 | Demo mode | `demo:true` in production. `/api/v1/auth/me` **publishes demo logins in clear, including a `manager` account** (password `gardekalinga-demo`). The dashboard has "Demo controls" (fault, offline, solar, rain, dry soil, reset, buffered readings) driving a "virtual controller". How it stores data (separate tables or same tables by device_id) needs source | curl + bundle strings | High |
| 5 | Keys, nonces, rate limits | Need source. Check for in-process dicts / `functools.lru_cache` / module globals | — | — |
| 6 | Worker jobs (C-5) | `/api/cron/forecast` exists, answers GET with 404 `"Cron endpoints are disabled (set CRON_SECRET)."` and POST with 405. So **CRON_SECRET is not set**, and cron routes are **GET-only** (Vercel Cron sends GET; the prompt says POST, see decision D-04) | curl | High |
| 7 | firmware/gardekalinga_node/ | Not in this repo | — | — |
| 8 | Env vars | Inferred from outside: database URL set; `OPENWEATHER_API_KEY` **not set**; `CRON_SECRET` **not set**; a demo flag **on**. Full list needs `.env.example` and the Vercel dashboard | /api/ready, cron 404 | Medium |
| 9 | Region / protection | Functions run in **iad1 (Washington, D.C.)** (`x-vercel-id: iad1::iad1::…` on every call). No Deployment Protection, Firewall challenge or bot page in front of `/api/device/*` for a non-browser client: plain curl gets JSON. DB region unknown. If the DB is in Singapore, every poll crosses the Pacific twice. | headers | High |
| 10 | TLS chain | **Not observable from this sandbox**: outbound TLS goes through an inspecting egress proxy, so `openssl s_client` shows the proxy's CA, not Vercel's. Run the Part 2 command from the bench laptop. Expected (unverified): Let's Encrypt intermediate → **ISRG Root X1**. Plan: pin ISRG Root X1 + X2 + whatever the bench shows | openssl | — |

Timing from this sandbox (US-based, not representative of Manila): unauthenticated poll 401 in
0.135–0.151 s total. Re-measure from the bench (Part 3.3).

## 2. What already works vs what is missing

Works (seen from outside): health and ready probes; JSON error shape `{"error":{"code","message"[,"fields"]}}`
on every path tried; device route family under `/api/device/v1/` returning 401; no trailing-slash
redirects; dashboard with roles (manager, caretaker, leader), CSRF, bilingual (EN / Filipino)
strings including "Not installed" / "Sensor problem"; watering start/stop, status, settings,
forecast, model routes under `/api/v1/`; a cron route guarded by CRON_SECRET.

Missing or wrong:
- Source, spec and sketch in this repo (Section 0).
- `OPENWEATHER_API_KEY` and `CRON_SECRET` unset → forecast, rain pause, TC8 and the fault watch cannot run.
- Function region iad1; should sit next to the DB (sin1 if the DB is in Singapore).
- Legacy `/api/sensors/readings` still routed.
- Demo mode on in production, with manager credentials published. **This must be off, or demo users must be limited to gk-sim-* devices, before gk-bench-01 or gk-node-01 is registered in production.** Otherwise anyone on the internet can start the real pump.
- Unknown until source: nonce store, key encryption, `GET /settings` content, `n` field, idempotency by UUID, read_now handling, `installed` flag, online/offline-on-read, expire-on-read, register-device script.

## 3. Stages

| Stage | Work | Needs |
|---|---|---|
| S0 | This audit; budget decision by the group (Section 4) | Group |
| S1 | Source audit items 2, 3, 5, 6, 8; golden HMAC vector `docs/hmac_test_vector.json`; server fixes from Part 3.1 (nonce table, no in-memory state, remove `/api/sensors/*`, `GET /settings`, `n`, expire-on-read, online-on-read); register-device script; simulator gk-sim-01 against a preview deployment with its own DB branch | Source repo, BUILD_PROMPT.md, a preview DB |
| S2 | Firmware Stage 1 (two tasks, HTTPS + pinned CA, HMAC, 3 s poll, readings, Serial console with `v` relay identify) | Sketch, BUILD_PROMPT C-6, bench |
| S3 | Bench bring-up Part 5 steps 3–6; dashboard device panel, command flow, latency, bench tag | Bench hardware, Vercel access |
| S4 | Firmware Stage 2 (cycle events, retries → fail-safe, LittleFS buffer, watchdog, NVS settings) | — |
| S5 | Firmware Stage 3 (provisioning page, FR-SEN/PWR/FS rest, native Unity tests) | — |
| S6 | Part 7 checks K1–K14 into docs/TEST_EVIDENCE.md | Bench, 24 h run |

## 4. Vercel budget arithmetic (Part 6), done before measuring

Function invocations, 30-day month:

| Source | Calls / month |
|---|---|
| Poll, 1 node, every 3 s (86,400 / 3 × 30) | 864,000 |
| Readings at :00/:30 | 1,440 |
| Events, acks, settings, sync (estimate) | ~3,000 |
| Dashboard `/status` every 5 s, 1 tab open 4 h/day (720 × 4 × 30) | 86,400 |
| **Total, one real node, light dashboard use** | **~954,840 = 95 % of 1,000,000** |
| gk-sim-01 polling production at 3 s as well | +864,000 → **~182 %** |
| Two real nodes (bench + garden) at 3 s | +864,000 → **~182 %** |

The poll alone is **86.4 %** of the Hobby invocation allowance, above the 80 % stop line from
Part 6, before any dashboard traffic. Edge requests use the same count against their own
Hobby allowance (1,000,000 as I understand it), so the result there is the same.

Active CPU: at a target of 10 ms per poll, 864,000 polls = 8,640 s ≈ 2.4 CPU-hours a month. If
Python (Flask + DB driver) costs 20–30 ms per warm call, that is 4.8–7.2 CPU-hours, at or above
the Hobby Active CPU allowance (about 4 h, to be confirmed on the Usage tab). Cold starts add more.

**Per Part 6, I am stopping here and not choosing for the group.** Options (none implemented):
- **a. Vercel Pro** for the deployment and evaluation months. Removes the cap risk. Costs money.
- **b. Move only `/api/device/v1/*`** to a host without per-call caps (a small VPS or container in Singapore, same DB). The dashboard stays on Vercel.
- **c. On-site profile** (BUILD_PROMPT C-10).
- **d. Adaptive poll** (3 s while a dashboard is open or water is running, slower otherwise). Changes FR-COM-02 and the wording of TC4, so it needs the adviser's approval. With the `n` field it becomes a setting, but `n` stays 3 until the group decides.

Also, regardless of option: never point gk-sim-01 at production for longer than a short smoke
test, and do the 24-hour measurement (K14) once a choice is made.

## 5. Risks

1. **Demo manager login is public while demo is on.** If real hardware is registered in that state, anyone can water or stop the garden. Highest priority before bench step 4.
2. **Budget**: Hobby overrun takes the system down mid cold-start or mid evaluation (Section 4).
3. **Relay pins**: sketch has pump=26 / valve=27, paper FR-ACT-01 has valve=26 / pump=27. Unresolved until the bench `v` test. A swap means the pump runs against a closed valve.
4. **Legacy route** `/api/sensors/readings` may accept unauthenticated writes.
5. **Region**: iad1 functions; if the DB is in Asia, each poll pays two trans-Pacific DB round trips. Still well inside the 6 s budget, but it wastes CPU and wall time.
6. **TLS pinning**: wrong or missing root → the node cannot connect at all. Must read the chain from the bench, and keep two or more roots.
7. **Calibration**: dry 1500 / wet 1300 is a 200-count span, likely a bad probe or bad reading. Readings are bench-only until re-measured (Part 1.2).
8. **Serverless state**: any nonce, rate limit or key cache in process memory breaks replay protection across instances.

## 6. Open questions for the group

1. Which repo (or CLI upload) does Vercel deploy gardekalinga.vercel.app from? Please add it to this session, or push the source plus BUILD_PROMPT.md and the sketch here.
2. Budget: option a, b, c or d (Section 4)?
3. May demo mode be turned off in production now (it hides the public demo logins)? Or should demo stay on and be limited to gk-sim-*?
4. Part 0, H1–H11: please fill in the Confirmed column at the bench.
5. Where is the database hosted (provider and region)?
6. Who can set Vercel env vars (`OPENWEATHER_API_KEY`, `CRON_SECRET`, `DEVICE_KEY_ENC_KEY`) and the function region?

## 7. Decisions recorded so far

To move into docs/DECISIONS.md once the real repo is in place.

- D-01: All Part 0 rows use the defaults until confirmed; relay pins stay in config.h and are settled only by the bench `v` test.
- D-02: The TLS root is unknown until read from the bench; ca_certs.h will carry ISRG Root X1 + X2 plus the observed root.
- D-03: The budget decision is handed to the group (Part 6); nothing changed.
- D-04: Cron routes stay **GET + Bearer CRON_SECRET**, which is what is deployed and what Vercel Cron sends. External schedulers (cron-job.org, GitHub Actions) can send GET too. Change it by accepting POST as well in the cron blueprint.
