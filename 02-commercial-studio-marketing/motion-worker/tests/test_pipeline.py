"""Pipelines: the CPU fake really moves; WanPipeline calls diffusers exactly as proven on the A100."""

from __future__ import annotations

import statistics
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from motion_worker import contract
from motion_worker import pipeline as pipeline_mod
from motion_worker.errors import InternalError, JobAborted, classify_exception
from motion_worker.pipeline import FakePipeline, LoadInfo, WanPipeline, build_pipeline
from motion_worker.video import find_ffmpeg

from .conftest import keyframe_bytes, make_cfg
from .test_media import decode_frames


def request(**over) -> contract.MotionRequest:
    doc = {
        "v": 1, "job_id": "mj_0123456789abcdef01234567", "model": "wan2.2-ti2v-5b", "prompt": "slow push-in",
        "negative_prompt": "blurry", "width": 320, "height": 256, "num_frames": 49, "fps": 24, "steps": 8,
        "guidance_scale": 4.0, "seed": 11, "image": "image.jpg",
    }  # fmt: skip
    doc.update(over)
    return contract.parse_request(doc)


def source_image(width=320, height=256) -> Image.Image:
    import io

    return Image.open(io.BytesIO(keyframe_bytes(width, height))).convert("RGB")


def mad(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


# ---------------------------------------------------------------------------------------------- fake pipeline


@pytest.mark.ffmpeg
def test_the_fake_clip_really_moves_in_the_encoded_video(tmp_path):
    req, image = request(), source_image()
    clip = FakePipeline().generate(req, image, workdir=tmp_path / "w")
    path = tmp_path / "clip.mp4"
    path.write_bytes(clip.data)
    frames = decode_frames(path, 320, 256)
    assert (clip.num_frames, frames.shape) == (49, (49, 256, 320, 3))
    consecutive = [mad(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    assert min(consecutive) > 0.08, f"a frame pair is (nearly) frozen: {min(consecutive):.3f}"
    assert statistics.median(consecutive) > 1.5, "typical frame-to-frame change is too small to read as motion"
    assert max(consecutive) < 15, "motion must be smooth, not cuts"
    assert mad(frames[0], frames[-1]) > 3.0, "first and last frame must differ"
    assert mad(frames[0], frames[12]) < mad(frames[0], frames[48]), "the motion accumulates over time"
    assert mad(frames[0], np.asarray(image)) < 8, "frame 0 is (a lossy encode of) the conditioning image"
    assert (clip.width, clip.height) == (320, 256)
    assert clip.generate_s >= 0 and clip.encode_s > 0


@pytest.mark.ffmpeg
def test_the_fake_is_deterministic_and_the_seed_changes_the_motion(tmp_path):
    image = source_image()
    a = list(FakePipeline.render_frames(request(seed=5), image))
    b = list(FakePipeline.render_frames(request(seed=5), image))
    c = list(FakePipeline.render_frames(request(seed=6), image))
    assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))
    assert not all(np.array_equal(x, y) for x, y in zip(a, c, strict=True))
    assert np.array_equal(a[0], np.asarray(image))  # frame 0 is exactly the input
    assert mad(a[-1], c[-1]) > 1.0


def test_fake_renders_the_requested_frame_count_and_size():
    frames = list(FakePipeline.render_frames(request(width=256, height=256, num_frames=25), source_image(256, 256)))
    assert len(frames) == 25
    assert {f.shape for f in frames} == {(256, 256, 3)}
    assert frames[0].dtype == np.uint8


def test_fake_reports_every_step_then_the_encoding_phase(tmp_path):
    steps, phases = [], []
    pipe = FakePipeline(encoder=lambda frames, **kw: (b"mp4", sum(1 for _ in frames)))
    clip = pipe.generate(
        request(steps=8, num_frames=25), source_image(), on_step=lambda s, n: steps.append((s, n)),
        on_phase=phases.append, workdir=tmp_path,
    )  # fmt: skip
    assert steps == [(i, 8) for i in range(1, 9)]
    assert phases == ["encoding"]
    assert (clip.data, clip.num_frames) == (b"mp4", 25)


def test_step_delay_makes_progress_observable(tmp_path):
    pipe = FakePipeline(step_delay_s=0.02, encoder=lambda frames, **kw: (b"x", sum(1 for _ in frames)))
    started = time.monotonic()
    pipe.generate(request(steps=8, num_frames=25), source_image(), workdir=tmp_path)
    assert time.monotonic() - started >= 8 * 0.02


def test_failure_markers_inject_oom_and_internal_errors(tmp_path):
    pipe = FakePipeline(encoder=lambda frames, **kw: (b"x", 1))
    with pytest.raises(Exception, match="out of memory") as oom:
        pipe.generate(request(prompt="push [FAKE:OOM] in"), source_image(), workdir=tmp_path)
    assert classify_exception(oom.value).code == "oom"
    with pytest.raises(RuntimeError, match="simulated") as boom:
        pipe.generate(request(prompt="x [fake:error]"), source_image(), workdir=tmp_path)
    assert classify_exception(boom.value).code == "internal"


def test_fake_lifecycle_hooks_are_inert():
    pipe = FakePipeline(load_delay_s=0.01)
    assert pipe.needs_weights is False and pipe.revision == "fake" and pipe.name == "fake"
    assert pipe.load(None) == LoadInfo(0.0, False)
    pipe.preflight()
    pipe.warmup(Path("."))
    pipe.release_memory()
    assert pipe.vram_gib == 0.0


def test_build_pipeline_selects_by_config(tmp_path):
    fake = build_pipeline(make_cfg(tmp_path, pipeline="fake", fake_step_delay_s=0.5, fake_load_delay_s=1.5))
    assert isinstance(fake, FakePipeline) and (fake.step_delay_s, fake.load_delay_s) == (0.5, 1.5)
    wan = build_pipeline(make_cfg(tmp_path, pipeline="wan"))
    assert isinstance(wan, WanPipeline)  # constructing it needs neither torch nor a GPU


# ---------------------------------------------------------------------------------------------- WanPipeline


class GpuStack:
    """Fake torch + diffusers. The pipeline __call__ signature is copied from diffusers 0.40.0
    (pipeline_wan_i2v.WanImageToVideoPipeline.__call__), so any wrong keyword fails here."""

    def __init__(self, monkeypatch, *, cuda=True, frames="np", fail=None, export_ok=True):
        self.calls: list[tuple] = []
        stack = self
        calls = self.calls

        class OutOfMemoryError(RuntimeError):
            pass

        class Generator:
            def __init__(self, device="cpu"):
                calls.append(("Generator", device))

            def manual_seed(self, seed):
                calls.append(("manual_seed", seed))
                return self

        class Cuda:
            @staticmethod
            def is_available():
                return cuda

            @staticmethod
            def get_device_properties(index):
                return types.SimpleNamespace(name="NVIDIA A100 80GB PCIe", total_memory=80 * 2**30)

            @staticmethod
            def memory_allocated():
                return int(22.6 * 2**30)

            @staticmethod
            def empty_cache():
                calls.append(("empty_cache",))

        torch = types.ModuleType("torch")
        torch.float32, torch.bfloat16, torch.__version__ = "float32", "bfloat16", "2.8.0+cu126-fake"
        torch.Generator, torch.cuda = Generator, Cuda
        stack.OutOfMemoryError = OutOfMemoryError

        class Transformer:
            def save_pretrained(self, path, safe_serialization=None, max_shard_size=None):
                calls.append(("save_pretrained", Path(path).name, safe_serialization, max_shard_size))
                if not export_ok:
                    raise OSError("disk full")
                Path(path).mkdir(parents=True, exist_ok=True)
                (Path(path) / "config.json").write_text("{}")
                (Path(path) / "diffusion_pytorch_model.safetensors").write_bytes(b"bf16")

        class AutoencoderKLWan:
            @classmethod
            def from_pretrained(cls, path, subfolder=None, torch_dtype=None):
                calls.append(("vae", str(path), subfolder, torch_dtype))
                return cls()

        class WanImageToVideoPipeline:
            @classmethod
            def from_pretrained(cls, path, vae=None, torch_dtype=None):
                calls.append(("pipeline", str(path), type(vae).__name__, torch_dtype))
                inst = cls()
                inst.transformer = Transformer()
                return inst

            def to(self, device):
                calls.append(("to", device))
                return self

            def set_progress_bar_config(self, **kwargs):
                calls.append(("progress_bar", kwargs))

            def __call__(
                self, image, prompt=None, negative_prompt=None, height=480, width=832, num_frames=81,
                num_inference_steps=50, guidance_scale=5.0, guidance_scale_2=None, num_videos_per_prompt=1,
                generator=None, latents=None, prompt_embeds=None, negative_prompt_embeds=None, image_embeds=None,
                last_image=None, output_type="np", return_dict=True, attention_kwargs=None,
                callback_on_step_end=None, callback_on_step_end_tensor_inputs=("latents",), max_sequence_length=512,
            ):  # fmt: skip
                calls.append((
                    "call",
                    {"size": image.size, "prompt": prompt, "negative_prompt": negative_prompt, "height": height,
                     "width": width, "num_frames": num_frames, "steps": num_inference_steps,
                     "guidance": guidance_scale, "output_type": output_type, "generator": generator},
                ))  # fmt: skip
                if fail == "oom":
                    raise OutOfMemoryError("CUDA out of memory. Tried to allocate 3.50 GiB")
                for i in range(num_inference_steps):
                    out = callback_on_step_end(self, i, 1000 - i, {"latents": object()})
                    assert isinstance(out, dict) and "latents" in out, "diffusers pops latents from the returned dict"
                rng = np.random.default_rng(0)
                video = rng.random((num_frames, height, width, 3), dtype=np.float32)
                if frames == "pil":
                    return types.SimpleNamespace(frames=[[Image.fromarray((f * 255).astype(np.uint8)) for f in video]])
                return types.SimpleNamespace(frames=[video])

        diffusers = types.ModuleType("diffusers")
        diffusers.AutoencoderKLWan, diffusers.WanImageToVideoPipeline = AutoencoderKLWan, WanImageToVideoPipeline
        monkeypatch.setitem(sys.modules, "torch", torch)
        monkeypatch.setitem(sys.modules, "diffusers", diffusers)

    def names(self):
        return [c[0] for c in self.calls]

    def one(self, name):
        return next(c for c in self.calls if c[0] == name)


@pytest.fixture
def captured_encoder(monkeypatch):
    seen: dict = {}

    def encoder(frames, **kwargs):
        frames = list(frames)
        seen.update(kwargs, frames=frames)
        return b"mp4-bytes", len(frames)

    monkeypatch.setattr(pipeline_mod, "encode_h264", encoder)
    return seen


def loaded_wan(tmp_path, monkeypatch, **kw):
    stack = GpuStack(monkeypatch, **kw)
    pipe = WanPipeline(make_cfg(tmp_path, pipeline="wan"))
    info = pipe.load(tmp_path / "weights")
    return stack, pipe, info


def test_preflight_requires_a_cuda_device(tmp_path, monkeypatch):
    stack = GpuStack(monkeypatch, cuda=True)
    WanPipeline(make_cfg(tmp_path)).preflight()
    stack = GpuStack(monkeypatch, cuda=False)
    with pytest.raises(InternalError, match="CUDA is not available"):
        WanPipeline(make_cfg(tmp_path)).preflight()
    assert stack.names() == []


def test_load_follows_the_proven_recipe_vae_fp32_rest_bf16_on_cuda(tmp_path, monkeypatch):
    stack, pipe, info = loaded_wan(tmp_path, monkeypatch)
    weights = str(tmp_path / "weights")
    assert stack.one("vae") == ("vae", weights, "vae", "float32")
    assert stack.one("pipeline") == ("pipeline", weights, "AutoencoderKLWan", "bfloat16")
    assert stack.names().index("to") > stack.names().index("pipeline")
    assert stack.one("to") == ("to", "cuda")
    assert stack.one("progress_bar") == ("progress_bar", {"disable": True})
    assert (info, pipe.vram_gib) == (LoadInfo(22.6, False), 22.6)
    assert pipe.revision == pipe.cfg.model_revision and pipe.needs_weights and pipe.name == "wan"


def test_generate_calls_the_pipeline_with_the_proven_arguments(tmp_path, monkeypatch, captured_encoder):
    stack, pipe, _ = loaded_wan(tmp_path, monkeypatch)
    req = request(
        width=1024, height=576, num_frames=93, steps=20, guidance_scale=4.5, seed=424242, negative_prompt="bad"
    )
    steps = []
    phases = []
    clip = pipe.generate(req, Image.new("RGB", (1024, 576)), on_step=lambda s, n: steps.append((s, n)),
                         on_phase=phases.append, workdir=tmp_path / "w")  # fmt: skip
    call = stack.one("call")[1]
    assert call["size"] == (1024, 576)
    assert (call["prompt"], call["negative_prompt"]) == (req.prompt, "bad")
    assert (call["height"], call["width"], call["num_frames"], call["steps"], call["guidance"]) == (
        576,
        1024,
        93,
        20,
        4.5,
    )
    assert call["output_type"] == "np"
    assert ("Generator", "cuda") in stack.calls and ("manual_seed", 424242) in stack.calls
    assert steps == [(i, 20) for i in range(1, 21)], "1-based step numbers, one per denoising step"
    assert phases == ["encoding"]
    assert (clip.data, clip.num_frames, clip.width, clip.height) == (b"mp4-bytes", 93, 1024, 576)
    assert captured_encoder["fps"] == 24 and captured_encoder["width"] == 1024
    frames = captured_encoder["frames"]
    assert len(frames) == 93 and frames[0].shape == (576, 1024, 3) and frames[0].dtype == np.float32
    assert stack.names().count("empty_cache") >= 1, "VRAM is released after every job"


def test_pil_frames_are_supported_too(tmp_path, monkeypatch, captured_encoder):
    _, pipe, _ = loaded_wan(tmp_path, monkeypatch, frames="pil")
    clip = pipe.generate(request(num_frames=25, width=256, height=256), Image.new("RGB", (256, 256)), workdir=tmp_path)
    assert clip.num_frames == 25
    assert all(isinstance(f, Image.Image) for f in captured_encoder["frames"])


def test_a_callback_exception_aborts_generation_and_the_pipeline_stays_usable(tmp_path, monkeypatch, captured_encoder):
    stack, pipe, _ = loaded_wan(tmp_path, monkeypatch)

    def abort(step, steps):
        if step == 3:
            raise JobAborted()

    with pytest.raises(JobAborted):
        pipe.generate(request(), Image.new("RGB", (320, 256)), on_step=abort, workdir=tmp_path)
    assert stack.names().count("empty_cache") >= 1
    assert pipe.generate(request(), Image.new("RGB", (320, 256)), workdir=tmp_path).data == b"mp4-bytes"


def test_cuda_oom_propagates_as_an_oom_and_memory_is_released(tmp_path, monkeypatch, captured_encoder):
    stack, pipe, _ = loaded_wan(tmp_path, monkeypatch, fail="oom")
    with pytest.raises(stack.OutOfMemoryError) as err:
        pipe.generate(request(), Image.new("RGB", (320, 256)), workdir=tmp_path)
    assert classify_exception(err.value).code == "oom"
    assert classify_exception(err.value).retryable is False
    assert stack.names().count("empty_cache") >= 1


def test_generate_before_load_and_load_without_a_model_directory_fail_clearly(tmp_path, monkeypatch):
    GpuStack(monkeypatch)
    pipe = WanPipeline(make_cfg(tmp_path))
    with pytest.raises(InternalError, match="not loaded"):
        pipe.generate(request(), Image.new("RGB", (320, 256)), workdir=tmp_path)
    with pytest.raises(InternalError, match="model directory"):
        pipe.load(None)


def test_bf16_export_happens_on_the_cpu_before_the_move_to_cuda(tmp_path, monkeypatch):
    stack = GpuStack(monkeypatch)
    pipe = WanPipeline(make_cfg(tmp_path))
    export = tmp_path / "bf16"
    info = pipe.load(tmp_path / "weights", export_bf16_to=export)
    assert info.exported_bf16 is True
    assert stack.one("save_pretrained") == ("save_pretrained", "bf16", True, "5GB")
    assert stack.names().index("save_pretrained") < stack.names().index("to")
    assert {p.name for p in export.iterdir()} == {"config.json", "diffusion_pytorch_model.safetensors"}


def test_a_failing_bf16_export_never_fails_the_load(tmp_path, monkeypatch):
    stack = GpuStack(monkeypatch, export_ok=False)
    pipe = WanPipeline(make_cfg(tmp_path))
    export = tmp_path / "bf16"
    info = pipe.load(tmp_path / "weights", export_bf16_to=export)
    assert info.exported_bf16 is False and not export.exists()
    assert "to" in stack.names()


def test_an_incomplete_bf16_export_is_discarded(tmp_path, monkeypatch):
    stack = GpuStack(monkeypatch)
    monkeypatch.setattr(WanPipeline, "_export_bf16", staticmethod(WanPipeline._export_bf16))
    export = tmp_path / "bf16"

    def partial(self, path, safe_serialization=None, max_shard_size=None):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "config.json").write_text("{}")  # no weights

    sys.modules["diffusers"].WanImageToVideoPipeline.from_pretrained.__func__  # noqa: B018 - stack is installed
    transformer_cls = type("T", (), {"save_pretrained": partial})
    assert WanPipeline._export_bf16(types.SimpleNamespace(transformer=transformer_cls()), export) is False
    assert not export.exists()
    assert stack.names() == []


def test_warmup_runs_a_tiny_generation(tmp_path, monkeypatch, captured_encoder):
    stack, pipe, _ = loaded_wan(tmp_path, monkeypatch)
    pipe.warmup(tmp_path / "w")
    call = stack.one("call")[1]
    assert (call["width"], call["height"], call["num_frames"], call["steps"]) == (256, 256, 5, 2)


def test_release_memory_without_torch_is_silent(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "torch", None)  # import raises ImportError
    WanPipeline(make_cfg(tmp_path)).release_memory()


def test_the_pipeline_does_not_need_ffmpeg_to_import():
    assert callable(find_ffmpeg)
