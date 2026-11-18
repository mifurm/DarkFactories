/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, assetUrl } from "../api";
import { getTranslator, useI18n } from "../i18n";
import { Badge, JobProgress, cn } from "./ui";

export function useCampaign(id: string) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["campaign", id], queryFn: () => api.get(`/api/campaigns/${id}`), refetchInterval: 8000 });
  const reload = () => {
    qc.invalidateQueries({ queryKey: ["campaign", id] });
    qc.invalidateQueries({ queryKey: ["usage"] });
  };
  return { ...q, reload };
}

/** Starts an async job (POST …) and shows live SSE progress; calls onDone when finished. */
export function useJobStarter(onDone?: (job: any) => void) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const start = async (path: string, body: any = {}) => {
    setBusy(true);
    try {
      const j = await api.post(path, body);
      setJobId(j.id);
    } finally {
      setBusy(false);
    }
  };
  const node: ReactNode = jobId ? (
    <JobProgress
      jobId={jobId}
      onDone={(j) => {
        setJobId(null);
        onDone?.(j);
      }}
    />
  ) : null;
  return { start, busy: busy || !!jobId, node };
}

export const mediaUrl = (id?: string | null, download = false) => (id ? assetUrl(id, { download }) : "");

export function Img({ id, alt, className }: { id?: string | null; alt?: string; className?: string }) {
  const { t } = useI18n();
  if (!id) return <div className={cn("flex items-center justify-center bg-cream-200 text-[12px] text-espresso-400", className)}>{t("no image")}</div>;
  return <img src={mediaUrl(id)} alt={alt ?? ""} loading="lazy" className={cn("object-cover", className)} />;
}

export function Video({ id, poster, className }: { id?: string | null; poster?: string | null; className?: string }) {
  if (!id) return null;
  return <video data-testid="video-player" controls preload="metadata" poster={mediaUrl(poster)} src={mediaUrl(id)} className={cn("w-full rounded-xl bg-espresso-950", className)} />;
}

export function GuardianBadge({ g }: { g?: any }) {
  const { t, tn, tEnum } = useI18n();
  if (!g) return <Badge>{t("not reviewed")}</Badge>;
  const tone = g.verdict === "block" ? "bad" : g.verdict === "warn" ? "warn" : "good";
  const Icon = g.verdict === "block" ? ShieldAlert : g.verdict === "warn" ? AlertTriangle : ShieldCheck;
  return (
    <Badge tone={tone} className="gap-1">
      <Icon className="h-3 w-3" />
      {t("Guardian {verdict}", { verdict: tEnum("verdict", g.verdict) })}
      {g.score != null && <span className="opacity-70">· {g.score}</span>}
      {g.blocks ? <span>· {tn(g.blocks, { one: "{n} block", other: "{n} blocks" })}</span> : null}
    </Badge>
  );
}

const sevTone: Record<string, "bad" | "warn" | "neutral"> = { block: "bad", warn: "warn", info: "neutral" };

export function FindingList({ findings, onWaive, canWaive }: { findings: any[]; onWaive?: (f: any) => void; canWaive?: boolean }) {
  const { t, tEnum } = useI18n();
  const live = (findings ?? []).filter((f) => f.severity !== "info");
  if (!live.length)
    return (
      <div className="flex items-center gap-2 rounded-xl bg-sage-100 px-4 py-3 text-[13px] text-sage-600">
        <CheckCircle2 className="h-4 w-4" /> {t("No findings — compliant.")}
      </div>
    );
  return (
    <ul className="space-y-2" data-testid="findings">
      {live.map((f) => (
        <li key={f.id} className={cn("rounded-xl border px-3.5 py-2.5 text-[13px]", f.waived ? "border-cream-300 bg-cream-50 opacity-70" : f.severity === "block" ? "border-roast-500/40 bg-roast-500/5" : "border-dawn-400/50 bg-dawn-300/10")}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={sevTone[f.severity]}>{tEnum("severity", f.waived ? "waived" : f.severity)}</Badge>
            <code className="rounded bg-cream-200 px-1.5 py-0.5 text-[11.5px]">{f.rule_id}</code>
            <span className="text-[11.5px] uppercase tracking-wide text-espresso-500">{tEnum("guardianCheck", f.check)}</span>
            {canWaive && f.severity === "block" && !f.waived && onWaive && (
              <button className="ml-auto text-[12px] font-medium text-dawn-700 hover:underline" onClick={() => onWaive(f)}>
                {t("Waive…")}
              </button>
            )}
          </div>
          <div className="mt-1 break-words font-medium text-espresso-900">{f.message}</div>
          {f.suggestion && <div className="mt-0.5 break-words text-espresso-600">{t("Fix: {text}", { text: f.suggestion })}</div>}
        </li>
      ))}
    </ul>
  );
}

