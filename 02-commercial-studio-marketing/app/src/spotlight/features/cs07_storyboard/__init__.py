"""CS-07 Storyboard & Art Direction agent — shot list, style bible and consistent keyframes via image generation."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.guardian_service import evaluate, subject_from_storyboard, summarize
from ...core.jobs import JobContext
from ...core.studio import campaign_lang
from ...deps import mutate_limit, spend_limit
from ...errors import AppError, NotFound, ValidationFailed
from ...i18n import t
from ...i18n.directive import lang_directive
from ...motion.prompts import camera_phrase, default_motion
from ...registry import Feature
from ...roles import Actor, require
from ...seed.data import PALETTE_PL
from ..common import CREW_PREAMBLE, studio
from ..jobs_util import submit_job

router = APIRouter(prefix="/api/campaigns/{campaign_id}/storyboard", tags=["CS-07 Storyboard"])
MOVES = {"hook": "zoom_in", "product": "pan_right", "proof": "parallax", "cta": "pan_left", "brand": "zoom_out"}
FRAMING = {"hook": "wide establishing shot", "product": "medium close-up", "proof": "macro close-up with shallow depth of field", "cta": "medium shot", "brand": "centered hero shot, calm negative space"}
FRAMING_PL = {"hook": "plan ogólny wprowadzający", "product": "plan półzbliżony", "proof": "makro z płytką głębią ostrości", "cta": "plan średni", "brand": "centralne ujęcie produktu, spokojna wolna przestrzeń"}
PALETTE_NAMES_PL = {name.lower(): pl_name.lower() for name, (pl_name, _role) in PALETTE_PL.items()}  # the colour names used in the Polish Brand Book
FOCAL = {"hook": (0.5, 0.58), "product": (0.45, 0.52), "proof": (0.5, 0.55), "cta": (0.55, 0.55), "brand": (0.5, 0.58)}
MAX_MOTION_CHARS = 280
DIPTYCH_GUARD = "Depict ONE single frame — the opening moment of the shot. Never a collage, split screen, diptych, panels, sequence or text."

# Offline storyboard: (opening frame, what moves — English, what moves — Polish) per role, and per subject for the longer scripts. The camera move is not part of
# the motion text: it is added from the shot's ``movement`` (see ``spotlight.motion.prompts``).
_ROLE_SHOTS: dict[str, tuple[str, str, str]] = {
    "hook": (
        "Pre-dawn kitchen in soft blue-grey light; a ceramic mug stands on the counter beside the kraft Dawn Roast bag.",
        "A hand enters the frame and lifts the mug while the window light slowly warms from blue-grey to amber; a thin curl of steam rises.",
        "Dłoń wchodzi w kadr i unosi kubek, a światło w oknie powoli ciepleje z niebiesko-szarego do bursztynowego; unosi się cienka smużka pary.",
    ),
    "product": (
        "Close-up of the kraft Dawn Roast bag with the amber sun mark, in soft backlight on a kitchen counter.",
        "A hand unrolls the top of the bag; steam and a faint haze of aroma drift upward through the backlight.",
        "Dłoń rozwija górę torby; para i delikatna mgiełka aromatu unoszą się w kontrświetle.",
    ),
    "proof": (
        "A ceramic cup on a wooden counter, golden light across its rim.",
        "Coffee pours slowly into the cup, ripples spread across the surface and steam curls up through a sunbeam.",
        "Kawa powoli wlewa się do filiżanki, po powierzchni rozchodzą się fale, a para wije się w smudze słońca.",
    ),
    "cta": (
        "A person at a kitchen table holds a warm mug in soft morning light, calm expression.",
        "They lift the mug and take a slow sip; their shoulders relax and the light shifts gently across their face.",
        "Unoszą kubek i biorą powolny łyk; barki się rozluźniają, a światło łagodnie przesuwa się po twarzy.",
    ),
    "brand": (
        "Cup and kraft bag on a sunlit windowsill, the amber sun mark glowing.",
        "Steam rises softly from the cup while the sunlight glows a little warmer; the scene stays calm and nearly still.",
        "Z filiżanki łagodnie unosi się para, a światło słońca robi się odrobinę cieplejsze; scena pozostaje spokojna, prawie nieruchoma.",
    ),
}
_SUBJECT_SHOTS: list[tuple[str, tuple[str, str, str]]] = [
    (r"\bbaker\b", ("A dark street at 4:45 a.m. with one lit bakery window and a baker behind the counter.", "The baker ties her apron and turns toward the oven; warm window light flickers softly on the pavement.", "Piekarka zawiązuje fartuch i odwraca się w stronę pieca; ciepłe światło z okna migocze łagodnie na chodniku.")),
    (r"\bnurse\b", ("A nurse sits on a stoop with both hands around a warm cup, the street behind her still quiet.", "She breathes out and lifts the cup; steam drifts past her face while the street slowly wakes behind her.", "Wydycha powietrze i unosi filiżankę; para przesuwa się obok jej twarzy, a za nią powoli budzi się ulica.")),
    (r"\b(?:dad|commuter)\b", ("A commuting dad stands on a porch with a mug in early light.", "He takes a slow sip and glances back toward the door; the morning light warms his face.", "Bierze powolny łyk i spogląda w stronę drzwi; poranne światło ogrzewa jego twarz.")),
    (r"\b(?:beans?|roaster)\b", ("Coffee beans in the roaster window, still green with a hint of gold.", "The beans tumble slowly in the drum, turning from green to gold; warm light pulses on the glass.", "Ziarna powoli przesypują się w bębnie, zmieniając barwę z zielonej na złotą; ciepłe światło pulsuje na szybie.")),
    (r"\bshelf\b", ("A shelf of kraft Dawn Roast bags in a neighbourhood store, soft shop light.", "A hand takes one bag from the shelf; light glints softly on the kraft paper.", "Dłoń zdejmuje jedną torbę z półki; światło delikatnie połyskuje na papierze kraft.")),
    (r"\b(?:city|streetlights?)\b", ("A city before sunrise: streetlights, a parked delivery van and a single lit window.", "The streetlights glow steadily as the sky brightens at the horizon; a delivery van pulls slowly away.", "Latarnie świecą równo, a niebo na horyzoncie rozjaśnia się; furgonetka dostawcza powoli odjeżdża.")),
    (r"\bnotebook\b", ("A table with a notebook and a cup, a patch of sunlight on the wood.", "The sunlight slowly crosses the table; a hand closes the notebook and lifts the cup.", "Światło słoneczne powoli wędruje po stole; dłoń zamyka notes i unosi filiżankę.")),
    (r"\bpour-over\b", ("A pour-over dripper above a glass server, steam backlit.", "Hot water blooms the grounds, which swell and release steam in the backlight.", "Gorąca woda sprawia, że zmielona kawa „rozkwita”, a z niej unosi się para w kontrświetle.")),
]


def stub_shot_plan(role: str, visual_en: str) -> tuple[str, str, str]:
    """(opening frame, motion in English, motion in Polish) for an offline shot: by subject when the scene names one, else by beat role."""
    low = visual_en.lower()
    for pattern, plan in _SUBJECT_SHOTS:
        if re.search(pattern, low):
            return plan
    return _ROLE_SHOTS.get(role, _ROLE_SHOTS["proof"])


def trim_motion(text: str, limit: int = MAX_MOTION_CHARS) -> str:
    """One clean motion sentence of at most ``limit`` characters (cut at a word boundary)."""
    t_ = re.sub(r"\s+", " ", text or "").strip()
    if len(t_) <= limit:
        return t_
    return t_[:limit].rsplit(" ", 1)[0].rstrip(",;: ")


class StyleBible(BaseModel):
    look: str
    lighting: str
    lens: str
    product_description: str
    character_description: str
    palette_notes: str


class ShotOut(BaseModel):
    beat_index: int
    description: str
    framing: str
    movement: str
    image_prompt: str
    focal_x: float
    focal_y: float
    super_text: str
    opening_en: str  # ONE single frame: the first instant of the shot (never a sequence, transition or split screen); English — it feeds the image model and is the first frame of the AI clip
    motion_en: str  # what MOVES during the shot (subject action, camera move, steam / light / dust), <= 280 characters, English, concrete and physically plausible, one action per shot


class ShotOutL10n(ShotOut):
    description_en: str  # the same shot in English: the (English-prompted) image model never sees the campaign language
    framing_en: str
    motion: str  # the same motion in the campaign language (shown to people; the video model reads motion_en)


class StoryboardOut(BaseModel):
    style_bible: StyleBible
    shots: list[ShotOut]


class StoryboardOutL10n(StoryboardOut):
    style_bible_en: StyleBible
    shots: list[ShotOutL10n]  # type: ignore[assignment]


def _bible_pl(pal: str) -> dict[str, str]:
    return {
        "look": "Ciepła, mało kontrastowa fotografia redakcyjna; prawdziwe faktury (para, ceramika, papier kraft); delikatne ziarno filmowe.",
        "lighting": "Niskie, ciepłe światło wschodu słońca z długimi, miękkimi cieniami; para w kontrświetle.",
        "lens": "Ujęcia jak z obiektywów stałoogniskowych 35 mm i 85 mm; płytka głębia ostrości w zbliżeniach.",
        "product_description": "Torba z papieru kraft 340 g z małym bursztynowym znakiem słońca i napisem NORTHWIND (bez innego tekstu), matowe wykończenie.",
        "character_description": "Maja, około trzydziestki, krótkie ciemne włosy, miękki sweter z dzianiny, spokojny wyraz twarzy, poranne światło na twarzy.",
        "palette_notes": f"Paleta: {pal}.",
    }


@stub_task("storyboard.shots")
def _stub_storyboard(ctx: dict[str, Any]) -> dict[str, Any]:
    pal = ctx.get("palette_names", "espresso brown, dawn amber, cream, roast red and sage")
    bible = {
        "look": "Warm, low-contrast editorial photography; real textures (steam, ceramic, kraft paper); gentle film grain.",
        "lighting": "Low, warm sunrise light with long soft shadows; backlit steam.",
        "lens": "35mm and 85mm prime look, shallow depth of field on close-ups.",
        "product_description": "A 12 oz kraft-paper coffee bag with a small amber sun mark and the word NORTHWIND (no other text), matte finish.",
        "character_description": "Maya, mid-30s, short dark hair, soft knit sweater, calm expression, early-morning light on her face.",
        "palette_notes": f"Palette: {pal}.",
    }
    pl = ctx.get("lang") == "pl"
    shots = []
    for i, b in enumerate(ctx.get("beats", []), start=1):
        role = b.get("role", "proof")
        fx, fy = FOCAL.get(role, (0.5, 0.55))
        opening_en, motion_en, motion_pl = stub_shot_plan(role, b.get("visual_en") or b["visual"])
        shot = {"beat_index": i, "description": b["visual"], "framing": FRAMING.get(role, "medium shot"), "movement": MOVES.get(role, "zoom_in"), "image_prompt": b.get("visual_en") or b["visual"], "focal_x": fx, "focal_y": fy, "super_text": b.get("super_text") or "", "opening_en": opening_en, "motion_en": motion_en}
        if pl:
            shot.update(framing=FRAMING_PL.get(role, "plan średni"), description_en=b.get("visual_en") or b["visual"], framing_en=FRAMING.get(role, "medium shot"), motion=motion_pl)
        shots.append(shot)
    if pl:
        return {"style_bible": _bible_pl(ctx.get("palette_names_pl") or pal), "style_bible_en": bible, "shots": shots}
    return {"style_bible": bible, "shots": shots}


def compose_image_prompt(shot: dict[str, Any], bible: dict[str, Any], palette_hex: list[str]) -> str:
    """Consistency by construction: every frame carries the same style bible, product/character descriptions and palette.

    The image model is prompted in English: for non-English campaigns the shot's ``opening_en`` / ``framing_en`` and the English bible are used. The keyframe is the OPENING
    frame of an AI clip, so it is ONE single frame (storyboards written before ``opening_en`` existed fall back to the full English description)."""
    return (
        f"{shot.get('opening_en') or shot.get('description_en') or shot['description']} Framing: {shot.get('framing_en') or shot['framing']}. "
        f"Lighting: {bible['lighting']} Look: {bible['look']} Lens: {bible['lens']} "
        f"Product (when visible): {bible['product_description']} Person (when visible): {bible['character_description']} "
        f"{bible['palette_notes']} Brand colours as hex: {', '.join(palette_hex)}. "
        "Photographic, cinematic 3:2 composition with calm negative space in the lower third for captions. "
        "No text, no logos, no letters, no captions, no watermark, no UI. "
        f"{DIPTYCH_GUARD}"
    )


def prompt_bible(sb: dict[str, Any]) -> dict[str, Any]:
    """The style bible the image model reads (English)."""
    return sb.get("style_bible_en") or sb["style_bible"]


class GenIn(BaseModel):
    script_id: str | None = None


@router.post("/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate_shots(request: Request, campaign_id: str, body: GenIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        script = await (st.artifact(campaign_id, body.script_id, "script") if body and body.script_id else st.latest(campaign_id, "script"))
        if not script:
            raise ValidationFailed("Generate a script first (CS-06).", code="script_missing")
        kit = (await st.brand_kit(camp["brand_id"]))["kit"]
        palette = [p["hex"] for p in kit["palette"]]
        names = ", ".join(f"{p['name'].lower()} {p['hex']}" for p in kit["palette"])
        await job.progress(0.2, step="shots", key="job.msg.shots.start")
        beats = script["beats"]
        lang = campaign_lang(camp)
        pl_names = ", ".join(f"{PALETTE_NAMES_PL.get(p['name'].lower(), p['name'].lower())} {p['hex']}" for p in kit["palette"])
        out = await s.llm.complete(
            task="storyboard.shots",
            system=CREW_PREAMBLE + " You are the Art Director. Produce a style bible (look, lighting, lens, product and character descriptions that stay IDENTICAL across all frames, palette notes) and exactly one shot per script beat, in order. Each shot has a concrete description, framing, camera movement (zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down|parallax), an image prompt for a text-free photographic keyframe, and a focal point (0..1) where the subject sits so reframing to 9:16/1:1 keeps it in view."
            " Every shot becomes a short AI-generated video clip whose FIRST frame is the approved keyframe, so also write for each shot: opening_en = ONE single frame, the first instant of the shot as a still photograph (what is in the frame at second zero: subject, setting, light; NEVER a sequence, a transition, a split screen, a collage, panels, 'then…' or 'the frame tightens'); "
            "motion_en = what MOVES during the shot (the subject's action, the camera move, ambient steam / light / dust), at most 280 characters, English, concrete, physically plausible, ONE action per shot, no cuts and no text."
            + (lang_directive(lang) + " Write the style_bible and every shot's description, framing and motion in the output language; ALSO fill style_bible_en, description_en and framing_en with the same content in English and write image_prompt, opening_en and motion_en in English — they feed English-prompted image and video models." if lang != "en" else ""),
            user=f"Brand palette: {names}\nBrand look: warm sunrise light, real textures, product = kraft bag with amber sun mark.\nScript ({script['duration_s']}s) beats:\n" + "\n".join(f"{i + 1}. [{b['role']} {b['t_start']}-{b['t_end']}s] visual: {b['visual']}{' (EN: ' + b['visual_en'] + ')' if b.get('visual_en') else ''} | super: {b.get('super_text') or '-'}" for i, b in enumerate(beats)),
            schema=StoryboardOut if lang == "en" else StoryboardOutL10n,
            context={"beats": beats, "palette_names": names, "palette_names_pl": pl_names, "lang": lang},
            max_tokens=4200 if lang == "en" else 6000,
            effort="low",
        )
        bible = out.style_bible.model_dump()
        bible_en = out.style_bible_en.model_dump() if isinstance(out, StoryboardOutL10n) else None
        shots = []
        for i, b in enumerate(beats):
            raw = out.shots[i] if i < len(out.shots) else None
            role = b.get("role", "proof")
            fx, fy = FOCAL.get(role, (0.5, 0.55))
            sh = {
                "id": f"s{i + 1}",
                "idx": i + 1,
                "beat_id": b["id"],
                "role": role,
                "duration": round(b["t_end"] - b["t_start"], 2),
                "description": (raw.description if raw else b["visual"]),
                "framing": (raw.framing if raw else (FRAMING_PL if lang == "pl" else FRAMING).get(role, "medium shot")),
                "movement": (raw.movement if raw and raw.movement in {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "parallax"} else MOVES.get(role, "zoom_in")),
                "focal": [min(1, max(0, raw.focal_x)) if raw else fx, min(1, max(0, raw.focal_y)) if raw else fy],
                "super_text": (raw.super_text if raw else b.get("super_text") or "") or None,
                "asset_id": None,
                "image_status": "pending",
            }
            if lang != "en":  # display text in the campaign language, the image model reads the English twins
                sh["description_en"] = (getattr(raw, "description_en", None) if raw else None) or b.get("visual_en") or b["visual"]
                sh["framing_en"] = (getattr(raw, "framing_en", None) if raw else None) or FRAMING.get(role, "medium shot")
            sh["opening_en"] = re.sub(r"\s+", " ", (getattr(raw, "opening_en", None) if raw else None) or sh.get("description_en") or sh["description"]).strip()  # ONE frame; older / failed outputs fall back to the description
            motion_en = trim_motion((getattr(raw, "motion_en", None) if raw else None) or default_motion(role))
            sh["motion"] = {"prompt_en": motion_en, "prompt": trim_motion((getattr(raw, "motion", None) if raw and lang != "en" else None) or motion_en), "camera": camera_phrase(sh["movement"])}
            sh["image_prompt"] = compose_image_prompt(sh, bible_en or bible, palette)
            shots.append(sh)
        title = t("artifact.title.storyboard", lang, d=script["duration_s"])
        art = await st.create_artifact(campaign_id, "storyboard", {"title": title, "lang": lang, "script_id": script["id"], "duration_s": script["duration_s"], "style_bible": bible, **({"style_bible_en": bible_en} if bible_en else {}), "shots": shots}, actor=actor)
        camp["selected_script_id"] = script["id"]
        await st.save_campaign(camp)
        await st.set_stage(campaign_id, "storyboard")
        await st.audit(campaign_id, actor, "storyboard.shots_generated", {"artifact_id": art["id"]}, {"shots": len(shots)})
        return {"artifact_id": art["id"], "shots": len(shots)}

    return await submit_job(request, "storyboard.shots", run, campaign_id, "job.title.shots", "CS-07", wait)


@router.get("")
async def get_storyboard(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    arts = await st.artifacts(campaign_id, "storyboard")
    return {"latest": arts[0] if arts else None, "versions": [{"id": a["id"], "version": a["version"], "created_at": a["created_at"], "status": a["status"], "script_id": a.get("script_id")} for a in arts]}


class FramesIn(BaseModel):
    quality: str = Field(default="low", pattern="^(low|medium|high)$")
    shots: list[str] | None = None
    model: str = Field(default="image", pattern="^(image|image_draft)$")
    anchor: bool = False


async def _frames(request: Request, campaign_id: str, sb_id: str, body: FramesIn, actor: Actor, job: JobContext) -> dict[str, Any]:
    s = request.app.state.services
    st = studio(request)
    camp = await st.campaign(campaign_id)
    sb = await st.artifact(campaign_id, sb_id, "storyboard")
    kit = (await st.brand_kit(camp["brand_id"]))["kit"]
    palette = [p["hex"] for p in kit["palette"]]
    todo = [sh for sh in sb["shots"] if not body.shots or sh["id"] in body.shots]
    done = 0
    cost = 0.0
    errors: list[str] = []
    sem = asyncio.Semaphore(3)
    anchor_bytes: list[bytes] | None = None

    async def one(sh: dict[str, Any], refs: list[bytes] | None) -> None:
        nonlocal done, cost
        async with sem:
            try:
                res = await s.image.generate(sh["image_prompt"], size="1536x1024", quality=body.quality, model_role=body.model, references=refs, palette=palette, seed=int(hashlib.sha256(sh["id"].encode()).hexdigest()[:6], 16))
            except AppError as exc:
                if exc.code in {"daily_budget_exceeded", "campaign_budget_exceeded", "premium_requires_approval"}:
                    raise
                msg = exc.localized()[0]  # rendered in the request language (the stored text is shown as is)
                sh["image_status"], sh["image_error"] = "failed", msg
                errors.append(f"{sh['id']}: {msg}")
                return
            except Exception as exc:
                sh["image_status"], sh["image_error"] = "failed", f"{type(exc).__name__}: {str(exc)[:160]}"
                errors.append(f"{sh['id']}: {type(exc).__name__}")
                return
            asset = await st.put_asset(
                campaign_id=campaign_id, name=f"{sb['id']}-{sh['id']}.{'png' if res.mime == 'image/png' else 'jpg'}", data=res.data, mime=res.mime, kind="image", actor=actor,
                tags=["storyboard", sh["role"], "ai-generated"], description=sh["description"], meta={"prompt": sh["image_prompt"], "shot_id": sh["id"], "model": res.model, "quality": res.quality, "size": res.size, "cached": res.cached, "cost_usd": res.cost_usd, "storyboard_id": sb["id"]},
            )
            sh.update(asset_id=asset["id"], image_status="ready", image_error=None, image_model=res.model, image_quality=res.quality, cost_usd=res.cost_usd)
            cost += res.cost_usd
            done += 1
            await job.progress(0.1 + 0.7 * done / len(todo), step=f"frame-{sh['id']}", key="job.msg.frames.frame", params={"done": done, "total": len(todo)})

    await job.progress(0.05, step="frames", key="job.msg.frames.start", params={"total": len(todo), "model": body.model, "quality": body.quality})
    if body.anchor and len(todo) > 1:
        await one(todo[0], None)
        if todo[0].get("asset_id"):
            anchor_bytes = [await st.asset_bytes(await st.asset(todo[0]["asset_id"], campaign_id))]
        await asyncio.gather(*(one(sh, anchor_bytes) for sh in todo[1:]))
    else:
        await asyncio.gather(*(one(sh, None) for sh in todo))
    sb["frames_quality"] = body.quality
    await st.save_artifact(sb)
    await job.progress(0.85, step="guardian", key="job.msg.frames.guardian")
    subject, images = await subject_from_storyboard(st, camp, sb)
    report, _ = await evaluate(s, subject, image_bytes=images)
    sb["guardian"] = summarize(report)
    sb["status"] = "draft"
    await st.save_artifact(sb)
    await st.audit(campaign_id, actor, "storyboard.frames_generated", {"artifact_id": sb["id"]}, {"frames": done, "cost_usd": round(cost, 4), "quality": body.quality})
    if done == 0 and errors:
        raise AppError("No keyframes could be generated: " + "; ".join(errors[:2]), code="image_failed", status=502, params={"errors": "; ".join(errors[:2])})
    return {"artifact_id": sb["id"], "frames": done, "failed": len(errors), "cost_usd": round(cost, 4), "guardian": sb["guardian"]}


@router.post("/{sb_id}/frames", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate_frames(request: Request, campaign_id: str, sb_id: str, body: FramesIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or FramesIn()
    await studio(request).artifact(campaign_id, sb_id, "storyboard")

    async def run(job: JobContext) -> dict[str, Any]:
        return await _frames(request, campaign_id, sb_id, body, actor, job)

    return await submit_job(request, "storyboard.frames", run, campaign_id, "job.title.frames", "CS-07", wait, timeout=175, title_params={"quality": body.quality})


class ShotPatch(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    movement: str | None = Field(default=None, pattern="^(zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down|parallax)$")
    focal: list[float] | None = Field(default=None, min_length=2, max_length=2)
    super_text: str | None = Field(default=None, max_length=80)
    prompt_tweak: str | None = Field(default=None, max_length=300)
    motion: str | None = Field(default=None, max_length=300)  # what moves during the shot (the AI-video prompt); editing it never invalidates the keyframe


@router.patch("/{sb_id}/shots/{shot_id}", dependencies=[Depends(mutate_limit)])
async def patch_shot(request: Request, campaign_id: str, sb_id: str, shot_id: str, body: ShotPatch, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    sb = await st.artifact(campaign_id, sb_id, "storyboard")
    sh = next((x for x in sb["shots"] if x["id"] == shot_id), None)
    if sh is None:
        raise NotFound("shot not found", code="shot_not_found")
    camp = await st.campaign(campaign_id)
    kit = (await st.brand_kit(camp["brand_id"]))["kit"]
    if body.description is not None:
        sh["description"] = body.description
        if "description_en" in sh:
            sh["description_en"] = body.description  # a hand-edited line is the best English-prompt we have for the model
        if "opening_en" in sh:
            sh["opening_en"] = body.description  # the keyframe is drawn from the opening frame: an edited description has to reach it
        lang = campaign_lang(camp)
        if lang == "en":
            sh.pop("opening_edited_lang", None)
        else:
            sh["opening_edited_lang"] = lang  # the image model took the edit; the English-only video model leaves such an opening line out of its prompt (motion.prompts.opening_text)
    if body.movement:
        sh["movement"] = body.movement
        if isinstance(sh.get("motion"), dict):
            sh["motion"]["camera"] = camera_phrase(body.movement)
        sh["motion_stale"] = True  # the camera phrase is part of the clip's prompt
    if body.motion is not None:
        m = sh["motion"] if isinstance(sh.get("motion"), dict) else sh.setdefault("motion", {})
        text = trim_motion(body.motion, 300)
        m["prompt"], m["edited"] = text, True  # `prompt` is what people read (in the campaign's language)
        if campaign_lang(camp) == "en":
            m["prompt_en"] = text  # an English hand-edit is the best English prompt we have for the video model (the convention of description_en)
            sh["motion_stale"] = True  # the clip has to be generated again; the keyframe stays valid
        # Another language: the video model only reads English, so a hand-edited line changes the text shown to people and nothing the model gets: `prompt_en` stays the last
        # machine-generated English prompt and the clip stays valid (same prompt, same seed, same cached clip).
        m["camera"] = m.get("camera") or camera_phrase(sh.get("movement"))
    if body.focal:
        sh["focal"] = [min(1, max(0, v)) for v in body.focal]
    if body.super_text is not None:
        sh["super_text"] = body.super_text or None
    sh["image_prompt"] = compose_image_prompt(sh, prompt_bible(sb), [p["hex"] for p in kit["palette"]]) + (f" Art direction note: {body.prompt_tweak}" if body.prompt_tweak else "")
    if body.description is not None or body.prompt_tweak:
        sh["image_status"] = "stale"
    sb["status"] = "draft"
    await st.save_artifact(sb)
    await st.audit(campaign_id, actor, "storyboard.shot_edited", {"artifact_id": sb_id, "shot": shot_id})
    return sh


FEATURE = Feature(id="CS-07", summary="Shot list + style bible and storyboard keyframes via gpt-image with consistency by construction (style bible, palette conditioning, optional reference anchor).", router=router)
