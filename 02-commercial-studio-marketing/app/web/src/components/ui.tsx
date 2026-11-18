/* eslint-disable @typescript-eslint/no-explicit-any */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type ButtonHTMLAttributes, type InputHTMLAttributes, type TextareaHTMLAttributes, type SelectHTMLAttributes } from "react";
import { CheckCircle2, AlertTriangle, XCircle, Info, Loader2, X } from "lucide-react";
import { ApiError, api, onApiError, withLang } from "../api";
import { useI18n } from "../i18n";
import { stepLabel } from "./jobSteps";

export const cn = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "dawn" | "dark";
const toneCls: Record<Tone, string> = {
  neutral: "bg-cream-200 text-espresso-700",
  good: "bg-sage-100 text-sage-600",
  warn: "bg-dawn-300/40 text-dawn-700",
  bad: "bg-roast-500/15 text-roast-600",
  info: "bg-sky-100 text-sky-800",
  dawn: "bg-dawn-500 text-white",
  dark: "bg-espresso-800 text-cream-100",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide", toneCls[tone], className)}>{children}</span>;
}

export const statusTone = (s?: string): Tone => {
  const v = (s || "").toLowerCase();
  if (["approved", "pass", "passed", "succeeded", "implemented", "active", "ok", "ready", "verified", "licensed", "done", "valid"].includes(v)) return "good";
  if (["warn", "warning", "pending", "in_review", "running", "queued", "draft", "changes_requested", "expiring", "needs_substantiation", "planned", "paused"].includes(v)) return "warn";
  if (["block", "blocked", "failed", "rejected", "expired", "prohibited", "invalid", "tampered", "unlicensed", "error"].includes(v)) return "bad";
  return "neutral";
};

export function StatusBadge({ s }: { s?: string }) {
  const { tEnum } = useI18n();
  return <Badge tone={statusTone(s)}>{tEnum("status", s)}</Badge>;
}

