import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, setCsrf, setReauthHandler, setUnauthorizedHandler } from "../api/client";
import type { Me, Role, User } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { useTheme } from "./Theme";
import ReauthDialog from "../components/ReauthDialog";

interface AuthValue {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (cap: Capability) => boolean;
  savePrefs: (p: Partial<Pick<User, "language" | "theme">>) => void;
}

export type Capability = "water" | "export" | "settings" | "users" | "audit" | "retrain" | "testbench_write" | "reports";

const MATRIX: Record<Capability, Role[]> = {
  water: ["caretaker", "manager"],
  export: ["manager", "leader"],
  reports: ["manager", "leader"],
  settings: ["manager"],
  users: ["manager"],
  retrain: ["manager"],
  testbench_write: ["manager"],
  audit: ["manager", "leader"],
};

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { setLang } = useI18n();
  const { setPref } = useTheme();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [reauthOpen, setReauthOpen] = useState(false);
  const reauthResolve = useRef<((ok: boolean) => void) | null>(null);

  const applyUser = useCallback(
    (u: User | null) => {
      if (u?.language) setLang(u.language);
      if (u?.theme) setPref(u.theme);
    },
    [setLang, setPref],
  );

  useEffect(() => {
    api
      .get<Me>("/api/v1/auth/me")
      .then((m) => {
        setCsrf(m.csrf);
        setMe(m);
        applyUser(m.user);
      })
      .catch(() => setMe({ user: null, csrf: null }))
      .finally(() => setLoading(false));
  }, [applyUser]);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe((m) => (m ? { ...m, user: null } : m)));
    setReauthHandler(
      () =>
        new Promise<boolean>((resolve) => {
          reauthResolve.current = resolve;
          setReauthOpen(true);
        }),
    );
    return () => {
      setUnauthorizedHandler(null);
      setReauthHandler(null);
    };
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const r = await api.post<{ user: User; csrf: string }>("/api/v1/auth/login", { username, password });
      setCsrf(r.csrf);
      qc.clear();
      setMe({ user: r.user, csrf: r.csrf });
      applyUser(r.user);
    },
    [qc, applyUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/v1/auth/logout");
    } finally {
      setCsrf(null);
      qc.clear();
      try {
        localStorage.removeItem("gk.lastStatus");
      } catch {
        /* ignore */
      }
      const m = await api.get<Me>("/api/v1/auth/me").catch(() => null);
      setCsrf(m?.csrf ?? null);
      setMe(m ?? { user: null, csrf: null });
    }
  }, [qc]);

  const savePrefs = useCallback((p: Partial<Pick<User, "language" | "theme">>) => {
    api.patch("/api/v1/auth/preferences", p).catch(() => undefined);
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      user: me?.user ?? null,
      loading,
      login,
      logout,
      savePrefs,
      can: (cap) => !!me?.user && MATRIX[cap].includes(me.user.role),
    }),
    [me, loading, login, logout, savePrefs],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <ReauthDialog
        open={reauthOpen}
        onDone={(ok) => {
          setReauthOpen(false);
          reauthResolve.current?.(ok);
          reauthResolve.current = null;
        }}
      />
    </Ctx.Provider>
  );
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("AuthProvider missing");
  return v;
}
