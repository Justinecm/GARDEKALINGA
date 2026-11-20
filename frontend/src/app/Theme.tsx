import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ThemePref } from "../api/types";
import { isNight, skyPeriod, type SkyPeriod } from "../lib/sky";
import { manilaHour } from "../lib/time";

interface ThemeValue {
  pref: ThemePref;
  setPref: (p: ThemePref) => void;
  resolved: "light" | "dark";
  period: SkyPeriod;
  /** Preview another time of day in the scene (resets after 8 s). */
  previewPeriod: (p: SkyPeriod | null) => void;
  hour: number;
}

const Ctx = createContext<ThemeValue | null>(null);
const KEY = "gk.theme";
const PREVIEW_HOUR: Record<SkyPeriod, number> = { umaga: 7.5, tanghali: 12, hapon: 16.5, gabi: 21 };

function storedPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "auto" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(storedPref());
  const [hour, setHour] = useState(manilaHour());
  const [preview, setPreview] = useState<SkyPeriod | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setHour(manilaHour()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!preview) return;
    const id = window.setTimeout(() => setPreview(null), 8000);
    return () => window.clearTimeout(id);
  }, [preview]);

  const effectiveHour = preview ? PREVIEW_HOUR[preview] : hour;
  const resolved: "light" | "dark" = pref === "dark" || (pref === "auto" && isNight(effectiveHour)) ? "dark" : "light";

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
    const meta = document.querySelectorAll('meta[name="theme-color"]');
    meta.forEach((m) => m.setAttribute("content", resolved === "dark" ? "#0E1A1F" : "#EAF1EE"));
  }, [resolved]);

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(
    () => ({ pref, setPref, resolved, period: skyPeriod(effectiveHour), previewPeriod: setPreview, hour: effectiveHour }),
    [pref, setPref, resolved, effectiveHour],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("ThemeProvider missing");
  return v;
}
