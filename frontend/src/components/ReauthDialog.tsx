import { useState } from "react";
import { api, ApiError } from "../api/client";
import { useI18n } from "../i18n/I18n";
import Sheet from "./Sheet";

export default function ReauthDialog({ open, onDone }: { open: boolean; onDone: (ok: boolean) => void }) {
  const { t } = useI18n();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.post("/api/v1/auth/reauth", { password: pw });
      setPw("");
      onDone(true);
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : t("error_generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} title={t("reauth_title")} onClose={() => onDone(false)}>
      <form onSubmit={submit}>
        <p className="hint" style={{ marginBottom: 12 }}>{t("reauth_lead")}</p>
        <label className="label" htmlFor="reauth-pw">{t("password")}</label>
        <input id="reauth-pw" className="input" type="password" autoComplete="current-password" value={pw}
          onChange={(e) => setPw(e.target.value)} aria-invalid={!!err} aria-describedby={err ? "reauth-err" : undefined} required autoFocus />
        {err && <p id="reauth-err" className="error-text" role="alert" style={{ marginTop: 6 }}>{err}</p>}
        <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
          <button className="btn btn-water" type="submit" disabled={busy || !pw}>{t("confirm")}</button>
          <button className="btn btn-quiet" type="button" onClick={() => onDone(false)}>{t("cancel")}</button>
        </div>
      </form>
    </Sheet>
  );
}
