import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useStatus } from "../api/hooks";
import Icon, { type IconName } from "../components/Icon";
import Segmented from "../components/Segmented";
import Sheet from "../components/Sheet";
import { useI18n } from "../i18n/I18n";
import type { StringKey } from "../i18n/strings";
import { skyStops, type SkyPeriod } from "../lib/sky";
import { fmtSmart } from "../lib/time";
import { useAuth } from "./Auth";
import s from "./Layout.module.css";
import { useTheme } from "./Theme";
import DemoPanel from "../screens/DemoPanel";

interface NavItem { to: string; label: StringKey; icon: IconName }

export function navItems(role: string | undefined): { bottom: NavItem[]; all: NavItem[] } {
  const garden: NavItem = { to: "/", label: "nav_garden", icon: "home" };
  const history: NavItem = { to: "/history", label: "nav_history", icon: "chart" };
  const forecast: NavItem = { to: "/forecast", label: "nav_forecast", icon: "forecast" };
  const logs: NavItem = { to: "/records", label: "nav_logs", icon: "list" };
  const settings: NavItem = { to: "/settings", label: "nav_settings", icon: "gear" };
  const users: NavItem = { to: "/users", label: "nav_users", icon: "users" };
  const reports: NavItem = { to: "/reports", label: "nav_reports", icon: "download" };
  const help: NavItem = { to: "/help", label: "nav_help", icon: "help" };
  if (role === "manager") return { bottom: [garden, history, forecast, logs, settings], all: [garden, history, forecast, logs, settings, users, reports, help] };
  if (role === "leader") return { bottom: [garden, history, forecast, logs, reports], all: [garden, history, forecast, logs, reports, help] };
  return { bottom: [garden, history, forecast, logs, help], all: [garden, history, forecast, logs, help] };
}

function Logo() {
  return (
    <svg className={s.brandMark} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="var(--drum)" />
      <path d="M32 10c9 12 15 20 15 28a15 15 0 0 1-30 0c0-8 6-16 15-28z" fill="var(--page)" />
      <path d="M32 52V34m0 6c-4-1-7-4-8-8 4 0 7 2 8 6zm0-3c3-1 6-4 7-8-4 0-6 3-7 6z" stroke="var(--leaf)" strokeWidth="3" fill="var(--leaf)" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Layout() {
  const { t, lang, setLang } = useI18n();
  const { user, logout, demo, savePrefs } = useAuth();
  const theme = useTheme();
  const { data, error, isError } = useStatus();
  const [menuOpen, setMenuOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const loc = useLocation();
  const nav = navItems(user?.role);
  const online = data?.device?.online;
  const networkDown = isError && error instanceof ApiError && error.code === "network";

  return (
    <div className={s.shell}>
      <a href="#main" className="visually-hidden">Skip to content</a>
      <header className={s.top}>
        <NavLink to="/" className={s.brand} aria-label={t("app_name") + ", " + t("nav_garden")}>
          <Logo />
          <span>{t("app_name")}</span>
        </NavLink>
        {demo && (
          <button type="button" className={s.demo} onClick={() => setDemoOpen(true)} aria-haspopup="dialog" aria-label={t("demo_controls")}>
            <Icon name="flask" size={15} />
            {t("demo_badge")}
          </button>
        )}
        <span className={s.spacer} />
        {data?.device && (
          <span className={s.node} title={t("last_seen", { time: fmtSmart(data.device.last_seen_at, lang) })}>
            <span className={`${s.nodeDot} ${online ? s.nodeOn : s.nodeOff}`} aria-hidden="true" />
            {online ? t("online") : t("offline")}
          </span>
        )}
        <button type="button" className={`btn btn-link ${s.menuBtn}`} onClick={() => setMenuOpen(true)} aria-label={t("menu")} aria-haspopup="dialog">
          <Icon name="menu" size={24} />
        </button>
      </header>

      <nav className={s.rail} aria-label={t("nav_main")}>
        {nav.all.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} className={s.railLink}>
            <Icon name={n.icon} />
            {t(n.label)}
          </NavLink>
        ))}
        <div className={s.railFoot}>
          <span>{t("garden_name")}</span>
          <span>{t("garden_place")}</span>
        </div>
      </nav>

      <div className={s.main}>
        {networkDown && data && (
          <div className={`${s.banner} ${s.bannerCache}`} role="status">
            <Icon name="wifi-off" />
            {t("showing_cached", { time: fmtSmart(data.server_time, lang) })}
          </div>
        )}
        {!networkDown && data?.device && !data.device.online && loc.pathname !== "/" && (
          <div className={`${s.banner} ${s.bannerOffline}`} role="status">
            <Icon name="wifi-off" />
            <span>
              {t("offline_since", { time: fmtSmart(data.device.last_seen_at, lang) })} {t("offline_help")}
            </span>
          </div>
        )}
        <main id="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>

      <nav className={s.bottom} aria-label={t("nav_main")}>
        {nav.bottom.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} className={s.navLink}>
            <Icon name={n.icon} size={22} />
            <span>{t(n.label)}</span>
          </NavLink>
        ))}
      </nav>

      {demo && <DemoPanel open={demoOpen} onClose={() => setDemoOpen(false)} />}

      <Sheet open={menuOpen} title={t("menu")} onClose={() => setMenuOpen(false)}>
        <div className={s.menu}>
          {user && (
            <div className={s.who}>
              <span className={s.avatar} aria-hidden="true">{user.full_name.slice(0, 1)}</span>
              <div>
                <strong>{user.full_name}</strong>
                <div className="muted small">{t(`role_${user.role}` as const)}</div>
              </div>
            </div>
          )}
          <div className="stack">
            <Segmented
              label={t("theme")}
              value={theme.pref}
              onChange={(v) => {
                theme.setPref(v);
                savePrefs({ theme: v });
              }}
              options={[
                { value: "auto", label: t("theme_auto") },
                { value: "light", label: t("theme_light") },
                { value: "dark", label: t("theme_dark") },
              ]}
            />
            <div className={s.skyChips} role="group" aria-label="Langit">
              {(["umaga", "tanghali", "hapon", "gabi"] as SkyPeriod[]).map((p) => (
                <button key={p} type="button" className={s.skyChip} onClick={() => theme.previewPeriod(p)} aria-pressed={theme.period === p}>
                  <i style={{ background: `linear-gradient(${skyStops(p, "clear").join(",")})` }} aria-hidden="true" />
                  {t(`sky_${p}` as const)}
                </button>
              ))}
            </div>
          </div>
          <Segmented
            label={t("language")}
            value={lang}
            onChange={(v) => {
              setLang(v);
              savePrefs({ language: v });
            }}
            options={[
              { value: "en", label: t("lang_en") },
              { value: "fil", label: t("lang_fil") },
            ]}
          />
          <div className={s.menuLinks}>
            {nav.all
              .filter((n) => !nav.bottom.includes(n))
              .map((n) => (
                <NavLink key={n.to} to={n.to} className={s.menuLink} onClick={() => setMenuOpen(false)}>
                  <Icon name={n.icon} />
                  {t(n.label)}
                </NavLink>
              ))}
            {demo && (
              <button type="button" className={s.menuLink} onClick={() => { setMenuOpen(false); setDemoOpen(true); }}>
                <Icon name="flask" />
                {t("demo_controls")}
              </button>
            )}
            <button type="button" className={s.menuLink} onClick={() => { setMenuOpen(false); void logout(); }}>
              <Icon name="logout" />
              {t("sign_out")}
            </button>
          </div>
        </div>
      </Sheet>
    </div>
  );
}
