# Operations

## Daily
- The Garden screen should show **Online** and a reading from the last 30 minutes.
- Records → Online / offline lists every outage; Reports → Readings stored per day should show 46–48.

## When something is wrong
| Symptom | Check |
|---|---|
| Controller offline | Wi-Fi router power; Box B power LED; the 12 V adapter in the wall socket |
| "Forecast not updated since …" | `OWM_API_KEY`; internet at the server; on Vercel, that someone opened the dashboard or the hourly cron runs |
| A plot shows "Sensor problem" | Cable gland and screw terminal of that probe; probe in the soil; raw value in the plot sheet |
| Water now does nothing | Records → Watering; Reports → Command delivery (expired = the node did not poll) |
| Auto watering never happens | Rain pause on Forecast; soak time; Settings (limit, minimum); model card (is the model in use?) |

## Maintenance
- **Backups** (Docker): nightly at 02:00, 14 kept. Test a restore each month: `make restore FILE=…` on a spare host.
- **Device key**: Settings → Controller → Make a new device key, then enter it in the setup page (hold BOOT at power-up).
- **Model**: retrained weekly (Sunday 01:00). The model is used only while it beats "same as now".
- **Updates**: `git pull && make up && make migrate` (Docker); push to the Vercel branch (Vercel).
- **Secrets** live only in `.env` / Vercel environment variables. Rotate `SECRET_KEY` to sign everyone out.
