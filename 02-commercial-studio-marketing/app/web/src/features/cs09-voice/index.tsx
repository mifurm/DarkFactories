/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mic2, Music2 } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Select, Skeleton, Table, useToast } from "../../components/ui";
import { mediaUrl, useJobStarter } from "../../components/common";

const LANGS: Record<string, string> = { en: "English", de: "German", fr: "French", es: "Spanish", it: "Italian", pl: "Polish", pt: "Portuguese", nl: "Dutch" };

function AudioTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const toast = useToast();
  const audio = useQuery({ queryKey: ["audio", id], queryFn: () => api.get(`/api/campaigns/${id}/audio`) });
  const voices = useQuery({ queryKey: ["voices"], queryFn: () => api.get("/api/audio/voices"), staleTime: 600000 });
  const music = useQuery({ queryKey: ["music", id], queryFn: () => api.get(`/api/campaigns/${id}/audio/music`) });
  const [lang, setLang] = useState("en");
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState(1);
  const job = useJobStarter(() => {
    audio.refetch();
    reload();
  });
  const v = audio.data?.latest;
  const list = (voices.data?.voices ?? []).filter((x: any) => x.lang === "*" || x.lang === lang);
  const pick = async (rid: string) => {
    await api.post(`/api/campaigns/${id}/audio/music/select`, { rights_id: rid });
    toast({ tone: "good", title: "Licensed track selected" });
    music.refetch();
  };
  return (
    <div className="space-y-5">
      <Card title="Sound Designer" subtitle="Voice-over via Azure OpenAI tts-hd or Azure AI Speech neural voices, timed to each script beat; SRT captions; loudness normalised (EBU R128) at render.">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Language">
            <Select value={lang} onChange={(e) => { setLang(e.target.value); setVoice(""); }} className="w-40" aria-label="language">
              {Object.entries(LANGS).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </Select>
          </Field>
          <Field label="Voice">
            <Select value={voice} onChange={(e) => setVoice(e.target.value)} className="w-64" aria-label="voice">
              <option value="">default for language</option>
              {list.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </Select>
          </Field>
          <Field label={`Speed ×${speed.toFixed(2)}`}>
            <input type="range" min={0.8} max={1.2} step={0.05} value={speed} onChange={(e) => setSpeed(+e.target.value)} className="w-36" aria-label="speed" />
          </Field>
          <Button variant="accent" icon={<Mic2 className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/audio/generate`, { lang, voice: voice || null, speed })}>
            Generate voice-over
          </Button>
        </div>
        {job.node && <div className="mt-3">{job.node}</div>}
      </Card>
      {audio.isLoading && <Skeleton h={160} />}
      {!audio.isLoading && !v && <Empty title="No voice-over yet" hint="Write a script (CS-06) and generate the voice-over." />}
      {v && (
        <Card title={`Voice-over · ${LANGS[v.lang]} · ${v.voice}`} subtitle={`${v.total_vo_seconds}s of speech · $${v.cost_usd}`} actions={v.overflow_lines.length ? <Badge tone="warn">{v.overflow_lines.length} line(s) too long for their beat</Badge> : <Badge tone="good">fits the timeline</Badge>} pad={false}>
          <div className="p-3">
            <Table
              head={["Beat", "Starts", "Length", "Speed", "Line", "Audio"]}
              rows={v.lines.map((l: any) => [<Badge key="b">{l.beat_id}</Badge>, `${l.start}s`, `${l.duration}s`, `×${l.speed}`, l.text, <audio key="a" controls preload="metadata" src={mediaUrl(l.asset_id)} className="h-8" />])}
            />
          </div>
          <div className="border-t border-cream-200 px-5 py-3 text-[12.5px]">
            <b>Captions (SRT)</b> · {v.captions.length} cues, monotonic timing ·{" "}
            <a className="text-dawn-600 underline" href={mediaUrl(v.srt_asset_id, true)}>download .srt</a>
          </div>
        </Card>
      )}
      <Card title="Music bed" subtitle="Only licensed library tracks from the Rights Registry are selectable; the bed is generated procedurally (royalty-free, CC0)." actions={<Music2 className="h-4 w-4 text-espresso-400" />}>
        {music.data?.wanted_mood && <div className="mb-2 text-[12.5px] text-espresso-500">Script mood: <b>{music.data.wanted_mood}</b></div>}
        <div className="grid gap-3 md:grid-cols-2" data-testid="music">
          {(music.data?.candidates ?? []).map((m: any) => (
            <div key={m.rights_id} className={`rounded-xl border px-4 py-3 ${music.data.selected === m.rights_id ? "border-dawn-500 bg-dawn-300/15" : "border-cream-300"}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold">{m.title}</div>
                <Badge tone={m.cleared ? "good" : "bad"}>{m.cleared ? "cleared" : "blocked"}</Badge>
              </div>
              <div className="text-[12px] text-espresso-500">{m.licensor}{m.library_track ? ` · ${m.library_track.mood}, ${m.library_track.bpm} bpm` : ""}</div>
              {m.verdicts.map((vd: any, i: number) => <div key={i} className="mt-1 text-[12px] text-roast-600">{vd.message}</div>)}
              <div className="mt-2 flex items-center gap-2">
                {m.preview_url && <audio controls preload="none" src={m.preview_url} className="h-8 flex-1" />}
                <Button size="sm" variant="outline" disabled={!m.cleared || !m.library_track || music.data.selected === m.rights_id} onClick={() => pick(m.rights_id)}>{music.data.selected === m.rights_id ? "Selected" : "Use"}</Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-09", workspaceTabs: [{ id: "audio", label: "Voice & audio", order: 50, Component: AudioTab }] };
