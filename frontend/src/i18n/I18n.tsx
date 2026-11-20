import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Lang } from "../api/types";
import { en, fil, type StringKey } from "./strings";

type Vars = Record<string, string | number | null | undefined>;
interface I18nValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: StringKey, vars?: Vars) => string;
  hasChosen: boolean;
}

const Ctx = createContext<I18nValue | null>(null);
const KEY = "gk.lang";

function stored(): Lang | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "en" || v === "fil" ? v : null;
  } catch {
    return null;
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(stored() ?? "en");
  const [hasChosen, setChosen] = useState(stored() !== null);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    setChosen(true);
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("lang", lang === "fil" ? "fil" : "en");
  }, [lang]);

  const t = useCallback(
    (key: StringKey, vars?: Vars) => {
      const table = lang === "fil" ? fil : en;
      let s: string = table[key] ?? en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.split("{" + k + "}").join(v == null ? "—" : String(v));
      return s;
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t, hasChosen }), [lang, setLang, t, hasChosen]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("I18nProvider missing");
  return v;
}
