/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BellRing, FileKey2, Plus, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Skeleton, Stat, StatusBadge, Table, useToast } from "../../components/ui";
import { msg, useI18n, useLocalizedDefault, useOnLangChange } from "../../i18n";

const KINDS = ["music", "talent", "stock", "font", "other"];
const EMPTY = { kind: "music", title: "", licensor: "", status: "active", territories: "WW", channels: "", valid_from: "", valid_to: "", ai_voice_consent: false, ai_likeness_consent: false, usage_notes: "" };

function RightsPage() {
  const { t, tn, tEnum, tOpen, fmt } = useI18n();
  const toast = useToast();
  const [kind, setKind] = useState("");
  const list = useQuery({ queryKey: ["rights", kind], queryFn: () => api.get(`/api/rights${kind ? `?kind=${kind}` : ""}`) });
  const [edit, setEdit] = useState<any>(null);
  const [chk, setChk] = useState<any>({ kind: "music", title: "Sunrise Anthem", channels: "youtube", air_start: "2026-12-01", air_end: "2027-01-31", ai_synthesis: false });
  const [markets, setMarkets] = useLocalizedDefault((i) => (i.lang === "pl" ? "PL" : "US"));
  const [res, setRes] = useState<any>(null);
  const d = list.data;
  const save = async () => {
    const body = { ...edit, territories: edit.territories.split(",").map((x: string) => x.trim().toUpperCase()).filter(Boolean), channels: edit.channels.split(",").map((x: string) => x.trim().toLowerCase()).filter(Boolean), valid_from: edit.valid_from || null, valid_to: edit.valid_to || null, licensor: edit.licensor || null };
    await api.post("/api/rights", body);
    toast({ tone: "good", title: t("Rights entry added") });
    setEdit(null);
    list.refetch();
  };
  const check = async () => setRes(await api.post("/api/rights/check", { kind: chk.kind, title: chk.title, markets: markets.split(",").map((x: string) => x.trim().toUpperCase()), channels: chk.channels.split(",").map((x: string) => x.trim().toLowerCase()).filter(Boolean), air_start: chk.air_start || null, air_end: chk.air_end || null, ai_synthesis: chk.ai_synthesis, usage: chk.kind === "talent" ? "voice" : "use" }));
  useOnLangChange(() => {
    if (res) check(); // clearance messages are rendered by the server in the request language
  });
  const notify = async () => {
    const r = await api.post("/api/rights/alerts/notify?days=45");
    toast({ tone: "good", title: tn(r.notified, { one: "{n} expiry alert(s) sent", other: "{n} expiry alert(s) sent" }), body: t("Delivered to configured webhooks (Teams/Slack).") });
  };
  const titles = (d?.entries ?? []).filter((e: any) => e.kind === chk.kind).map((e: any) => e.title);
  const expiryBadge = (a: any) => (a.state === "expired" ? tn(-a.days_left, { one: "expired {n} d ago", other: "expired {n} d ago" }) : tn(a.days_left, { one: "{n} d left", other: "{n} d left" }));
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-03 · Rights, talent & consent registry")}
        title={t("Rights registry")}
        subtitle={t("Talent likeness and voice consent, licensed music and stock, windows, territories and channel limits. Out-of-rights use is blocked by the Guardian before it reaches approval; expiry alerts go to Teams/Slack.")}
        actions={
          <>
            <Button variant="outline" icon={<BellRing className="h-4 w-4" />} onClick={notify}>
              {t("Send expiry alerts")}
            </Button>
            <Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit({ ...EMPTY })}>
              {t("Add entry")}
            </Button>
          </>
        }
      />
      <div className="mb-5 grid gap-3 md:grid-cols-5">
        {KINDS.map((k) => (
          <button key={k} onClick={() => setKind(kind === k ? "" : k)} className="text-left">
            <Stat label={tEnum("rightsKind", k)} value={d?.counts[k] ?? "—"} tone={kind === k ? "dawn" : undefined} />
          </button>
        ))}
      </div>
      {(d?.alerts ?? []).length > 0 && (
        <Card className="mb-5" title={t("Expiry alerts")} subtitle={t("Within 45 days or already expired")} testId="rights-alerts">
          <ul className="grid gap-2 md:grid-cols-2">
            {d.alerts.map((a: any) => (
              <li key={a.id} className="flex items-center justify-between gap-2 rounded-lg bg-cream-100 px-3 py-2 text-[13px]">
                <span>
                  <b>{a.title}</b> <span className="text-espresso-500">({tEnum("rightsKind", a.kind)})</span>
                </span>
                <Badge tone={a.state === "expired" ? "bad" : "warn"}>{expiryBadge(a)}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <div className="grid gap-5 xl:grid-cols-[1fr_400px]">
        <Card title={t("Registry")} pad={false}>
          <div className="p-3" data-testid="rights-table">
            {list.isLoading ? (
              <Skeleton h={200} />
            ) : (
              <Table
                head={[t("Kind"), t("Title"), t("Status"), t("Territories"), t("Window"), t("AI consent"), ""]}
                rows={(d?.entries ?? []).map((e: any) => [
                  <Badge key="k" tone="dark">
                    {tEnum("rightsKind", e.kind)}
                  </Badge>,
                  <span key="t">
                    <b>{e.title}</b>
                    <div className="text-[11.5px] text-espresso-400">
                      {e.licensor_label ?? e.licensor}
                      {e.library_track ? ` · ${t("library track")}` : ""}
                    </div>
                  </span>,
                  <span key="s" className="flex flex-wrap gap-1">
                    <StatusBadge s={e.expiry?.state ?? e.status} />
                    {e.status === "revoked" && <Badge tone="bad">{tEnum("status", "revoked")}</Badge>}
                  </span>,
                  <span key="r" className="text-[12px]">
                    {(e.territory_labels ?? e.territories.map((x: string) => tOpen("territory", x))).join(", ")}
                    {e.channels.length ? <div className="text-espresso-400">{(e.channel_labels ?? e.channels.map((x: string) => tOpen("channel", x))).join(", ")}</div> : null}
                  </span>,
                  <span key="w" className="whitespace-nowrap text-[12px]">
                    {e.valid_from ? fmt.isoDate(e.valid_from) : "—"} → {e.valid_to ? fmt.isoDate(e.valid_to) : t("open")}
                  </span>,
                  <span key="c" className="text-[12px]">
                    {e.kind === "talent" ? t("voice {voice} · likeness {likeness}", { voice: e.ai_voice_consent ? "✔" : "✘", likeness: e.ai_likeness_consent ? "✔" : "✘" }) : "—"}
                  </span>,
                  e.status !== "revoked" ? (
                    <Button
                      key="x"
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        await api.post(`/api/rights/${e.id}/revoke`);
                        toast({ tone: "warn", title: t("{title} revoked", { title: e.title }) });
                        list.refetch();
                      }}
                    >
                      {t("Revoke")}
                    </Button>
                  ) : null,
                ])}
              />
            )}
          </div>
        </Card>
        <Card title={t("Would this use be cleared?")} subtitle={t("The same check the Guardian runs")} actions={<FileKey2 className="h-4 w-4 text-espresso-400" />}>
          <div className="space-y-2.5">
            <div className="grid grid-cols-2 gap-2">
              <Field label={t("Kind")}>
                <Select value={chk.kind} onChange={(e) => setChk({ ...chk, kind: e.target.value, title: "" })} aria-label={t("kind")}>
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {tEnum("rightsKind", k)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("Title")}>
                <Input list="rights-titles" value={chk.title} onChange={(e) => setChk({ ...chk, title: e.target.value })} aria-label={t("title")} />
                <datalist id="rights-titles">
                  {titles.map((x: string) => (
                    <option key={x} value={x} />
                  ))}
                </datalist>
              </Field>
              <Field label={t("Markets")}>
                <Input value={markets} onChange={(e) => setMarkets(e.target.value)} aria-label={t("markets")} />
              </Field>
              <Field label={t("Channels")}>
                <Input value={chk.channels} onChange={(e) => setChk({ ...chk, channels: e.target.value })} aria-label={t("channels")} />
              </Field>
              <Field label={t("On air from")}>
                <Input type="date" value={chk.air_start} onChange={(e) => setChk({ ...chk, air_start: e.target.value })} />
              </Field>
              <Field label={t("On air to")}>
                <Input type="date" value={chk.air_end} onChange={(e) => setChk({ ...chk, air_end: e.target.value })} />
              </Field>
            </div>
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={chk.ai_synthesis} onChange={(e) => setChk({ ...chk, ai_synthesis: e.target.checked })} /> {t("synthesised (AI voice / likeness)")}
            </label>
            <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} onClick={check}>
              {t("Check clearance")}
            </Button>
          </div>
          {res && (
            <div className="mt-4 space-y-2 text-[13px]" data-testid="rights-result">
              <div className="flex items-center gap-2">
                {res.cleared ? <ShieldCheck className="h-5 w-5 text-sage-600" /> : <ShieldX className="h-5 w-5 text-roast-500" />}
                <b>{res.cleared ? t("Cleared") : t("NOT cleared")}</b>
              </div>
              <ul className="space-y-1">
                {res.verdicts
                  .filter((v: any) => !v.ok)
                  .map((v: any, i: number) => (
                    <li key={i} className="rounded-lg bg-roast-500/10 px-3 py-1.5">
                      <code className="text-[11.5px]">{v.code}</code> — {v.message}
                    </li>
                  ))}
              </ul>
              {res.cleared && (
                <div className="text-espresso-500">
                  {chk.ai_synthesis
                    ? t("{title} — all checks passed (status, territory, window, channel, AI consent).", { title: res.entry?.title })
                    : t("{title} — all checks passed (status, territory, window, channel).", { title: res.entry?.title })}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={t("Add rights entry")} wide>
        {edit && (
          <div className="grid gap-3 md:grid-cols-2">
            <Field label={t("Kind")}>
              <Select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {tEnum("rightsKind", k)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("Title / name")}>
              <Input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} aria-label={t("rights title")} />
            </Field>
            <Field label={t("Licensor")}>
              <Input value={edit.licensor} onChange={(e) => setEdit({ ...edit, licensor: e.target.value })} />
            </Field>
            <Field label={t("Territories (WW or codes)")}>
              <Input value={edit.territories} onChange={(e) => setEdit({ ...edit, territories: e.target.value })} />
            </Field>
            <Field label={t("Valid from")}>
              <Input type="date" value={edit.valid_from} onChange={(e) => setEdit({ ...edit, valid_from: e.target.value })} />
            </Field>
            <Field label={t("Valid to")}>
              <Input type="date" value={edit.valid_to} onChange={(e) => setEdit({ ...edit, valid_to: e.target.value })} />
            </Field>
            <Field label={t("Channels (empty = all)")}>
              <Input value={edit.channels} onChange={(e) => setEdit({ ...edit, channels: e.target.value })} />
            </Field>
            <div className="flex flex-wrap items-end gap-x-4 gap-y-1 pb-2 text-[13px]">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={edit.ai_voice_consent} onChange={(e) => setEdit({ ...edit, ai_voice_consent: e.target.checked })} /> {t("AI voice consent")}
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={edit.ai_likeness_consent} onChange={(e) => setEdit({ ...edit, ai_likeness_consent: e.target.checked })} /> {t("AI likeness consent")}
              </label>
            </div>
            <div className="flex justify-end gap-2 md:col-span-2">
              <Button variant="ghost" onClick={() => setEdit(null)}>
                {t("Cancel")}
              </Button>
              <Button variant="accent" disabled={edit.title.length < 2} onClick={save}>
                {t("Save")}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-03",
  routes: [{ path: "/rights", element: <RightsPage /> }],
  nav: { group: "Brand Brain", label: msg("Rights registry"), to: "/rights", order: 20, icon: FileKey2 },
};
