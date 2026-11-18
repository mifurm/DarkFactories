/* eslint-disable @typescript-eslint/no-explicit-any */
import { BrowserRouter, NavLink, Route, Routes, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Sun, Map as MapIcon, ShieldCheck, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ROLES, getRole, setRole } from "./api";
import { featureDefs, NAV_GROUPS } from "./registry";
import { ToastProvider, Badge, Meter, cn } from "./components/ui";
import { LanguageSwitcher } from "./components/LanguageSwitcher";
import { useLocalizedChartLegends } from "./components/common";
import FeatureMap from "./pages/FeatureMap";
import { getLang, I18nProvider, msg, useI18n } from "./i18n";

// The UI language is part of every query's identity: switching language re-requests everything the server localizes (no reload, no stale mix).
const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 4000, refetchOnWindowFocus: false, retry: 1, queryKeyHashFn: (key) => JSON.stringify([...key, getLang()]) } } });

function Sidebar() {
  const { t, tEnum } = useI18n();
  const items = featureDefs.filter((f) => f.nav).map((f) => ({ ...f.nav!, id: f.id }));
  items.push({ group: "Operate", label: msg("Feature map"), to: "/features", order: 99, icon: MapIcon, id: "map" });
  return (
    <aside className="hidden w-[248px] shrink-0 flex-col bg-espresso-900 text-cream-200 lg:flex">
      <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-dawn-500 text-espresso-950">
          <Sun className="h-5 w-5" />
        </div>
        <div>
          <div className="font-display text-[22px] font-semibold leading-none text-cream-50">Spotlight</div>
          <div className="mt-0.5 text-[10.5px] uppercase tracking-[0.18em] text-espresso-400">SwarmAI · Commercial Studio</div>
        </div>
      </div>
      <nav className="scroll-thin flex-1 overflow-y-auto px-3 pb-4" aria-label={t("Main")}>
        {NAV_GROUPS.map((g) => {
          const group = items.filter((i) => i.group === g).sort((a, b) => a.order - b.order);
          if (!group.length) return null;
          return (
            <div key={g} className="mt-4">
              <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-espresso-400">{tEnum("navGroup", g)}</div>
              {group.map((i) => (
                <NavLink
                  key={i.id + i.to}
                  to={i.to}
                  end={i.to === "/"}
                  className={({ isActive }) => cn("mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] transition-colors", isActive ? "bg-espresso-700 text-cream-50" : "text-cream-300 hover:bg-espresso-800 hover:text-cream-50")}
                >
                  <i.icon className="h-4 w-4 shrink-0 opacity-80" />
                  {t(i.label)}
                </NavLink>
              ))}
            </div>
          );
        })}
      </nav>
      <div className="border-t border-espresso-700 px-5 py-3 text-[11px] leading-snug text-espresso-400">
        {t("Sample brand")} <span className="text-cream-200">Northwind Coffee Roasters</span>
        <br />
        {t("campaign “{name}”", { name: "Dawn Roast" })}
      </div>
    </aside>
  );
}

function TopBar() {
  const { t, tEnum, fmt } = useI18n();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api.get("/api/meta"), staleTime: 60000 });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => api.get("/api/usage"), refetchInterval: 15000 });
  const [role, setR] = useState(getRole());
  useEffect(() => {
    const h = () => setR(getRole());
    window.addEventListener("studio-role", h);
    return () => window.removeEventListener("studio-role", h);
  }, []);
  const b = usage.data?.budget;
  return (
    <header className="flex items-center justify-between gap-4 border-b border-cream-300 bg-cream-50/90 px-6 py-2.5 backdrop-blur">
      <div className="flex items-center gap-2 text-[12.5px]">
        <Badge tone={meta.data?.mode === "azure" ? "good" : "warn"}>{meta.data?.mode === "azure" ? t("Azure · live") : t("Offline · simulated AI")}</Badge>
        {meta.data && <span className="hidden text-espresso-500 md:inline">{meta.data.region} · v{meta.data.version}</span>}
      </div>
      <div className="flex items-center gap-4">
        {b && (
          <NavLink to="/cost" className="hidden items-center gap-2 rounded-lg px-2 py-1 text-[12px] hover:bg-cream-200 md:flex" title={t("Daily AI budget (fails closed)")}>
            <Wallet className="h-3.5 w-3.5 text-dawn-600" />
            <span className="tabular-nums text-espresso-700">{t("{spent} / {cap} today", { spent: fmt.usd(b.spent_today_usd), cap: fmt.usd(b.daily_cap_usd) })}</span>
            <span className="w-20">
              <Meter value={b.spent_today_usd} max={b.daily_cap_usd} />
            </span>
          </NavLink>
        )}
        <LanguageSwitcher />
        <label className="flex items-center gap-2 text-[12px] text-espresso-500">
          <ShieldCheck className="h-3.5 w-3.5" />
          <span className="sr-only">{t("Acting as")}</span>
          <select
            aria-label={t("Acting as role")}
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              qc.invalidateQueries();
            }}
            className="rounded-lg border border-cream-300 bg-white px-2 py-1 text-[12.5px] font-medium text-espresso-800"
          >
            {ROLES.map((r) => (
              <option key={r.id} value={r.id}>
                {tEnum("role", r.id)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </header>
  );
}

function Shell() {
  const { t } = useI18n();
  useLocalizedChartLegends();
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="scroll-thin min-h-0 flex-1 overflow-y-auto" id="main">
          <div className="mx-auto max-w-[1320px] px-6 py-7">
            <Routes>
              {featureDefs.flatMap((f) => (f.routes ?? []).map((r) => <Route key={f.id + r.path} path={r.path} element={r.element} />))}
              <Route path="/features" element={<FeatureMap />} />
              <Route path="/brand-brain" element={<Navigate to="/brand" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </main>
        <footer className="border-t border-cream-300 bg-cream-50 px-6 py-1.5 text-[11.5px] text-espresso-500" data-testid="synthetic-banner">
          <span className="font-semibold text-espresso-700">{t("Synthetic data / simulated environment")}</span> — {t("fictional brand, simulated ad platforms & audience panel, demo roles (self-declared). AI generation, storage and rendering are real in Azure mode.")}
        </footer>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <BrowserRouter>
            <Shell />
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
