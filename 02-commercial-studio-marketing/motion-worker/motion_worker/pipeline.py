"""Generation pipelines.

* ``WanPipeline``: Wan 2.2 TI2V-5B via diffusers on a CUDA GPU (torch/diffusers imported lazily).
* ``FakePipeline``: CPU-only, deterministic, genuinely *moving* clip (camera push/drift/rotation + light sweep) so the
  whole queue/blob/worker path is testable without a GPU (``MOTION_PIPELINE=fake``).
"""

from __future__ import annotations

import contextlib
import gc
import logging
import math
import random
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from .config import Config
from .contract import MotionRequest
from .errors import InternalError
from .logs import event
from .video import encode_h264

StepCallback = Callable[[int, int], None]
PhaseCallback = Callable[[str], None]
Encoder = Callable[..., tuple[bytes, int]]


@dataclass(frozen=True)
class Clip:
    data: bytes
    width: int
    height: int
    num_frames: int
    generate_s: float
    encode_s: float


@dataclass(frozen=True)
class LoadInfo:
    vram_gib: float
    exported_bf16: bool = False


class Pipeline(Protocol):
    name: str
    revision: str
    needs_weights: bool
    vram_gib: float

    def preflight(self) -> None: ...
    def load(self, model_path: Path | None, *, export_bf16_to: Path | None = None) -> LoadInfo: ...
    def generate(
        self,
        request: MotionRequest,
        image: Image.Image,
        on_step: StepCallback | None = None,
        on_phase: PhaseCallback | None = None,
        *,
        workdir: Path,
    ) -> Clip: ...
    def warmup(self, workdir: Path) -> None: ...
    def release_memory(self) -> None: ...


def _frame_iter(frames: Any) -> Iterator[Any]:
    """diffusers 0.40 returns ``frames[0]`` as a float array (T,H,W,3) in [0,1] for output_type="np" (its default)
    and a list of PIL images for "pil"; both iterate frame by frame."""
    yield from frames


