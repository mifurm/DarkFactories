"""VideoProvider interface (pluggable model layer). The ffmpeg compositor is the default; external video models plug in here."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..errors import ProviderUnavailable
from .spec import RenderSpec

ProgressCb = Callable[[float, str], Awaitable[None]]


@dataclass
class RenderOutput:
    video: bytes
    srt: str
    poster: bytes
    probe: dict[str, Any]
    loudness: dict[str, float]
    meta: dict[str, Any] = field(default_factory=dict)


class VideoProvider(Protocol):
    name: str

    def capabilities(self) -> dict[str, Any]: ...

    async def render(self, spec: RenderSpec, scene_images: dict[str, bytes], vo_audio: dict[str, bytes], progress: ProgressCb | None = None, clips: dict[str, bytes] | None = None) -> RenderOutput: ...


class CompositorProvider:
    """Default provider: Pillow/numpy frame compositor + ffmpeg, executed in an isolated subprocess."""

    name = "compositor"

    def __init__(self, timeout_s: int = 420, work_dir: str | None = None, nice: int = 5) -> None:
        self.timeout_s = timeout_s
        self.work_dir = work_dir or None
        self.nice = nice

    def capabilities(self) -> dict[str, Any]:
        return {
            "kind": "keyframes+motion compositor",
            "motion": ["zoom_in", "zoom_out", "pan_*", "parallax"],
            "audio": "voice-over + procedural music bed, EBU R128 two-pass",
            "captions": "burned-in + SRT",
            "aspects": ["16:9", "9:16", "1:1", "4:5"],
            "codec": "H.264/AAC MP4",
            "generative_motion": False,
            "clip_scenes": True,  # plays generated clips (cinematic quality) as scenes, with the same dissolves, captions, badge, end card and audio
        }

    async def render(self, spec: RenderSpec, scene_images: dict[str, bytes], vo_audio: dict[str, bytes], progress: ProgressCb | None = None, clips: dict[str, bytes] | None = None) -> RenderOutput:
        if self.work_dir:
            await asyncio.to_thread(Path(self.work_dir).mkdir, parents=True, exist_ok=True)  # a configured scratch directory that does not exist yet is created, not a 500
        with tempfile.TemporaryDirectory(prefix="spot-", dir=self.work_dir) as td:
            root = Path(td)
            (root / "assets").mkdir()
            (root / "vo").mkdir()
            assets = {}
            for k, v in scene_images.items():
                (root / "assets" / f"{k}.bin").write_bytes(v)
                assets[k] = f"assets/{k}.bin"
            vo = {}
            for k, v in vo_audio.items():
                (root / "vo" / f"{k}.bin").write_bytes(v)
                vo[k] = f"vo/{k}.bin"
            clip_files: dict[str, str] = {}
            if clips:
                (root / "clips").mkdir()
                for i, (scene_id, data) in enumerate(clips.items()):
                    (root / "clips" / f"clip{i}.mp4").write_bytes(data)
                    clip_files[scene_id] = f"clips/clip{i}.mp4"
            job: dict[str, Any] = {"spec": json.loads(spec.model_dump_json()), "assets": assets, "vo": vo, "timeout": self.timeout_s}
            if clip_files:
                job["clips"] = clip_files
            (root / "job.json").write_text(json.dumps(job))
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "spotlight.video.worker", str(root),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "OMP_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1"},
                preexec_fn=(lambda: os.nice(self.nice)) if self.nice and os.name == "posix" else None,
            )  # fmt: skip
            result: dict[str, Any] | None = None
            error = ""
            assert proc.stdout is not None
            try:
                async with asyncio.timeout(self.timeout_s + 60):
                    async for raw in proc.stdout:
                        line = raw.decode(errors="replace").strip()
                        if line.startswith("PROGRESS ") and progress:
                            parts = line.split(" ", 2)
                            await progress(float(parts[1]), parts[2] if len(parts) > 2 else "")
                        elif line.startswith("RESULT "):
                            result = json.loads(line[7:])
                        elif line.startswith("ERROR "):
                            error = line[6:]
                    await proc.wait()
            except TimeoutError as exc:
                proc.kill()
                raise ProviderUnavailable("render timed out", code="render_timeout") from exc
            if proc.returncode != 0 or result is None:
                stderr = (await proc.stderr.read()).decode(errors="replace")[-400:] if proc.stderr else ""
                raise ProviderUnavailable(f"render failed: {error or stderr or 'unknown error'}", code="render_failed", params={"detail": error or stderr or "unknown error"})
            out = root / "out"
            return RenderOutput(
                video=(out / result["video"]).read_bytes(),
                srt=(out / result["srt"]).read_text(encoding="utf-8"),
                poster=(out / result["poster"]).read_bytes(),
                probe=result["probe"],
                loudness=result["loudness"],
                meta={"frames": result["frames"], "render_seconds": result["render_seconds"], "loudnorm_input": result["loudnorm_input"]},
            )


class ExternalVideoModelProvider:
    """Documented plug-in point for a generative video model (e.g. Azure OpenAI Sora when available in a region,
    or any third-party text/image-to-video API). Azure OpenAI Sora-2 is DEPRECATED in swedencentral, so this provider
    is intentionally inert: configure an endpoint + implement ``render`` to image-to-video each keyframe, then hand the
    clips to the compositor for captions / audio / end card (set ``generative_motion=True``)."""

    name = "external-video-model"

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = endpoint

    def capabilities(self) -> dict[str, Any]:
        return {"kind": "generative video (stub)", "generative_motion": True, "configured": bool(self.endpoint), "note": "Azure OpenAI Sora-2 is deprecated in swedencentral; plug any image-to-video model here."}

    async def render(self, spec: RenderSpec, scene_images: dict[str, bytes], vo_audio: dict[str, bytes], progress: ProgressCb | None = None, clips: dict[str, bytes] | None = None) -> RenderOutput:
        raise ProviderUnavailable("No external video model is configured; the ffmpeg compositor is the default provider.", code="provider_not_configured", hint="Set VIDEO_PROVIDER=compositor or implement ExternalVideoModelProvider.render.")


def get_provider(name: str, timeout_s: int = 420, work_dir: str | None = None) -> VideoProvider:
    if name == "external":
        return ExternalVideoModelProvider()
    return CompositorProvider(timeout_s, work_dir)
