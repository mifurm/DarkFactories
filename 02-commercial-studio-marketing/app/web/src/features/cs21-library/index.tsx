/* eslint-disable @typescript-eslint/no-explicit-any */
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileAudio, FileText, FolderPlus, Library, Search, Upload } from "lucide-react";
import { api, fmtDate, fmtNum } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Select, Skeleton, StatusBadge, useToast } from "../../components/ui";
import { mediaUrl } from "../../components/common";

function Thumb({ a, className = "" }: { a: any; className?: string }) {
  if (a.kind === "image") return <img src={mediaUrl(a.id)} alt={a.name} loading="lazy" className={`object-cover ${className}`} />;
  if (a.kind === "video") return <video src={`${mediaUrl(a.id)}#t=0.5`} preload="metadata" muted playsInline className={`bg-espresso-950 object-cover ${className}`} />;
  const I = a.kind === "audio" ? FileAudio : FileText;
  return <div className={`flex items-center justify-center bg-cream-200 text-espresso-400 ${className}`}><I className="h-8 w-8" /></div>;
}

function Detail({ id, onClose, onChange }: { id: string; onClose: () => void; onChange: () => void }) {
  const toast = useToast();
  const q = useQuery({ queryKey: ["asset", id], queryFn: () => api.get(`/api/library/assets/${id}`) });
  const [tags, setTags] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const a = q.data;
  const save = async (patch: any) => {
    await api.put(`/api/library/assets/${id}`, patch);
    toast({ tone: "good", title: "Saved" });
    q.refetch();
    onChange();
  };
  const version = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("note", "new version from the library");
    const r = await api.upload(`/api/library/assets/${id}/version`, fd);
    toast({ tone: "good", title: `Version ${r.version} stored` });
    q.refetch();
    onChange();
  };
  return (
    <Modal open onClose={onClose} title={a?.name ?? "Asset"} wide>
      {!a ? <Skeleton h={240} /> : (
        <div className="grid gap-5 md:grid-cols-[1.2fr_1fr]">
          <div>
            {a.kind === "video" ? <video controls preload="metadata" src={mediaUrl(a.id)} className="w-full rounded-xl bg-espresso-950" /> : a.kind === "audio" ? <audio controls src={mediaUrl(a.id)} className="w-full" /> : a.kind === "image" ? <img src={mediaUrl(a.id)} alt={a.name} className="w-full rounded-xl" /> : <Thumb a={a} className="h-48 w-full rounded-xl" />}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <a href={`${mediaUrl(a.id)}?download=true`} className="inline-flex items-center gap-1 text-[13px] text-dawn-700 underline"><Download className="h-3.5 w-3.5" />Download</a>
              <input ref={file} type="file" hidden onChange={(e) => e.target.files?.[0] && version(e.target.files[0])} />
              <Button size="sm" variant="outline" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => file.current?.click()}>Upload new version</Button>
            </div>
          </div>
          <div className="space-y-3 text-[13px]">
            <div className="flex flex-wrap gap-1.5"><Badge tone="dark">{a.kind}</Badge><StatusBadge s={a.status} /><Badge>v{a.version}</Badge>{a.ai_generated && <Badge tone="warn">AI-generated</Badge>}</div>
            <div className="text-espresso-500">{a.mime} · {fmtNum(a.size / 1024)} KB · {fmtDate(a.created_at)} · sha256 {a.sha256.slice(0, 12)}…</div>
            {a.description && <div className="text-espresso-700">{a.description}</div>}
            <Field label="Tags"><Input value={tags ?? a.tags.join(", ")} onChange={(e) => setTags(e.target.value)} onBlur={() => tags !== null && save({ tags: tags.split(",") })} aria-label="tags" /></Field>
            <Field label="Status"><Select value={a.status} onChange={(e) => save({ status: e.target.value })} aria-label="status">{["draft", "in_review", "approved", "archived"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
            {a.ancestors.length > 0 && <div><b>Earlier versions:</b> {a.ancestors.map((x: any) => `v${x.version}`).join(", ")}</div>}
            {a.children.length > 0 && <div><b>Derived / newer:</b> {a.children.map((x: any) => `v${x.version}`).join(", ")}</div>}
            {a.rights.length > 0 && <div><b>Rights:</b><ul className="mt-1 list-disc pl-5">{a.rights.map((r: any) => <li key={r.id}>{r.title} <StatusBadge s={r.status} /> {r.valid_to && <span className="text-espresso-400">until {r.valid_to}</span>}</li>)}</ul></div>}
            {a.provenance_id && <Badge tone="good">provenance manifest signed</Badge>}
          </div>
        </div>
      )}
    </Modal>
  );
}

