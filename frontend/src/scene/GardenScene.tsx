// The live garden scene (BUILD_PROMPT C-7): hand-built SVG driven by /status.
// Three plots (soil colour from each probe's VWC, plants droop below the plot
// minimum, hatched grey when the sensor has a problem), the blue water drum with
// pump and valve, six sprinklers that spray while the pump runs, the Gawad
// Kalinga house wall with Box A and Box B, a PV panel that glows on solar and a
// wall plug that lights on the wall socket. The sky ("Langit") follows Asia/Manila
// time and the forecast. The SVG is role="img" with a live sentence; the plot
// buttons are real HTML buttons laid over it so they work with keyboard and
// screen readers.
import { memo, useMemo } from "react";
import type { Probe, Status } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { celestialPosition, skyStops, skyWeather, soilColor, type SkyPeriod, type SkyWeather } from "../lib/sky";
import s from "./GardenScene.module.css";

const W = 400;
const H = 250;
const GROUND = 196;
const PLOTS = [
  { x: 12, w: 64 },
  { x: 84, w: 64 },
  { x: 156, w: 64 },
];
const BED_TOP = 178;
const BED_H = 30;

type PlotState = { probe: Probe | null; vwc: number | null; state: "up" | "dry" | "droop" | "fault" | "none" };

interface Props {
  status: Status | undefined;
  period: SkyPeriod;
  hour: number;
  onPlot?: (index: number) => void;
  /** Decorative copy (sign-in page): no buttons, hidden from screen readers. */
  decorative?: boolean;
}

function plotStates(status: Status | undefined): PlotState[] {
  const probes = status?.reading?.probes ?? [];
  const pmin = status?.settings.probe_min_vwc ?? 22;
  const thr = status?.settings.moisture_threshold ?? 30;
  return [0, 1, 2].map((i) => {
    const p = probes[i] ?? null;
    if (!p || !p.installed) return { probe: p, vwc: null, state: "none" };
    if (p.fault || p.vwc == null) return { probe: p, vwc: null, state: "fault" };
    return { probe: p, vwc: p.vwc, state: p.vwc < pmin ? "droop" : p.vwc < thr ? "dry" : "up" };
  });
}

