# Deploying GARDEKALINGA

Three ways to run it. All use the same code.

| | Vercel (cloud) | Docker on site (recommended for the prototype) | Docker on a cloud VPS |
|---|---|---|---|
| Dashboard | Vercel CDN | Caddy on a mini PC / Raspberry Pi in the house | Caddy |
| API | Python serverless function | gunicorn container | gunicorn container |
| Database | Managed MySQL (TiDB Cloud, Aiven, PlanetScale…) | MySQL 8.4 container | MySQL 8.4 container |
| Scheduled jobs | Opportunistic runner + Vercel Cron + GitHub Action for training | worker container (exact times) | worker container |
| Works when the internet is down | No (the node falls back to its own fail-safe) | **Yes**, only the forecast stops | No |

---

## 1. Vercel

There is no demo mode: the dashboard shows only what the ESP32 (Box B) sends, so a Vercel
deployment needs a real database. Without `DATABASE_URL` and `SECRET_KEY` the API refuses to start.

Push this repository to GitHub and click **Add New → Project** in Vercel, then import it.
`vercel.json` already sets the build (`frontend/dist`) and the Python function (`api/index.py`,
Python 3.12 from `.python-version`). Then:

1. **Database.** Create a MySQL-compatible database, for example TiDB Cloud Serverless
   (free tier, MySQL 8 compatible, needs TLS). Note the host, port, user and password.
2. **Create the tables** from your computer (once, and after each update that adds a migration):

   ```bash
   pip install -r requirements-dev.txt
   ```

   ```bash
   DATABASE_URL="mysql+pymysql://USER:PASSWORD@HOST:4000/gardekalinga" DATABASE_SSL=true alembic -c backend/alembic.ini upgrade head
   ```

3. **Environment variables** (Vercel → Settings → Environment Variables, Production):

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | `mysql+pymysql://USER:PASSWORD@HOST:4000/gardekalinga` |
   | `DATABASE_SSL` | `true` for managed MySQL |
   | `SECRET_KEY` | 64 random hex characters (`python -c "import secrets;print(secrets.token_hex(32))"`) |
   | `DEVICE_KEY_ENC_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
   | `OWM_API_KEY` | your OpenWeatherMap key |
   | `CRON_SECRET` | 32+ random characters (Vercel sends it to the cron job) |
   | `GK_LEGACY_DEVICE_API` | `true` only while the original 1-probe sketch is in use |

   If an older deployment had `GK_DEMO_MODE` set, delete it; it is no longer read.

4. **First manager and the device**, from your computer against the same database:

   ```bash
   DATABASE_URL="mysql+pymysql://USER:PASSWORD@HOST:4000/gardekalinga" DATABASE_SSL=true DEVICE_KEY_ENC_KEY="<same key as Vercel>" SECRET_KEY="<same>" python -m backend.cli create-manager --username ana --name "Ana Cruz"
   ```

   ```bash
   DATABASE_URL="mysql+pymysql://USER:PASSWORD@HOST:4000/gardekalinga" DATABASE_SSL=true DEVICE_KEY_ENC_KEY="<same key as Vercel>" SECRET_KEY="<same>" python -m backend.cli register-device --id gk-node-01
   ```

   The device secret is printed once. Enter it in the controller's setup page
   (see [firmware/README.md](../firmware/README.md), "First setup"). Once a manager exists you can also
   register or re-key the controller from the dashboard: **Settings → Controller**.
   The Garden screen says "No readings yet" until the ESP32 sends its first reading.
5. **Scheduled jobs.** The dashboard runs due jobs on its own (forecast every hour while someone
   has it open). `vercel.json` adds one daily cron (allowed on the Hobby plan). For hourly
   forecasts with nobody watching, call `https://<app>/api/cron/due` every hour from any external
   scheduler with the header `Authorization: Bearer <CRON_SECRET>`, or use the Pro plan and change
   the cron schedule to `50 * * * *`.
6. **Training.** In GitHub → Settings → Secrets add `DATABASE_URL`, `SECRET_KEY`,
   `DEVICE_KEY_ENC_KEY`; in Variables set `GK_ENABLE_TRAINING=true` and `DATABASE_SSL=true`.
   `.github/workflows/retrain.yml` then trains weekly (Sunday 01:00 Manila) and picks up
   "Retrain now" requests every 6 hours.

**Request volume.** The node polls every 3 s, about 29,000 function calls a day. Check your
Vercel plan's function-invocation limits. The on-site Docker profile has no such limit.

**ESP32 and Vercel TLS.** The firmware pins the Let's Encrypt roots (ISRG Root X1/X2). If your
domain's certificate chains to another root, choose "custom root CA" in the setup page and paste
that root. You can find it with
`openssl s_client -showcerts -connect your-app.vercel.app:443`.

---

## 2. Docker on site (paper's recommended profile)

Hardware: mini PC or Raspberry Pi 4/5 (4 GB+) in the adjacent structure, on the same Wi-Fi as Box B.

```bash
cp .env.example .env
```

Fill in `SECRET_KEY`, `DEVICE_KEY_ENC_KEY`, `OWM_API_KEY`, `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`,
`MYSQL_MIGRATE_PASSWORD`, and `GK_DOMAIN` (e.g. `gardekalinga.local`). Then:

```bash
make up
```

```bash
make migrate
```

```bash
make create-manager USERNAME=ana NAME="Ana Cruz"
```

```bash
make register-device
```

```bash
make export-ca
```

Paste the printed root CA into the controller's setup page ("On-site server").
Caddy uses `tls internal` by default. Backups run nightly at 02:00 Manila and keep 14 files
(`make backup` runs one now; `make restore FILE=…`).

Security notes: MySQL is on an internal Docker network only; the app user has no DDL rights
(migrations use `gk_migrate`); all containers restart automatically.

## 3. Docker on a cloud VPS

Same as 2, with `GK_DOMAIN=your.domain` and `GK_TLS=you@example.org` (Let's Encrypt).
The node then needs internet for everything except its offline fail-safe.

## Local development

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
make dev-api
```

```bash
make dev-web
```

Create a manager for the local database and register a controller:

```bash
python -m backend.cli create-manager --username ana --name "Ana Cruz"
```

```bash
python -m backend.cli register-device --id gk-node-01
```

Open http://localhost:5173 and sign in. Nothing appears on the dashboard until the controller sends data.
For a bench ESP32 on the same Wi-Fi, run the API without the debugger so it listens on the network:

```bash
flask --app "backend.app:create_app" run -p 5000 --host 0.0.0.0
```

and enter `http://<this computer's LAN IP>:5000` in the controller's setup page ("Plain HTTP, bench test only")
with the printed secret.
