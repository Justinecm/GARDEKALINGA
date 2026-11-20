import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, qs } from "./client";
import type { Forecast, ModelCard, Readings, SettingsResponse, Status } from "./types";

const LAST_STATUS = "gk.lastStatus";

export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(typeof document === "undefined" ? true : document.visibilityState === "visible");
  useEffect(() => {
    const on = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return visible;
}

function readCachedStatus(): Status | undefined {
  try {
    const raw = localStorage.getItem(LAST_STATUS);
    return raw ? (JSON.parse(raw) as Status) : undefined;
  } catch {
    return undefined;
  }
}

/** /status every 5 s while the tab is visible; paused when hidden (NFR-PERF-01/02). */
export function useStatus(fast = false) {
  const visible = usePageVisible();
  const q = useQuery({
    queryKey: ["status"],
    queryFn: async () => {
      const s = await api.get<Status>("/api/v1/status");
      try {
        localStorage.setItem(LAST_STATUS, JSON.stringify(s));
      } catch {
        /* storage full or blocked */
      }
      return s;
    },
    refetchInterval: visible ? (fast ? 1500 : 5000) : false,
    refetchIntervalInBackground: false,
    placeholderData: (prev) => prev ?? readCachedStatus(),
    retry: 1,
  });
  return q;
}

export function useReadings(from: string, to?: string, bucket = "auto") {
  return useQuery({
    queryKey: ["readings", from, to, bucket],
    queryFn: () => api.get<Readings>("/api/v1/readings" + qs({ from, to, bucket })),
    staleTime: 60_000,
  });
}

export function useForecast() {
  return useQuery({ queryKey: ["forecast"], queryFn: () => api.get<Forecast>("/api/v1/forecast?hours=24"), staleTime: 5 * 60_000 });
}

export function useModel() {
  return useQuery({ queryKey: ["model"], queryFn: () => api.get<ModelCard>("/api/v1/model"), staleTime: 60_000 });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<SettingsResponse>("/api/v1/settings") });
}

export function useList<T>(key: string, path: string, enabled = true) {
  return useQuery({ queryKey: [key, path], queryFn: () => api.get<{ items: T[] }>(path), enabled, staleTime: 30_000 });
}
