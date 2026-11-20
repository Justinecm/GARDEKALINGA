// Users (manager): add, deactivate, reset password, change role. No self-registration (FR-UI-09).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Role, User } from "../api/types";
import { useAuth } from "../app/Auth";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/I18n";
import { fmtSmart } from "../lib/time";

const ROLES: Role[] = ["caretaker", "manager", "leader"];

export default function Users() {
  const { t, lang } = useI18n();
  const { user: me } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["users"], queryFn: () => api.get<{ items: User[] }>("/api/v1/users") });
  const [adding, setAdding] = useState(false);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [form, setForm] = useState({ full_name: "", username: "", role: "caretaker" as Role, password: "", language: "fil" });
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<Record<string, string>>({});

  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });

  async function patch(u: User, body: Partial<{ role: Role; is_active: boolean; password: string }>) {
    try {
      await api.patch(`/api/v1/users/${u.id}`, body);
      toast(t("user_saved"), "good");
      void refresh();
      return true;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "critical");
      return false;
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/v1/users", form);
      setAdding(false);
      setForm({ full_name: "", username: "", role: "caretaker", password: "", language: "fil" });
      setErr({});
      toast(t("user_saved"), "good");
      void refresh();
    } catch (x) {
      if (x instanceof ApiError) setErr({ ...x.fields, _: x.message });
    }
  }

  return (
    <div className="page">
      <div className="page-head row" style={{ justifyContent: "space-between" }}>
        <h1>{t("users_title")}</h1>
        <button className="btn btn-water" onClick={() => setAdding(true)}><Icon name="users" size={18} />{t("add_user")}</button>
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>{t("full_name")}</th><th>{t("username")}</th><th>{t("role")}</th><th>{t("col_status")}</th><th>{t("last_login")}</th><th><span className="visually-hidden">{t("details")}</span></th></tr></thead>
          <tbody>
            {data?.items.map((u) => (
              <tr key={u.id}>
                <td><strong>{u.full_name}</strong></td>
                <td>{u.username}</td>
                <td>
                  <label className="visually-hidden" htmlFor={`role-${u.id}`}>{t("role")}</label>
                  <select id={`role-${u.id}`} className="select" style={{ minWidth: 150 }} value={u.role} onChange={(e) => void patch(u, { role: e.target.value as Role })}>
                    {ROLES.map((r) => <option key={r} value={r}>{t(`role_${r}` as const)}</option>)}
                  </select>
                </td>
                <td>{u.is_active ? t("status_active") : t("status_inactive")}</td>
                <td>{fmtSmart(u.last_login_at, lang)}</td>
                <td>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="btn btn-quiet btn-sm" onClick={() => { setResetFor(u); setPw(""); }}>{t("reset_password")}</button>
                    {u.id !== me?.id && (
                      <button className="btn btn-quiet btn-sm" onClick={() => void patch(u, { is_active: !u.is_active })}>{u.is_active ? t("deactivate") : t("activate_user")}</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Sheet open={adding} title={t("add_user")} onClose={() => setAdding(false)}>
        <form className="stack" onSubmit={add}>
          {(["full_name", "username"] as const).map((f) => (
            <div key={f}>
              <label className="label" htmlFor={`nu-${f}`}>{t(f)}</label>
              <input id={`nu-${f}`} className="input" value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} required aria-invalid={!!err[f]}
                autoCapitalize={f === "username" ? "none" : undefined} />
              {err[f] && <p className="error-text">{err[f]}</p>}
            </div>
          ))}
          <div>
            <label className="label" htmlFor="nu-role">{t("role")}</label>
            <select id="nu-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{t(`role_${r}` as const)}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="nu-lang">{t("language")}</label>
            <select id="nu-lang" className="select" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
              <option value="fil">Filipino</option><option value="en">English</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="nu-pw">{t("password")}</label>
            <input id="nu-pw" className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required aria-describedby="nu-pw-h" aria-invalid={!!err.password} />
            <p id="nu-pw-h" className="hint">{t("password_rule")}</p>
          </div>
          {err._ && <p className="error-text" role="alert">{err._}</p>}
          <button className="btn btn-water btn-big" type="submit">{t("save")}</button>
        </form>
      </Sheet>

      <Sheet open={!!resetFor} title={`${t("reset_password")}: ${resetFor?.full_name ?? ""}`} onClose={() => setResetFor(null)}>
        <form className="stack" onSubmit={async (e) => { e.preventDefault(); if (resetFor && (await patch(resetFor, { password: pw }))) setResetFor(null); }}>
          <label className="label" htmlFor="rp">{t("new_password")}</label>
          <input id="rp" className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={10} required aria-describedby="rp-h" />
          <p id="rp-h" className="hint">{t("password_rule")}</p>
          <button className="btn btn-water btn-big" type="submit" disabled={pw.length < 10}>{t("save")}</button>
        </form>
      </Sheet>
    </div>
  );
}
