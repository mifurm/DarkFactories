/* eslint-disable @typescript-eslint/no-explicit-any */
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, FilePlus2, Search, Sparkles, Trash2 } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Skeleton, Stat, Textarea, useToast } from "../../components/ui";
import { msg, useI18n, useLocalizedDefault } from "../../i18n";

function BrandBrainPage() {
  const { t, tn, tEnum, fmt } = useI18n();
  const toast = useToast();
  const b = useQuery({ queryKey: ["brand"], queryFn: () => api.get("/api/brand") });
  const learn = useQuery({ queryKey: ["learnings"], queryFn: () => api.get("/api/brand/learnings") });
  const [q, setQ] = useLocalizedDefault((i) => i.t("What is the brand voice and tone?"));
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
      toast({ tone: "good", title: t("{name} ingested", { name: r.name }), body: tn(r.chunks, { one: "{n} passage embedded and indexed", other: "{n} passages embedded and indexed" }) });
      setPaste({ ...paste, text: "" });
      b.refetch();
    } finally {
      setBusy(null);
      if (file.current) file.current.value = "";
    }
  };
  const saveKit = async () => {
    await api.put("/api/brand/kit", { note: kitEdit.note, tagline: kitEdit.tagline, voice: { ...kit.voice, forbidden_words: kitEdit.forbidden.split(",").map((x: string) => x.trim()).filter(Boolean) }, logo: { ...kit.logo, min_width_pct: +kitEdit.logoMin } });
    toast({ tone: "good", title: t("New brand kit version saved") });
    setEdit(false);
    b.refetch();
  };
  const openEdit = () => {
    setKitEdit({ note: t("Updated from the Brand Brain"), tagline: kit.tagline, forbidden: kit.voice.forbidden_words.join(", "), logoMin: kit.logo.min_width_pct });
    setEdit(true);
  };
  const dt = "text-[11px] uppercase tracking-wide text-espresso-500";
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-01 · Brand kit & Brand Brain")}
        title="Brand Brain"
        subtitle={t("The grounding every agent uses: the versioned brand kit, ingested guidelines (embedded with text-embedding-3-small, retrieved with citations) and learnings written back from performance data.")}
        actions={
          <Button variant="outline" onClick={openEdit} disabled={!kit}>
            {t("Edit kit → new version")}
          </Button>
        }
      />
      {!d ? (
        <Skeleton h={300} />
      ) : (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4">
            <Stat label={t("Brand")} value={<span className="text-[22px]">{d.name}</span>} hint={d.synthetic ? t("fictional sample brand") : undefined} />
            <Stat label={t("Active kit version")} value={`v${d.active_version}`} hint={tn(d.versions.length, { one: "{n} version(s)", other: "{n} version(s)" })} />
            <Stat label={t("Indexed passages")} value={fmt.number(d.counts.chunks)} hint={tn(d.counts.documents, { one: "{n} document(s)", other: "{n} document(s)" })} />
            <Stat label={t("Learnings")} value={fmt.number(d.counts.learnings)} hint={t("from performance + manual")} tone="dawn" />
          </div>
          <div className="grid gap-5 xl:grid-cols-3">
            <Card title={t("Brand kit")} subtitle={t("“{text}”", { text: kit.tagline })} className="xl:col-span-1" testId="brand-kit">
              <div className="flex flex-wrap gap-2">
                {kit.palette.map((p: any) => (
                  <div key={p.hex} className="w-[88px] overflow-hidden rounded-lg border border-cream-300 text-[11px]">
                    <div className="h-10" style={{ background: p.hex }} />
                    <div className="px-1.5 py-1">
                      <b>{p.name}</b>
                      <br />
                      <span className="text-espresso-500">{p.hex}</span>
                    </div>
                  </div>
                ))}
              </div>
              <dl className="mt-4 space-y-2 text-[13px]">
                <div>
                  <dt className={dt}>{t("Typography")}</dt>
                  <dd>
                    {kit.typography.display} · {kit.typography.body}
                  </dd>
                </div>
                <div>
                  <dt className={dt}>{t("Logo")}</dt>
                  <dd>{t("{wordmark} — min. {pct}% of frame width, clear space {ratio}× height", { wordmark: kit.logo.wordmark, pct: fmt.number(kit.logo.min_width_pct, 1), ratio: fmt.number(kit.logo.clear_space_ratio, 2) })}</dd>
                </div>
                <div>
                  <dt className={dt}>{t("Voice")}</dt>
                  <dd className="flex flex-wrap gap-1">
                    {kit.voice.tone.map((x: string) => (
                      <Badge key={x}>{x}</Badge>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt className={dt}>{t("Forbidden words")}</dt>
                  <dd className="flex flex-wrap gap-1">
                    {kit.voice.forbidden_words.map((x: string) => (
                      <Badge key={x} tone="bad">
                        {x}
                      </Badge>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt className={dt}>{t("Glossary / do-not-translate")}</dt>
                  <dd className="flex flex-wrap gap-1">
                    {kit.voice.glossary.map((g: any) => (
                      <Badge key={g.term} tone={g.translate === false ? "dark" : "neutral"}>
                        {g.term}
                        {g.translate === false ? " · DNT" : ""}
                      </Badge>
                    ))}
                  </dd>
                </div>
              </dl>
            </Card>
            <Card title={t("Ask the Brand Brain")} subtitle={t("Semantic search with citations")} className="xl:col-span-2">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-espresso-400" />
                  <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} className="pl-9" aria-label={t("brand question")} />
                </div>
                <Button variant="accent" icon={<Sparkles className="h-4 w-4" />} loading={busy === "ask"} onClick={ask}>
                  {t("Retrieve")}
                </Button>
              </div>
              {!hits && (
                <div className="mt-4">
                  <Empty title={t("Ask anything about the brand")} hint={t("e.g. “Can we compare ourselves to competitors?” or “What are the logo rules?”")} />
                </div>
              )}
              {hits && (
                <ol className="mt-4 space-y-3" data-testid="brain-hits">
                  {hits.hits.map((h: any, i: number) => (
                    <li key={h.chunk_id} className="rounded-xl border border-cream-300 bg-cream-50 px-4 py-3 text-[13px]">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <Badge tone="dark">[{i + 1}]</Badge>
                        <b>{h.title}</b>
                        <span className="text-espresso-400">· {h.source}</span>
                        <span className="ml-auto tabular-nums text-espresso-400">{t("score {score}", { score: fmt.number(h.score, 4) })}</span>
                      </div>
                      <div className="text-espresso-700">
                        {h.text.slice(0, 380)}
                        {h.text.length > 380 ? "…" : ""}
                      </div>
                    </li>
                  ))}
                  {hits.hits.length === 0 && <li className="text-[13px] text-espresso-500">{t("No passages found.")}</li>}
                </ol>
              )}
            </Card>
          </div>
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <Card title={t("Guidelines & documents")} subtitle={t("Markdown, text, PDF or DOCX — scanned for prompt injection before indexing")} pad={false}>
              <ul className="divide-y divide-cream-200 text-[13px]">
                {d.documents.map((x: any) => (
                  <li key={x.id} className="flex items-start justify-between gap-3 px-5 py-3">
                    <span className="min-w-0">
                      <b className="break-words">{x.name}</b> {x.lang && <Badge>{String(x.lang).toUpperCase()}</Badge>} {x.quarantined && <Badge tone="bad">{t("quarantined")}</Badge>}
                      <br />
                      <span className="text-espresso-400">
                        {t("{chars} · {passages} · {date}", { chars: tn(x.chars, { one: "{n} char", other: "{n} chars" }), passages: tn(x.chunk_count ?? 0, { one: "{n} passage", other: "{n} passages" }), date: fmt.dateTime(x.created_at) })}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("delete {name}", { name: x.name })}
                      onClick={async () => {
                        await api.del(`/api/brand/documents/${x.id}`);
                        b.refetch();
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
              <div className="space-y-2 border-t border-cream-200 p-4">
                <input ref={file} type="file" accept=".md,.txt,.pdf,.docx" hidden onChange={(e) => e.target.files?.[0] && ingest(e.target.files[0])} aria-label={t("guideline file")} />
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" icon={<FilePlus2 className="h-4 w-4" />} loading={busy === "ingest"} onClick={() => file.current?.click()}>
                    {t("Upload a file")}
                  </Button>
                </div>
                <Textarea value={paste.text} onChange={(e) => setPaste({ ...paste, text: e.target.value })} placeholder={t("…or paste guidelines text here")} rows={3} aria-label={t("paste guidelines")} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="primary" disabled={paste.text.trim().length < 40} loading={busy === "ingest"} onClick={() => ingest()}>
                    {t("Ingest pasted text")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={async () => setVoice(await api.post("/api/brand/voice-profile/extract"))}>
                    {t("Extract voice profile (LLM)")}
                  </Button>
                </div>
              </div>
              {voice && (
                <div className="border-t border-cream-200 p-4 text-[12.5px]">
                  <b>{t("Suggested voice:")}</b> {voice.suggested_voice.tone.join(", ")} — {voice.suggested_voice.summary}
                  <div className="mt-1 text-espresso-400">{voice.note}</div>
                </div>
              )}
            </Card>
            <Card title={t("Learnings")} subtitle={t("Insights written back from performance (CS-18) or entered manually — retrieved by every agent")}>
              <div className="mb-3 flex gap-2">
                <Input value={addText} onChange={(e) => setAddText(e.target.value)} placeholder={t("Add a learning, e.g. ‘Warm kitchen visuals beat street scenes on Meta’")} aria-label={t("new learning")} />
                <Button
                  variant="outline"
                  disabled={addText.length < 8}
                  onClick={async () => {
                    await api.post("/api/brand/learnings", { statement: addText, confidence: 0.6 });
                    setAddText("");
                    learn.refetch();
                    b.refetch();
                  }}
                >
                  {t("Add")}
                </Button>
              </div>
              <ul className="max-h-80 space-y-2 overflow-auto text-[13px]" data-testid="learnings">
                {(learn.data ?? []).map((l: any) => (
                  <li key={l.id} className="rounded-lg bg-cream-100 px-3 py-2">
                    {l.statement}
                    <div className="text-[11.5px] text-espresso-400">{t("{source} · confidence {pct}% · {date}", { source: tEnum("learningSource", l.source), pct: String(Math.round(l.confidence * 100)), date: fmt.dateTime(l.created_at) })}</div>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
          <Card className="mt-5" title={t("Kit versions")} subtitle={t("Each edit creates a new version; any version can be re-activated")} pad={false}>
            <ul className="divide-y divide-cream-200 text-[13px]">
              {d.versions.map((v: any) => (
                <li key={v.version} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <span className="min-w-0">
                    <Badge tone={v.version === d.active_version ? "good" : "neutral"}>
                      v{v.version}
                      {v.version === d.active_version ? ` · ${tEnum("versionState", "active")}` : ""}
                    </Badge>{" "}
                    {v.note}{" "}
                    <span className="text-espresso-400">
                      · {v.author} · {fmt.dateTime(v.created_at)}
                    </span>
                  </span>
                  {v.version !== d.active_version && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        await api.post(`/api/brand/versions/${v.version}/activate`);
                        b.refetch();
                      }}
                    >
                      {t("Activate")}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
      <Modal open={edit} onClose={() => setEdit(false)} title={t("Edit brand kit (creates a new version)")}>
        {kitEdit && (
          <div className="space-y-3">
            <Field label={t("Tagline")}>
              <Input value={kitEdit.tagline} onChange={(e) => setKitEdit({ ...kitEdit, tagline: e.target.value })} />
            </Field>
            <Field label={t("Forbidden words (comma separated)")}>
              <Textarea rows={2} value={kitEdit.forbidden} onChange={(e) => setKitEdit({ ...kitEdit, forbidden: e.target.value })} />
            </Field>
            <Field label={t("Logo minimum width (% of frame)")}>
              <Input type="number" min={1} max={60} value={kitEdit.logoMin} onChange={(e) => setKitEdit({ ...kitEdit, logoMin: e.target.value })} />
            </Field>
            <Field label={t("Version note")}>
              <Input value={kitEdit.note} onChange={(e) => setKitEdit({ ...kitEdit, note: e.target.value })} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEdit(false)}>
                {t("Cancel")}
              </Button>
              <Button variant="accent" onClick={saveKit}>
                {t("Save as new version")}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-01",
  routes: [{ path: "/brand", element: <BrandBrainPage /> }],
  nav: { group: "Brand Brain", label: msg("Brand Brain"), to: "/brand", order: 0, icon: BookOpen },
};
