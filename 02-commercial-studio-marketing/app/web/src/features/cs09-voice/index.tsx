/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mic2, Music2 } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Select, Skeleton, Table, useToast } from "../../components/ui";
import { mediaUrl, useJobStarter } from "../../components/common";
import { msg, sortByLocale, useI18n } from "../../i18n";

const LANG_CODES = ["en", "de", "fr", "es", "it", "pl", "pt", "nl"];
// English constants the API returns verbatim (the built-in music library, the voice catalogue's names); tKnown() translates them in a non-English UI when the server did not localize them.
const KNOWN_SERVER_TEXT = [
  msg("Spotlight Procedural Library (generated, CC0)"),
  msg("Nova — warm, friendly"),
  msg("Shimmer — bright, upbeat"),
  msg("Alloy — neutral, clear"),
  msg("Fable — expressive storyteller"),
  msg("Echo — calm, composed"),
  msg("Onyx — deep, authoritative"),
];

function AudioTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tn, tEnum, tKnown, fmt, lang: ui } = useI18n();
  const id = campaign.campaign.id;
  const toast = useToast();
  const audio = useQuery({ queryKey: ["audio", id], queryFn: () => api.get(`/api/campaigns/${id}/audio`) });
  const voices = useQuery({ queryKey: ["voices"], queryFn: () => api.get("/api/audio/voices"), staleTime: 600000 });
  const music = useQuery({ queryKey: ["music", id], queryFn: () => api.get(`/api/campaigns/${id}/audio/music`) });
  const [lang, setLang] = useState<string>(campaign.campaign.language ?? "en"); // the voice-over follows the language of the campaign's script
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState(1);
  const job = useJobStarter(() => {
    audio.refetch();
    reload();
  });
  const v = audio.data?.latest;
  const list = (voices.data?.voices ?? []).filter((x: any) => x.lang === "*" || x.lang === lang);
  const langName = (code: string) => fmt.languageName(code);
  // the catalogue names carry English descriptors ("Onyx — deep, authoritative", "Zofia (PL neural)"): a server that already localizes them is shown as received,
  // an English catalogue name is translated (descriptors from the dictionary, neural voices composed)
  const voiceName = (x: any): string => {
    if (ui === "en") return x.name;
    const m = /^(.+) \(([A-Z]{2}) neural\)$/.exec(x.name ?? "");
    return m ? t("{name} ({lang}, neural voice)", { name: m[1], lang: m[2] }) : tKnown(x.name);
  };
  const voiceTitle = (id: string): string => {
    const x = (voices.data?.voices ?? []).find((c: any) => c.id === id);
    return ui === "en" || !x ? id : voiceName(x).split(/ — | \(/)[0];
  };
  const langCodes = ui === "en" ? LANG_CODES : sortByLocale(ui, LANG_CODES, langName);
  const pick = async (rid: string) => {
    await api.post(`/api/campaigns/${id}/audio/music/select`, { rights_id: rid });
    toast({ tone: "good", title: t("Licensed track selected") });
    music.refetch();
  };
  return (
    <div className="space-y-5">
      <Card title={t("Sound Designer")} subtitle={t("Voice-over via Azure OpenAI tts-hd or Azure AI Speech neural voices, timed to each script beat; SRT captions; loudness normalised (EBU R128) at render.")}>
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("Language")}>
            <Select
              value={lang}
              onChange={(e) => {
                setLang(e.target.value);
                setVoice("");
              }}
              className="w-44"
              aria-label={t("language")}
            >
              {langCodes.map((c) => (
                <option key={c} value={c}>
                  {langName(c)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("Voice")}>
            <Select value={voice} onChange={(e) => setVoice(e.target.value)} className="w-64" aria-label={t("voice")}>
              <option value="">{t("default for language")}</option>
              {list.map((x: any) => (
                <option key={x.id} value={x.id}>
                  {voiceName(x)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("Speed ×{n}", { n: fmt.fixed(speed, 2) })}>
            <input type="range" min={0.8} max={1.2} step={0.05} value={speed} onChange={(e) => setSpeed(+e.target.value)} className="w-36" aria-label={t("speed")} />
          </Field>
          <Button variant="accent" icon={<Mic2 className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/audio/generate`, { lang, voice: voice || null, speed })}>
            {t("Generate voice-over")}
          </Button>
        </div>
        {job.node && <div className="mt-3">{job.node}</div>}
      </Card>
      {audio.isLoading && <Skeleton h={160} />}
      {!audio.isLoading && !v && <Empty title={t("No voice-over yet")} hint={t("Write a script (CS-06) and generate the voice-over.")} />}
      {v && (
        <Card
          title={t("Voice-over · {lang} · {voice}", { lang: langName(v.lang), voice: voiceTitle(v.voice) })}
          subtitle={t("{n}s of speech · {cost}", { n: v.total_vo_seconds, cost: fmt.usd(v.cost_usd, { min: 0, max: 5 }) })}
          actions={v.overflow_lines.length ? <Badge tone="warn">{tn(v.overflow_lines.length, { one: "{n} line(s) too long for their beat", other: "{n} line(s) too long for their beat" })}</Badge> : <Badge tone="good">{t("fits the timeline")}</Badge>}
          pad={false}
        >
          <div className="p-3">
            <Table
              head={[t("Beat"), t("Starts"), t("Length"), t("Speed"), t("Line"), t("Audio")]}
              rows={v.lines.map((l: any) => [<Badge key="b">{l.beat_id}</Badge>, t("{n}s", { n: l.start }), t("{n}s", { n: l.duration }), t("×{n}", { n: l.speed }), l.text, <audio key="a" controls preload="metadata" src={mediaUrl(l.asset_id)} className="h-8" />])}
            />
          </div>
          <div className="border-t border-cream-200 px-5 py-3 text-[12.5px]">
            <b>{t("Captions (SRT)")}</b> · {tn(v.captions.length, { one: "{n} cues, monotonic timing", other: "{n} cues, monotonic timing" })} ·{" "}
            <a className="text-dawn-600 underline" href={mediaUrl(v.srt_asset_id, true)}>
              {t("download .srt")}
            </a>
          </div>
        </Card>
      )}
      <Card title={t("Music bed")} subtitle={t("Only licensed library tracks from the Rights Registry are selectable; the bed is generated procedurally (royalty-free, CC0).")} actions={<Music2 className="h-4 w-4 text-espresso-400" />}>
        {music.data?.wanted_mood && (
          <div className="mb-2 text-[12.5px] text-espresso-500">
            {t("Script mood:")} <b>{tEnum("musicMood", music.data.wanted_mood)}</b>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2" data-testid="music">
          {(music.data?.candidates ?? []).map((m: any) => (
            <div key={m.rights_id} className={`rounded-xl border px-4 py-3 ${music.data.selected === m.rights_id ? "border-dawn-500 bg-dawn-300/15" : "border-cream-300"}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold">{m.title}</div>
                <Badge tone={m.cleared ? "good" : "bad"}>{m.cleared ? t("cleared") : t("blocked")}</Badge>
              </div>
              <div className="text-[12px] text-espresso-500">
                {m.licensor_label ?? tKnown(m.licensor)}
                {m.library_track ? ` · ${t("{mood}, {bpm} bpm", { mood: tEnum("musicMood", m.library_track.mood), bpm: m.library_track.bpm })}` : ""}
              </div>
              {m.verdicts.map((vd: any, i: number) => (
                <div key={i} className="mt-1 text-[12px] text-roast-600">
                  {vd.message}
                </div>
              ))}
              <div className="mt-2 flex items-center gap-2">
                {m.preview_url && <audio controls preload="none" src={m.preview_url} className="h-8 flex-1" />}
                <Button size="sm" variant="outline" disabled={!m.cleared || !m.library_track || music.data.selected === m.rights_id} onClick={() => pick(m.rights_id)}>
                  {music.data.selected === m.rights_id ? t("Selected") : t("Use")}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-09", workspaceTabs: [{ id: "audio", label: msg("Voice & audio"), order: 50, Component: AudioTab }] };
