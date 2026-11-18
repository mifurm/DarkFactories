/* eslint-disable @typescript-eslint/no-explicit-any */
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, FilePlus2, Search, Sparkles, Trash2 } from "lucide-react";
import { api, fmtDate } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Skeleton, Stat, Textarea, useToast } from "../../components/ui";

function BrandBrainPage() {
  const toast = useToast();
  const b = useQuery({ queryKey: ["brand"], queryFn: () => api.get("/api/brand") });
  const learn = useQuery({ queryKey: ["learnings"], queryFn: () => api.get("/api/brand/learnings") });
  const [q, setQ] = useState("What is the brand voice and tone?");
  const [hits, setHits] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [addText, setAddText] = useState("");
  const [paste, setPaste] = useState({ name: "pasted-guidelines.md", text: "" });
  const [edit, setEdit] = useState(false);
  const [kitEdit, setKitEdit] = useState<any>(null);
  const [voice, setVoice] = useState<any>(null);
  const file = useRef<HTMLInputElement>(null);
  const d = b.data;
  const kit = d?.kit;
  const ask = async () => {
    setBusy("ask");
    try {
      setHits(await api.get(`/api/brand/search?q=${encodeURIComponent(q)}&k=5`));
    } finally {
      setBusy(null);
    }
  };
  const ingest = async (f?: File) => {
    setBusy("ingest");
    try {
      const fd = new FormData();
      if (f) fd.append("file", f);
      else {
        fd.append("name", paste.name);
        fd.append("text", paste.text);
      }
      const r = await api.upload("/api/brand/ingest", fd);
      toast({ tone: "good", title: `${r.name} ingested`, body: `${r.chunks} passages embedded and indexed` });
      setPaste({ ...paste, text: "" });
      b.refetch();
    } finally {
      setBusy(null);
      if (file.current) file.current.value = "";
    }
  };
  const saveKit = async () => {
    await api.put("/api/brand/kit", { note: kitEdit.note, tagline: kitEdit.tagline, voice: { ...kit.voice, forbidden_words: kitEdit.forbidden.split(",").map((x: string) => x.trim()).filter(Boolean) }, logo: { ...kit.logo, min_width_pct: +kitEdit.logoMin } });
    toast({ tone: "good", title: "New brand kit version saved" });
    setEdit(false);
    b.refetch();
  };
  const openEdit = () => {
    setKitEdit({ note: "Updated from the Brand Brain", tagline: kit.tagline, forbidden: kit.voice.forbidden_words.join(", "), logoMin: kit.logo.min_width_pct });
    setEdit(true);
  };
  return (
    <div>
      <PageHeader eyebrow="CS-01 · Brand kit & Brand Brain" title="Brand Brain" subtitle="The grounding every agent uses: the versioned brand kit, ingested guidelines (embedded with text-embedding-3-small, retrieved with citations) and learnings written back from performance data." actions={<Button variant="outline" onClick={openEdit} disabled={!kit}>Edit kit → new version</Button>} />
      {!d ? <Skeleton h={300} /> : (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4">
            <Stat label="Brand" value={<span className="text-[22px]">{d.name}</span>} hint={d.synthetic ? "fictional sample brand" : undefined} />
            <Stat label="Active kit version" value={`v${d.active_version}`} hint={`${d.versions.length} version(s)`} />
            <Stat label="Indexed passages" value={d.counts.chunks} hint={`${d.counts.documents} document(s)`} />
            <Stat label="Learnings" value={d.counts.learnings} hint="from performance + manual" tone="dawn" />
          </div>
          <div className="grid gap-5 xl:grid-cols-3">
            <Card title="Brand kit" subtitle={`“${kit.tagline}”`} className="xl:col-span-1" testId="brand-kit">
              <div className="flex flex-wrap gap-2">{kit.palette.map((p: any) => <div key={p.hex} className="w-[88px] overflow-hidden rounded-lg border border-cream-300 text-[11px]"><div className="h-10" style={{ background: p.hex }} /><div className="px-1.5 py-1"><b>{p.name}</b><br /><span className="text-espresso-500">{p.hex}</span></div></div>)}</div>
              <dl className="mt-4 space-y-2 text-[13px]">
                <div><dt className="text-[11px] uppercase tracking-wide text-espresso-500">Typography</dt><dd>{kit.typography.display} · {kit.typography.body}</dd></div>
                <div><dt className="text-[11px] uppercase tracking-wide text-espresso-500">Logo</dt><dd>{kit.logo.wordmark} — min. {kit.logo.min_width_pct}% of frame width, clear space {kit.logo.clear_space_ratio}× height</dd></div>
                <div><dt className="text-[11px] uppercase tracking-wide text-espresso-500">Voice</dt><dd className="flex flex-wrap gap-1">{kit.voice.tone.map((t: string) => <Badge key={t}>{t}</Badge>)}</dd></div>
                <div><dt className="text-[11px] uppercase tracking-wide text-espresso-500">Forbidden words</dt><dd className="flex flex-wrap gap-1">{kit.voice.forbidden_words.map((t: string) => <Badge key={t} tone="bad">{t}</Badge>)}</dd></div>
                <div><dt className="text-[11px] uppercase tracking-wide text-espresso-500">Glossary / do-not-translate</dt><dd className="flex flex-wrap gap-1">{kit.voice.glossary.map((g: any) => <Badge key={g.term} tone={g.translate === false ? "dark" : "neutral"}>{g.term}{g.translate === false ? " · DNT" : ""}</Badge>)}</dd></div>
              </dl>
            </Card>
            <Card title="Ask the Brand Brain" subtitle="Semantic search with citations" className="xl:col-span-2">
              <div className="flex gap-2"><div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-espresso-400" /><Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} className="pl-9" aria-label="brand question" /></div><Button variant="accent" icon={<Sparkles className="h-4 w-4" />} loading={busy === "ask"} onClick={ask}>Retrieve</Button></div>
              {!hits && <div className="mt-4"><Empty title="Ask anything about the brand" hint="e.g. “Can we compare ourselves to competitors?” or “What are the logo rules?”" /></div>}
              {hits && (
                <ol className="mt-4 space-y-3" data-testid="brain-hits">
                  {hits.hits.map((h: any, i: number) => (
                    <li key={h.chunk_id} className="rounded-xl border border-cream-300 bg-cream-50 px-4 py-3 text-[13px]">
                      <div className="mb-1 flex items-center gap-2"><Badge tone="dark">[{i + 1}]</Badge><b>{h.title}</b><span className="text-espresso-400">· {h.source}</span><span className="ml-auto tabular-nums text-espresso-400">score {h.score}</span></div>
                      <div className="text-espresso-700">{h.text.slice(0, 380)}{h.text.length > 380 ? "…" : ""}</div>
                    </li>
                  ))}
                  {hits.hits.length === 0 && <li className="text-[13px] text-espresso-500">No passages found.</li>}
                </ol>
              )}
            </Card>
          </div>
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <Card title="Guidelines & documents" subtitle="Markdown, text, PDF or DOCX — scanned for prompt injection before indexing" pad={false}>
              <ul className="divide-y divide-cream-200 text-[13px]">
                {d.documents.map((x: any) => (
                  <li key={x.id} className="flex items-start justify-between gap-3 px-5 py-3"><span><b>{x.name}</b> {x.quarantined && <Badge tone="bad">quarantined</Badge>}<br /><span className="text-espresso-400">{x.chars.toLocaleString()} chars · {x.chunk_count ?? 0} passages · {fmtDate(x.created_at)}</span></span><Button size="sm" variant="ghost" aria-label={`delete ${x.name}`} onClick={async () => { await api.del(`/api/brand/documents/${x.id}`); b.refetch(); }}><Trash2 className="h-3.5 w-3.5" /></Button></li>
                ))}
              </ul>
              <div className="space-y-2 border-t border-cream-200 p-4">
                <input ref={file} type="file" accept=".md,.txt,.pdf,.docx" hidden onChange={(e) => e.target.files?.[0] && ingest(e.target.files[0])} aria-label="guideline file" />
                <Button variant="outline" size="sm" icon={<FilePlus2 className="h-4 w-4" />} loading={busy === "ingest"} onClick={() => file.current?.click()}>Upload a file</Button>
                <Textarea value={paste.text} onChange={(e) => setPaste({ ...paste, text: e.target.value })} placeholder="…or paste guidelines text here" rows={3} aria-label="paste guidelines" />
                <Button size="sm" variant="primary" disabled={paste.text.trim().length < 40} loading={busy === "ingest"} onClick={() => ingest()}>Ingest pasted text</Button>
                <Button size="sm" variant="ghost" onClick={async () => setVoice(await api.post("/api/brand/voice-profile/extract"))}>Extract voice profile (LLM)</Button>
              </div>
              {voice && <div className="border-t border-cream-200 p-4 text-[12.5px]"><b>Suggested voice:</b> {voice.suggested_voice.tone.join(", ")} — {voice.suggested_voice.summary}<div className="mt-1 text-espresso-400">{voice.note}</div></div>}
            </Card>
            <Card title="Learnings" subtitle="Insights written back from performance (CS-18) or entered manually — retrieved by every agent">
              <div className="mb-3 flex gap-2"><Input value={addText} onChange={(e) => setAddText(e.target.value)} placeholder="Add a learning, e.g. ‘Warm kitchen visuals beat street scenes on Meta’" aria-label="new learning" /><Button variant="outline" disabled={addText.length < 8} onClick={async () => { await api.post("/api/brand/learnings", { statement: addText, confidence: 0.6 }); setAddText(""); learn.refetch(); b.refetch(); }}>Add</Button></div>
              <ul className="max-h-80 space-y-2 overflow-auto text-[13px]" data-testid="learnings">
                {(learn.data ?? []).map((l: any) => <li key={l.id} className="rounded-lg bg-cream-100 px-3 py-2">{l.statement}<div className="text-[11.5px] text-espresso-400">{l.source} · confidence {Math.round(l.confidence * 100)}% · {fmtDate(l.created_at)}</div></li>)}
              </ul>
            </Card>
          </div>
          <Card className="mt-5" title="Kit versions" subtitle="Each edit creates a new version; any version can be re-activated" pad={false}>
            <ul className="divide-y divide-cream-200 text-[13px]">
              {d.versions.map((v: any) => (
                <li key={v.version} className="flex items-center justify-between px-5 py-2.5"><span><Badge tone={v.version === d.active_version ? "good" : "neutral"}>v{v.version}{v.version === d.active_version ? " · active" : ""}</Badge> {v.note} <span className="text-espresso-400">· {v.author} · {fmtDate(v.created_at)}</span></span>{v.version !== d.active_version && <Button size="sm" variant="outline" onClick={async () => { await api.post(`/api/brand/versions/${v.version}/activate`); b.refetch(); }}>Activate</Button>}</li>
              ))}
            </ul>
          </Card>
        </>
      )}
      <Modal open={edit} onClose={() => setEdit(false)} title="Edit brand kit (creates a new version)">
        {kitEdit && (
          <div className="space-y-3">
            <Field label="Tagline"><Input value={kitEdit.tagline} onChange={(e) => setKitEdit({ ...kitEdit, tagline: e.target.value })} /></Field>
            <Field label="Forbidden words (comma separated)"><Textarea rows={2} value={kitEdit.forbidden} onChange={(e) => setKitEdit({ ...kitEdit, forbidden: e.target.value })} /></Field>
            <Field label="Logo minimum width (% of frame)"><Input type="number" min={1} max={60} value={kitEdit.logoMin} onChange={(e) => setKitEdit({ ...kitEdit, logoMin: e.target.value })} /></Field>
            <Field label="Version note"><Input value={kitEdit.note} onChange={(e) => setKitEdit({ ...kitEdit, note: e.target.value })} /></Field>
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setEdit(false)}>Cancel</Button><Button variant="accent" onClick={saveKit}>Save as new version</Button></div>
          </div>
        )}
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-01",
  routes: [{ path: "/brand", element: <BrandBrainPage /> }],
  nav: { group: "Brand Brain", label: "Brand Brain", to: "/brand", order: 0, icon: BookOpen },
};