export function Card({ title, subtitle, actions, children, className, pad = true, testId }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode; className?: string; pad?: boolean; testId?: string }) {
  return (
    <section data-testid={testId} className={cn("min-w-0 rounded-2xl border border-cream-300 bg-white shadow-[0_1px_0_rgba(43,26,18,0.04)]", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-cream-200 px-5 py-3.5">
          <div className="min-w-0">
            {title && <h3 className="font-display text-[17px] font-semibold leading-tight text-espresso-800">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-[12.5px] text-espresso-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">{actions}</div>}
        </header>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function Spinner({ className }: { className?: string }) {
  const { t } = useI18n();
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} aria-label={t("loading")} data-spinner="" />;
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "accent" | "ghost" | "danger" | "outline"; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode };
export function Button({ variant = "primary", size = "md", loading, icon, children, className, disabled, ...rest }: BtnProps) {
  const v = {
    primary: "bg-espresso-800 text-cream-50 hover:bg-espresso-700",
    accent: "bg-dawn-500 text-white hover:bg-dawn-600",
    ghost: "text-espresso-700 hover:bg-cream-200",
    danger: "bg-roast-500 text-white hover:bg-roast-600",
    outline: "border border-cream-300 bg-white text-espresso-800 hover:bg-cream-100",
  }[variant];
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn("inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50", size === "sm" ? "px-2.5 py-1 text-[12.5px]" : "px-3.5 py-2 text-[13.5px]", v, className)}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

/** A big figure that shrinks (28 → 16 px) until it fits its tile: Polish values ("465 tys. USD", "15,86 mln USD") are wider than the English "$465k". */
function FitValue({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const fit = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    let size = 28;
    el.style.whiteSpace = "nowrap";
    el.style.fontSize = `${size}px`;
    while (el.scrollWidth > el.clientWidth + 1 && size > 16) el.style.fontSize = `${--size}px`;
    if (el.scrollWidth > el.clientWidth + 1) el.style.whiteSpace = "normal"; // still too wide at the minimum size: wrap instead of clipping
  }, []);
  useLayoutEffect(fit);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="min-w-0 rounded-2xl border border-cream-300 bg-white px-4 py-3.5">
      <div className="text-[11.5px] font-semibold uppercase tracking-wider text-espresso-500">{label}</div>
      <FitValue className={cn("mt-1 font-display font-semibold leading-none", tone === "bad" && "text-roast-600", tone === "good" && "text-sage-600", tone === "dawn" && "text-dawn-600")}>{value}</FitValue>
      {hint && <div className="mt-1.5 text-[12px] text-espresso-500">{hint}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode; badge?: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="tablist" className="scroll-thin flex gap-1 overflow-x-auto border-b border-cream-300">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cn("relative -mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3.5 py-2.5 text-[13.5px] font-medium transition-colors", value === t.id ? "border-dawn-500 text-espresso-900" : "border-transparent text-espresso-500 hover:text-espresso-800")}
        >
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, className, group }: { label: string; hint?: ReactNode; children: ReactNode; className?: string; group?: boolean }) {
  const text = <span className="mb-1 block text-[12px] font-semibold uppercase tracking-wide text-espresso-500">{label}</span>;
  // A <label> around several buttons would name the first one after the whole group ("Markets US DE FR …"): button groups get role="group" instead.
  if (group)
    return (
      <div role="group" aria-label={label} className={cn("block", className)}>
        {text}
        {children}
        {hint && <span className="mt-1 block text-[12px] text-espresso-400">{hint}</span>}
      </div>
    );
  return (
    <label className={cn("block", className)}>
      {text}
      {children}
      {hint && <span className="mt-1 block text-[12px] text-espresso-400">{hint}</span>}
    </label>
  );
}
const inputCls = "rounded-lg border border-cream-300 bg-cream-50 px-3 py-2 text-[14px] text-espresso-900 placeholder:text-espresso-400 focus:border-dawn-500 focus:bg-white";
const widthCls = (c?: string) => (c && /(^|\s)(w|max-w|flex)-/.test(c) ? "" : "w-full");
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cn(inputCls, widthCls(p.className), p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cn(inputCls, widthCls(p.className), "min-h-[90px] leading-relaxed", p.className)} />;
/** An explicit `w-NN` is a minimum: the control grows to its longest option so longer (Polish) labels are never cut off. */
export const Select = ({ style, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => {
  const w = /(?:^|\s)w-(\d+)(?:\s|$)/.exec(p.className ?? "");
  const grow = w ? { width: "auto", minWidth: `${Number(w[1]) / 4}rem` } : undefined;
  return <select {...p} style={{ ...grow, ...style }} className={cn(inputCls, widthCls(p.className), p.className)} />;
};

export function Empty({ title, hint, action }: { title: string; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-cream-300 bg-cream-50 px-6 py-10 text-center">
      <div className="font-display text-[17px] font-semibold text-espresso-700">{title}</div>
      {hint && <div className="max-w-md text-[13px] text-espresso-500">{hint}</div>}
      {action}
    </div>
  );
}

export function PageHeader({ eyebrow, title, subtitle, actions }: { eyebrow?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[11.5px] font-semibold uppercase tracking-[0.14em] text-dawn-600">{eyebrow}</div>}
        <h1 className="text-[32px] font-semibold leading-[1.1] text-espresso-900">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-[14px] text-espresso-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const { t } = useI18n();
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-espresso-950/50 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className={cn("max-h-[90vh] w-full overflow-auto rounded-2xl bg-white shadow-2xl", wide ? "max-w-4xl" : "max-w-xl")} onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-cream-200 px-5 py-3.5">
          <h3 className="font-display text-lg font-semibold">{title}</h3>
          <button onClick={onClose} aria-label={t("Close")} className="rounded p-1 hover:bg-cream-200">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Meter({ value, max = 1, tone }: { value: number; max?: number; tone?: Tone }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  const col = tone === "bad" || pct >= 100 ? "bg-roast-500" : tone === "warn" || pct >= 80 ? "bg-dawn-500" : "bg-sage-500";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-cream-200" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn("h-full rounded-full transition-all", col)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-5 gap-y-1.5 text-[13px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-espresso-500">{k}</dt>
          <dd className="min-w-0 break-words font-medium text-espresso-800">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({ head, rows, empty }: { head: ReactNode[]; rows: ReactNode[][]; empty?: string }) {
  const { t } = useI18n();
  if (!rows.length) return <div className="px-2 py-6 text-center text-[13px] text-espresso-400">{empty || t("Nothing here yet.")}</div>;
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-cream-300 text-[11.5px] uppercase tracking-wider text-espresso-500">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-cream-200 last:border-0 hover:bg-cream-50">
              {r.map((c, j) => (
                <td key={j} className="px-3 py-2 align-top">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- toasts
type ToastT = { id: number; tone: "good" | "bad" | "info" | "warn"; title: string; body?: string };
const ToastCtx = createContext<(t: Omit<ToastT, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastT[]>([]);
  const idRef = useRef(1);
  const push = useCallback((t: Omit<ToastT, "id">) => {
    const id = idRef.current++;
    setItems((x) => [...x, { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.tone === "bad" ? 9000 : 4500);
  }, []);
  useEffect(
    () =>
      onApiError((e: ApiError) => {
        push({ tone: e.status === 402 || e.code === "guardian_blocked" ? "warn" : "bad", title: e.message, body: e.hint });
      }),
    [push],
  );
  const Icon = { good: CheckCircle2, bad: XCircle, info: Info, warn: AlertTriangle };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-[360px] max-w-[92vw] flex-col gap-2" aria-live="polite">
        {items.map((t) => {
          const I = Icon[t.tone];
          return (
            <div key={t.id} className={cn("flex gap-2.5 rounded-xl border px-3.5 py-3 shadow-lg", t.tone === "bad" ? "border-roast-500/40 bg-white" : t.tone === "warn" ? "border-dawn-400 bg-white" : "border-cream-300 bg-white")}>
              <I className={cn("mt-0.5 h-4 w-4 shrink-0", t.tone === "bad" ? "text-roast-500" : t.tone === "warn" ? "text-dawn-600" : t.tone === "good" ? "text-sage-600" : "text-sky-700")} />
              <div className="min-w-0 text-[13px]">
                <div className="font-semibold text-espresso-900">{t.title}</div>
                {t.body && <div className="mt-0.5 text-espresso-500">{t.body}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------------------------------------------------------------------------------------------- jobs (SSE)
export function JobProgress({ jobId, onDone, compact }: { jobId: string; onDone?: (job: any) => void; compact?: boolean }) {
  const i18n = useI18n();
  const { t, lang } = i18n;
  const [job, setJob] = useState<any>(null);
  const doneRef = useRef(false);
  useEffect(() => {
    doneRef.current = false;
    const es = new EventSource(withLang(`/api/stream/jobs/${jobId}`));
    const handle = (ev: MessageEvent) => {
      const j = JSON.parse(ev.data);
      setJob(j);
      if (["succeeded", "failed", "cancelled"].includes(j.status) && !doneRef.current) {
        doneRef.current = true;
        es.close();
        onDone?.(j);
      }
    };
    es.addEventListener("progress", handle);
    es.addEventListener("done", handle);
    es.onerror = async () => {
      es.close();
      if (doneRef.current) return;
      try {
        const j = await api.get(`/api/jobs/${jobId}`, { quiet: true });
        setJob(j);
        if (["succeeded", "failed", "cancelled"].includes(j.status)) {
          doneRef.current = true;
          onDone?.(j);
        }
      } catch {
        /* ignore */
      }
    };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);
  if (!job)
    return (
      <div className="flex items-center gap-2 text-[13px] text-espresso-500">
        <Spinner /> {t("Connecting…")}
      </div>
    );
  const failed = job.status === "failed";
  // the server renders the title in the request language (with the persona and details); the dictionary is only the fallback
  const title = job.title || (lang !== "en" && i18n.hasEnum("jobKind", job.kind) ? i18n.tEnum("jobKind", job.kind) : job.kind);
  return (
    <div className={cn("rounded-xl border px-4 py-3", failed ? "border-roast-500/40 bg-roast-500/5" : "border-cream-300 bg-cream-50")} data-testid="job-progress">
      <div className="flex items-center justify-between text-[13px]">
        <div className="flex items-center gap-2 font-medium">
          {job.status === "running" || job.status === "queued" ? <Spinner /> : failed ? <XCircle className="h-4 w-4 text-roast-500" /> : <CheckCircle2 className="h-4 w-4 text-sage-600" />}
          {title}
        </div>
        <span className="tabular-nums text-espresso-500">{Math.round((job.progress || 0) * 100)}%</span>
      </div>
      <div className="mt-2">
        <Meter value={job.progress || 0} tone={failed ? "bad" : undefined} />
      </div>
      <div className="mt-1.5 text-[12.5px] text-espresso-500">{failed ? job.error : job.message}</div>
      {!compact && job.steps?.length > 0 && (
        <ol className="mt-2 flex flex-wrap gap-1.5">
          {job.steps.slice(-8).map((s: any, i: number) => (
            <li key={i} className="rounded-full bg-cream-200 px-2 py-0.5 text-[11px] text-espresso-600">
              {stepLabel(i18n, s.name)}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function Json({ data }: { data: any }) {
  return <pre className="scroll-thin max-h-80 overflow-auto rounded-lg bg-espresso-900 p-3 text-[12px] leading-relaxed text-cream-100">{JSON.stringify(data, null, 2)}</pre>;
}

export function Skeleton({ h = 20, className }: { h?: number; className?: string }) {
  return <div className={cn("skeleton", className)} style={{ height: h }} />;
}
