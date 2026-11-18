"""The JSON Schema file: valid draft 2020-12, its examples validate, and it is strict where the contract says so."""

from __future__ import annotations

import copy
from typing import Any

import pytest


def walk_examples(node: Any, path: str = "#"):
    if isinstance(node, dict):
        for example in node.get("examples", []) if isinstance(node.get("examples"), list) else []:
            yield path, example
        for key, value in node.items():
            if key != "examples":
                yield from walk_examples(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_examples(value, f"{path}/{index}")


def test_schema_is_a_valid_draft_2020_12_document(schema):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$schema"].endswith("2020-12/schema")
    assert set(schema["$defs"]) >= {"queueMessage", "request", "status", "result", "ready", "error", "jobId"}


def test_every_example_in_the_schema_validates(schema, validate):
    examples = list(walk_examples(schema["$defs"]))
    assert len(examples) >= 6
    by_def = {
        "queueMessage": "queueMessage",
        "request": "request",
        "status": "status",
        "result": "result",
        "ready": "ready",
    }
    checked = 0
    for path, example in examples:
        top = path.split("/")[1]
        validate(by_def[top], example)
        checked += 1
    assert checked == len(examples)


STATUS = {
    "v": 1,
    "job_id": "mj_0123456789abcdef01234567",
    "state": "running",
    "progress": 0.5,
    "step": 4,
    "steps": 8,
    "message": "denoising",
    "replica": "r1",
    "updated_at": "2026-11-18T18:00:00Z",
}


def test_worker_written_documents_are_strict(validate):
    validate("status", STATUS)
    for bad in (
        {**STATUS, "extra": 1},
        {**STATUS, "state": "paused"},
        {**STATUS, "progress": 1.5},
        {**STATUS, "updated_at": "2026-11-18 18:00:00"},
        {k: v for k, v in STATUS.items() if k != "replica"},
    ):
        with pytest.raises(Exception, match=r".+"):
            validate("status", bad)


def test_result_requires_consistent_state_clip_and_error(schema, validate):
    ok = copy.deepcopy(schema["$defs"]["result"]["examples"][0])
    failed = copy.deepcopy(schema["$defs"]["result"]["examples"][1])
    validate("result", ok)
    validate("result", failed)
    for bad in (
        {**ok, "error": failed["error"]},  # succeeded but carries an error
        {**ok, "clip": None},  # succeeded without a clip
        {**failed, "clip": "clip.mp4"},  # failed with a clip
        {**failed, "error": None},  # failed without an error
        {**failed, "error": {**failed["error"], "code": "kaboom"}},
        {k: v for k, v in ok.items() if k != "timings"},
        {**ok, "timings": {"queue_wait_s": 1, "generate_s": 1}},
    ):
        with pytest.raises(Exception, match=r".+"):
            validate("result", bad)
    # a failure before the request was readable has null echo fields
    blind = {**failed, "width": None, "height": None, "fps": None, "num_frames": None, "seed": None}
    validate("result", blind)


def test_ready_states_are_only_ready_or_loading(schema, validate):
    ready = copy.deepcopy(schema["$defs"]["ready"]["examples"][0])
    validate("ready", {**ready, "state": "loading"})
    for bad in ({**ready, "state": "cold"}, {**ready, "vram_gib": -1}, {**ready, "busy": True}):
        with pytest.raises(Exception, match=r".+"):
            validate("ready", bad)


def test_request_allows_unknown_fields_but_pins_the_frame_grid(schema, validate):
    example = copy.deepcopy(schema["$defs"]["request"]["examples"][0])
    validate("request", {**example, "future": True})
    frames = schema["$defs"]["request"]["properties"]["num_frames"]["enum"]
    assert frames == list(range(25, 122, 4))
    assert len(frames) == 25
