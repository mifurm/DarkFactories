"""Local-dir transport: blob IO, path safety, and Azure-like queue semantics (visibility, receipts, dequeue count)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from motion_worker.config import Config
from motion_worker.errors import MessageLost
from motion_worker.transport import IN, MODELS, OUT, LocalTransport, build_transport

from .conftest import make_cfg


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def bus(tmp_path):
    clock = Clock()
    return LocalTransport(tmp_path / "bus", clock=clock), clock


# ---------------------------------------------------------------------------------------------- blobs


def test_blob_roundtrip_overwrite_size_exists_delete(bus):
    t, _ = bus
    assert t.read_blob(OUT, "j/result.json") is None
    assert not t.blob_exists(OUT, "j/result.json")
    assert t.blob_size(OUT, "j/result.json") is None
    t.write_blob(OUT, "j/result.json", b'{"a":1}')
    assert t.read_blob(OUT, "j/result.json") == b'{"a":1}'
    assert t.blob_exists(OUT, "j/result.json")
    assert t.blob_size(OUT, "j/result.json") == 7
    t.write_blob(OUT, "j/result.json", b"xy")
    assert t.read_blob(OUT, "j/result.json") == b"xy"
    assert t.delete_blob(OUT, "j/result.json") is True
    assert t.delete_blob(OUT, "j/result.json") is False


def test_areas_map_to_the_container_directories(bus, tmp_path):
    t, _ = bus
    t.write_blob(IN, "a", b"1")
    t.write_blob(OUT, "a", b"2")
    t.write_blob(MODELS, "a", b"3")
    root = tmp_path / "bus"
    assert (root / "motion-in" / "a").read_bytes() == b"1"
    assert (root / "motion-out" / "a").read_bytes() == b"2"
    assert (root / "motion-models" / "a").read_bytes() == b"3"
    assert t.read_blob(IN, "a") == b"1"


@pytest.mark.parametrize("name", ["../escape", "a/../../escape", "/etc/passwd", "", "."])
def test_unsafe_blob_names_are_rejected(bus, name):
    t, _ = bus
    with pytest.raises(ValueError, match="unsafe"):
        t.write_blob(OUT, name, b"x")
    with pytest.raises(ValueError, match="unsafe"):
        t.read_blob(OUT, name)


def test_list_blobs_filters_by_prefix_and_ignores_temp_files(bus, tmp_path):
    t, _ = bus
    t.write_blob(MODELS, "m/r/transformer/a.safetensors", b"aaa")
    t.write_blob(MODELS, "m/r/model_index.json", b"{}")
    t.write_blob(MODELS, "other/x", b"x")
    (tmp_path / "bus" / "motion-models" / "m" / "r" / ".partial.tmp").write_bytes(b"junk")
    listing = t.list_blobs(MODELS, "m/r/")
    assert [(b.name, b.size) for b in listing] == [("m/r/model_index.json", 2), ("m/r/transformer/a.safetensors", 3)]
    assert t.list_blobs(IN) == []
    assert len(t.list_blobs(MODELS)) == 3


def test_download_and_upload_copy_files(bus, tmp_path):
    t, _ = bus
    src = tmp_path / "src.bin"
    src.write_bytes(b"0123456789")
    t.upload_from(MODELS, "w/f.bin", src)
    assert t.read_blob(MODELS, "w/f.bin") == b"0123456789"
    dest = tmp_path / "dl" / "deep" / "f.bin"
    t.download_to(MODELS, "w/f.bin", dest)
    assert dest.read_bytes() == b"0123456789"
    with pytest.raises(FileNotFoundError):
        t.download_to(MODELS, "w/missing.bin", tmp_path / "x")


# ---------------------------------------------------------------------------------------------- queue


def test_fifo_and_exclusive_claim(bus):
    t, _ = bus
    for i in range(3):
        t.send(f'{{"n":{i}}}')
    assert t.queue_depth() == 3
    first = t.receive(60)
    second = t.receive(60)
    assert (first.body, second.body) == ('{"n":0}', '{"n":1}')
    assert first.dequeue_count == 1
    assert first.inserted_at is not None
    assert t.queue_depth() == 3  # in-flight messages still count (like Azure's approximate count)
    assert t.receive(60).body == '{"n":2}'
    assert t.receive(60) is None


def test_message_reappears_after_the_visibility_timeout_with_a_higher_dequeue_count(bus):
    t, clock = bus
    t.send("hello")
    first = t.receive(10)
    clock.now += 9
    assert t.receive(10) is None  # still invisible
    clock.now += 2
    again = t.receive(10)
    assert (again.id, again.body, again.dequeue_count) == (first.id, "hello", 2)
    clock.now += 11
    assert t.receive(10).dequeue_count == 3
    with pytest.raises(MessageLost):  # the first consumer's receipt is long obsolete
        t.delete(first)
    assert first.lost is True


def test_renew_extends_visibility_and_rotates_the_receipt(bus):
    t, clock = bus
    t.send("work")
    msg = t.receive(10)
    first_receipt = msg.receipt
    for _ in range(4):  # 4 x 8 s = 32 s of work, far beyond the original 10 s
        clock.now += 8
        t.renew(msg, 10)
        assert t.receive(10) is None
    assert msg.receipt != first_receipt
    t.delete(msg)
    assert t.queue_depth() == 0


def test_stale_receipts_cannot_renew_release_or_delete(bus):
    t, _ = bus
    t.send("m")
    msg = t.receive(10)
    old = msg.receipt
    t.renew(msg, 10)
    stale = type(msg)(id=msg.id, body=msg.body, dequeue_count=1, receipt=old)
    for action in (lambda: t.renew(stale, 10), lambda: t.release(stale), lambda: t.delete(stale)):
        with pytest.raises(MessageLost):
            action()
    t.delete(msg)
    with pytest.raises(MessageLost):  # already deleted
        t.delete(msg)


def test_release_makes_the_message_visible_immediately_and_keeps_the_count(bus):
    t, _ = bus
    t.send("again")
    msg = t.receive(600)
    t.release(msg)
    assert t.queue_depth() == 1
    back = t.receive(600)
    assert (back.body, back.dequeue_count) == ("again", 2)


def test_empty_files_from_non_atomic_producers_are_skipped(bus, tmp_path):
    t, _ = bus
    (tmp_path / "bus" / "queue" / "00000000000000000001-torn.json").write_bytes(b"")
    assert t.receive(10) is None
    (tmp_path / "bus" / "queue" / "00000000000000000001-torn.json").write_text('{"v":1}')
    assert t.receive(10).body == '{"v":1}'


def test_each_message_is_delivered_to_exactly_one_of_many_competing_consumers(tmp_path):
    root = tmp_path / "bus"
    producer = LocalTransport(root)
    for i in range(24):
        producer.send(str(i))
    seen: list[str] = []
    lock = threading.Lock()

    def consume() -> None:
        consumer = LocalTransport(root)  # separate instance, like a separate process
        while (msg := consumer.receive(60)) is not None:
            with lock:
                seen.append(msg.body)
            consumer.delete(msg)

    threads = [threading.Thread(target=consume) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(30)
    assert sorted(seen, key=int) == [str(i) for i in range(24)]
    assert producer.queue_depth() == 0


def test_build_transport_selects_the_local_implementation(tmp_path):
    cfg = make_cfg(tmp_path)
    transport = build_transport(cfg)
    assert isinstance(transport, LocalTransport)
    assert transport.containers == {"in": "motion-in", "out": "motion-out", "models": "motion-models"}
    assert isinstance(cfg, Config)
    assert Path(transport.root) == cfg.local_dir