/**
 * Recharts draws each legend swatch as `<svg aria-label="{series} legend icon">` — hard-coded English that cannot be configured. In a non-English UI the label is
 * rewritten once rendered (and again whenever a chart re-renders its legend); English keeps the library's own label.
 */
export function useLocalizedChartLegends() {
  const { t, lang } = useI18n();
  useEffect(() => {
    if (lang === "en") return;
    const suffix = " legend icon";
    let frame = 0;
    const fix = () => {
      frame = 0;
      document.querySelectorAll<SVGElement>(`svg[aria-label$="${suffix}"]`).forEach((svg) => {
        const label = svg.getAttribute("aria-label") ?? "";
        svg.setAttribute("aria-label", t("{name} legend icon", { name: label.slice(0, label.length - suffix.length) }));
      });
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(fix);
    };
    fix();
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [lang, t]);
}

export function useUsage() {
  return useQuery({ queryKey: ["usage"], queryFn: () => api.get("/api/usage"), refetchInterval: 15000 });
}

/** Audit/activity entries carry a machine action code (`approval.approved`). English keeps showing the code; other languages show the server's localized `message` or the dictionary label. */
export function useAuditLabel() {
  const { lang, tEnum } = useI18n();
  return (e: { action: string; message?: string }) => (lang === "en" ? e.action : e.message ?? tEnum("auditAction", e.action));
}

/** Demo identities default their name to the English role label ("Creative Director"): the UI shows the role in its own language then; names typed by users stay as typed. */
export function useActorName() {
  const { tEnum } = useI18n();
  return (a?: { name?: string | null; role?: string | null } | null): string => {
    if (!a) return "—";
    if (a.role && (!a.name || a.name === getTranslator("en").tEnum("role", a.role))) return tEnum("role", a.role);
    return a.name ?? "—";
  };
}

export function Tag({ children }: { children: ReactNode }) {
  return <span className="inline-block rounded-full border border-cream-300 bg-cream-50 px-2 py-0.5 text-[11.5px] text-espresso-600">{children}</span>;
}

export function PipelineStepper({ pipeline, onPick }: { pipeline: any[]; onPick?: (gate: string) => void }) {
  const { t, tEnum } = useI18n();
  return (
    <ol className="flex flex-wrap items-center gap-1.5" aria-label={t("Stage gates")}>
      {pipeline.map((p, i) => {
        const state = p.approval_state === "approved" || p.artifact_status === "approved" ? "approved" : p.artifact_status === "empty" ? "empty" : p.guardian?.verdict === "block" ? "blocked" : p.approval_state === "pending" ? "pending" : "draft";
        const tone = { approved: "bg-sage-500 text-white", blocked: "bg-roast-500 text-white", pending: "bg-dawn-500 text-white", draft: "bg-cream-300 text-espresso-700", empty: "bg-cream-100 text-espresso-400 border border-dashed border-cream-300" }[state];
        const label = tEnum("gate", p.gate, p.label);
        const stateLabel = tEnum("pipelineState", state);
        return (
          <li key={p.gate} className="flex items-center gap-1.5">
            <button onClick={() => onPick?.(p.gate)} className={cn("rounded-full px-3 py-1 text-[12px] font-semibold", tone)} title={`${label}: ${stateLabel}`}>
              {i + 1}. {label}
              <span className="ml-1 font-normal opacity-80">· {stateLabel}</span>
            </button>
            {i < pipeline.length - 1 && <span className="text-espresso-300">›</span>}
          </li>
        );
      })}
    </ol>
  );
}
