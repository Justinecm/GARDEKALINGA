# Test evidence (paper Table 8)

For each acceptance test: what the system records, how to run it, and what was already checked in
software. Field trials (hardware, reference meter, 14-day data) are run by the group and exported
from **Reports** or **Reports → Test bench**.

| TC | Criterion (FIXED) | Evidence the system produces | How to run | Checked in software |
|---|---|---|---|---|
| 1 Sensor accuracy | MAD ≤ 5 VWC points per soil state, 10 pairs per sensor per state | Test bench TC1 pairs, Eq. 5 per sensor and state, pass/fail, CSV | Settings → Capture raw reading; read the reference meter; enter the pair in Reports → Test bench → TC1 | Eq. 5 computation (`compute_result`, `summarise`) |
| 2 Cable length | ≤ 2 VWC points, 10 pairs per state | Test bench TC2 | Same, 15 m cable vs short lead | Same |
| 3 Faulty sensor | < 5 % / > 95 % marked faulty and excluded, 10 trials | `sensor_logs.probe_fault_json`, `active_probe_count`; firmware log `READING raw=…` | Unplug / short a probe; check Records and History | Firmware native tests `test_fault_filter_boundaries`, `test_spatial_mean_excludes_faulty`; server re-check `test_fault_rule_overrides_node` |
| 4 Logging and command response | ≥ 46 / 48 records per 24 h on each source; commands ≤ 6 s | Reports → Readings stored per day (by source); command latency table; `ingestion.csv` | Run 24 h on adapter and 24 h on solar; press Water now 10× on each | Simulator: 49 readings / 24 h; latency 2.0 s; `test_poll_size_and_command_flow` |
| 5 Max watering and soak | Pump stops at max time; no new watering before soak ends, 10 trials | `actuation_events.ended_reason = max_cutoff`; decisions with reason `soak` | Dry the soil (or Demo → Make the soil dry) and watch two cycles | `test_interlock_sequence` (max cutoff), decision table `in soak` / `soak just ended`, end-to-end `soak` after a cycle |
| 6 Valve before pump | Valve 500 ± 50 ms before pump; pump stops before valve closes, 20 cycles | `interlock_ms`, `close_gap_ms` per event; serial `CYCLE …` lines with millis | 20 cycles; export Watering log; serial log at 115200 baud | Native `test_interlock_sequence` (500 / 100 ms), `test_stop_order_and_busy`; simulator 498 ms |
| 7 Manual commands | Ahead of automatic control, logged with user and time, max time still applies, 10 trials | `audit_logs` (`watering.start/stop`), `actuation_events.user_id` | 10 starts/stops from the dashboard | `test_max_duration_clamp_manual`, `start` clamp to 180 s, event user attached (`test_poll_size_and_command_flow`) |
| 8 Weather and rain pause | Every forecast stored; pause in every cycle meeting the rule and no other, 7 days | `weather_forecasts` (Forecast history); `decisions.csv` with pop/mm inputs | Run 7 days with `OWM_API_KEY`; check `decisions.csv`: rows with `rain_pop_max ≥ 70` and `rain_mm_6h ≥ 2` must be `rain_pause` when watering was needed | `test_rain_rule` boundaries (70 %, 2.0 mm, 6 h window, sum vs max) |
| 9 Prediction accuracy | MAE and RMSE lower than persistence on held-out records | Model card; `ml_models` metrics; held-out rows in metadata; `prediction-accuracy.csv` | After day 14: Forecast → Forecast model | `test_gate_activates_when_better`, `test_gate_rejects_when_not_better`, `test_runtime_matches_sklearn` |
| 10 Offline fail-safe | After 2 failed retries waters from own readings; syncs on reconnection, 10 trials | `device_status_periods`; events `offline_failsafe`; readings `synced_offline` | Unplug the router for 2 h | Simulator `offline` mode; `test_offline_sync` (idempotent); native `test_failsafe` |
| 11 Sensor-fault schedule | Starts about 06:00 and 16:00 (± 5 min), 60 % / 40 %, 4 runs | events `sensor_fault_schedule` with durations; litres from flow rate | Unplug all probes for 2 days | Native `test_fault_plan`, `test_fault_scheduler_clock`, `test_fault_scheduler_boot_relative`; worker watchdog at 06:20 / 16:20 |
| 12 Power failover | 11.6 V → adapter, 13.2 V → solar (± 0.1 V), no repeated switching, no reset, latency (Eq. 6), 10 each way | `power_state_transitions`; boot events (none expected); Test bench TC12 | Bench supply sweep; record switching voltage and latency | Native `test_power_hysteresis` (3 samples, no flapping at 12.0 V) |
| 13 Power stability | No brownout in 20 switches; watchdog restarts after 5 forced stops; valve stays closed | `device_events` boot with `reset_reason` (BROWNOUT / TASK_WDT) | Build `env:esp32dev-test-hang`; send the test hang 5× | Firmware writes relays HIGH before `pinMode`; boot event + open-cycle report |
| 14 Water flow | Flow rate (Eq. 7) trials within 10 %, 5 trials; daily use (Eq. 8) | Test bench TC14 → "Use as pump flow rate"; Reports → Daily water use | Measure volume in a container for a timed run, 5× | `test_test_bench_tc14`, `test_daily_water_equation_8` |
| 15 Dashboard functions | Readings, forecast, prediction, power source, supply voltage, pump and valve status, login required, 3 browsers | Garden, Forecast, Records → Power | Open on Chrome for Android, Samsung Internet, Safari iOS | `test_login_required`; axe 0 violations on 9 screens (Chromium); screenshots in `docs/screenshots/` |

## Hardware checklist before field tests

- [ ] Relays click OFF at power-up (both pins HIGH before OUTPUT).
- [ ] Valve on GPIO26 (K1), pump on GPIO27 (K2). **The original sketch had them swapped.**
- [ ] Divider on GPIO33: 12.00 V in → about 2.16 V at the pin; the dashboard shows 12.0 V ± 0.1.
- [ ] Probes on GPIO34 / 35 / 32; raw values in air ≈ 3000+, in water ≈ 1300 (calibrate with TC1).
- [ ] Setup page reachable (hold BOOT at power-up), device secret entered, node shows Online.