function GardenScene({ status, period, hour, onPlot, decorative = false }: Props) {
  const { t } = useI18n();
  const weather: SkyWeather = skyWeather(status?.weather_now?.condition, status?.weather_now?.pop_pct);
  const [top, mid, horizon] = skyStops(period, weather);
  const night = period === "gabi";
  const plots = useMemo(() => plotStates(status), [status]);
  const spraying = !!status?.watering.pump;
  const valveOpen = !!status?.watering.valve;
  const solar = status?.power.source === "solar";
  const adapter = status?.power.source === "adapter";
  const online = !!status?.device?.online;
  const cel = celestialPosition(hour);

  const word = (p: PlotState) =>
    p.state === "fault" ? t("sensor_problem") : p.state === "none" ? t("not_installed") : `${Math.round(p.vwc ?? 0)}%`;
  const statusWord = status ? t(`st_${status.status.code}` as const) : "";
  const label = t("scene_label", {
    status: spraying ? t("watering_marks") + "." : statusWord,
    p1: word(plots[0]),
    p2: word(plots[1]),
    p3: word(plots[2]),
    pump: spraying ? t("on") : t("off"),
    power: solar ? t("power_solar") : adapter ? t("power_adapter") : t("power_unknown"),
  });

  return (
    <div className={`${s.wrap} ${night ? s.night : ""}`} data-period={period} data-weather={weather} aria-hidden={decorative || undefined}>
      <svg viewBox={`0 0 ${W} ${H}`} className={s.svg} role={decorative ? undefined : "img"} aria-label={decorative ? undefined : label} preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="gk-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={top} />
            <stop offset="0.55" stopColor={mid} />
            <stop offset="1" stopColor={horizon} />
          </linearGradient>
          <radialGradient id="gk-sun" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#fff6c8" />
            <stop offset="0.45" stopColor="#f2b705" />
            <stop offset="1" stopColor="#f2b705" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="gk-glow" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#ffe27a" stopOpacity="0.95" />
            <stop offset="1" stopColor="#ffe27a" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="gk-plug" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#9fd0ff" stopOpacity="0.95" />
            <stop offset="1" stopColor="#9fd0ff" stopOpacity="0" />
          </radialGradient>
          <pattern id="gk-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#a7aaa6" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#6e726e" strokeWidth="2.2" />
          </pattern>
          <linearGradient id="gk-drum" x1="0" x2="1">
            <stop offset="0" stopColor="#174b86" />
            <stop offset="0.45" stopColor="#2a74c4" />
            <stop offset="1" stopColor="#163f70" />
          </linearGradient>
          <clipPath id="gk-clip">
            <rect width={W} height={H} rx="0" />
          </clipPath>
        </defs>

        <g clipPath="url(#gk-clip)">
          {/* ---------------- sky ---------------- */}
          <rect width={W} height={H} fill="url(#gk-sky)" className={s.sky} />
          {night && <Stars />}
          {cel.isSun ? (
            <g className={s.sun} transform={`translate(${cel.x * W} ${cel.y * 170 + 14})`} opacity={weather === "rain" || weather === "storm" ? 0.35 : 1}>
              <circle r="30" fill="url(#gk-sun)" />
              <circle r="12" fill="#ffd84a" />
            </g>
          ) : (
            <g transform={`translate(${cel.x * W} ${cel.y * 170 + 14})`}>
              <circle r="16" fill="#f4f1de" opacity="0.15" />
              <circle r="10" fill="#efe9cf" />
              <circle r="9" cx="4" cy="-3" fill={top} />
            </g>
          )}
          <Clouds weather={weather} night={night} />

          {/* distant Tondo rooftops */}
          <path
            d="M0 150 L18 150 L18 140 L34 132 L50 140 L50 150 L62 150 L62 136 L88 136 L88 150 L100 150 L112 128 L124 150 L140 150 L140 138 L170 138 L170 150 L186 150 L186 132 L196 126 L206 132 L206 150 L222 150 L222 142 L240 142 L240 150 L400 150 L400 200 L0 200 Z"
            className={s.skyline}
          />

          {/* ---------------- ground ---------------- */}
          <rect x="0" y={GROUND - 22} width={W} height={H - GROUND + 22} className={s.grass} />
          <path d={`M0 ${GROUND + 26} Q200 ${GROUND + 12} 400 ${GROUND + 28} L400 ${H} L0 ${H} Z`} className={s.path} />

          {/* ---------------- GK house ---------------- */}
          <House solar={solar} adapter={adapter} online={online} night={night} valve={valveOpen} />

          {/* ---------------- drum, pump, valve, tube ---------------- */}
          <Drum pump={spraying} valve={valveOpen} />
          <path d={`M232 ${GROUND + 4} L222 ${GROUND + 4} L222 ${BED_TOP - 9} L8 ${BED_TOP - 9}`} className={s.tube} />
          {valveOpen && <path d={`M232 ${GROUND + 4} L222 ${GROUND + 4} L222 ${BED_TOP - 9} L8 ${BED_TOP - 9}`} className={`${s.flow} ${spraying ? s.flowOn : ""}`} />}

          {/* ---------------- plots ---------------- */}
          {PLOTS.map((p, i) => (
            <Plot key={i} index={i} x={p.x} w={p.w} plot={plots[i]} spraying={spraying} label={word(plots[i])} problem="Sensor" />
          ))}

          {/* rain falls in front of everything */}
          {(weather === "rain" || weather === "storm") && <Rain storm={weather === "storm"} />}
          {weather === "haze" && <rect width={W} height={H} fill="#e9ecef" opacity={night ? 0.08 : 0.22} />}
          {night && <rect width={W} height={H} fill="#06121c" opacity="0.28" pointerEvents="none" />}
          {night && <Windows />}
        </g>
      </svg>

      {/* Real buttons over the plots (keyboard + screen reader). */}
      {!decorative && PLOTS.map((p, i) => (
        <button
          key={i}
          type="button"
          className={s.plotButton}
          style={{
            left: `${(p.x / W) * 100}%`,
            top: `${((BED_TOP - 42) / H) * 100}%`,
            width: `${(p.w / W) * 100}%`,
            height: `${((BED_H + 46) / H) * 100}%`,
          }}
          onClick={() => onPlot?.(i)}
          aria-label={`${t("plot_n", { n: i + 1 })}: ${word(plots[i])}. ${t("details")}`}
        />
      ))}
    </div>
  );
}

