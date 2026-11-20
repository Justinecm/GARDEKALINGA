# PLAN

Built from BUILD_PROMPT.md (paper draft v2) plus the group's request: an interactive, creative
dashboard with light and dark modes, deployable on Vercel. The original `sketch_nov20a.ino` is the
"heart": its state machine and serial commands carry into the new firmware.

## Milestones (paper Table 7, Agile)

| # | Milestone | Status |
|---|---|---|
| M0 | Scaffold, Vercel config, Docker Compose, CI, `/api/health` | Done (Vercel build verified; compose validated) |
| M1 | Schema (ERD + supporting tables), Alembic, auth, roles, audit, settings versions | Done (tested on SQLite and MySQL 8.4) |
| M2 | Device API (HMAC), simulator, ingestion, commands, offline sync, status periods | Done (simulator: TC4 / TC10 rehearsed) |
| M3 | Decision engine, weather client, rain pause | Done (table-driven tests incl. boundaries) |
| M4 | Dashboard: tokens, garden scene, all screens, i18n EN/FIL, PWA shell | Done (axe clean; Chromium screenshots) |
| M5 | ML dataset, training, baseline gate, inline prediction, model card | Done (pure-Python inference for Vercel) |
| M6 | Firmware: sensing, calibration, interlock, fail-safe, fault schedule, power, watchdog, provisioning, buffer | Done (native logic tests pass); ESP32 compile runs in CI |
| M7 | Reports, test bench, backups, security checklist, docs EN/FIL | Done |

## Risks and how they are handled

| Risk | Handling |
|---|---|
| Vercel functions cannot hold scikit-learn comfortably | Train elsewhere (worker / CLI / GitHub Action); export trees; pure-Python inference (tested equal to sklearn). |
| Vercel Hobby cron is daily only | Opportunistic job runner on dashboard requests + `/api/cron/due` for any external scheduler. |
| 3-second polling = ~29k requests/day on serverless | Documented; the on-site Docker profile is recommended for the prototype. |
| Weak data at the garden | Small JS budget, cached last status, offline banner, node fail-safe. |
| Pin mismatch between original sketch and paper | Flagged in README, firmware README and `config.h`; bridge sketch keeps the old wiring. |
| No hardware during development | Demo mode (virtual node) and the signed device simulator. |

## Open items for the group

- Fill in the STARTING VALUES after the 14-day cold start (threshold, probe minimum, max watering, soak, calibration, flow rate).
- Enter the garden's exact coordinates (Settings → Garden location).
- Two caretakers review the Filipino strings (`frontend/src/i18n/strings.ts`).
- Correct the paper text listed in docs/DECISIONS.md (A-9).
