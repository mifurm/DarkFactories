/* eslint-disable @typescript-eslint/no-explicit-any */
export class ApiError extends Error {
  code: string;
  hint?: string;
  status: number;
  details?: any;
  constructor(status: number, body: any) {
    const e = body?.error ?? {};
    super(e.message ?? `Request failed (${status})`);
    this.status = status;
    this.code = e.code ?? "error";
    this.hint = e.hint;
    this.details = e.details;
  }
}

export const ROLES = [
  { id: "admin", label: "Admin" },
  { id: "brand_manager", label: "Brand Manager" },
  { id: "creative_director", label: "Creative Director" },
  { id: "creative", label: "Creative" },
  { id: "legal", label: "Legal / Compliance" },
  { id: "agency_guest", label: "Agency (guest)" },
];

export function getRole(): string {
  return localStorage.getItem("studio.role") || "creative_director";
}
export function setRole(r: string) {
  localStorage.setItem("studio.role", r);
  window.dispatchEvent(new Event("studio-role"));
}

type Listener = (e: ApiError) => void;
const errorListeners = new Set<Listener>();
export const onApiError = (fn: Listener) => {
  errorListeners.add(fn);
  return () => {
    errorListeners.delete(fn);
  };
};

async function request<T = any>(method: string, path: string, body?: any, opts: { quiet?: boolean; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Studio-Role": getRole(), "X-Studio-User": localStorage.getItem("studio.user") || "" };
  let payload: BodyInit | undefined;
  if (opts.form) payload = opts.form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = new ApiError(res.status, typeof data === "string" ? {} : data);
    if (!opts.quiet) errorListeners.forEach((l) => l(err));
    throw err;
  }
  return data as T;
}

export const api = {
  get: <T = any>(p: string, o?: { quiet?: boolean }) => request<T>("GET", p, undefined, o),
  post: <T = any>(p: string, b?: any, o?: { quiet?: boolean }) => request<T>("POST", p, b ?? {}, o),
  put: <T = any>(p: string, b?: any, o?: { quiet?: boolean }) => request<T>("PUT", p, b ?? {}, o),
  patch: <T = any>(p: string, b?: any, o?: { quiet?: boolean }) => request<T>("PATCH", p, b ?? {}, o),
  del: <T = any>(p: string, o?: { quiet?: boolean }) => request<T>("DELETE", p, undefined, o),
  upload: <T = any>(p: string, form: FormData, o?: { quiet?: boolean }) => request<T>("POST", p, undefined, { ...o, form }),
};

export const fmtUsd = (v?: number | null, d = 2) => (v == null ? "—" : `$${v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`);
export const fmtNum = (v?: number | null, d = 0) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: d }));
export const fmtPct = (v?: number | null, d = 1) => (v == null ? "—" : `${v.toFixed(d)}%`);
export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—");
export const assetUrl = (id: string, campaignId?: string) => `/api/library/assets/${id}/content${campaignId ? `?campaign_id=${campaignId}` : ""}`;