export default memo(GardenScene);

/* ====================================================================== parts */

function Stars() {
  const pts = [
    [24, 22], [62, 48], [98, 16], [140, 36], [176, 12], [214, 44], [252, 20], [300, 34], [338, 14], [372, 46], [120, 64], [44, 80], [282, 70],
  ];
  return (
    <g className={s.stars}>
      {pts.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.4 : 0.9} fill="#f5f3e6" style={{ animationDelay: `${(i % 5) * 0.7}s` }} />
      ))}
    </g>
  );
}

function Cloud({ x, y, scale, fill, className }: { x: number; y: number; scale: number; fill: string; className?: string }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} className={className}>
      <path d="M0 20 C-2 10 8 4 16 8 C20 -2 36 -2 40 8 C50 4 60 10 58 20 Z" fill={fill} />
    </g>
  );
}

function Clouds({ weather, night }: { weather: SkyWeather; night: boolean }) {
  const light = night ? "#3a5064" : "#ffffff";
  const grey = night ? "#2a3a4a" : "#c9d2d8";
  const dark = night ? "#1f2c38" : "#9aa7b1";
  if (weather === "clear") {
    return (
      <g opacity={night ? 0.5 : 0.9}>
        <Cloud x={250} y={34} scale={0.7} fill={light} className={s.drift} />
      </g>
    );
  }
  const heavy = weather === "rain" || weather === "storm";
  return (
    <g>
      <Cloud x={20} y={20} scale={1.1} fill={heavy ? dark : light} className={s.drift} />
      <Cloud x={150} y={8} scale={1.4} fill={heavy ? dark : grey} className={s.driftSlow} />
      <Cloud x={280} y={30} scale={1.0} fill={heavy ? grey : light} className={s.drift} />
      {heavy && <Cloud x={80} y={44} scale={1.2} fill={grey} className={s.driftSlow} />}
    </g>
  );
}

function Rain({ storm }: { storm: boolean }) {
  const drops = [];
  for (let i = 0; i < 46; i++) {
    const x = (i * 37) % 400;
    const y = (i * 53) % 160;
    drops.push(<line key={i} x1={x} y1={y} x2={x - 3} y2={y + 9} style={{ animationDelay: `${(i % 7) * 0.13}s` }} />);
  }
  return (
    <g className={s.rain} aria-hidden="true">
      {drops}
      {storm && <rect width="400" height="250" className={s.flash} />}
    </g>
  );
}

function House({ solar, adapter, online, night, valve }: { solar: boolean; adapter: boolean; online: boolean; night: boolean; valve: boolean }) {
  return (
    <g>
      {/* roof with PV panel */}
      <path d="M262 98 L332 66 L400 92 L400 104 L262 104 Z" fill="#6f7f8a" />
      <path d="M268 100 L332 70 L396 95" stroke="#8796a0" strokeWidth="2" fill="none" />
      <g className={solar ? s.pvOn : s.pv}>
        <path d="M300 84 L338 67 L370 80 L332 97 Z" fill="#1b2f52" stroke={solar ? "#f2b705" : "#3b4f72"} strokeWidth="1.5" />
        <path d="M309 80 L341 94 M319 76 L351 90 M329 71 L361 85 M316 90.5 L348 74 M324 93 L356 77" stroke="#4d6a99" strokeWidth="0.8" />
        {solar && <ellipse cx="335" cy="82" rx="40" ry="20" fill="url(#gk-glow)" className={s.glowPulse} />}
      </g>
      {/* wall in Gawad Kalinga yellow, green trim */}
      <rect x="266" y="104" width="134" height={GROUND - 104} fill="#f5c842" />
      <rect x="266" y="104" width="134" height="6" fill="#2e7d32" />
      <rect x="266" y={GROUND - 8} width="134" height="8" fill="#2e7d32" />
      {/* door and window */}
      <rect x="356" y="128" width="28" height={GROUND - 136} rx="2" fill="#1f5fa6" />
      <circle cx="378" cy="160" r="1.8" fill="#f5c842" />
      <rect x="300" y="118" width="40" height="26" rx="2" fill={night ? "#ffd982" : "#cfe6f7"} stroke="#2e7d32" strokeWidth="3" />
      <path d="M320 118 V144 M300 131 H340" stroke="#2e7d32" strokeWidth="2" />
      {/* Box A (solar box) and Box B (controller) */}
      <g>
        <rect x="276" y="150" width="20" height="24" rx="2" fill="#d9dcd8" stroke="#8b918c" />
        <text x="286" y="166" textAnchor="middle" className={s.boxText}>A</text>
        <rect x="302" y="152" width="26" height="22" rx="2" fill="#eceee9" stroke="#8b918c" />
        <text x="312" y="167" textAnchor="middle" className={s.boxText}>B</text>
        <circle cx="323" cy="157" r="2.4" fill={online ? "#0ca30c" : "#d03b3b"} className={online ? s.ledOn : ""} />
        {/* field cables from Box B down to the drum */}
        <path d="M315 174 L315 186 L262 186" stroke="#4a4f4b" strokeWidth="1.4" fill="none" />
      </g>
      {/* wall plug */}
      <g>
        {adapter && <circle cx="344" cy="172" r="12" fill="url(#gk-plug)" className={s.glowPulse} />}
        <rect x="337" y="165" width="14" height="14" rx="2" fill="#f4f4ef" stroke={adapter ? "#1f5fa6" : "#8b918c"} strokeWidth={adapter ? 1.6 : 1} />
        <rect x="341" y="169" width="1.8" height="5" fill="#3a3f3c" />
        <rect x="345.5" y="169" width="1.8" height="5" fill="#3a3f3c" />
        <path d="M344 179 Q340 186 330 186 L315 186" stroke={adapter ? "#1f5fa6" : "#4a4f4b"} strokeWidth="1.4" fill="none" />
      </g>
      {valve && <title>valve</title>}
    </g>
  );
}

