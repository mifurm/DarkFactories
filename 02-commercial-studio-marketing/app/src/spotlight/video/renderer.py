"""The spot compositor: Ken-Burns / parallax motion on generated keyframes, dissolves, burned-in captions + SRT, supers,
logo bug, AI-disclosure badge, brand end card, voice-over + procedural music bed, EBU R128 loudness, H.264/AAC MP4.

Frames are composed with Pillow/numpy and piped to ffmpeg (libx264). Audio is mixed in numpy and normalised with
ffmpeg's two-pass loudnorm. CPU-heavy work belongs in the render worker subprocess (see worker.py / provider.py).
"""

from __future__ import annotations

import io
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageFilter

from . import media, overlays
from .music import generate_track
from .spec import Cue, RenderSpec, to_srt

TD = 0.42  # cross-dissolve length (seconds), centred on scene boundaries
ProgressFn = Callable[[float, str], None]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _ease(p: float) -> float:
    p = _clamp(p, 0.0, 1.0)
    return p * p * (3 - 2 * p)


def cover_box(sw: int, sh: int, w: int, h: int, zoom: float, cx: float, cy: float) -> tuple[float, float, float, float]:
    """Crop box (source pixels) that covers the w:h frame at the given zoom, centred on (cx, cy) in 0..1, kept inside the image."""
    target, src = w / h, sw / sh
    if src >= target:
        ch = float(sh)
        cw = ch * target
    else:
        cw = float(sw)
        ch = cw / target
    cw, ch = cw / zoom, ch / zoom
    x0 = _clamp(cx * sw - cw / 2, 0, sw - cw)
    y0 = _clamp(cy * sh - ch / 2, 0, sh - ch)
    return x0, y0, x0 + cw, y0 + ch


def motion_params(motion: str, focal: tuple[float, float], p: float) -> tuple[float, float, float]:
    fx, fy = focal
    e = _ease(p)
    if motion == "zoom_in":
        return 1.0 + 0.13 * e, fx, fy
    if motion == "zoom_out":
        return 1.13 - 0.13 * e, fx, fy
    if motion == "pan_left":
        return 1.12, fx + 0.07 * (1 - 2 * e), fy
    if motion == "pan_right":
        return 1.12, fx + 0.07 * (2 * e - 1), fy
    if motion == "pan_up":
        return 1.12, fx, fy + 0.07 * (1 - 2 * e)
    if motion == "pan_down":
        return 1.12, fx, fy + 0.07 * (2 * e - 1)
    return 1.1, fx, fy


