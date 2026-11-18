"""Cinematic motion: real generative image-to-video behind the spot compositor.

The approved storyboard keyframe becomes the first frame of an AI-generated clip with real subject and camera motion; the compositor then edits the clips
exactly as it edits stills (dissolves, captions, logo, AI badge, end card, voice-over, music, EBU R128). The queue + blob protocol to the GPU worker is the wire
contract in ``contracts/`` (job ids, request / status / result / ready documents); the API lives in ``features/cs25_motion`` (worker status + warm-up) and
``features/cs08_spot`` (``quality`` on render, the priced estimate)."""

from __future__ import annotations

from .client import MotionClient, OffMotionClient, build_client
from .models import MotionError, MotionRequest, MotionResult, WorkerStatus
from .wire import compute_job_id

__all__ = ["MotionClient", "MotionError", "MotionRequest", "MotionResult", "OffMotionClient", "WorkerStatus", "build_client", "compute_job_id"]
