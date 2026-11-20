import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "../components/Toast";
import { I18nProvider, useI18n } from "../i18n/I18n";
import Garden from "../screens/Garden";
import SignIn from "../screens/SignIn";
import { AuthProvider, useAuth, type Capability } from "./Auth";
import Layout from "./Layout";
import { ThemeProvider } from "./Theme";
import FirstRun from "./FirstRun";

const History = lazy(() => import("../screens/History"));
const Forecast = lazy(() => import("../screens/Forecast"));
const Records = lazy(() => import("../screens/Records"));
const Settings = lazy(() => import("../screens/Settings"));
const Users = lazy(() => import("../screens/Users"));
const Reports = lazy(() => import("../screens/Reports"));
const Help = lazy(() => import("../screens/Help"));

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: true, retry: 1 } } });

function Guard({ cap, children }: { cap?: Capability; children: ReactNode }) {
  const { can } = useAuth();
  if (cap && !can(cap)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function Loading() {
  const { t } = useI18n();
  return <div className="page"><p className="muted">{t("loading")}</p></div>;
}

function Gate() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  if (!user) return <SignIn />;
  return (
    <>
      <FirstRun />
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Garden />} />
            <Route path="history" element={<History />} />
            <Route path="forecast" element={<Forecast />} />
            <Route path="records" element={<Records />} />
            <Route path="settings" element={<Guard cap="settings"><Settings /></Guard>} />
            <Route path="users" element={<Guard cap="users"><Users /></Guard>} />
            <Route path="reports" element={<Guard cap="reports"><Reports /></Guard>} />
            <Route path="help" element={<Help />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <I18nProvider>
        <ThemeProvider>
          <ToastProvider>
            <BrowserRouter>
              <AuthProvider>
                <Gate />
              </AuthProvider>
            </BrowserRouter>
          </ToastProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
