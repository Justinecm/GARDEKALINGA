// Status always = colour + icon + word (never colour alone).
import type { Level } from "../api/types";
import { useI18n } from "../i18n/I18n";
import Icon, { type IconName } from "./Icon";

const ICON: Record<Level, IconName> = { good: "check", warning: "drop", serious: "alert", critical: "alert", none: "minus" };

export function levelColor(level: Level): string {
  return level === "none" ? "var(--ink-muted)" : `var(--${level})`;
}

export default function StatusBadge({ level, label, compact = false }: { level: Level; label?: string; compact?: boolean }) {
  const { t } = useI18n();
  const word = label ?? t(`lvl_${level}` as const);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 600, fontSize: compact ? "var(--fs-14)" : undefined }}>
      <span
        aria-hidden="true"
        style={{ display: "inline-grid", placeItems: "center", width: 20, height: 20, borderRadius: 999, background: levelColor(level), color: "#14201a", flex: "none" }}
      >
        <Icon name={ICON[level]} size={13} strokeWidth={2.6} />
      </span>
      <span>{word}</span>
    </span>
  );
}
