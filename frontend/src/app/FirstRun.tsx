// First sign-in: choose English or Filipino (FR-UI-13). Saved per user.
import { useState } from "react";
import Sheet from "../components/Sheet";
import { useI18n } from "../i18n/I18n";
import { useAuth } from "./Auth";

export default function FirstRun() {
  const { user, savePrefs } = useAuth();
  const { t, setLang } = useI18n();
  const [done, setDone] = useState(false);
  const open = !!user && !user.language && !done;
  const choose = (l: "en" | "fil") => {
    setLang(l);
    savePrefs({ language: l });
    setDone(true);
  };
  return (
    <Sheet open={open} title={t("choose_language")} onClose={() => choose("en")}>
      <div className="stack">
        <button className="btn btn-quiet btn-big" onClick={() => choose("fil")}>Filipino</button>
        <button className="btn btn-quiet btn-big" onClick={() => choose("en")}>English</button>
      </div>
    </Sheet>
  );
}