function Windows() {
  return <rect x="300" y="118" width="40" height="26" rx="2" fill="#ffd982" opacity="0.55" />;
}

function Drum({ pump, valve }: { pump: boolean; valve: boolean }) {
  return (
    <g>
      {/* stand */}
      <path d="M232 170 L228 196 M260 170 L264 196 M230 182 H262" stroke="#5c4a3a" strokeWidth="3" strokeLinecap="round" />
      {/* drum */}
      <rect x="230" y="122" width="32" height="48" rx="5" fill="url(#gk-drum)" />
      <ellipse cx="246" cy="123" rx="16" ry="4" fill="#3b85d4" />
      <path d="M230 136 H262 M230 156 H262" stroke="#123a66" strokeWidth="2" />
      {/* pump (K2) and valve (K1) */}
      <rect x="236" y="188" width="18" height="14" rx="2" fill={pump ? "#2e7d32" : "#46514b"} />
      <path d="M240 195 h10" stroke="#e7efea" strokeWidth="1.5" />
      {pump && <circle cx="250" cy="191" r="1.6" fill="#b6f5b9" className={s.ledOn} />}
      <path d="M232 199 l-6 -4 v8 z M226 199 l-6 -4 v8 z" fill={valve ? "#1f5fa6" : "#6b7570"} transform="translate(8 0)" />
    </g>
  );
}

function Plant({ x, base, state, delay }: { x: number; base: number; state: PlotState["state"]; delay: number }) {
  const droop = state === "droop";
  const dry = state === "dry";
  const fault = state === "fault" || state === "none";
  const leaf = fault ? "#8c918d" : droop ? "#9a9a3e" : dry ? "#5f9a3b" : "var(--scene-leaf)";
  const stemTop = base - (droop ? 13 : 18);
  const angL = droop ? 58 : dry ? 12 : -18;
  const angR = droop ? -58 : dry ? -12 : 18;
  const tipX = droop ? x + 4 : x;
  return (
    <g className={s.plant} style={{ transitionDelay: `${delay}ms` }}>
      <path d={`M${x} ${base} Q${x + (droop ? 1 : 0)} ${base - 8} ${tipX} ${stemTop}`} stroke={leaf} strokeWidth="1.8" fill="none" strokeLinecap="round" />
      <path
        d={`M${x} ${base - 7} q-9 -5 -12 -1 q5 5 12 1z`}
        fill={leaf}
        className={s.leaf}
        style={{ transformOrigin: `${x}px ${base - 7}px`, transform: `rotate(${angL}deg)` }}
      />
      <path
        d={`M${x} ${base - 10} q9 -5 12 -1 q-5 5 -12 1z`}
        fill={leaf}
        className={s.leaf}
        style={{ transformOrigin: `${x}px ${base - 10}px`, transform: `rotate(${angR}deg)` }}
      />
      <path
        d={`M${tipX} ${stemTop} q-5 -8 0 -11 q5 3 0 11z`}
        fill={leaf}
        className={s.leaf}
        style={{ transformOrigin: `${tipX}px ${stemTop}px`, transform: `rotate(${droop ? 70 : 0}deg)` }}
      />
    </g>
  );
}

