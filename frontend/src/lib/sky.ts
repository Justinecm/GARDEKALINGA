// "Langit": the sky follows Asia/Manila time of day and the current forecast.
import { manilaHour } from "./time";

export type SkyPeriod = "umaga" | "tanghali" | "hapon" | "gabi";
export type SkyWeather = "clear" | "clouds" | "rain" | "storm" | "haze";

export function skyPeriod(hour = manilaHour()): SkyPeriod {
  if (hour >= 5 && hour < 10) return "umaga";
  if (hour >= 10 && hour < 14) return "tanghali";
  if (hour >= 14 && hour < 18) return "hapon";
  return "gabi";
}

export function isNight(hour = manilaHour()): boolean {
  return skyPeriod(hour) === "gabi";
}

export function skyWeather(condition: string | null | undefined, pop?: number | null): SkyWeather {
  switch (condition) {
    case "Thunderstorm":
      return "storm";
    case "Rain":
    case "Drizzle":
      return "rain";
    case "Clouds":
      return (pop ?? 0) >= 60 ? "rain" : "clouds";
    case "Clear":
      return "clear";
    case null:
    case undefined:
      return "clear";
    default:
      return "haze";
  }
}

/** Sky gradient stops (top -> horizon). Cloudy and rainy skies are desaturated. */
export function skyStops(period: SkyPeriod, weather: SkyWeather): [string, string, string] {
  const base: Record<SkyPeriod, [string, string, string]> = {
    umaga: ["#8fc2e8", "#cfe5ef", "#fde3c4"],
    tanghali: ["#3f8fd6", "#8cc4ee", "#d8eef7"],
    hapon: ["#5f86c4", "#f0b27a", "#fbd38d"],
    gabi: ["#071521", "#12304a", "#2a4a63"],
  };
  const grey: Record<SkyPeriod, [string, string, string]> = {
    umaga: ["#8ea3b3", "#b9c7cf", "#d8dcd6"],
    tanghali: ["#7b93a8", "#a9bac6", "#d0d9dd"],
    hapon: ["#6f7f99", "#b19c8c", "#cdbba4"],
    gabi: ["#0a141c", "#17283a", "#25384a"],
  };
  if (weather === "rain" || weather === "storm") return grey[period];
  if (weather === "clouds" || weather === "haze") {
    const a = base[period];
    const b = grey[period];
    return [mix(a[0], b[0], 0.45), mix(a[1], b[1], 0.45), mix(a[2], b[2], 0.35)];
  }
  return base[period];
}

/** Position of the sun or moon along an arc, 0..1 across the scene. */
export function celestialPosition(hour = manilaHour()): { x: number; y: number; isSun: boolean } {
  const isSun = hour >= 5.5 && hour < 18.5;
  const t = isSun ? (hour - 5.5) / 13 : ((hour + 24 - 18.5) % 24) / 11;
  const x = 0.08 + t * 0.6;
  const y = 0.62 - Math.sin(Math.min(1, Math.max(0, t)) * Math.PI) * 0.5;
  return { x, y, isSun };
}

export function mix(a: string, b: string, t: number): string {
  const pa = hex(a);
  const pb = hex(b);
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
}

function hex(h: string): [number, number, number] {
  const s = h.replace("#", "");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}

/** Soil ramp: pale dry brown (10% VWC) to dark wet brown (45% VWC). */
export function soilColor(vwc: number | null): string {
  if (vwc == null) return "#9a9a94";
  const t = Math.min(1, Math.max(0, (vwc - 10) / 35));
  const stops = ["#e2c9a0", "#bd9467", "#8a5f3d", "#5a3a24", "#3c2516"];
  const pos = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  return mix(stops[i], stops[i + 1], pos - i);
}