class SceneRenderer:
    def __init__(self, img: Image.Image, motion: str, focal: tuple[float, float], w: int, h: int) -> None:
        # keep a working copy ~1.6x the frame so crops stay sharp without excess memory
        scale = max(1.6 * w / img.width, 1.6 * h / img.height)
        if scale < 1:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        self.img = img
        self.motion, self.focal, self.w, self.h = motion, focal, w, h
        self.blur: Image.Image | None = None
        self.mask: Image.Image | None = None

    def _crop(self, im: Image.Image, zoom: float, cx: float, cy: float) -> Image.Image:
        box = cover_box(im.width, im.height, self.w, self.h, zoom, cx, cy)
        return im.resize((self.w, self.h), Image.BILINEAR, box=box)

    def frame(self, p: float) -> Image.Image:
        p = _clamp(p, 0.0, 1.0)
        if self.motion == "parallax":
            if self.blur is None:
                small = self.img.resize((max(8, self.img.width // 6), max(8, self.img.height // 6)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3))
                self.blur = small.resize(self.img.size, Image.BILINEAR)
                m = Image.new("L", (self.w, self.h), 0)
                yy, xx = np.mgrid[0 : self.h, 0 : self.w].astype(np.float32)
                d = np.sqrt(((xx - self.w * 0.5) / (self.w * 0.46)) ** 2 + ((yy - self.h * 0.55) / (self.h * 0.5)) ** 2)
                m = Image.fromarray((np.clip(1.25 - d, 0, 1) ** 0.8 * 255).astype(np.uint8), "L")
                self.mask = m.filter(ImageFilter.GaussianBlur(self.w * 0.02))
            e = _ease(p)
            fx, fy = self.focal
            bg = self._crop(self.blur, 1.22 + 0.04 * e, fx + 0.03 * (1 - 2 * e), fy)
            fg = self._crop(self.img, 1.03 + 0.11 * e, fx - 0.03 * (1 - 2 * e), fy)
            assert self.mask is not None
            return Image.composite(fg, bg, self.mask)
        z, cx, cy = motion_params(self.motion, self.focal, p)
        return self._crop(self.img, z, cx, cy)


def _blit(frame: np.ndarray, ov: np.ndarray, x: int, y: int, opacity: float = 1.0) -> None:
    h, w = frame.shape[:2]
    oh, ow = ov.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + ow), min(h, y + oh)
    if x1 <= x0 or y1 <= y0 or opacity <= 0:
        return
    sub = ov[y0 - y : y1 - y, x0 - x : x1 - x]
    a = (sub[..., 3:4].astype(np.float32) / 255.0) * opacity
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (sub[..., :3].astype(np.float32) * a + region * (1 - a)).astype(np.uint8)


def prepare_audio(spec: RenderSpec, vo_audio: dict[str, bytes], work: Path) -> tuple[Path, dict[str, Any]]:
    total = spec.duration
    segs: list[tuple[float, np.ndarray]] = []
    for line in spec.vo:
        data = vo_audio.get(line.id)
        if data:
            segs.append((line.start, media.decode_audio(data)))
    music = None
    ms = spec.music
    if ms is not None:
        music = generate_track(ms.mood, ms.bpm, ms.key, ms.seed, total + 1.0)
    mix, _ = media.mix_timeline(segs, music, total, ms.gain_db if ms else -19.0, ms.duck_db if ms else -11.0, ms.fade_in if ms else 0.5, ms.fade_out if ms else 1.4)
    raw, final = work / "mix.wav", work / "final.wav"
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.98:
        mix = mix / peak * 0.98
    media.write_wav(raw, mix)
    stats = media.loudnorm_two_pass(raw, final, spec.loudness_lufs, spec.true_peak_db)
    return final, stats


def render(
    spec: RenderSpec,
    scene_images: dict[str, bytes],
    vo_audio: dict[str, bytes],
    out_dir: Path,
    progress: ProgressFn | None = None,
    timeout: float = 420.0,
) -> dict[str, Any]:
    t_start = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    W, H = spec.size
    fps = spec.fps
    notify = progress or (lambda p, m: None)
    notify(0.01, "Preparing keyframes")
    missing = [s.asset_id for s in spec.scenes if not s.asset_id or s.asset_id not in scene_images]
    if missing:
        raise media.MediaError(f"missing keyframe images for scenes: {missing}")
    renderers: list[SceneRenderer] = []
    for s in spec.scenes:
        im = Image.open(io.BytesIO(scene_images[s.asset_id or ""])).convert("RGB")
        renderers.append(SceneRenderer(im, s.motion, s.focal, W, H))
    starts = spec.scene_starts()
    t_scenes = sum(s.duration for s in spec.scenes)
    duration = spec.duration
    n_frames = round(duration * fps)

    notify(0.04, "Mixing voice-over + music, normalising loudness (EBU R128)")
    final_wav, lstats = prepare_audio(spec, vo_audio, out_dir)

    # pre-rendered overlays (cached per run)
    vign = overlays.vignette(W, H)
    brand = spec.brand
    logo_w = int(W * (0.15 if W >= H else 0.26))
    logo_ov = overlays.to_np(overlays.draw_logo(logo_w, brand.wordmark, brand.sub))
    safe = overlays.SAFE_AREAS[spec.aspect]
    logo_xy = (int(W * (1 - safe["right"]) - logo_w), int(H * safe["top"]))
    badge = overlays.render_label(spec.disclosure_badge, W, H, spec.aspect, "tl") if spec.disclosure_badge else None
    cap_cache: dict[str, tuple[np.ndarray, int, int]] = {}
    super_cache: dict[int, tuple[np.ndarray, int, int]] = {}
    legal_ov = overlays.render_legal(spec.legal_supers, W, H, spec.aspect) if spec.legal_supers else None
    endcard_img = overlays.render_endcard(spec, W, H) if spec.endcard else None
    warm = Image.new("RGB", (W, H), (201, 138, 75))
    cues = sorted(spec.captions, key=lambda c: c.start) if spec.captions_burned else []
    poster: bytes | None = None
    poster_n = int(min(1.8, duration * 0.3) * fps)

    def scene_at(t: float) -> int:
        idx = 0
        for i, s0 in enumerate(starts):
            if t >= s0:
                idx = i
        return idx

    def scene_img(i: int, t: float) -> Image.Image:
        p = (t - starts[i]) / spec.scenes[i].duration
        fr = renderers[i].frame(p)
        fr = ImageChops.multiply(fr, vign)
        if spec.grade_strength > 0:
            fr = Image.blend(fr, ImageChops.multiply(fr, warm), min(0.6, spec.grade_strength))
        return fr

    def compose(t: float) -> Image.Image:
        if t >= t_scenes and endcard_img is not None:
            if t < t_scenes + TD / 2:
                a = _ease((t - (t_scenes - TD / 2)) / TD)
                return Image.blend(scene_img(len(spec.scenes) - 1, min(t, t_scenes - 1e-3)), endcard_img, a)
            return endcard_img
        i = scene_at(t)
        base = scene_img(i, t)
        # symmetric cross-dissolve around the next boundary / previous boundary
        if i + 1 < len(spec.scenes) and t > starts[i + 1] - TD / 2:
            a = _ease((t - (starts[i + 1] - TD / 2)) / TD)
            return Image.blend(base, scene_img(i + 1, t), a)
        if i > 0 and t < starts[i] + TD / 2:
            a = _ease((t - (starts[i] - TD / 2)) / TD)
            return Image.blend(scene_img(i - 1, t), base, a)
        if i == len(spec.scenes) - 1 and endcard_img is not None and t > t_scenes - TD / 2:
            return Image.blend(base, endcard_img, _ease((t - (t_scenes - TD / 2)) / TD))
        return base

    cmd = [
        media.FFMPEG, "-y", "-v", "error", "-nostats",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
        "-i", str(final_wav), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{duration:.3f}", str(out_dir / "video.mp4"),
    ]  # fmt: skip
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for n in range(n_frames):
            t = n / fps
            if time.monotonic() - t_start > timeout:
                raise media.MediaError(f"render exceeded {timeout:.0f}s timeout")
            frame_img = compose(min(t, duration - 1e-3))
            arr = np.array(frame_img, dtype=np.uint8)
            in_scenes = t < t_scenes
            i = scene_at(t) if in_scenes else len(spec.scenes) - 1
            sc = spec.scenes[i]
            if in_scenes:
                if sc.super_text:
                    if i not in super_cache:
                        ov, x, y = overlays.render_super(sc.super_text, W, H, spec.aspect, brand.palette[1], brand.palette[2])
                        super_cache[i] = (ov, x, y)
                    ov, x, y = super_cache[i]
                    local = t - starts[i]
                    op = _clamp((local - 0.35) / 0.4, 0, 1) * _clamp((sc.duration - 0.25 - local) / 0.3, 0, 1)
                    _blit(arr, ov, x, y, op)
                _blit(arr, logo_ov, logo_xy[0], logo_xy[1], 0.92)
                if legal_ov is not None and i == len(spec.scenes) - 1:
                    _blit(arr, legal_ov[0], legal_ov[1], legal_ov[2], _clamp((t - starts[i]) / 0.5, 0, 1))
            if badge is not None:
                _blit(arr, badge[0], badge[1], badge[2], 0.95)
            for c in cues:
                if c.start <= t < c.end:
                    if c.id not in cap_cache:
                        cap_cache[c.id] = overlays.render_caption(c.text, W, H, spec.aspect)
                    ov, x, y = cap_cache[c.id]
                    _blit(arr, ov, x, y, _clamp((t - c.start) / 0.12, 0, 1) * _clamp((c.end - t) / 0.12, 0, 1))
                    break
            if n == poster_n:
                buf = io.BytesIO()
                Image.fromarray(arr).save(buf, "JPEG", quality=86)
                poster = buf.getvalue()
            assert proc.stdin is not None
            proc.stdin.write(arr.tobytes())
            if n % 12 == 0:
                notify(0.10 + 0.85 * n / n_frames, f"Rendering frame {n}/{n_frames}")
        assert proc.stdin is not None
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        rc = proc.wait(timeout=120)
        if rc != 0:
            raise media.MediaError(f"ffmpeg encode failed ({rc}): {err[-500:]}")
    except BrokenPipeError as exc:
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise media.MediaError(f"ffmpeg closed the pipe: {err[-500:]}") from exc
    finally:
        if proc.poll() is None:
            proc.kill()
    notify(0.97, "Verifying output (ffprobe, loudness)")
    out_mp4 = out_dir / "video.mp4"
    info = media.probe(out_mp4)
    loud = media.measure_loudness(out_mp4)
    srt = to_srt([Cue(id=c.id, start=c.start, end=c.end, text=c.text) for c in cues]) if cues else ""
    (out_dir / "captions.srt").write_text(srt, encoding="utf-8")
    if poster is None:
        poster = media.extract_frame(out_mp4, min(1.5, duration / 3))
    (out_dir / "poster.jpg").write_bytes(poster)
    notify(1.0, "Done")
    return {"video": "video.mp4", "srt": "captions.srt", "poster": "poster.jpg", "probe": info, "loudness": loud, "loudnorm_input": lstats, "frames": n_frames, "render_seconds": round(time.monotonic() - t_start, 2)}