function LibraryPage() {
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
  const assets = useQuery({
    queryKey: key,
    queryFn: async () => {
      if (semantic && q.trim().length > 1) {
        const r = await api.get(`/api/library/search?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ""}`);
        return { assets: r.results, count: r.results.length, scores: true };
      }
      const p = new URLSearchParams();
      if (q) p.set("q", q);
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
      toast({ tone: "good", title: `${r.name} uploaded` });
      assets.refetch();
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  };
  const newCol = async () => {
    const name = window.prompt("Collection name");
    if (!name) return;
    await api.post("/api/library/collections", { name });
    cols.refetch();
  };
  const list: any[] = assets.data?.assets ?? [];
  return (
    <div>
      <PageHeader eyebrow="CS-21 · Asset library" title="Asset library" subtitle="Everything the studio produces or you upload — images, spots, voice-overs, captions — in private Blob Storage, served only through the API (Entra RBAC, no public blobs). Keyword or semantic search over names, tags and prompts." actions={<><input ref={file} type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label="upload" /><Button variant="accent" icon={<Upload className="h-4 w-4" />} loading={busy} onClick={() => file.current?.click()}>Upload</Button></>} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-md"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-espresso-400" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={semantic ? "Describe what you need… e.g. warm kitchen morning light" : "Search name, tag, description"} className="pl-9" aria-label="search" /></div>
        <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} /> semantic</label>
        <Select value={kind} onChange={(e) => setKind(e.target.value)} className="w-36" aria-label="kind"><option value="">all kinds</option>{["image", "video", "audio", "subtitle", "document", "archive"].map((k) => <option key={k}>{k}</option>)}</Select>
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-36" aria-label="status filter"><option value="">any status</option>{["draft", "in_review", "approved", "archived"].map((k) => <option key={k}>{k}</option>)}</Select>
        <Select value={collection} onChange={(e) => setCollection(e.target.value)} className="w-44" aria-label="collection"><option value="">all collections</option>{(cols.data ?? []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        <Button size="sm" variant="ghost" icon={<FolderPlus className="h-4 w-4" />} onClick={newCol}>New collection</Button>
        <span className="ml-auto text-[12.5px] text-espresso-500">{assets.data?.count ?? 0} asset(s)</span>
      </div>
      {assets.isLoading && <Skeleton h={300} />}
      {!assets.isLoading && !list.length && <Empty title="No assets match" hint="Generate keyframes and spots in a campaign workspace, or upload a file." />}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5" data-testid="asset-grid">
        {list.map((a) => (
          <button key={a.id} onClick={() => setOpen(a.id)} className="text-left">
            <Card pad={false} className="overflow-hidden transition-shadow hover:shadow-md">
              <Thumb a={a} className="aspect-[4/3] w-full" />
              <div className="space-y-1 p-3 text-[12.5px]">
                <div className="truncate font-semibold text-espresso-900">{a.name}</div>
                <div className="flex flex-wrap items-center gap-1"><Badge>{a.kind}</Badge><StatusBadge s={a.status} />{a.ai_generated && <Badge tone="warn">AI</Badge>}{a.score != null && <Badge tone="info">{a.score.toFixed(2)}</Badge>}</div>
                <div className="truncate text-espresso-400">{a.tags.slice(0, 4).join(" · ")}</div>
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
  nav: { group: "Studio", label: "Asset library", to: "/library", order: 20, icon: Library },
};
