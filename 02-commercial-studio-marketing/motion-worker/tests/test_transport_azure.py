"""Azure transport: behaviour with SDK-faithful fakes (always run) and against the real SDK clients (when installed)."""

from __future__ import annotations

import enum
import inspect
import sys
import types

import pytest

from motion_worker.config import Config
from motion_worker.errors import MessageLost
from motion_worker.transport import IN, MODELS, OUT, AzureTransport, BlobInfo

from .azure_fakes import (
    FakeBlobClient,
    FakeBlobService,
    FakeContainerClient,
    FakeDownloader,
    FakeHttpError,
    FakeQueueClient,
    SdkWire,
    StaticTokenCredential,
    write_file,
)

VIS = 600


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def az():
    clock = Clock()
    queue = FakeQueueClient(clock)
    blobs = FakeBlobService()
    transport = AzureTransport(queue_client=queue, blob_service=blobs, content_settings=lambda ct: {"content_type": ct})
    return transport, queue, blobs, clock


# ---------------------------------------------------------------------------------------------- queue


def test_receive_takes_exactly_one_message_and_maps_it(az):
    t, queue, _, _ = az
    for i in range(3):
        t.send(f'{{"n":{i}}}')
    msg = t.receive(VIS)
    assert (msg.body, msg.dequeue_count) == ('{"n":0}', 1)
    assert msg.receipt and msg.id
    call = next(c for c in queue.calls if c[0] == "receive_messages")
    assert call[2] == {"visibility_timeout": VIS, "max_messages": 1}
    # only the first message was claimed: the other two stay visible
    assert sum(1 for m in queue.messages if m.visible_at > 1_000.0) == 1


def test_empty_queue_returns_none(az):
    t, *_ = az
    assert t.receive(VIS) is None


def test_missing_dequeue_count_and_bytes_content_are_normalised(az):
    t, queue, *_ = az
    t.send("x")
    original = queue.receive_messages

    def odd(**kw):
        (m,) = list(original(**kw))
        m.content, m.dequeue_count = b'{"v":1}', None
        return iter([m])

    queue.receive_messages = odd
    msg = t.receive(VIS)
    assert (msg.body, msg.dequeue_count) == ('{"v":1}', 1)


def test_renew_extends_visibility_with_an_explicit_timeout_and_rotates_the_receipt(az):
    t, queue, _, clock = az
    t.send("job")
    msg = t.receive(VIS)
    receipts = [msg.receipt]
    for _ in range(3):
        clock.now += 300
        t.renew(msg, VIS)
        receipts.append(msg.receipt)
        assert t.receive(VIS) is None, "the message must stay invisible while renewed"
    assert len(set(receipts)) == 4
    update = [c for c in queue.calls if c[0] == "update_message"][0]
    assert update[1] == (msg.id,)  # id string, not the message object: the SDK would re-send the content
    assert update[2]["visibility_timeout"] == VIS
    assert update[2]["pop_receipt"] == receipts[0]
    t.delete(msg)
    assert queue.messages == []
    assert [c[2]["pop_receipt"] for c in queue.calls if c[0] == "delete_message"] == [receipts[-1]]


def test_release_makes_the_message_visible_immediately(az):
    t, queue, *_ = az
    t.send("job")
    msg = t.receive(VIS)
    t.release(msg)
    again = t.receive(VIS)
    assert (again.id, again.dequeue_count) == (msg.id, 2)
    assert [c for c in queue.calls if c[0] == "update_message"][0][2]["visibility_timeout"] == 0


@pytest.mark.parametrize("error", [FakeHttpError(404, "MessageNotFound"), FakeHttpError(400, "PopReceiptMismatch")])
@pytest.mark.parametrize("action", ["renew", "release", "delete"])
def test_a_message_that_is_no_longer_ours_raises_message_lost(az, error, action):
    t, queue, *_ = az
    t.send("job")
    msg = t.receive(VIS)
    queue.fail_next["delete_message" if action == "delete" else "update_message"] = error
    call = {"renew": lambda: t.renew(msg, VIS), "release": lambda: t.release(msg), "delete": lambda: t.delete(msg)}[
        action
    ]
    with pytest.raises(MessageLost):
        call()
    assert msg.lost is True


