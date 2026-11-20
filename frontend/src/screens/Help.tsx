// Help: what the colours and words mean, what to do when the controller is offline,
// solar vs wall-socket numbers, in English and Filipino (C-7 screen 10).
import StatusBadge from "../components/StatusBadge";
import Icon from "../components/Icon";
import { useI18n } from "../i18n/I18n";

export default function Help() {
  const { t } = useI18n();
  const sections = [
    { icon: "drop" as const, title: t("help_water_title"), body: t("help_water_body") },
    { icon: "wifi-off" as const, title: t("help_offline_title"), body: t("help_offline_body") },
    { icon: "solar" as const, title: t("help_power_title"), body: t("help_power_body") },
    { icon: "alert" as const, title: t("help_fault_title"), body: t("help_fault_body") },
  ];
  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <div className="page-head"><h1>{t("help_title")}</h1></div>
      <section className="panel stack" aria-labelledby="colors-h">
        <h2 id="colors-h" style={{ fontSize: "var(--fs-20)" }}>{t("help_colors")}</h2>
        <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          <li><StatusBadge level="good" /></li>
          <li><StatusBadge level="warning" /></li>
          <li><StatusBadge level="serious" /></li>
          <li><StatusBadge level="critical" /> <span className="muted small">/ {t("controller_offline")}</span></li>
        </ul>
        <p className="hint">{t("help_drum")}</p>
      </section>
      {sections.map((x) => (
        <section key={x.title} className="stack" style={{ gap: 8 }}>
          <h2 style={{ fontSize: "var(--fs-20)", display: "flex", gap: 10, alignItems: "center" }}><Icon name={x.icon} />{x.title}</h2>
          <p>{x.body}</p>
        </section>
      ))}
    </div>
  );
}
