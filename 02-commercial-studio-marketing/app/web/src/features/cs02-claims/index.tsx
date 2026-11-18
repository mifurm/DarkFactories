/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Pencil, Plus, Scale, Trash2 } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Skeleton, Stat, StatusBadge, Table, Textarea, useToast } from "../../components/ui";
import { LANG_META, matchesQuery, msg, sortByLocale, useI18n, useLocalizedDefault, useOnLangChange, type Lang } from "../../i18n";

const EMPTY = { text: "", type: "prohibited", markets: "*", categories: "*", patterns: "", required_disclaimer: "", substantiation_url: "", alternative: "", severity: "block", notes: "" };
const MARKET_CODES = ["US", "DE", "FR", "PL", "GB"];
const CLAIM_TYPES = ["approved", "prohibited", "needs_substantiation"] as const;

function ClaimsPage() {
  const { t, tEnum, tOpen, fmt, lang, langs } = useI18n();
  const toast = useToast();
  const [type, setType] = useState("");
  const [market, setMarket] = useState("");
  const [qs, setQs] = useState("");
  // Claim packs are per language (each claim carries `lang`): the list follows the UI language until the user picks another one.
  const [pickedLang, setPickedLang] = useState<Lang | "all" | null>(null);
  const claimLang = pickedLang ?? lang;
  const params = new URLSearchParams({ ...(type && { type }), ...(market && { market }) });
  const list = useQuery({ queryKey: ["claims", type, market], queryFn: () => api.get(`/api/claims?${params}`) });
  const all = useQuery({ queryKey: ["claims", "", ""], queryFn: () => api.get("/api/claims") }); // tiles are not affected by the table filters
  const [edit, setEdit] = useState<any>(null);
  const [text, setText] = useLocalizedDefault((i) => i.t("Dawn Roast cures morning anxiety and burns fat. It gives you energy to start the day."));
  const [mk, setMk] = useLocalizedDefault((i) => (i.lang === "pl" ? "PL" : "US"));
  const [res, setRes] = useState<any>(null);
  const inLang = (c: any) => claimLang === "all" || !c.lang || c.lang === claimLang; // a claim without a language tag applies to every language
  const d = list.data;
  // the API orders by (type, raw text): re-sort each type group in the UI language's alphabet (Polish: ł after l, ż after z …)
  const rows: any[] = useMemo(
    () =>
      sortByLocale(lang, (d?.claims ?? []).filter(inLang).filter((c: any) => matchesQuery(`${c.text} ${c.label ?? ""} ${c.notes ?? ""} ${c.notes_label ?? ""} ${c.required_disclaimer ?? ""} ${c.alternative ?? ""}`, qs)), (c: any) => c.label ?? c.text).sort((a: any, b: any) =>
        a.type < b.type ? -1 : a.type > b.type ? 1 : 0,
      ),
    [d, claimLang, qs, lang], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const pool: any[] = useMemo(() => (all.data?.claims ?? []).filter(inLang), [all.data, claimLang]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = (k: string) => pool.filter((c) => c.type === k).length;
  const packs: string[] = useMemo(() => [...new Set<string>(pool.map((c) => c.rule_pack).filter(Boolean))].sort(), [pool]);
  const save = async () => {
    const body = { ...edit, markets: String(edit.markets).split(",").map((x: string) => x.trim()).filter(Boolean), categories: String(edit.categories).split(",").map((x: string) => x.trim()).filter(Boolean), patterns: String(edit.patterns).split("\n").map((x: string) => x.trim()).filter(Boolean), required_disclaimer: edit.required_disclaimer || null, substantiation_url: edit.substantiation_url || null, alternative: edit.alternative || null, lang: edit.lang ?? (claimLang === "all" ? lang : claimLang) };
    delete body.id;
    delete body.pk;
    delete body.brand_id;
    if (edit.id) await api.put(`/api/claims/${edit.id}`, body);
    else await api.post("/api/claims", body);
    toast({ tone: "good", title: t("Claim saved") });
    setEdit(null);
    list.refetch();
    all.refetch();
  };
  const open = (c?: any) => setEdit(c ? { ...c, markets: c.markets.join(", "), categories: c.categories.join(", "), patterns: c.patterns.join("\n"), required_disclaimer: c.required_disclaimer ?? "", substantiation_url: c.substantiation_url ?? "", alternative: c.alternative ?? "" } : { ...EMPTY });
  const check = async () => setRes(await api.post("/api/claims/check", { text, market: [mk], category: "beverage" }));
  useOnLangChange(() => {
    if (res) check(); // the verdict messages are rendered by the server in the request language
  });
  const highlight = (txt: string, hits: any[]) => {
    if (!hits?.length) return txt;
    const spans = hits.filter((h) => h.type !== "approved" || h.required_disclaimer).map((h) => h.span).filter(Boolean);
    if (!spans.length) return txt;
    const esc = spans.map((s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    return txt.split(new RegExp(`(${esc.join("|")})`, "gi")).map((part, i) => (spans.some((s: string) => s.toLowerCase() === part.toLowerCase()) ? <mark key={i} className="rounded bg-roast-500/20 px-0.5 text-roast-600">{part}</mark> : part));
  };
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-02 · Claims & compliance library")}
        title={t("Claims library")}
        subtitle={t("Approved, prohibited and needs-substantiation claims per market and category, with required disclaimers and regulated-category rule packs. The Brand Guardian enforces exactly this list — deterministic rules first.")}
        actions={
          <Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => open()}>
            {t("Add claim")}
          </Button>
        }
      />
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Stat label={t("Approved")} value={all.data ? counts("approved") : "—"} tone="good" />
        <Stat label={t("Prohibited")} value={all.data ? counts("prohibited") : "—"} tone="bad" />
        <Stat label={t("Needs substantiation")} value={all.data ? counts("needs_substantiation") : "—"} tone="dawn" />
        <Stat label={t("Rule packs")} value={all.data ? packs.length : "—"} hint={sortByLocale(lang, packs, (p: string) => tOpen("rulePack", p)).map((p: string) => tOpen("rulePack", p)).join(", ")} />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
        <Card
          title={t("Claims")}
          pad={false}
          actions={
            <div className="flex flex-wrap justify-end gap-2">
              <Select value={claimLang} onChange={(e) => setPickedLang(e.target.value as Lang | "all")} className="w-32" aria-label={t("claim language")} data-testid="claims-lang">
                {langs.map((l) => (
                  <option key={l} value={l} lang={l}>
                    {LANG_META[l].name}
                  </option>
                ))}
                <option value="all">{t("all languages")}</option>
              </Select>
              <Select value={type} onChange={(e) => setType(e.target.value)} className="w-44" aria-label={t("type filter")}>
                <option value="">{t("all types")}</option>
                {CLAIM_TYPES.map((x) => (
                  <option key={x} value={x}>
                    {tEnum("status", x)}
                  </option>
                ))}
              </Select>
              <Select value={market} onChange={(e) => setMarket(e.target.value)} className="w-28" aria-label={t("market filter")}>
                <option value="">{t("any market")}</option>
                {MARKET_CODES.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </Select>
              <Input value={qs} onChange={(e) => setQs(e.target.value)} placeholder={t("search")} className="w-36" aria-label={t("search claims")} />
            </div>
          }
        >
          <div className="p-3" data-testid="claims-table">
            {list.isLoading ? (
              <Skeleton h={200} />
            ) : (
              <Table
                head={[t("Claim"), t("Type"), t("Scope"), t("Disclaimer / alternative"), ""]}
                rows={rows.map((c: any) => [
                  <span key="t">
                    <b>{c.label ?? c.text}</b>
                    {c.label && c.label !== c.text && (
                      <div className="text-[11.5px] text-espresso-400">
                        <Badge>{String(c.lang ?? "en").toUpperCase()}</Badge> {c.text}
                      </div>
                    )}
                    {(c.notes_label ?? c.notes) && <div className="text-[11.5px] text-espresso-400">{c.notes_label ?? c.notes}</div>}
                  </span>,
                  <span key="y" className="whitespace-nowrap">
                    <StatusBadge s={c.type} /> {c.severity === "warn" && <Badge>{tEnum("severity", "warn")}</Badge>}
                  </span>,
                  <span key="s" className="text-[12px] text-espresso-500">
                    {t("{markets} · {categories}", { markets: fmt.codes(c.markets.map((m: string) => tOpen("territory", m))), categories: fmt.codes(c.categories.map((x: string) => tOpen("category", x))) })}
                    {c.rule_pack ? ` · ${tOpen("rulePack", c.rule_pack)}` : ""}
                  </span>,
                  <span key="d" className="text-[12.5px]">
                    {c.required_disclaimer && <div>{t("Must show: “{text}”", { text: c.required_disclaimer })}</div>}
                    {c.alternative && <div className="text-espresso-500">{t("Instead: “{text}”", { text: c.alternative })}</div>}
                  </span>,
                  <span key="a" className="flex gap-1">
                    <Button size="sm" variant="ghost" aria-label={t("edit claim")} onClick={() => open(c)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("delete claim")}
                      onClick={async () => {
                        await api.del(`/api/claims/${c.id}`);
                        list.refetch();
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </span>,
                ])}
              />
            )}
          </div>
        </Card>
        <Card title={t("Claim checker")} subtitle={t("What the Guardian sees in any line of copy")}>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} aria-label={t("text to check")} />
          <div className="mt-2 flex items-center gap-2">
            <Select value={mk} onChange={(e) => setMk(e.target.value)} className="w-28" aria-label={t("market")}>
              {MARKET_CODES.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </Select>
            <Button variant="primary" icon={<Scale className="h-4 w-4" />} onClick={check}>
              {t("Check")}
            </Button>
          </div>
          {res && (
            <div className="mt-4 space-y-3 text-[13px]" data-testid="claim-result">
              <div className="flex items-center gap-2">
                <b>{t("Verdict")}</b>
                <StatusBadge s={res.verdict} />
              </div>
              <div className="rounded-lg bg-cream-100 px-3 py-2 leading-relaxed">{highlight(text, res.hits)}</div>
              <ul className="space-y-1.5">
                {res.hits.map((h: any, i: number) => (
                  <li key={i}>
                    <StatusBadge s={h.type} /> {t("“{text}”", { text: h.span })} → <span className="text-espresso-600">{h.claim}</span>
                    {h.alternative && <div className="text-espresso-500">{t("Suggest: {text}", { text: h.alternative })}</div>}
                  </li>
                ))}
                {res.missing_disclaimers.map((m: string, i: number) => (
                  <li key={`m${i}`} className="text-roast-600">
                    {t("Missing disclaimer: “{text}”", { text: m })}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? t("Edit claim") : t("Add claim")} wide>
        {edit && (
          <div className="grid gap-3 md:grid-cols-2">
            <Field label={t("Claim text")} className="md:col-span-2">
              <Input value={edit.text} onChange={(e) => setEdit({ ...edit, text: e.target.value })} aria-label={t("claim text")} />
            </Field>
            <Field label={t("Type")}>
              <Select value={edit.type} onChange={(e) => setEdit({ ...edit, type: e.target.value })}>
                <option value="approved">{tEnum("status", "approved")}</option>
                <option value="prohibited">{tEnum("status", "prohibited")}</option>
                <option value="needs_substantiation">{tEnum("status", "needs_substantiation")}</option>
              </Select>
            </Field>
            <Field label={t("Severity")}>
              <Select value={edit.severity} onChange={(e) => setEdit({ ...edit, severity: e.target.value })}>
                <option value="block">{tEnum("severity", "block")}</option>
                <option value="warn">{tEnum("severity", "warn")}</option>
              </Select>
            </Field>
            <Field label={t("Markets (comma, * = all)")}>
              <Input value={edit.markets} onChange={(e) => setEdit({ ...edit, markets: e.target.value })} />
            </Field>
            <Field label={t("Categories")}>
              <Input value={edit.categories} onChange={(e) => setEdit({ ...edit, categories: e.target.value })} />
            </Field>
            <Field label={t("Match patterns (one per line; prefix re: for a regex)")} className="md:col-span-2">
              <Textarea rows={3} value={edit.patterns} onChange={(e) => setEdit({ ...edit, patterns: e.target.value })} aria-label={t("patterns")} />
            </Field>
            <Field label={t("Required disclaimer")}>
              <Input value={edit.required_disclaimer} onChange={(e) => setEdit({ ...edit, required_disclaimer: e.target.value })} />
            </Field>
            <Field label={t("Compliant alternative")}>
              <Input value={edit.alternative} onChange={(e) => setEdit({ ...edit, alternative: e.target.value })} />
            </Field>
            <Field label={t("Notes")} className="md:col-span-2">
              <Input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
            </Field>
            <div className="flex justify-end gap-2 md:col-span-2">
              <Button variant="ghost" onClick={() => setEdit(null)}>
                {t("Cancel")}
              </Button>
              <Button variant="accent" disabled={edit.text.length < 3} onClick={save}>
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
  id: "CS-02",
  routes: [{ path: "/claims", element: <ClaimsPage /> }],
  nav: { group: "Brand Brain", label: msg("Claims library"), to: "/claims", order: 10, icon: Scale },
};