@pytest.mark.parametrize("action", ["renew", "release", "delete"])
def test_other_queue_errors_propagate(az, action):
    t, queue, *_ = az
    t.send("job")
    msg = t.receive(VIS)
    queue.fail_next["delete_message" if action == "delete" else "update_message"] = FakeHttpError(
        403, "AuthorizationFailure"
    )
    call = {"renew": lambda: t.renew(msg, VIS), "release": lambda: t.release(msg), "delete": lambda: t.delete(msg)}[
        action
    ]
    with pytest.raises(FakeHttpError):
        call()
    assert msg.lost is False


class _WireCode(enum.Enum):
    """Like azure.storage StorageErrorCode: a str-valued enum whose str() is 'Class.member', not the wire code."""

    pop_receipt_mismatch = "PopReceiptMismatch"
    container_not_found = "ContainerNotFound"


def test_enum_style_error_codes_are_matched_on_their_wire_value(az):
    t, queue, blobs, _ = az
    t.send("job")
    msg = t.receive(VIS)
    queue.fail_next["delete_message"] = FakeHttpError(400, _WireCode.pop_receipt_mismatch)
    with pytest.raises(MessageLost):
        t.delete(msg)
    blobs.fail_next["download_blob"] = FakeHttpError(404, _WireCode.container_not_found)
    with pytest.raises(FakeHttpError):
        t.read_blob(OUT, "x")


def test_real_stale_receipt_is_reported_as_lost(az):
    t, _, _, clock = az
    t.send("job")
    msg = t.receive(VIS)
    clock.now += VIS + 1  # expired: another consumer receives it and gets a fresh receipt
    other = t.receive(VIS)
    assert other.id == msg.id
    with pytest.raises(MessageLost):
        t.delete(msg)


def test_queue_depth(az):
    t, *_ = az
    t.send("a")
    t.send("b")
    assert t.queue_depth() == 2


# ---------------------------------------------------------------------------------------------- blobs


def test_blob_roundtrip_with_content_types_and_overwrite(az):
    t, _, blobs, _ = az
    assert t.read_blob(OUT, "j/result.json") is None
    assert t.blob_exists(OUT, "j/result.json") is False
    assert t.blob_size(OUT, "j/result.json") is None
    t.write_blob(OUT, "j/result.json", b'{"a":1}')
    t.write_blob(OUT, "j/clip.mp4", b"\x00\x00", "video/mp4")
    assert t.read_blob(OUT, "j/result.json") == b'{"a":1}'
    assert t.blob_exists(OUT, "j/result.json") and t.blob_size(OUT, "j/result.json") == 7
    kinds = {name: blobs.blobs[(OUT and "motion-out", name)][1] for name in ("j/result.json", "j/clip.mp4")}
    assert kinds == {"j/result.json": {"content_type": "application/json"}, "j/clip.mp4": {"content_type": "video/mp4"}}
    upload = [c for c in blobs.calls if c[0] == "upload_blob"][0]
    assert upload[2]["overwrite"] is True
    assert t.delete_blob(OUT, "j/result.json") is True
    assert t.delete_blob(OUT, "j/result.json") is False


def test_areas_use_the_configured_container_names(az):
    t, _, blobs, _ = az
    t.write_blob(IN, "a", b"1")
    t.write_blob(MODELS, "a", b"2")
    assert set(blobs.blobs) == {("motion-in", "a"), ("motion-models", "a")}


