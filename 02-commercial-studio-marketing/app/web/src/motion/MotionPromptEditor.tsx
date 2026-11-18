import { useId, useState } from "react";
import { ApiError } from "../api";
import { Badge, Button, Textarea, useToast } from "../components/ui";
import { useI18n } from "../i18n";
import { MOTION_MAX_PROMPT, readShotMotion } from "./model";
import { saveMotionPrompt } from "./queries";

export interface MotionEditorShot {
  id: string;
  idx?: number;
  motion?: unknown;
  motion_stale?: boolean;
}

/**
 * The shot's motion prompt — what moves after the opening frame. The keyframe is the first frame of the AI clip, so the text describes subject action, camera
 * and ambient movement, never the picture itself. Saving only touches the motion: the keyframe stays valid and the next Cinematic render regenerates this clip.
 */
export function MotionPromptEditor({ campaignId, storyboardId, shot, onSaved }: { campaignId: string; storyboardId: string; shot: MotionEditorShot; onSaved?: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const fieldId = useId();
  const hintId = useId();
  const motion = readShotMotion(shot);
  const saved = motion?.prompt ?? "";
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const value = draft ?? saved;
  const text = value.trim();
  const canSave = draft !== null && draft !== saved && text.length > 0;
  const modelPrompt = motion && motion.prompt_en && motion.prompt_en !== saved ? motion.prompt_en : null; // a non-English campaign: what the (English) model reads
  const save = async () => {
    setSaving(true);
    try {
      await saveMotionPrompt(campaignId, storyboardId, shot.id, text);
      setDraft(null);
      toast({ tone: "good", title: t("Motion prompt saved"), body: t("The keyframe stays; the clip is generated again on the next Cinematic render.") });
      onSaved?.();
    } catch (e) {
      if (!(e instanceof ApiError)) throw e; // an API error is already shown as a toast
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="space-y-1 border-t border-cream-200 pt-2" data-testid={`motion-editor-${shot.id}`}>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={fieldId} className="text-[11px] font-semibold uppercase tracking-wide text-espresso-500">
          {t("Motion · shot {n}", { n: shot.idx ?? shot.id })}
        </label>
        {shot.motion_stale && <Badge tone="warn">{t("motion prompt edited")}</Badge>}
      </div>
      <Textarea
        id={fieldId}
        data-testid="motion-prompt"
        rows={3}
        maxLength={MOTION_MAX_PROMPT}
        value={value}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={t("e.g. She lifts the mug and sips; slow push-in; steam drifts up.")}
        aria-describedby={hintId}
        className="text-[12.5px]"
      />
      <p id={hintId} className="text-[11.5px] text-espresso-400">
        {t("The keyframe is the opening frame. Describe what moves after it: the subject, the camera, steam or light.")}
      </p>
      {modelPrompt && (
        <p className="text-[11.5px] text-espresso-400" data-testid="motion-prompt-en">
          {t("Model prompt (EN):")}{" "}
          <span lang="en" data-user-content>
            {modelPrompt}
          </span>
        </p>
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] tabular-nums text-espresso-400">{t("{count}/{max} characters", { count: value.length, max: MOTION_MAX_PROMPT })}</span>
        <Button size="sm" variant="outline" disabled={!canSave} loading={saving} onClick={save}>
          {t("Save motion")}
        </Button>
      </div>
    </div>
  );
}
