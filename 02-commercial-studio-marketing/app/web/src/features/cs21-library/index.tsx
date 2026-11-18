/* eslint-disable @typescript-eslint/no-explicit-any */
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileAudio, FileText, FolderPlus, Library, Search, Upload } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Select, Skeleton, StatusBadge, useToast } from "../../components/ui";
import { mediaUrl } from "../../components/common";
import { msg, useI18n } from "../../i18n";

const KINDS = ["image", "video", "audio", "subtitle", "document", "archive"];
const STATUSES = ["draft", "in_review", "approved", "archived"];

function Thumb({ a, className = "" }: { a: any; className?: string }) {
  if (a.kind === "image") return <img src={mediaUrl(a.id)} alt={a.name} loading="lazy" className={`object-cover ${className}`} />;
  if (a.kind === "video") return <video src={`${mediaUrl(a.id)}#t=0.5`} preload="metadata" muted playsInline className={`bg-espresso-950 object-cover ${className}`} />;
  const I = a.kind === "audio" ? FileAudio : FileText;
  return (
    <div className={`flex items-center justify-center bg-cream-200 text-espresso-400 ${className}`}>
      <I className="h-8 w-8" />
    </div>
  );
}

function Detail({ id, onClose, onChange }: { id: string; onClose: () => void; onChange: () => void }) {
  const { t, tEnum, tOpen, fmt } = useI18n();
  const toast = useToast();
  const q = useQuery({ queryKey: ["asset", id], queryFn: () => api.get(`/api/library/assets/${id}`) });
  const [tags, setTags] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const a = q.data;
  const save = async (patch: any) => {
    await api.put(`/api/library/assets/${id}`, patch);
    toast({ tone: "good", title: t("Saved") });
    q.refetch();
    onChange();
  };
  const version = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("note", t("new version from the library"));
    const r = await api.upload(`/api/library/assets/${id}/version`, fd);
    toast({ tone: "good", title: t("Version {n} stored", { n: String(r.version) }) });
    q.refetch();
    onChange();
  };
  return (
    <Modal open onClose={onClose} title={a?.name ?? t("Asset")} wide>
      {!a ? (
        <Skeleton h={240} />
      ) : (
        <div className="grid gap-5 md:grid-cols-[1.2fr_1fr]">
          <div>
            {a.kind === "video" ? <video controls preload="metadata" src={mediaUrl(a.id)} className="w-full rounded-xl bg-espresso-950" /> : a.kind === "audio" ? <audio controls src={mediaUrl(a.id)} className="w-full" /> : a.kind === "image" ? <img src={mediaUrl(a.id)} alt={a.name} className="w-full rounded-xl" /> : <Thumb a={a} className="h-48 w-full rounded-xl" />}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <a href={mediaUrl(a.id, true)} className="inline-flex items-center gap-1 text-[13px] text-dawn-700 underline">
                <Download className="h-3.5 w-3.5" />
                {t("Download")}
              </a>
              <input ref={file} type="file" hidden onChange={(e) => e.target.files?.[0] && version(e.target.files[0])} />
              <Button size="sm" variant="outline" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => file.current?.click()}>
                {t("Upload new version")}
              </Button>
            </div>
          </div>
          <div className="min-w-0 space-y-3 text-[13px]">
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="dark">{tOpen("assetKind", a.kind)}</Badge>
              <StatusBadge s={a.status} />
              <Badge>v{a.version}</Badge>
              {a.ai_generated && <Badge tone="warn">{t("AI-generated")}</Badge>}
            </div>
            <div className="break-words text-espresso-500">{t("{mime} · {size} KB · {date} · sha256 {hash}…", { mime: a.mime, size: fmt.number(a.size / 1024), date: fmt.dateTime(a.created_at), hash: a.sha256.slice(0, 12) })}</div>
            {a.description && <div className="text-espresso-700">{a.description}</div>}
            <Field label={t("Tags")}>
              <Input value={tags ?? a.tags.join(", ")} onChange={(e) => setTags(e.target.value)} onBlur={() => tags !== null && save({ tags: tags.split(",") })} aria-label={t("tags")} />
            </Field>
            <Field label={t("Status")}>
              <Select value={a.status} onChange={(e) => save({ status: e.target.value })} aria-label={t("status")}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {tEnum("status", s)}
                  </option>
                ))}
              </Select>
            </Field>
            {a.ancestors.length > 0 && (
              <div>
                <b>{t("Earlier versions:")}</b> {a.ancestors.map((x: any) => `v${x.version}`).join(", ")}
              </div>
            )}
            {a.children.length > 0 && (
              <div>
                <b>{t("Derived / newer:")}</b> {a.children.map((x: any) => `v${x.version}`).join(", ")}
              </div>
            )}
            {a.rights.length > 0 && (
              <div>
                <b>{t("Rights:")}</b>
                <ul className="mt-1 list-disc pl-5">
                  {a.rights.map((r: any) => (
                    <li key={r.id}>
                      {r.title} <StatusBadge s={r.status} /> {r.valid_to && <span className="text-espresso-400">{t("until {date}", { date: fmt.isoDate(r.valid_to) })}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {a.provenance_id && <Badge tone="good">{t("provenance manifest signed")}</Badge>}
          </div>
        </div>
      )}
    </Modal>
  );
}

function LibraryPage() {
  const { t, tn, tEnum, tOpen, findEnum, fmt } = useI18n();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [semantic, setSemantic] = useState(false);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [collection, setCollection] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const key = ["library", q, semantic, kind, status, collection];
  // the studio's own tags are shown in Polish ("napisy"); the API stores and matches the raw tag ("captions"), so a query that is exactly a Polish tag label is sent as the tag
  const apiQuery = (text: string) => findEnum("assetTag", text) ?? text;
  const assets = useQuery({
    queryKey: key,
    queryFn: async () => {
      if (semantic && q.trim().length > 1) {
        const r = await api.get(`/api/library/search?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ""}`);
        return { assets: r.results, count: r.results.length, scores: true };
      }
      const p = new URLSearchParams();
      if (q) p.set("q", apiQuery(q));
      if (kind) p.set("kind", kind);
      if (status) p.set("status", status);
      if (collection) p.set("collection", collection);
      p.set("limit", "80");
      return api.get(`/api/library/assets?${p}`);
    },
  });
  const cols = useQuery({ queryKey: ["collections"], queryFn: () => api.get("/api/library/collections") });
  const upload = async (f: File) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("tags", "upload");
      const r = await api.upload("/api/library/assets", fd);
      toast({ tone: "good", title: t("{name} uploaded", { name: r.name }) });
      assets.refetch();
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  };
  const newCol = async () => {
    const name = window.prompt(t("Collection name"));
    if (!name) return;
    await api.post("/api/library/collections", { name });
    cols.refetch();
  };
  const list: any[] = assets.data?.assets ?? [];
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-21 · Asset library")}
        title={t("Asset library")}
        subtitle={t("Everything the studio produces or you upload — images, spots, voice-overs, captions — in private Blob Storage, served only through the API (Entra RBAC, no public blobs). Keyword or semantic search over names, tags and prompts.")}
        actions={
          <>
            <input ref={file} type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label={t("upload")} />
            <Button variant="accent" icon={<Upload className="h-4 w-4" />} loading={busy} onClick={() => file.current?.click()}>
              {t("Upload")}
            </Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-md">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-espresso-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={semantic ? t("Describe what you need… e.g. warm kitchen morning light") : t("Search name, tag, description")} className="pl-9" aria-label={t("search")} />
        </div>
        <label className="flex items-center gap-1.5 text-[13px]">
          <input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} /> {t("semantic")}
        </label>
        <Select value={kind} onChange={(e) => setKind(e.target.value)} className="w-40" aria-label={t("kind")}>
          <option value="">{t("all kinds")}</option>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {tOpen("assetKind", k)}
            </option>
          ))}
        </Select>
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-40" aria-label={t("status filter")}>
          <option value="">{t("any status")}</option>
          {STATUSES.map((k) => (
            <option key={k} value={k}>
              {tEnum("status", k)}
            </option>
          ))}
        </Select>
        <Select value={collection} onChange={(e) => setCollection(e.target.value)} className="w-48" aria-label={t("collection")}>
          <option value="">{t("all collections")}</option>
          {(cols.data ?? []).map((c: any) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Button size="sm" variant="ghost" icon={<FolderPlus className="h-4 w-4" />} onClick={newCol}>
          {t("New collection")}
        </Button>
        <span className="ml-auto text-[12.5px] text-espresso-500">{tn(assets.data?.count ?? 0, { one: "{n} asset(s)", other: "{n} asset(s)" })}</span>
      </div>
      {assets.isLoading && <Skeleton h={300} />}
      {!assets.isLoading && !list.length && <Empty title={t("No assets match")} hint={t("Generate keyframes and spots in a campaign workspace, or upload a file.")} />}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5" data-testid="asset-grid">
        {list.map((a) => (
          <button key={a.id} onClick={() => setOpen(a.id)} className="flex text-left">
            <Card pad={false} className="w-full overflow-hidden transition-shadow hover:shadow-md">
              <Thumb a={a} className="aspect-[4/3] w-full" />
              <div className="space-y-1 p-3 text-[12.5px]">
                <div className="break-words font-semibold text-espresso-900">{a.name}</div>
                <div className="flex flex-wrap items-center gap-1">
                  <Badge>{tOpen("assetKind", a.kind)}</Badge>
                  <StatusBadge s={a.status} />
                  {a.ai_generated && <Badge tone="warn">{t("AI")}</Badge>}
                  {a.score != null && <Badge tone="info">{fmt.fixed(a.score, 2)}</Badge>}
                </div>
                <div className="break-words text-espresso-400" title={a.tags.map((x: string) => tOpen("assetTag", x)).join(" · ")}>{a.tags.slice(0, 4).map((x: string) => tOpen("assetTag", x)).join(" · ")}</div>
              </div>
            </Card>
          </button>
        ))}
      </div>
      {open && <Detail id={open} onClose={() => setOpen(null)} onChange={() => assets.refetch()} />}
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-21",
  routes: [{ path: "/library", element: <LibraryPage /> }],
  nav: { group: "Studio", label: msg("Asset library"), to: "/library", order: 20, icon: Library },
};
