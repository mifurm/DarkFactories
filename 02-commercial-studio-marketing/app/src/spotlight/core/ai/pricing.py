"""List-price estimates used by the AI usage meter (USD). All figures are ESTIMATES for FinOps display.

Basis: Azure Retail Prices API (retrieved 2026-11-17; Azure OpenAI / Foundry Models, global deployments)
where a meter exists; image per-image figures are derived from published per-image list prices for the
quality/size tier; Azure AI Speech / Content Safety from the public pricing pages. Validate with your invoice.
"""

from __future__ import annotations

PRICES_AS_OF = "2026-11-17"
PRICING_NOTE = (
    "Estimated list prices (USD, pay-as-you-go, no discounts). Token prices: Azure Retail Prices API; "
    "per-image / per-character prices: public price lists. Validate against your Azure invoice."
)

# (input, cached input, output) USD per 1M tokens
LLM_PER_MTOK: dict[str, tuple[float, float, float]] = {
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5-mini": (0.25, 0.025, 2.00),
}
EMBED_PER_MTOK: dict[str, float] = {"text-embedding-3-small": 0.02}

# per image, keyed by (model, quality, size class: "sq" 1024x1024 | "rect" 1024x1536 / 1536x1024)
IMAGE_PER_IMAGE: dict[tuple[str, str, str], float] = {
    ("gpt-image-1.5", "low", "sq"): 0.009,
    ("gpt-image-1.5", "low", "rect"): 0.013,
    ("gpt-image-1.5", "medium", "sq"): 0.034,
    ("gpt-image-1.5", "medium", "rect"): 0.050,
    ("gpt-image-1.5", "high", "sq"): 0.133,
    ("gpt-image-1.5", "high", "rect"): 0.200,
    ("gpt-image-1-mini", "low", "sq"): 0.005,
    ("gpt-image-1-mini", "low", "rect"): 0.006,
    ("gpt-image-1-mini", "medium", "sq"): 0.011,
    ("gpt-image-1-mini", "medium", "rect"): 0.015,
    ("gpt-image-1-mini", "high", "sq"): 0.036,
    ("gpt-image-1-mini", "high", "rect"): 0.052,
}

TTS_PER_MCHAR: dict[str, float] = {"tts-hd": 30.0, "neural": 16.0}
SAFETY_PER_1K_TEXT = 0.75
SAFETY_PER_1K_IMAGE = 1.50
# Azure Container Apps consumption (active): ~US$0.000024 / vCPU-second (+ memory); used for render seconds.
RENDER_PER_VCPU_SECOND = 0.000024 + 0.0000030 * 2  # 1 vCPU + 2 GiB

# Cinematic motion: self-hosted open image-to-video model (Wan 2.2 TI2V-5B, Apache-2.0) on Azure Container Apps serverless GPU (NC24-A100, swedencentral).
# Azure Retail Prices (retrieved 2026-11-18): A100 US$0.000688/s + vCPU US$0.000024/s + GiB US$0.000003/s; the worker runs with 8 vCPU / 64 GiB
# => 0.000688 + 8 * 0.000024 + 64 * 0.000003 = US$0.001072/s, rounded up to the figure below (the app setting MOTION_PRICE_PER_GPU_SECOND overrides it).
MOTION_USD_PER_GPU_SECOND = 0.00108
# GPU seconds per generated frame, calibrated on the real A100 (1024x576, 20 steps: 73 frames = 55 s, 109 frames = 88 s; 12 steps: 73 frames = 38 s).
# A fixed part (text/VAE/encode) plus a part per denoising step; larger frames scale with their pixel count (1280x704: measured 92 s for 73 frames at 20 steps).
MOTION_SECONDS_PER_FRAME_FIXED = 0.10
MOTION_SECONDS_PER_FRAME_PER_STEP = 0.035
MOTION_REFERENCE_PIXELS = 1024 * 576

PREMIUM_IMAGE_QUALITIES = {"high"}
PREMIUM_LLM_ROLES = {"reasoning"}

# What a traditional agency / production house charges (editable ASSUMPTIONS, used for the live KPI comparison;
# the full ROI model lives in business-case/model.py).
AGENCY_BASELINE_PER_ASSET_USD = 1850.0


def size_class(size: str) -> str:
    return "sq" if size in {"1024x1024", "512x512", "256x256"} else "rect"


def llm_cost(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    p_in, p_cached, p_out = LLM_PER_MTOK.get(model, LLM_PER_MTOK["gpt-5.4-mini"])
    fresh = max(0, prompt_tokens - cached_tokens)
    return (fresh * p_in + cached_tokens * p_cached + completion_tokens * p_out) / 1_000_000


def embed_cost(model: str, tokens: int) -> float:
    return tokens * EMBED_PER_MTOK.get(model, 0.02) / 1_000_000


def image_cost(model: str, quality: str, size: str, n: int = 1) -> float:
    per = IMAGE_PER_IMAGE.get((model, quality, size_class(size)))
    if per is None:
        per = IMAGE_PER_IMAGE[("gpt-image-1.5", "medium", size_class(size))]
    return per * n


def tts_cost(kind: str, chars: int) -> float:
    return chars * TTS_PER_MCHAR.get(kind, 30.0) / 1_000_000


def safety_cost(kind: str, n: int = 1) -> float:
    return n * (SAFETY_PER_1K_IMAGE if kind == "image" else SAFETY_PER_1K_TEXT) / 1000


def render_cost(cpu_seconds: float) -> float:
    return cpu_seconds * RENDER_PER_VCPU_SECOND


def motion_cost(gpu_seconds: float, price_per_second: float = MOTION_USD_PER_GPU_SECOND) -> float:
    """USD for ``gpu_seconds`` of the serverless A100 worker."""
    return max(0.0, gpu_seconds) * price_per_second


def motion_estimate(frames: int, width: int, height: int, steps: int = 20) -> float:
    """Expected GPU seconds to generate one clip (a calibrated estimate, not a measurement): 1024x576 at 20 steps = 0.80 s per frame, 12 steps = 0.52 s per frame."""
    per_frame = MOTION_SECONDS_PER_FRAME_FIXED + MOTION_SECONDS_PER_FRAME_PER_STEP * steps
    return frames * per_frame * (width * height) / MOTION_REFERENCE_PIXELS


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