function Sprinkler({ x, y, on }: { x: number; y: number; on: boolean }) {
  return (
    <g>
      <line x1={x} y1={BED_TOP - 9} x2={x} y2={y} stroke="#5a6660" strokeWidth="1.6" />
      <circle cx={x} cy={y} r="2.2" fill="#3e4a44" />
      {on && (
        <g className={s.spray}>
          <path d={`M${x} ${y} Q${x - 10} ${y - 16} ${x - 20} ${y + 8}`} />
          <path d={`M${x} ${y} Q${x + 10} ${y - 16} ${x + 20} ${y + 8}`} />
          <path d={`M${x} ${y} Q${x - 4} ${y - 20} ${x - 10} ${y + 10}`} />
          <path d={`M${x} ${y} Q${x + 4} ${y - 20} ${x + 10} ${y + 10}`} />
          {[-16, -8, 0, 8, 16].map((dx, i) => (
            <circle key={i} cx={x + dx} cy={y + 4 + Math.abs(dx) / 3} r="1.3" className={s.droplet} style={{ animationDelay: `${i * 0.12}s` }} />
          ))}
        </g>
      )}
    </g>
  );
}

function Plot({ index, x, w, plot, spraying, label, problem }: { index: number; x: number; w: number; plot: PlotState; spraying: boolean; label: string; problem: string }) {
  const fault = plot.state === "fault" || plot.state === "none";
  const fill = fault ? "url(#gk-hatch)" : soilColor(plot.vwc);
  const tagW = fault ? 56 : 36;
  const tagX = x + w / 2 - tagW / 2;
  const sprinklers = [x + w * 0.27, x + w * 0.73];
  return (
    <g>
      {/* back frame */}
      <path d={`M${x + 4} ${BED_TOP} L${x + w - 4} ${BED_TOP} L${x + w} ${BED_TOP + 8} L${x} ${BED_TOP + 8} Z`} fill="#7a5532" />
      {/* soil surface */}
      <path
        d={`M${x + 5} ${BED_TOP + 1} L${x + w - 5} ${BED_TOP + 1} L${x + w - 1} ${BED_TOP + 8} L${x + 1} ${BED_TOP + 8} Z`}
        className={s.soil}
        style={{ fill }}
      />
      {/* plants */}
      {[0.2, 0.5, 0.8].map((f, i) => (
        <Plant key={i} x={x + w * f} base={BED_TOP + 6} state={plot.state} delay={index * 120 + i * 60} />
      ))}
      {/* front of the raised bed */}
      <rect x={x} y={BED_TOP + 8} width={w} height={BED_H - 8} rx="2" fill="#8a6038" />
      <rect x={x} y={BED_TOP + 8} width={w} height={BED_H - 8} rx="2" style={{ fill }} className={s.soilFront} />
      <path d={`M${x} ${BED_TOP + 15} H${x + w} M${x} ${BED_TOP + 22} H${x + w}`} stroke="#6b4626" strokeWidth="1" opacity="0.5" />
      {sprinklers.map((sx, i) => (
        <Sprinkler key={i} x={sx} y={BED_TOP - 14} on={spraying} />
      ))}
      {/* reading tag */}
      <g transform={`translate(${tagX} ${BED_TOP - 40})`}>
        <rect width={tagW} height="16" rx="4" className={fault ? s.tagFault : s.tag} />
        {fault && <path d="M8 12.5 L12.5 4 L17 12.5 Z" fill="#d03b3b" stroke="#fff" strokeWidth="0.8" />}
        <text x={fault ? tagW / 2 + 6 : tagW / 2} y="11.5" textAnchor="middle" className={s.tagText}>
          {fault ? problem : label}
        </text>
      </g>
      <text x={x + w / 2} y={BED_TOP + 24} textAnchor="middle" className={s.plotNo}>
        {index + 1}
      </text>
    </g>
  );
}
