/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileCheck2, ShieldCheck, ShieldX, Stamp } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, KV, Skeleton, Table } from "../../components/ui";

function Checks({ checks }: { checks: any[] }) {
  return (
    <ul className="space-y-1 text-[13px]">
      {checks.map((c, i) => (
        <li key={i} className="flex items-start gap-2">
          {c.ok ? <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-sage-600" /> : <ShieldX className="mt-0.5 h-4 w-4 shrink-0 text-roast-500" />}
          <span><b>{c.name}</b> <span className="text-espresso-500">{c.detail}</span></span>
        </li>
      ))}
    </ul>
  );
}

function ProvenanceTab({ campaign }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const markets = (campaign.campaign.markets ?? ["US"]).join(",");
  const channels = (campaign.campaign.channels ?? []).join(",");
  const sum = useQuery({ queryKey: ["prov-sum", id], queryFn: () => api.get(`/api/provenance/campaigns/${id}`) });
  const [aid, setAid] = useState<string>("");
  const videos: any[] = (sum.data?.assets ?? []).filter((a: any) => a.kind === "video");
  const cur = aid || videos.find((v) => v.has_manifest)?.asset_id || videos[0]?.asset_id || "";
  const man = useQuery({ queryKey: ["manifest", cur], enabled: !!cur, queryFn: () => api.get(`/api/provenance/assets/${cur}`, { quiet: true }).catch(() => null) });
  const [tamper, setTamper] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const labels = useQuery({ queryKey: ["prov-labels", markets, channels], queryFn: () => api.get(`/api/provenance/labels?markets=${markets}&channels=${channels}&ai=true`) });
  const create = async () => {
    setBusy(true);
    try {
      await api.post(`/api/provenance/assets/${cur}/manifest`);
      man.refetch();
      sum.refetch();
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    setBusy(true);
    try {
      setTamper(await api.post("/api/provenance/verify", { asset_id: cur, tamper_test: true }));
    } finally {
      setBusy(false);
    }
  };
  const m = man.data;
  const a = m?.manifest?.assertions;
  const L = labels.data;
  return (
    <div className="space-y-5">
      <Card title="Content credentials" subtitle="Every rendered spot carries a signed, hash-chained provenance manifest (C2PA-style, Ed25519): assets, models and prompt digests, edits, approvals and rights are bound to the file hash. A tampered file or manifest fails verification.">
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <Badge tone="good">coverage {sum.data?.coverage ?? "—"}%</Badge>
          <span className="text-espresso-500">signer {sum.data?.signer ?? "…"}</span>
        </div>
        {sum.isLoading && <Skeleton h={60} />}
        {!sum.isLoading && !videos.length && <div className="mt-3"><Empty title="No rendered spot yet" hint="Provenance manifests are created when a spot is rendered." /></div>}
        {videos.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <select value={cur} onChange={(e) => { setAid(e.target.value); setTamper(null); }} className="rounded-lg border border-cream-300 bg-white px-3 py-2 text-[13px]" aria-label="asset">
              {videos.map((v) => <option key={v.asset_id} value={v.asset_id}>{v.name} {v.has_manifest ? "✔" : "(no manifest)"}</option>)}
            </select>
            {!m && !man.isLoading && <Button variant="outline" loading={busy} icon={<Stamp className="h-4 w-4" />} onClick={create}>Create manifest</Button>}
            {m && <Button variant="accent" loading={busy} icon={<ShieldCheck className="h-4 w-4" />} onClick={test}>Run tamper test</Button>}
            {m && <a className="text-[13px] text-dawn-700 underline" href={m.sidecar_url}>sidecar .c2pa.json</a>}
            {m && <a className="text-[13px] text-dawn-700 underline" href={`/api/provenance/assets/${cur}/pack`}>provenance pack (.zip)</a>}
          </div>
        )}
      </Card>
      {m && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Verification" actions={<Badge tone={m.verification.ok ? "good" : "bad"}>{m.verification.ok ? "authentic" : "FAILED"}</Badge>} testId="verification">
            <Checks checks={m.verification.checks} />
            <div className="mt-3">
              <KV rows={[["Manifest hash", <code key="h" className="text-[11.5px]">{m.manifest_hash.slice(0, 28)}…</code>], ["Signature", `${m.signature.alg ?? "Ed25519"} · key ${m.signature.key_id}`], ["Format", m.manifest.manifest_version]]} />
            </div>
          </Card>
          <Card title="Manifest summary">
            <KV
              rows={[
                ["Asset", `${m.manifest.title} · sha256 ${String(m.manifest.asset.sha256).slice(0, 14)}…`],
                ["Generator", m.manifest.claim_generator],
                ["AI-generated", a.ai_disclosure.ai_generated ? <Badge key="ai" tone="warn">yes — disclosure applied</Badge> : "no"],
                ["Models", (a.models ?? []).map((x: any) => x.deployment).join(", ") || "—"],
                ["Ingredients", `${(a.ingredients ?? []).length} hashed (keyframes, voice-over)`],
                ["Actions", `${(a.actions ?? []).length} (created, placed, loudness, music)`],
                ["Approvals recorded", `${(a.approvals ?? []).length}`],
                ["Rights linked", (a.rights ?? []).map((r: any) => r.title).join(", ") || "—"],
                ["Audit anchor", `chain ${m.manifest.audit_anchor?.chain} #${m.manifest.audit_anchor?.seq}`],
              ]}
            />
            <div className="mt-2 text-[11.5px] text-espresso-400">{m.manifest.notice}</div>
          </Card>
        </div>
      )}
      {tamper && (
        <Card title="Tamper test" subtitle="Verification must FAIL when the manifest or the file is altered" actions={<Badge tone={tamper.tamper_detected ? "good" : "bad"}>{tamper.tamper_detected ? "tampering detected ✔" : "NOT detected"}</Badge>} testId="tamper-result">
          <div className="grid gap-4 md:grid-cols-3">
            <div><div className="mb-1 text-[12px] font-semibold uppercase text-espresso-500">Original</div><Checks checks={tamper.result.checks} /></div>
            <div><div className="mb-1 text-[12px] font-semibold uppercase text-espresso-500">Edited manifest</div><Checks checks={tamper.tamper_manifest.checks} /></div>
            <div><div className="mb-1 text-[12px] font-semibold uppercase text-espresso-500">Altered file (1 byte flipped)</div><Checks checks={tamper.tamper_asset.checks} /></div>
          </div>
        </Card>
      )}
      <Card title="Disclosure labels required" subtitle="Per jurisdiction and platform — illustrative; validate with counsel" actions={<FileCheck2 className="h-4 w-4 text-espresso-400" />}>
        {labels.isLoading || !L ? <Skeleton h={80} /> : (
          <div className="space-y-3 text-[13px]">
            <Table head={["Jurisdiction / platform", "Rule", "Label / mechanism"]} rows={[
              ...L.jurisdictions.map((j: any) => [<b key={j.code}>{j.name}</b>, j.required ? <Badge key="r" tone="warn">required</Badge> : <Badge key="r">advised</Badge>, <span key="b" className="text-espresso-600">{j.basis}</span>]),
              ...L.platforms.map((p: any) => [<b key={p.code}>{p.code}</b>, p.required ? <Badge key="r" tone="warn">disclose</Badge> : <Badge key="r">optional</Badge>, <span key="b" className="text-espresso-600"><b>{p.label}</b> — {p.mechanism}</span>]),
            ]} empty="No jurisdiction-specific labels." />
            <div className="rounded-lg bg-cream-100 px-3 py-2">Burned-in badge text: <b>{L.badge_text}</b> · {L.burn_in_required ? "required for these markets" : L.burn_in_advised ? "advised" : "not required"} · metadata: {L.metadata.join("; ")}</div>
            <div className="text-[11.5px] text-espresso-400">{L.notice}</div>
          </div>
        )}
      </Card>
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-14", workspaceTabs: [{ id: "provenance", label: "Provenance", order: 110, Component: ProvenanceTab }] };