def test_listing_downloading_and_uploading_files(az, tmp_path):
    t, _, blobs, _ = az
    src = write_file(tmp_path / "weights.bin", 5000)
    t.upload_from(MODELS, "m/r/transformer/w.bin", src)
    t.write_blob(MODELS, "m/r/manifest.json", b"{}")
    t.write_blob(MODELS, "other/x", b"x")
    assert t.list_blobs(MODELS, "m/r/") == [BlobInfo("m/r/manifest.json", 2), BlobInfo("m/r/transformer/w.bin", 5000)]
    up = [c for c in blobs.calls if c[0] == "upload_blob"][0]
    assert up[2]["length"] == 5000 and up[2]["max_concurrency"] == 8
    dest = tmp_path / "out" / "w.bin"
    t.download_to(MODELS, "m/r/transformer/w.bin", dest)
    assert dest.read_bytes() == src.read_bytes()
    dl = [c for c in blobs.calls if c[0] == "download_blob"][-1]
    assert dl[2]["max_concurrency"] == 8
    assert len(t.list_blobs(MODELS)) == 3


def test_only_a_missing_blob_is_none_other_errors_and_missing_containers_raise(az):
    t, _, blobs, _ = az
    blobs.fail_next["download_blob"] = FakeHttpError(403, "AuthorizationPermissionMismatch")
    with pytest.raises(FakeHttpError):
        t.read_blob(OUT, "x")
    blobs.fail_next["download_blob"] = FakeHttpError(404, "ContainerNotFound")
    with pytest.raises(FakeHttpError):  # a missing container is a deployment error, not "no such blob"
        t.read_blob(OUT, "x")
    blobs.fail_next["get_blob_properties"] = FakeHttpError(500, "InternalError")
    with pytest.raises(FakeHttpError):
        t.blob_size(OUT, "x")


# ---------------------------------------------------------------------------------------------- from_config


