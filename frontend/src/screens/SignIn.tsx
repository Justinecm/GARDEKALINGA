import { useMemo, useState } from "react";
import { ApiError } from "../api/client";
import type { Status } from "../api/types";
import { useAuth } from "../app/Auth";
import { useTheme } from "../app/Theme";
import Segmented from "../components/Segmented";
import { useI18n } from "../i18n/I18n";
import GardenScene from "../scene/GardenScene";
import s from "./SignIn.module.css";

// A calm, healthy garden for the sign-in picture (decorative only).
function welcomeStatus(): Status {
  const probe = (id: "S1" | "S2" | "S3", vwc: number) => ({ id, installed: true, vwc, raw: 1800, fault: false, level: "good" as const, calibrated_at: null });
  return {
    reading: { probes: [probe("S1", 36), probe("S2", 33), probe("S3", 38)] },
    settings: { probe_min_vwc: 22, moisture_threshold: 30 },
    watering: { pump: false, valve: false },
    power: { source: "solar" },
    device: { online: true },
    status: { code: "moist_enough" },
    weather_now: { condition: "Clouds", pop_pct: 10 },
  } as unknown as Status;
}

export default function SignIn() {
  const { t, lang, setLang } = useI18n();
  const { login } = useAuth();
  const theme = useTheme();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const status = useMemo(welcomeStatus, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : t("error_generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.page}>
      <div className={s.hero}>
        <GardenScene status={status} period={theme.period} hour={theme.hour} decorative />
        <div className={s.lang}>
          <Segmented label={t("choose_language")} hideLabel value={lang} onChange={setLang}
            options={[{ value: "en", label: "English" }, { value: "fil", label: "Filipino" }]} />
        </div>
      </div>
      <main className={s.body}>
        <div className={s.title}>
          <h1>{t("sign_in_title")}</h1>
          <p>{t("sign_in_lead")}</p>
          <p className={s.place}>{t("garden_name")}, {t("garden_place")}</p>
        </div>
        <form className={s.form} onSubmit={submit} noValidate>
          <div>
            <label className="label" htmlFor="username">{t("username")}</label>
            <input id="username" className="input" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username}
              onChange={(e) => setUsername(e.target.value)} required aria-invalid={!!err} aria-describedby={err ? "login-err" : undefined} />
          </div>
          <div>
            <label className="label" htmlFor="password">{t("password")}</label>
            <input id="password" className="input" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required aria-invalid={!!err} aria-describedby={err ? "login-err" : undefined} />
          </div>
          {err && <p id="login-err" className="error-text" role="alert">{err}</p>}
          <button className="btn btn-water btn-big" type="submit" disabled={busy || !username || !password}>
            {busy ? t("logging_in") : t("log_in")}
          </button>
        </form>
        <section aria-labelledby="privacy-h">
          <h2 id="privacy-h" className="visually-hidden">{t("privacy_title")}</h2>
          <p className={s.privacy}>{t("privacy_notice")}</p>
        </section>
      </main>
    </div>
  );
}
