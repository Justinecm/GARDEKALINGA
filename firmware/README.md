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
