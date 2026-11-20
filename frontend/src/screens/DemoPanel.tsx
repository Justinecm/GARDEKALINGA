// Demo controls (only when GK_DEMO_MODE is on): show the defense panel what the
// garden does with a broken sensor, no internet, low battery or rain coming.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { DemoState, ProbeId } from "../api/types";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { useI18n } from "../i18n/I18n";
import s from "./DemoPanel.module.css";

export default function DemoPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: ["demo"], queryFn: () => api.get<DemoState>("/api/v1/demo"), enabled: open });

  async function act(action: string, value?: unknown) {
    setBusy(true);
    try {
      const r = await api.post<DemoState>("/api/v1/demo", { action, value });
      qc.setQueryData(["demo"], r);
      await qc.invalidateQueries({ queryKey: ["status"] });
      void qc.invalidateQueries({ queryKey: ["readings"] });
    } finally {
      setBusy(false);
    }
  }

  const Toggle = ({ on, label, onChange }: { on: boolean; label: string; onChange: (v: boolean) => void }) => (
    <label className={s.toggle}>
      <span>{label}</span>
      <input type="checkbox" role="switch" checked={on} disabled={busy} onChange={(e) => onChange(e.target.checked)} />
      <i aria-hidden="true" />
    </label>
  );

  return (
    <>
      <Sheet open={open} title={t("demo_controls")} onClose={onClose}>
        <p className="hint" style={{ marginBottom: 12 }}>{t("demo_controls_lead")}</p>
        {data && (
          <div className={s.list}>
            {(["S1", "S2", "S3"] as ProbeId[]).map((p, i) => (
              <Toggle key={p} on={data.faults[p]} label={t("demo_fault", { plot: t("plot_n", { n: i + 1 }) })} onChange={(v) => act("fault", { probe: p, on: v })} />
            ))}
            <Toggle on={data.offline} label={t("demo_offline")} onChange={(v) => act("offline", v)} />
            {data.offline && data.buffered > 0 && <p className="hint">{t("demo_buffered", { n: data.buffered })}</p>}
            <Toggle on={data.power === "solar"} label={t("demo_solar")} onChange={(v) => act("power", v ? "solar" : "adapter")} />
            <Toggle on={data.force_rain} label={t("demo_rain")} onChange={(v) => act("rain", v)} />
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn btn-quiet" disabled={busy} onClick={() => act("dry")}><Icon name="sun" size={18} />{t("demo_dry")}</button>
              <button className="btn btn-quiet" disabled={busy} onClick={() => act("reset")}><Icon name="refresh" size={18} />{t("demo_reset")}</button>
            </div>
          </div>
        )}
      </Sheet>
    </>
  );
}
