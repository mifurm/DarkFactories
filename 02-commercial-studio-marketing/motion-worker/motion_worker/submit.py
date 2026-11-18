"""Dev/ops producer: submit one image-to-video job exactly like the Studio does, optionally wait for the clip.

    MOTION_TRANSPORT=local MOTION_LOCAL_DIR=./.motion python -m motion_worker.submit \\
        --image keyframe.jpg --prompt "slow push-in, steam rises" --wait 120 --out clip.mp4

Works against the Azure transport too (az login + Queue Data Message Sender / Blob Data Contributor roles).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import contract
from .config import Config
from .errors import BadRequest, ConfigError
from .transport import IN, OUT, Transport, build_transport

CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
POLL_SECONDS = 1.0


def is_cached(transport: Transport, job_id: str) -> bool:
    """Same inputs => same job id => a finished job needs no new work (transport-level cache)."""
    return transport.blob_exists(OUT, f"{job_id}/result.json")


def wait_for_result(transport: Transport, job_id: str, timeout_s: float, poll_s: float = 1.0) -> dict | None:
    deadline = time.monotonic() + timeout_s
    while True:
        raw = transport.read_blob(OUT, f"{job_id}/result.json")
        if raw is not None:
            return json.loads(raw)
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_s)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m motion_worker.submit", description=__doc__.split("\n")[0])
    parser.add_argument("--image", type=Path, help="keyframe (jpg/png/webp)")
    parser.add_argument("--prompt", default="slow cinematic push-in, natural motion, realistic commercial footage")
    parser.add_argument("--negative", default="blurry, distorted, text, watermark, static frame, low quality")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--frames", type=int, default=73, help="num_frames, must be 4n+1")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--campaign", default=None)
    parser.add_argument("--shot", default=None)
    parser.add_argument("--warmup", action="store_true", help="enqueue a warm-up message instead of a job")
    parser.add_argument("--wait", type=float, default=0.0, metavar="SECONDS", help="wait for result.json")
    parser.add_argument("--out", type=Path, default=None, help="where to save clip.mp4 when --wait succeeds")
    args = parser.parse_args(argv)
    try:
        transport = build_transport(Config.from_env(env))
    except ConfigError as exc:
        print(f"submit: {exc}", file=sys.stderr)
        return 2

    if args.warmup:
        job_id = contract.new_warmup_id()
        transport.send(contract.build_queue_message(job_id))
        print(json.dumps({"job_id": job_id, "type": "warmup"}))
        return 0
    if args.image is None:
        parser.error("--image is required (or use --warmup)")
    suffix = args.image.suffix.lower()
    if suffix not in CONTENT_TYPES:
        parser.error("--image must be .jpg, .jpeg, .png or .webp")
    image_bytes = args.image.read_bytes()
    request = contract.build_request(
        prompt=args.prompt,
        negative_prompt=args.negative,
        image_name=f"image{suffix}",
        image_bytes=image_bytes,
        width=args.width,
        height=args.height,
        num_frames=args.frames,
        steps=args.steps,
        guidance_scale=args.guidance,
        seed=args.seed,
        campaign_id=args.campaign,
        shot_id=args.shot,
    )
    try:
        contract.parse_request(request)  # fail fast, with the same rules the worker applies
    except BadRequest as exc:
        print(f"submit: invalid request: {exc.message}", file=sys.stderr)
        return 2
    job_id = request["job_id"]
    if not is_cached(transport, job_id):
        transport.write_blob(IN, f"{job_id}/{request['image']}", image_bytes, CONTENT_TYPES[suffix])
        transport.write_blob(IN, f"{job_id}/request.json", json.dumps(request).encode("utf-8"))
        transport.send(contract.build_queue_message(job_id))
        print(json.dumps({"job_id": job_id, "type": "generate", "enqueued": True}))
    else:
        print(json.dumps({"job_id": job_id, "type": "generate", "enqueued": False, "cached": True}))
    if not args.wait:
        return 0
    result = wait_for_result(transport, job_id, args.wait, POLL_SECONDS)
    if result is None:
        print(json.dumps({"job_id": job_id, "state": "timeout-waiting"}))
        return 1
    print(json.dumps(result))
    if result["state"] == "succeeded" and args.out is not None:
        clip = transport.read_blob(OUT, f"{job_id}/{result['clip']}")
        if clip is not None:
            args.out.write_bytes(clip)
    return 0 if result["state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