def install_fake_sdk(monkeypatch):
    seen: dict = {}

    class DefaultAzureCredential:
        def __init__(self, **kwargs):
            seen["credential"] = kwargs

    class Retry:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class BlobServiceClient:
        def __init__(self, account_url, credential=None, **kwargs):
            seen["blob"] = (account_url, credential, kwargs)

    class QueueClient:
        def __init__(self, account_url, queue_name, credential=None, **kwargs):
            seen["queue"] = (account_url, queue_name, credential, kwargs)

    modules = {
        "azure": types.ModuleType("azure"),
        "azure.identity": types.SimpleNamespace(DefaultAzureCredential=DefaultAzureCredential),
        "azure.storage": types.ModuleType("azure.storage"),
        "azure.storage.blob": types.SimpleNamespace(BlobServiceClient=BlobServiceClient, ExponentialRetry=Retry),
        "azure.storage.queue": types.SimpleNamespace(QueueClient=QueueClient, ExponentialRetry=Retry),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return seen


def azure_cfg(**overrides):
    env = {
        "MOTION_STORAGE_ACCOUNT_URL": "https://stdemo.blob.core.windows.net",
        "MOTION_QUEUE_URL": "https://stdemo.queue.core.windows.net",
        "AZURE_CLIENT_ID": "cid-123",
        "MOTION_QUEUE_NAME": "q-motion",
        "MOTION_IN_CONTAINER": "in-x",
        "MOTION_BLOB_CONCURRENCY": "5",
    }
    env.update(overrides)
    return Config.from_env({k: v for k, v in env.items() if v is not None})


def test_from_config_uses_entra_with_the_user_assigned_identity_and_no_keys(monkeypatch):
    seen = install_fake_sdk(monkeypatch)
    transport = AzureTransport.from_config(azure_cfg())
    assert seen["credential"] == {"managed_identity_client_id": "cid-123"}
    account_url, credential, blob_kwargs = seen["blob"]
    assert account_url == "https://stdemo.blob.core.windows.net"
    assert credential is not None and not isinstance(credential, str)
    q_url, q_name, q_cred, q_kwargs = seen["queue"]
    assert (q_url, q_name) == ("https://stdemo.queue.core.windows.net", "q-motion")
    assert q_cred is credential, "one credential (token cache) for queue and blobs"
    assert blob_kwargs["retry_policy"].kwargs == {
        "initial_backoff": 2, "increment_base": 2, "retry_total": 4, "random_jitter_range": 1,
    }  # fmt: skip
    assert q_kwargs["retry_policy"].kwargs["retry_total"] == 4
    assert transport.containers == {"in": "in-x", "out": "motion-out", "models": "motion-models"}
    assert transport.blob_concurrency == 5
    flat = repr(seen)
    assert "account_key" not in flat and "connection_string" not in flat and "sas" not in flat.lower()


def test_from_config_without_a_client_id_falls_back_to_the_default_chain(monkeypatch):
    seen = install_fake_sdk(monkeypatch)
    AzureTransport.from_config(azure_cfg(AZURE_CLIENT_ID=None))
    assert seen["credential"] == {}


# ---------------------------------------------------------------------------------------------- real SDK


class Spy:
    """Records the exact calls the transport makes so they can be bound to the REAL SDK signatures."""

    def __init__(self, target, kind, log):
        self._t, self._kind, self._log = target, kind, log

    def __getattr__(self, name):
        attr = getattr(self._t, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            self._log.append((self._kind, name, args, kwargs))
            result = attr(*args, **kwargs)
            kinds = {FakeBlobClient: "blob", FakeContainerClient: "container", FakeDownloader: "downloader"}
            return Spy(result, kinds[type(result)], self._log) if type(result) in kinds else result

        return call


def test_every_call_the_transport_makes_binds_to_the_real_sdk_signatures(tmp_path):
    pytest.importorskip("azure.storage.queue")
    blob_mod = pytest.importorskip("azure.storage.blob")
    from azure.storage.queue import QueueClient

    log: list = []
    queue, blobs = FakeQueueClient(Clock()), FakeBlobService()
    t = AzureTransport(
        queue_client=Spy(queue, "queue", log), blob_service=Spy(blobs, "service", log), content_settings=lambda ct: ct
    )
    t.send("m")
    msg = t.receive(VIS)
    t.renew(msg, VIS)
    t.release(msg)
    msg = t.receive(VIS)
    t.delete(msg)
    t.queue_depth()
    t.write_blob(OUT, "a", b"1")
    t.read_blob(OUT, "a")
    t.blob_exists(OUT, "a")
    t.blob_size(OUT, "a")
    t.list_blobs(OUT, "a")
    src = write_file(tmp_path / "f", 300)
    t.upload_from(MODELS, "f", src)
    t.download_to(MODELS, "f", tmp_path / "g")
    t.delete_blob(OUT, "a")

    real = {
        "queue": QueueClient,
        "service": blob_mod.BlobServiceClient,
        "blob": blob_mod.BlobClient,
        "container": blob_mod.ContainerClient,
        "downloader": blob_mod.StorageStreamDownloader,
    }
    assert {k for k, *_ in log} == set(real)
    for kind, name, args, kwargs in log:
        signature = inspect.signature(getattr(real[kind], name))
        signature.bind(object(), *args, **kwargs)  # TypeError = the real SDK would reject this call


@pytest.fixture
def sdk():
    pytest.importorskip("azure.storage.queue")
    pytest.importorskip("azure.storage.blob")
    from azure.storage.blob import BlobServiceClient
    from azure.storage.queue import QueueClient

    wire = SdkWire()
    try:
        http = wire.transport()
    except ImportError:
        pytest.skip("azure-core internals changed; wire-level SDK tests unavailable")
    credential = StaticTokenCredential()
    transport = AzureTransport(
        queue_client=QueueClient(
            "https://acct.queue.core.windows.net", "motion-jobs", credential=credential, transport=http
        ),
        blob_service=BlobServiceClient("https://acct.blob.core.windows.net", credential=credential, transport=http),
    )
    return transport, wire


def test_real_sdk_queue_flow_receive_renew_release_delete(sdk):
    t, wire = sdk
    wire.add_message('{"v":1,"type":"generate","job_id":"mj_0123456789abcdef01234567"}')
    wire.add_message("second")
    msg = t.receive(VIS)
    assert msg.body.startswith('{"v":1') and msg.dequeue_count == 1 and msg.inserted_at is not None
    assert wire.requests[0] == ("GET", "/motion-jobs/messages", {"numofmessages": "1", "visibilitytimeout": "600"})
    first = msg.receipt
    t.renew(msg, VIS)
    assert msg.receipt != first
    put = wire.requests[1]
    assert put[0] == "PUT" and put[2] == {"popreceipt": first, "visibilitytimeout": "600"}
    t.delete(msg)
    assert wire.requests[2][2] == {"popreceipt": msg.receipt}
    assert [m["text"] for m in wire.queue] == ["second"]

    other = t.receive(VIS)
    t.release(other)
    assert wire.requests[-1][2]["visibilitytimeout"] == "0"


def test_real_sdk_errors_are_mapped_to_message_lost(sdk):
    t, wire = sdk
    wire.add_message("x")
    msg = t.receive(VIS)
    good = msg.receipt
    msg.receipt = "bogus"
    with pytest.raises(MessageLost):  # 400 PopReceiptMismatch
        t.renew(msg, VIS)
    msg.receipt, msg.lost = good, False
    t.delete(msg)
    with pytest.raises(MessageLost):  # 404 MessageNotFound
        t.delete(msg)
    assert msg.lost is True


def test_real_sdk_blob_flow_and_error_semantics(sdk, tmp_path):
    t, wire = sdk
    assert t.read_blob(OUT, "j/result.json") is None
    assert t.blob_exists(OUT, "j/result.json") is False
    assert t.blob_size(OUT, "j/result.json") is None
    t.write_blob(OUT, "j/result.json", b'{"ok":true}')
    assert t.read_blob(OUT, "j/result.json") == b'{"ok":true}'
    assert t.blob_exists(OUT, "j/result.json") and t.blob_size(OUT, "j/result.json") == 11
    src = write_file(tmp_path / "f.bin", 4096)
    t.upload_from(MODELS, "m/r/f.bin", src)
    dest = tmp_path / "dl" / "f.bin"
    t.download_to(MODELS, "m/r/f.bin", dest)
    assert dest.read_bytes() == src.read_bytes()
    assert t.list_blobs(MODELS, "m/r/") == [BlobInfo("m/r/f.bin", 4096)]
    assert t.delete_blob(OUT, "j/result.json") is True
    assert t.delete_blob(OUT, "j/result.json") is False


def test_real_sdk_non_404_blob_errors_are_not_swallowed(sdk, monkeypatch):
    from azure.core.exceptions import HttpResponseError

    t, wire = sdk
    original = wire._blob
    monkeypatch.setattr(
        wire, "_blob", lambda *a, **k: (403, {"x-ms-error-code": "AuthorizationPermissionMismatch"}, b"")
    )
    with pytest.raises(HttpResponseError):
        t.read_blob(OUT, "x")
    with pytest.raises(HttpResponseError):
        t.blob_exists(OUT, "x")
    monkeypatch.setattr(wire, "_blob", original)


def test_from_config_builds_real_clients_without_network():
    pytest.importorskip("azure.identity")
    pytest.importorskip("azure.storage.queue")
    pytest.importorskip("azure.storage.blob")
    transport = AzureTransport.from_config(azure_cfg())
    assert transport._queue.queue_name == "q-motion"
    assert transport._queue.url.startswith("https://stdemo.queue.core.windows.net/q-motion")
    assert transport._blobs.url.startswith("https://stdemo.blob.core.windows.net")
    assert transport.containers["in"] == "in-x"
