// Small hand-drawn icon set (24 x 24, 2 px strokes). Icons are decorative
// (aria-hidden) unless a label is given; meaning is always carried by a word too.
import type { ReactElement, SVGProps } from "react";

export type IconName =
  | "drop" | "stop" | "leaf" | "sun" | "moon" | "cloud" | "rain" | "storm" | "haze" | "plug" | "solar" | "wifi" | "wifi-off"
  | "alert" | "check" | "clock" | "chart" | "list" | "gear" | "users" | "help" | "logout" | "menu" | "x" | "thermo"
  | "humidity" | "download" | "print" | "flask" | "sparkle" | "pause" | "home" | "forecast" | "bolt" | "chevron" | "key"
  | "refresh" | "info" | "minus";

const P: Record<IconName, ReactElement> = {
  drop: <path d="M12 3c4 5 6.5 8.6 6.5 11.5a6.5 6.5 0 0 1-13 0C5.5 11.6 8 8 12 3z" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  leaf: <><path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z" /><path d="M5 19l7-7" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
  cloud: <path d="M7 18h10a4 4 0 0 0 .6-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 18z" />,
  rain: <><path d="M7 15h10a4 4 0 0 0 .6-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 15z" /><path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3" /></>,
  storm: <><path d="M7 14h10a4 4 0 0 0 .6-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 14z" /><path d="M12 14l-2 4h3l-2 4" /></>,
  haze: <path d="M4 9h16M3 13h18M5 17h14" />,
  plug: <><path d="M9 3v5M15 3v5" /><path d="M6 8h12v3a6 6 0 0 1-12 0z" /><path d="M12 17v4" /></>,
  solar: <><path d="M4 18l2-10h12l2 10z" /><path d="M5 13h14M12 8v10M9 8l-1 10M15 8l1 10" /></>,
  wifi: <><path d="M2 9a15 15 0 0 1 20 0" /><path d="M5.5 12.5a10 10 0 0 1 13 0" /><path d="M9 16a5 5 0 0 1 6 0" /><circle cx="12" cy="19.5" r="1" /></>,
  "wifi-off": <><path d="M3 3l18 18" /><path d="M9 16a5 5 0 0 1 6 0M5.5 12.5a10 10 0 0 1 4-2.2M2 9a15 15 0 0 1 6.4-3.3M13.8 6A15 15 0 0 1 22 9M18.5 12.5a10 10 0 0 0-2.3-1.6" /><circle cx="12" cy="19.5" r="1" /></>,
  alert: <><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18v.5" /></>,
  check: <path d="M4 12.5l5 5 11-11" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  chart: <path d="M3 20h18M5 16l4-5 4 3 6-8" />,
  list: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.5M3.5 12h.5M3.5 18h.5" />,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></>,
  users: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7v.5M12 17.5v.5" /></>,
  logout: <><path d="M15 4h4v16h-4" /><path d="M10 8l-4 4 4 4M6 12h10" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  thermo: <><path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z" /></>,
  humidity: <><path d="M8 4c2.5 3.2 4 5.5 4 7.3a4 4 0 0 1-8 0C4 9.5 5.5 7.2 8 4z" /><path d="M16.5 10c1.8 2.3 3 4 3 5.3a3 3 0 0 1-6 0c0-1.3 1.2-3 3-5.3z" /></>,
  download: <><path d="M12 4v11M7 10l5 5 5-5" /><path d="M4 20h16" /></>,
  print: <><path d="M7 9V3h10v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><path d="M7 14h10v7H7z" /></>,
  flask: <><path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3" /><path d="M7 15h10" /></>,
  sparkle: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z" />,
  pause: <path d="M9 5v14M15 5v14" />,
  home: <><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /></>,
  forecast: <><path d="M8 13a4 4 0 1 1 7.5-2" /><path d="M10 20h8a3 3 0 0 0 .4-6 4.5 4.5 0 0 0-8.6 1A2.5 2.5 0 0 0 10 20z" /></>,
  bolt: <path d="M13 2L4 14h7l-1 8 9-12h-7z" />,
  chevron: <path d="M9 6l6 6-6 6" />,
  key: <><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M17 6l3 3M15 8l2 2" /></>,
  refresh: <><path d="M20 11a8 8 0 0 0-14.5-4.5L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16" /><path d="M20 20v-4h-4" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
  minus: <path d="M5 12h14" />,
};

interface Props extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
  label?: string;
}

export default function Icon({ name, size = 20, label, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      {...rest}
    >
      {P[name]}
    </svg>
  );
}