class WanPipeline:
    name = "wan"
    needs_weights = True

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.revision = cfg.model_revision
        self.vram_gib = 0.0
        self._pipe: Any = None

    @staticmethod
    def _torch() -> Any:
        import torch  # noqa: PLC0415 - heavy; imported lazily so unit tests run without it

        return torch

    def preflight(self) -> None:
        """Fail in seconds (before a 30 GiB download) when there is no usable GPU."""
        torch = self._torch()
        if not torch.cuda.is_available():
            raise InternalError("CUDA is not available: the worker needs an NVIDIA GPU (ACA workload profile gpu-a100)")
        props = torch.cuda.get_device_properties(0)
        event(
            "gpu_detected",
            gpu=props.name,
            total_gib=round(props.total_memory / 2**30, 1),
            torch=getattr(torch, "__version__", "?"),
        )

    def load(self, model_path: Path | None, *, export_bf16_to: Path | None = None) -> LoadInfo:
        """Load once: VAE in float32, everything else bf16, on the GPU (the configuration proven on the A100)."""
        if model_path is None:
            raise InternalError("WanPipeline needs a model directory")
        torch = self._torch()
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline  # noqa: PLC0415

        started = time.monotonic()
        vae = AutoencoderKLWan.from_pretrained(str(model_path), subfolder="vae", torch_dtype=torch.float32)
        pipe = WanImageToVideoPipeline.from_pretrained(str(model_path), vae=vae, torch_dtype=torch.bfloat16)
        exported = self._export_bf16(pipe, export_bf16_to) if export_bf16_to is not None else False
        pipe.to("cuda")
        if hasattr(pipe, "set_progress_bar_config"):
            pipe.set_progress_bar_config(disable=True)  # tqdm bars only pollute the JSON logs
        self._pipe = pipe
        self.vram_gib = round(torch.cuda.memory_allocated() / 2**30, 1)
        event(
            "pipeline_loaded",
            seconds=round(time.monotonic() - started, 1),
            vram_gib=self.vram_gib,
            exported_bf16=exported,
        )
        return LoadInfo(self.vram_gib, exported)

    @staticmethod
    def _export_bf16(pipe: Any, dest: Path) -> bool:
        """Optional: save the (already bf16) transformer so the mirror holds ~23 GiB instead of ~32 GiB.
        Never fatal: on any problem the mirror simply keeps the original files."""
        try:
            shutil.rmtree(dest, ignore_errors=True)
            pipe.transformer.save_pretrained(str(dest), safe_serialization=True, max_shard_size="5GB")
            names = {p.name for p in dest.iterdir()}
            if "config.json" not in names or not any(n.endswith(".safetensors") for n in names):
                raise InternalError(f"bf16 export is incomplete: {sorted(names)}")
            return True
        except Exception as exc:  # noqa: BLE001
            event("bf16_export_failed", logging.WARNING, error=f"{type(exc).__name__}: {exc}")
            shutil.rmtree(dest, ignore_errors=True)
            return False

    def generate(
        self,
        request: MotionRequest,
        image: Image.Image,
        on_step: StepCallback | None = None,
        on_phase: PhaseCallback | None = None,
        *,
        workdir: Path,
    ) -> Clip:
        if self._pipe is None:
            raise InternalError("pipeline is not loaded")
        torch = self._torch()
        steps = request.steps

        def on_step_end(_pipe: Any, index: int, _timestep: Any, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
            if on_step is not None:
                on_step(index + 1, steps)  # may raise to abort (timeout / shutdown): the exception unwinds the loop
            return callback_kwargs

        output: Any = None
        frames: Any = None
        started = time.monotonic()
        try:
            output = self._pipe(
                image=image,
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                height=request.height,
                width=request.width,
                num_frames=request.num_frames,
                guidance_scale=request.guidance_scale,
                num_inference_steps=steps,
                generator=torch.Generator("cuda").manual_seed(request.seed),
                output_type="np",
                callback_on_step_end=on_step_end,
            )
            frames = output.frames[0]
            generate_s = time.monotonic() - started
            if on_phase is not None:
                on_phase("encoding")
            encode_started = time.monotonic()
            data, count = encode_h264(
                _frame_iter(frames),
                width=request.width,
                height=request.height,
                fps=request.fps,
                workdir=workdir,
                ffmpeg=self.cfg.ffmpeg,
            )
            return Clip(data, request.width, request.height, count, generate_s, time.monotonic() - encode_started)
        finally:
            del output, frames
            self.release_memory()

    def warmup(self, workdir: Path) -> None:
        """A tiny generation that primes CUDA kernels / allocator (opt-in, never fatal)."""
        request = MotionRequest(
            job_id="mj_" + "0" * 24,
            model=self.cfg.model_id,
            prompt="warm-up",
            negative_prompt="",
            width=256,
            height=256,
            num_frames=5,
            fps=24,
            steps=2,
            guidance_scale=4.0,
            seed=1,
            image="warmup.png",
        )
        self.generate(request, Image.new("RGB", (256, 256), (127, 127, 127)), workdir=workdir)

    def release_memory(self) -> None:
        gc.collect()
        with contextlib.suppress(Exception):  # best effort, e.g. torch missing in unit tests
            self._torch().cuda.empty_cache()


# --------------------------------------------------------------------------------------------------
# Fake pipeline
# --------------------------------------------------------------------------------------------------


class OutOfMemoryError(RuntimeError):
    """Stand-in for torch.cuda.OutOfMemoryError (the worker classifies OOM by this class name, no torch import)."""


def _smoothstep(u: float) -> float:
    return u * u * (3.0 - 2.0 * u)


class FakePipeline:
    """Deterministic stand-in. Prompt markers inject failures: ``[fake:oom]``, ``[fake:error]``."""

    name = "fake"
    revision = "fake"
    needs_weights = False

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        step_delay_s: float = 0.0,
        load_delay_s: float = 0.0,
        ffmpeg: str | None = None,
        encoder: Encoder = encode_h264,
    ) -> None:
        self.cfg = cfg
        self.step_delay_s = step_delay_s
        self.load_delay_s = load_delay_s
        self.ffmpeg = ffmpeg
        self.encoder = encoder
        self.vram_gib = 0.0

    def preflight(self) -> None:
        return None

    def load(self, model_path: Path | None, *, export_bf16_to: Path | None = None) -> LoadInfo:
        if self.load_delay_s:
            time.sleep(self.load_delay_s)
        return LoadInfo(0.0, False)

    def warmup(self, workdir: Path) -> None:
        return None

    def release_memory(self) -> None:
        return None

    def generate(
        self,
        request: MotionRequest,
        image: Image.Image,
        on_step: StepCallback | None = None,
        on_phase: PhaseCallback | None = None,
        *,
        workdir: Path,
    ) -> Clip:
        started = time.monotonic()
        marker = request.prompt.lower()
        if "[fake:oom]" in marker:
            raise OutOfMemoryError("CUDA out of memory. Tried to allocate 20.00 GiB (simulated)")
        if "[fake:error]" in marker:
            raise RuntimeError("simulated pipeline failure")
        for step in range(1, request.steps + 1):
            if self.step_delay_s:
                time.sleep(self.step_delay_s)
            if on_step is not None:
                on_step(step, request.steps)
        frames = list(self.render_frames(request, image))
        generate_s = time.monotonic() - started
        if on_phase is not None:
            on_phase("encoding")
        encode_started = time.monotonic()
        data, count = self.encoder(
            iter(frames),
            width=request.width,
            height=request.height,
            fps=request.fps,
            workdir=workdir,
            ffmpeg=self.ffmpeg,
        )
        return Clip(data, request.width, request.height, count, generate_s, time.monotonic() - encode_started)

    @staticmethod
    def render_frames(request: MotionRequest, image: Image.Image) -> Iterator[np.ndarray]:
        """Frame 0 is the input image; afterwards a seeded push-in with drift, <=2 deg roll and a light sweep."""
        rng = random.Random(request.seed)
        zoom = rng.uniform(0.06, 0.12)
        roll = math.radians(rng.uniform(-1.5, 1.5))
        drift_x, drift_y = rng.uniform(-0.03, 0.03), rng.uniform(-0.02, 0.02)
        base = image.convert("RGB")
        width, height = base.size
        cx, cy = width / 2.0, height / 2.0
        columns = np.linspace(0.0, 1.0, width, dtype=np.float32)
        last = max(1, request.num_frames - 1)
        for index in range(request.num_frames):
            u = index / last
            e = _smoothstep(u)
            z = 1.0 + zoom * e
            ang = roll * e
            a, b = math.cos(ang) / z, math.sin(ang) / z
            c = cx - (a * cx + b * cy) + drift_x * width * e
            f = cy - (-b * cx + a * cy) + drift_y * height * e
            moved = base.transform(
                (width, height), Image.Transform.AFFINE, (a, b, c, -b, a, f), Image.Resampling.BICUBIC
            )
            band = np.exp(-(((columns - (0.05 + 0.9 * u)) / 0.18) ** 2))
            gain = 1.0 + 0.15 * e * band
            arr = np.asarray(moved, dtype=np.float32) * gain[None, :, None]
            yield np.clip(arr + 0.5, 0, 255).astype(np.uint8)


def build_pipeline(cfg: Config) -> Pipeline:
    if cfg.pipeline == "fake":
        return FakePipeline(
            cfg, step_delay_s=cfg.fake_step_delay_s, load_delay_s=cfg.fake_load_delay_s, ffmpeg=cfg.ffmpeg
        )
    return WanPipeline(cfg)
