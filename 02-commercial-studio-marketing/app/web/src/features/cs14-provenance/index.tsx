/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileCheck2, ShieldCheck, ShieldX, Stamp } from "lucide-react";
import { api, withLang } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, KV, Skeleton, Table } from "../../components/ui";
import { msg, useI18n, useOnLangChange } from "../../i18n";

// English constant the API returns verbatim; tKnown() translates it in a non-English UI when the server did not localize it.
const KNOWN_SERVER_TEXT = [
  msg("Illustrative disclosure rules — validate with legal counsel for each market/platform."),
  msg("C2PA-style (hash-based, signed) manifest for demonstration — not a certified C2PA Content Credential."),
];

function Checks({ checks }: { checks: any[] }) {
  const { tEnum } = useI18n();
  return (
    <ul className="space-y-1 text-[13px]">
      {checks.map((c, i) => (
        <li key={i} className="flex items-start gap-2">
          {c.ok ? <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-sage-600" /> : <ShieldX className="mt-0.5 h-4 w-4 shrink-0 text-roast-500" />}
          <span>
            <b>{tEnum("provCheck", c.name, c.name)}</b> <span className="text-espresso-500">{c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function ProvenanceTab({ campaign }: WorkspaceTabProps) {
  const { t, tEnum, tOpen, tKnown } = useI18n();
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
  useOnLangChange(() => {
    if (tamper) test(); // the check details are rendered by the server in the request language
  });
  const m = man.data;
  const a = m?.manifest?.assertions;
  const L = labels.data;
  return (
    <div className="space-y-5">
      <Card title={t("Content credentials")} subtitle={t("Every rendered spot carries a signed, hash-chained provenance manifest (C2PA-style, Ed25519): assets, models and prompt digests, edits, approvals and rights are bound to the file hash. A tampered file or manifest fails verification.")}>
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <Badge tone="good">{t("coverage {pct}%", { pct: sum.data?.coverage ?? "—" })}</Badge>
          <span className="text-espresso-500">{t("signer {name}", { name: sum.data?.signer ?? "…" })}</span>
        </div>
        {sum.isLoading && <Skeleton h={60} />}
        {!sum.isLoading && !videos.length && (
          <div className="mt-3">
            <Empty title={t("No rendered spot yet")} hint={t("Provenance manifests are created when a spot is rendered.")} />
          </div>
        )}
        {videos.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <select
              value={cur}
              onChange={(e) => {
                setAid(e.target.value);
                setTamper(null);
              }}
              className="rounded-lg border border-cream-300 bg-white px-3 py-2 text-[13px]"
              aria-label={t("asset")}
            >
              {videos.map((v) => (
                <option key={v.asset_id} value={v.asset_id}>
                  {v.name} {v.has_manifest ? "✔" : t("(no manifest)")}
                </option>
              ))}
            </select>
            {!m && !man.isLoading && (
              <Button variant="outline" loading={busy} icon={<Stamp className="h-4 w-4" />} onClick={create}>
                {t("Create manifest")}
              </Button>
            )}
            {m && (
              <Button variant="accent" loading={busy} icon={<ShieldCheck className="h-4 w-4" />} onClick={test}>
                {t("Run tamper test")}
              </Button>
            )}
            {m && (
              <a className="text-[13px] text-dawn-700 underline" href={withLang(m.sidecar_url)}>
                {t("sidecar .c2pa.json")}
              </a>
            )}
            {m && (
              <a className="text-[13px] text-dawn-700 underline" href={withLang(`/api/provenance/assets/${cur}/pack`)}>
                {t("provenance pack (.zip)")}
              </a>
            )}
          </div>
        )}
      </Card>
      {m && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title={t("Verification")} actions={<Badge tone={m.verification.ok ? "good" : "bad"}>{m.verification.ok ? t("authentic") : t("FAILED")}</Badge>} testId="verification">
            <Checks checks={m.verification.checks} />
            <div className="mt-3">
              <KV
                rows={[
                  [
                    t("Manifest hash"),
                    <code key="h" className="text-[11.5px]">
                      {m.manifest_hash.slice(0, 28)}…
                    </code>,
                  ],
                  [t("Signature"), t("{alg} · key {id}", { alg: m.signature.alg ?? "Ed25519", id: m.signature.key_id })],
                  [t("Format"), m.manifest.manifest_version],
                ]}
              />
            </div>
          </Card>
          <Card title={t("Manifest summary")}>
            <KV
              rows={[
                [t("Asset"), t("{title} · sha256 {hash}…", { title: m.manifest.title, hash: String(m.manifest.asset.sha256).slice(0, 14) })],
                [t("Generator"), m.manifest.claim_generator],
                [
                  t("AI-generated"),
                  a.ai_disclosure.ai_generated ? (
                    <Badge key="ai" tone="warn">
                      {t("yes — disclosure applied")}
                    </Badge>
                  ) : (
                    t("no")
                  ),
                ],
                [t("Models"), (a.models ?? []).map((x: any) => x.deployment).join(", ") || "—"],
                [t("Ingredients"), a.generative_video ? t("{n} hashed (keyframes, AI clips, voice-over)", { n: (a.ingredients ?? []).length }) : t("{n} hashed (keyframes, voice-over)", { n: (a.ingredients ?? []).length })],
                ...(a.generative_video
                  ? ([[t("Generative video"), t("{model} · licence {license} · {shots}/{total} shots with AI motion", { model: a.generative_video.model ?? "—", license: a.generative_video.license || "—", shots: (a.generative_video.shots ?? []).length, total: a.generative_video.shots_total ?? (a.generative_video.shots ?? []).length })]] as [string, ReactNode][])
                  : []),
                [t("Actions"), t("{n} (created, placed, loudness, music)", { n: (a.actions ?? []).length })],
                [t("Approvals recorded"), `${(a.approvals ?? []).length}`],
                [t("Rights linked"), (a.rights ?? []).map((r: any) => r.title).join(", ") || "—"],
                [t("Audit anchor"), t("chain {chain} #{seq}", { chain: m.manifest.audit_anchor?.chain, seq: String(m.manifest.audit_anchor?.seq) })],
              ]}
            />
            <div className="mt-2 text-[11.5px] text-espresso-400">{tKnown(m.manifest.notice)}</div>
          </Card>
        </div>
      )}
      {tamper && (
        <Card
          title={t("Tamper test")}
          subtitle={t("Verification must FAIL when the manifest or the file is altered")}
          actions={<Badge tone={tamper.tamper_detected ? "good" : "bad"}>{tamper.tamper_detected ? t("tampering detected ✔") : t("NOT detected")}</Badge>}
          testId="tamper-result"
        >
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <div className="mb-1 text-[12px] font-semibold uppercase text-espresso-500">{t("Original")}</div>
              <Checks checks={tamper.result.checks} />
            </div>
            <div>
              <div className="mb-1 text-[12px] font-semibold uppercase text-espresso-500">{t("Edited manifest")}</div>
              <Checks checks={tamper.tamper_manifest.checks} />
            </div>
            <div>
              <div className="mb-1 text-[12px] font-semibold uppercase text-espresso-500">{t("Altered file (1 byte flipped)")}</div>
              <Checks checks={tamper.tamper_asset.checks} />
            </div>
          </div>
        </Card>
      )}
      <Card title={t("Disclosure labels required")} subtitle={t("Per jurisdiction and platform — illustrative; validate with counsel")} actions={<FileCheck2 className="h-4 w-4 text-espresso-400" />}>
        {labels.isLoading || !L ? (
          <Skeleton h={80} />
        ) : (
          <div className="space-y-3 text-[13px]">
            <Table
              head={[t("Jurisdiction / platform"), t("Rule"), t("Label / mechanism")]}
              rows={[
                ...L.jurisdictions.map((j: any) => [
                  <b key={j.code}>{tEnum("jurisdiction", j.code, j.name)}</b>,
                  j.required ? (
                    <Badge key="r" tone="warn">
                      {t("required")}
                    </Badge>
                  ) : (
                    <Badge key="r">{t("advised")}</Badge>
                  ),
                  <span key="b" className="text-espresso-600">
                    {tEnum("jurisdictionBasis", j.code, j.basis)}
                  </span>,
                ]),
                ...L.platforms.map((p: any) => [
                  <b key={p.code}>{p.code}</b>,
                  p.required ? (
                    <Badge key="r" tone="warn">
                      {t("disclose")}
                    </Badge>
                  ) : (
                    <Badge key="r">{t("optional")}</Badge>
                  ),
                  <span key="b" className="text-espresso-600">
                    <b>{tEnum("platformLabel", p.code, p.label)}</b> — {tEnum("platformMechanism", p.code, p.mechanism)}
                  </span>,
                ]),
              ]}
              empty={t("No jurisdiction-specific labels.")}
            />
            <div className="rounded-lg bg-cream-100 px-3 py-2">
              {t("Burned-in badge text:")} <b>{L.badge_text}</b> · {L.burn_in_required ? t("required for these markets") : L.burn_in_advised ? t("advised") : t("not required")} · {t("metadata:")} {L.metadata.map((x: string) => tOpen("labelMetadata", x)).join("; ")}
            </div>
            <div className="text-[11.5px] text-espresso-400">{tKnown(L.notice)}</div>
          </div>
        )}
      </Card>
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-14", workspaceTabs: [{ id: "provenance", label: msg("Provenance"), order: 110, Component: ProvenanceTab }] };
