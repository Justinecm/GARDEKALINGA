# Box B firmware

| Folder | Use it when |
|---|---|
| `gardekalinga_node/` | Box B is wired to the paper: three probes, valve K1 on GPIO26, pump K2 on GPIO27, supply sense on GPIO33. |
| `legacy_single_probe/` | Today's 1-probe prototype (original wiring). Reports to the dashboard and obeys Water now / Stop. |
| `original/sketch_nov20a.ino` | The group's original sketch, unchanged, for reference. |

## Check the pins first

| Signal | Paper (FIXED) | Original sketch |
|---|---|---|
| Valve relay | **GPIO26 (K1, IN1)** | GPIO27 |
| Pump relay | **GPIO27 (K2, IN2)** | GPIO26 |
| Probes | GPIO34 (S1), GPIO35 (S2), GPIO32 (S3) | GPIO32 |
| Supply sense | GPIO33 (100k / 22k divider) | — |

If you flash `gardekalinga_node` on the original wiring, "valve first" becomes "pump first".
Swap the IN1 / IN2 wires on the relay board first.

## Connect the 1-probe sketch to Vercel (`legacy_single_probe/`)

Demo mode (`GK_DEMO_MODE=true`) cannot take a real controller: its data lives in one function
instance and its device key is never shown. Use the production setup in
[docs/DEPLOY.md §1b](../docs/DEPLOY.md) (managed MySQL), then:

1. **Vercel → Settings → Environment Variables (Production)**, in addition to the §1b variables:

   | Name | Value | Why |
   |---|---|---|
   | `GK_LEGACY_DEVICE_API` | `true` | turns on `/api/sensors/*`, the API this sketch uses |
   | `GK_OFFLINE_AFTER_S` | `60` | the sketch polls every 10 s and is quiet during a run; the default 15 s would flicker "offline" and block **Water now** |

   Redeploy: new variables only reach new deployments.
2. **Register the controller.** Sign in as a manager → **Settings → Controller → Register controller**,
   ID `gk-node-01`. Copy the 64-character secret; it is shown once.
3. **Edit the top of `legacy_single_probe.ino`:** `WIFI_SSID`, `WIFI_PASS`,
   `SERVER_BASE = "https://<project>.vercel.app"` (the production domain, `https`, no trailing slash;
   preview URLs are login-protected), `DEVICE_ID` (the ID from step 2) and `DEVICE_KEY` (the secret).
   Keep `certs.h` in the same folder. `*.vercel.app` uses Let's Encrypt, which `certs.h` trusts.
4. **Flash** (esp32 board package 3.x, no extra libraries) and open the Serial Monitor at 115200.
   Expect `[WiFi] POST status: 200` right after Wi-Fi connects, and **Online** on the dashboard.
   On a failed request the sketch prints a one-line hint under the status code
   (308: use `https://`; 401: wrong ID or key, or a preview URL; 404: `GK_LEGACY_DEVICE_API` is off;
   5xx: open the Vercel function logs).

What to expect from this sketch:
- About 10,000 requests a day (report every 60 s and after each run, poll every 10 s), well inside the
  Vercel Hobby limit of 1,000,000 function calls a month. Going over that limit pauses every
  deployment for 30 days, so do not shorten the intervals on Hobby.
- The server keeps one reading per 30-minute slot.
- **Water now** runs for the chosen time, but never longer than `MAX_RUN_MS` (10 s in this sketch).
- No network call while the valve or pump is on, so the dashboard shows the run once it has ended.
  Watering runs are not listed in History; the node has no clock. The full firmware does both.

## Build and flash (Arduino IDE)
1. Boards Manager: **esp32 by Espressif, version 3.x** (ESP-IDF 5). Board: *ESP32 Dev Module*.
2. Library Manager: **ArduinoJson 7**.
3. Open `gardekalinga_node/gardekalinga_node.ino`, upload, open the Serial Monitor at 115200.

Or with PlatformIO: `pio run -e esp32dev -t upload`. Unit tests of the pure logic on the PC:
`pio test -e native` or `make firmware-test`.

## First setup
1. On the server: `make register-device` (or Settings → Controller). Copy the 64-character secret.
2. Hold the **BOOT** button while powering Box B for 3 seconds. Connect a phone to the Wi-Fi
   **GARDEKALINGA-setup**; the setup page opens.
3. Enter the Wi-Fi name and password, the server URL (`https://your-app.vercel.app`, or the on-site
   address), the device ID and the secret. Choose the certificate:
   - Public domain: Let's Encrypt roots (built in).
   - On-site server: paste the output of `make export-ca`.
4. Save. The node restarts, shows `ONLINE` in the serial log and **Online** on the dashboard.

## Serial log (TC6, TC12, TC13)
Lines are `millis,EVENT,key=value…`, for example:

```
183245,VALVE_OPEN,trigger=auto,run_s=180
363746,CYCLE,n=4,trigger=auto,valve_open=183245,pump_on=183745,pump_off=363745,valve_close=363846,interlock_ms=500,close_gap_ms=101,ended=max_cutoff
```

Serial commands (from the original sketch): `1` manual on, `0` stop and disable automatic watering,
`a` automatic again, `r` read now, `s` status.

## TC13 build
`pio run -e esp32dev-test-hang` adds a `test_hang` command that stops feeding the watchdog.
Never use it in the garden.
