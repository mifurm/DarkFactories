"""Wire contract: deterministic ids (golden vectors), request validation, queue messages, document builders."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from motion_worker import contract
from motion_worker.contract import MODELS, MotionRequest, compute_job_id
from motion_worker.errors import (
    BadRequest,
    InternalError,
    JobTimeout,
    OutOfMemory,
    classify_exception,
    is_out_of_memory,
)

from .conftest import CONTRACT_README, VECTORS_PATH, sha256_hex

REV = MODELS["wan2.2-ti2v-5b"].revision

BASE: dict[str, Any] = {
    "v": 1,
    "job_id": "mj_0123456789abcdef01234567",
    "model": "wan2.2-ti2v-5b",
    "prompt": "A hand lifts the mug; steam rises.",
    "negative_prompt": "blurry",
    "width": 1024,
    "height": 576,
    "num_frames": 93,
    "fps": 24,
    "steps": 20,
    "guidance_scale": 4.0,
    "seed": 123456,
    "image": "image.jpg",
    "campaign_id": "cmp",
    "shot_id": "s1",
    "created_at": "2026-11-18T18:00:00Z",
}


def vector_kwargs(inputs: dict[str, Any]) -> dict[str, Any]:
    keys = "model revision prompt negative_prompt width height num_frames fps steps guidance_scale seed image_sha256"
    return {k: inputs[k] for k in keys.split()}


def load_vectors() -> list[dict[str, Any]]:
    return json.loads(VECTORS_PATH.read_text("utf-8"))["vectors"]


# ---------------------------------------------------------------------------------------------- job id


@pytest.mark.parametrize("vector", load_vectors(), ids=lambda v: v["name"])
def test_golden_vector_reproduces_job_id_and_canonical_form(vector):
    inputs = vector["inputs"]
    assert sha256_hex(inputs["image_bytes_ascii"].encode()) == inputs["image_sha256"]
    assert compute_job_id(**vector_kwargs(inputs)) == vector["job_id"]
    canonical = "|".join(
        [
            inputs["model"],
            inputs["revision"],
            contract.canonical_text(inputs["prompt"]),
            contract.canonical_text(inputs["negative_prompt"]),
            str(inputs["width"]),
            str(inputs["height"]),
            str(inputs["num_frames"]),
            str(inputs["fps"]),
            str(inputs["steps"]),
            contract.canonical_guidance(inputs["guidance_scale"]),
            str(inputs["seed"]),
            inputs["image_sha256"],
        ]
    )
    assert canonical == vector["canonical"]
    assert vector["job_id"] == "mj_" + sha256_hex(canonical.encode("utf-8"))[:24]


def test_contract_readme_documents_every_golden_vector():
    if not CONTRACT_README.exists():
        pytest.skip("contracts/README.md not present")
    text = CONTRACT_README.read_text("utf-8")
    for vector in load_vectors():
        assert vector["job_id"] in text, f"README is missing the golden id of {vector['name']}"
        assert vector["inputs"]["image_sha256"] in text


def test_job_id_pinned_for_the_spec_example():
    # The first golden vector is the request.json example from the spec, hashed over the ASCII "image".
    assert load_vectors()[0]["job_id"] == "mj_380b932f37f39c944afce70d"


@pytest.mark.parametrize(
    ("guidance", "expected"),
    [(4, "4"), (4.0, "4"), (3.5, "3.5"), (7.123456789, "7.12346"), (1, "1"), (0.1 + 0.2, "0.3"), (8.0, "8")],
)
def test_guidance_is_formatted_repr_stable(guidance, expected):
    assert contract.canonical_guidance(guidance) == expected


def test_free_text_escaping_prevents_field_boundary_shifts():
    base = {**vector_kwargs(load_vectors()[0]["inputs"])}
    a = compute_job_id(**{**base, "prompt": "a|b", "negative_prompt": "c"})
    b = compute_job_id(**{**base, "prompt": "a", "negative_prompt": "b|c"})
    c = compute_job_id(**{**base, "prompt": "a\\", "negative_prompt": "|c"})
    d = compute_job_id(**{**base, "prompt": "a", "negative_prompt": "\\|c"})
    assert len({a, b, c, d}) == 4
    assert contract.canonical_text("a\\b|c") == "a\\\\b\\|c"


def test_job_id_depends_on_every_input():
    base = vector_kwargs(load_vectors()[0]["inputs"])
    reference = compute_job_id(**base)
    changes = {
        "model": "other-model",
        "revision": "0" * 40,
        "prompt": base["prompt"] + " ",
        "negative_prompt": "x",
        "width": 1280,
        "height": 704,
        "num_frames": 97,
        "fps": 25,
        "steps": 21,
        "guidance_scale": 4.5,
        "seed": 1,
        "image_sha256": "0" * 64,
    }
    ids = {compute_job_id(**{**base, key: value}) for key, value in changes.items()}
    assert len(ids) == len(changes)
    assert reference not in ids


def test_job_id_is_case_insensitive_for_the_image_hash_and_numeric_types():
    base = vector_kwargs(load_vectors()[0]["inputs"])
    assert compute_job_id(**{**base, "image_sha256": base["image_sha256"].upper()}) == compute_job_id(**base)
    assert compute_job_id(**{**base, "width": 1024.0, "seed": "123456"}) == compute_job_id(**base)


# ---------------------------------------------------------------------------------------------- request

VALID_CASES = {
    "base": {},
    "max-16x9-high": {"width": 1280, "height": 704},
    "portrait": {"width": 576, "height": 1024},
    "square": {"width": 768, "height": 768},
    "frames-min": {"num_frames": 25},
    "frames-max": {"num_frames": 121},
    "steps-bounds-low": {"steps": 8},
    "steps-bounds-high": {"steps": 40},
    "guidance-int-low": {"guidance_scale": 1},
    "guidance-int-high": {"guidance_scale": 8},
    "seed-zero": {"seed": 0},
    "seed-max": {"seed": 2**32 - 1},
    "png": {"image": "keyframe_1.png"},
    "webp": {"image": "frame.webp"},
    "no-negative": {"negative_prompt": None},
    "extra-field-ignored": {"future_field": {"a": 1}},
    "integral-float-width": {"width": 1024.0},
    "with-revision": {"model_revision": REV},
    "with-sha": {"image_sha256": "a" * 64},
    "unicode-prompt": {"prompt": "Dłoń unosi kubek 🎬"},
}

# (mutation, expected substring of the error, schema_rejects) - schema_rejects False = rule JSON Schema cannot express
INVALID_CASES = {
    "version": ({"v": 2}, "version", True),
    "job-id-short": ({"job_id": "mj_abc"}, "job_id", True),
    "job-id-uppercase": ({"job_id": "mj_0123456789ABCDEF01234567"}, "job_id", True),
    "job-id-prefix": ({"job_id": "xx_0123456789abcdef01234567"}, "job_id", True),
    "model-uppercase": ({"model": "Wan"}, "model", True),
    "model-empty": ({"model": ""}, "model", True),
    "prompt-empty": ({"prompt": ""}, "prompt", True),
    "prompt-whitespace": ({"prompt": "   "}, "prompt", False),
    "prompt-too-long": ({"prompt": "x" * 4001}, "prompt", True),
    "width-not-32": ({"width": 1000}, "32", True),
    "height-not-32": ({"height": 570}, "32", True),
    "width-small": ({"width": 224}, "width", True),
    "width-large": ({"width": 1312}, "width", True),
    "height-small": ({"height": 128}, "height", True),
    "pixel-budget": ({"width": 1280, "height": 1280}, "budget", False),
    "frames-not-4n+1": ({"num_frames": 26}, "4n+1", True),
    "frames-low": ({"num_frames": 21}, "num_frames", True),
    "frames-high": ({"num_frames": 125}, "num_frames", True),
    "fps": ({"fps": 25}, "fps", True),
    "steps-low": ({"steps": 7}, "steps", True),
    "steps-high": ({"steps": 41}, "steps", True),
    "guidance-low": ({"guidance_scale": 0.9}, "guidance", True),
    "guidance-high": ({"guidance_scale": 8.1}, "guidance", True),
    "guidance-string": ({"guidance_scale": "4"}, "guidance", True),
    "seed-negative": ({"seed": -1}, "seed", True),
    "seed-too-large": ({"seed": 2**32}, "seed", True),
    "seed-bool": ({"seed": True}, "seed", True),
    "width-fraction": ({"width": 1024.5}, "width", True),
    "image-traversal": ({"image": "../x.jpg"}, "image", True),
    "image-subdir": ({"image": "a/b.jpg"}, "image", True),
    "image-gif": ({"image": "x.gif"}, "image", True),
    "image-no-extension": ({"image": "image"}, "image", True),
    "image-dotted-stem": ({"image": "a.b.jpg"}, "image", True),
    "sha-uppercase": ({"image_sha256": "A" * 64}, "image_sha256", True),
    "sha-short": ({"image_sha256": "ab"}, "image_sha256", True),
    "created-at": ({"created_at": "yesterday"}, "created_at", True),
    "revision-bad": ({"model_revision": "a b"}, "model_revision", True),
    "shot-too-long": ({"shot_id": "s" * 129}, "shot_id", True),
}


def mutate(changes: dict[str, Any]) -> dict[str, Any]:
    doc = dict(BASE)
    for key, value in changes.items():
        if value is None:
            doc.pop(key, None)
        else:
            doc[key] = value
    return doc


@pytest.mark.parametrize("name", VALID_CASES)
def test_valid_requests_are_accepted_by_python_and_schema(name, validate):
    doc = mutate(VALID_CASES[name])
    request = contract.parse_request(doc)
    assert isinstance(request, MotionRequest)
    validate("request", doc)


@pytest.mark.parametrize("name", INVALID_CASES)
def test_invalid_requests_are_rejected_with_the_offending_field(name, validate):
    changes, fragment, schema_rejects = INVALID_CASES[name]
    doc = mutate(changes)
    with pytest.raises(BadRequest, match=re.escape(fragment)) as err:
        contract.parse_request(doc)
    assert err.value.code == "bad_request"
    assert err.value.retryable is False
    if schema_rejects:
        with pytest.raises(Exception, match=r".+"):  # jsonschema.ValidationError
            validate("request", doc)
    else:
        validate("request", doc)  # documented: only the worker-side rule catches it


@pytest.mark.parametrize("missing", sorted(set(BASE) - {"negative_prompt", "campaign_id", "shot_id", "created_at"}))
def test_every_required_field_is_enforced(missing, validate):
    doc = dict(BASE)
    del doc[missing]
    with pytest.raises(BadRequest):
        contract.parse_request(doc)
    with pytest.raises(Exception, match=r".+"):
        validate("request", doc)


def test_non_object_and_missing_version_rejected():
    with pytest.raises(BadRequest, match="object"):
        contract.parse_request(["not", "an", "object"])
    with pytest.raises(BadRequest, match="version"):
        contract.parse_request({k: v for k, v in BASE.items() if k != "v"})


def test_parsed_request_fields_and_defaults():
    request = contract.parse_request(mutate({"negative_prompt": None, "guidance_scale": 4}))
    assert request.negative_prompt == ""
    assert request.guidance_scale == 4.0
    assert isinstance(request.guidance_scale, float)
    assert (request.model_revision, request.image_sha256) == (None, None)
    assert (request.shot_id, request.campaign_id) == ("s1", "cmp")


def test_build_request_roundtrips_and_the_id_is_recomputable(validate):
    image = b"\xff\xd8 pretend jpeg bytes"
    doc = contract.build_request(
        prompt="push-in",
        image_name="image.jpg",
        image_bytes=image,
        width=512,
        height=288,
        num_frames=49,
        seed=9,
        shot_id="s2",
        now=datetime(2026, 11, 18, 18, 0, 0, tzinfo=UTC),
    )
    validate("request", doc)
    assert doc["created_at"] == "2026-11-18T18:00:00Z"
    assert doc["image_sha256"] == sha256_hex(image)
    request = contract.parse_request(doc)
    assert request.expected_job_id(image_sha256=sha256_hex(image), default_revision="ignored") == doc["job_id"]
    # without model_revision the default revision of the worker is used
    bare = contract.parse_request({k: v for k, v in doc.items() if k != "model_revision"})
    assert bare.expected_job_id(image_sha256=sha256_hex(image), default_revision=REV) == doc["job_id"]


# ---------------------------------------------------------------------------------------------- queue messages


def test_queue_message_roundtrip_and_base64_tolerance(validate):
    text = contract.build_queue_message("mj_0123456789abcdef01234567")
    validate("queueMessage", json.loads(text))
    assert contract.parse_queue_message(text) == contract.QueueJob("generate", "mj_0123456789abcdef01234567")
    wrapped = base64.b64encode(text.encode()).decode()
    assert contract.parse_queue_message(wrapped).job_id == "mj_0123456789abcdef01234567"
    warm = contract.new_warmup_id()
    validate("queueMessage", json.loads(contract.build_queue_message(warm)))
    assert contract.parse_queue_message(contract.build_queue_message(warm)).type == "warmup"
    assert contract.parse_queue_message(text.encode()).type == "generate"


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        "[]",
        "{}",
        '{"v":2,"type":"generate","job_id":"mj_0123456789abcdef01234567"}',
        '{"v":1,"type":"explode","job_id":"mj_0123456789abcdef01234567"}',
        '{"v":1,"type":"generate","job_id":"mj_short"}',
        '{"v":1,"type":"generate","job_id":"mj_0123456789abcdef01234567\\n"}',
        '{"v":1,"type":"generate","job_id":"mw_0123456789abcdef0123456789abcdef"}',
        '{"v":1,"type":"warmup","job_id":"mj_0123456789abcdef01234567"}',
        "abcd",
    ],
)
def test_invalid_queue_messages_are_rejected(body):
    with pytest.raises(BadRequest):
        contract.parse_queue_message(body)


# ---------------------------------------------------------------------------------------------- documents


def test_documents_built_by_the_worker_validate_against_the_schema(validate):
    request = contract.parse_request(BASE)
    ok = contract.build_result(
        job_id=request.job_id, request=request, model=request.model, model_revision=REV, gpu_seconds=74.24,
        queue_wait_s=3.14, generate_s=70.5, encode_s=2.4, clip="clip.mp4", width=1024, height=576, num_frames=93,
    )  # fmt: skip
    validate("result", ok)
    assert (ok["state"], ok["error"], ok["gpu_seconds"], ok["timings"]["queue_wait_s"]) == (
        "succeeded",
        None,
        74.2,
        3.1,
    )

    err = BadRequest("nope").to_wire()
    failed = contract.build_result(
        job_id=request.job_id, request=request, model=request.model, model_revision=REV, gpu_seconds=1,
        queue_wait_s=0, generate_s=0, encode_s=0, error=err,
    )  # fmt: skip
    validate("result", failed)
    assert failed["clip"] is None
    assert failed["error"] == {"code": "bad_request", "message": "nope", "retryable": False}

    blind = contract.build_result(
        job_id=request.job_id, request=None, model="wan2.2-ti2v-5b", model_revision=REV, gpu_seconds=0,
        queue_wait_s=0, generate_s=0, encode_s=0,         error=InternalError("x").to_wire(),
    )  # fmt: skip
    validate("result", blind)
    assert blind["width"] is None
    assert blind["seed"] is None

    status = contract.build_status(
        job_id=request.job_id, state="running", progress=1.7, step=3, steps=8, message="denoising", replica="r"
    )
    validate("status", status)
    assert status["progress"] == 1.0
    validate(
        "ready",
        contract.build_ready(
            state="ready",
            replica="r",
            model="m",
            model_revision="rev",
            vram_gib=22.64,
            started_at=contract.utc_now_iso(),
        ),
    )


def test_timestamps():
    now = datetime(2026, 11, 18, 18, 0, 30, tzinfo=UTC)
    assert contract.utc_now_iso(now) == "2026-11-18T18:00:30Z"
    assert contract.parse_iso("2026-11-18T18:00:30Z") == now
    assert contract.parse_iso("2026-11-18T18:00:30") == now
    assert contract.parse_iso("garbage") is None
    assert contract.parse_iso(None) is None


def test_error_wire_shape_and_classification():
    assert OutOfMemory("x").to_wire() == {"code": "oom", "message": "x", "retryable": False}
    assert JobTimeout("x").retryable is True
    assert InternalError("x", retryable=False).retryable is False
    assert classify_exception(BadRequest("b")).code == "bad_request"
    assert classify_exception(RuntimeError("boom")).code == "internal"
    assert classify_exception(RuntimeError("CUDA out of memory. Tried to allocate 2 GiB")).code == "oom"
    assert classify_exception(MemoryError()).code == "oom"

    class OutOfMemoryError(RuntimeError):  # same name as torch.cuda.OutOfMemoryError
        pass

    assert is_out_of_memory(OutOfMemoryError("whatever"))
    try:
        try:
            raise RuntimeError("cuBLAS: CUBLAS_STATUS_ALLOC_FAILED when calling cublasCreate")
        except RuntimeError as inner:
            raise ValueError("wrapped") from inner
    except ValueError as outer:
        assert is_out_of_memory(outer)
    assert not is_out_of_memory(ValueError("fine"))
    assert len(InternalError("y" * 900).to_wire()["message"]) == 500
