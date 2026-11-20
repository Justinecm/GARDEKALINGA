// All dates shown in Asia/Manila, 12-hour clock (C-7).
export const TZ = "Asia/Manila";

function loc(lang: string) {
  return lang === "fil" ? "fil-PH" : "en-PH";
}

export function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtTime(iso: string | null | undefined, lang = "en"): string {
  const d = parse(iso);
  if (!d) return "—";
  return new Intl.DateTimeFormat(loc(lang), { hour: "numeric", minute: "2-digit", hour12: true, timeZone: TZ }).format(d);
}

export function fmtHour(iso: string | Date, lang = "en"): string {
  const d = typeof iso === "string" ? parse(iso) : iso;
  if (!d) return "—";
  return new Intl.DateTimeFormat(loc(lang), { hour: "numeric", hour12: true, timeZone: TZ }).format(d);
}

export function fmtDay(iso: string | Date | null | undefined, lang = "en"): string {
  const d = typeof iso === "string" || iso == null ? parse(iso as string) : iso;
  if (!d) return "—";
  return new Intl.DateTimeFormat(loc(lang), { weekday: "short", month: "short", day: "numeric", timeZone: TZ }).format(d);
}

export function fmtDateTime(iso: string | null | undefined, lang = "en"): string {
  const d = parse(iso);
  if (!d) return "—";
  return new Intl.DateTimeFormat(loc(lang), {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true, timeZone: TZ,
  }).format(d);
}

export function isToday(iso: string | null | undefined): boolean {
  const d = parse(iso);
  if (!d) return false;
  const f = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
  return f.format(d) === f.format(new Date());
}

/** "2:30 PM" today, otherwise "Nov 19, 2:30 PM". */
export function fmtSmart(iso: string | null | undefined, lang = "en"): string {
  return isToday(iso) ? fmtTime(iso, lang) : fmtDateTime(iso, lang);
}

export function manilaHour(d = new Date()): number {
  const h = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "numeric", hour12: false, timeZone: TZ }).formatToParts(d);
  const hh = Number(h.find((p) => p.type === "hour")?.value ?? 0) % 24;
  const mm = Number(h.find((p) => p.type === "minute")?.value ?? 0);
  return hh + mm / 60;
}

export function minutesBetween(a: string | null, b: Date = new Date()): number | null {
  const d = parse(a);
  return d ? Math.round((b.getTime() - d.getTime()) / 60000) : null;
}

export function fmtDuration(seconds: number | null | undefined, lang = "en"): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  const min = lang === "fil" ? "min" : "min";
  if (m === 0) return `${r} s`;
  if (r === 0) return `${m} ${min}`;
  return `${m} ${min} ${r} s`;
}

export function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86400000).toISOString();
}

/** yyyy-mm-dd in Manila for <input type=date>. */
export function manilaDateInput(d = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

/** Start of a Manila calendar day (yyyy-mm-dd) as an ISO UTC string. */
export function manilaDayStartIso(day: string): string {
  return new Date(day + "T00:00:00+08:00").toISOString();
}
