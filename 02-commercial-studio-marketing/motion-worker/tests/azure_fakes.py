"""Fakes for the Azure transport tests.

* ``FakeQueueClient`` / ``FakeBlobService``: in-memory objects with the *keyword-only signatures and the quirks* of
  the real azure-storage SDKs (e.g. ``update_message`` without ``visibility_timeout`` makes the message visible;
  ``receive_messages`` without ``max_messages`` drains the queue). No SDK import needed.
* ``SdkWire``: a canned HTTP layer so the REAL SDK clients can be driven without any network (SDK tests only).
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


class FakeHttpError(Exception):
    """Duck-types azure.core.exceptions.HttpResponseError (status_code + error_code)."""

    def __init__(self, status_code: int, error_code: str = "") -> None:
        super().__init__(f"{status_code} {error_code}")
        self.status_code = status_code
        self.error_code = error_code


@dataclass
class _Msg:
    id: str
    content: str
    inserted_on: float
    dequeue_count: int = 0
    pop_receipt: str = ""
    visible_at: float = 0.0
    next_visible_on: Any = None
    expires_on: Any = None


class FakeQueueClient:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.messages: list[_Msg] = []
        self.calls: list[tuple[str, tuple, dict]] = []
        self.fail_next: dict[str, Exception] = {}

    def _record(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.append((name, args, kwargs))
        if name in self.fail_next:
            raise self.fail_next.pop(name)

    def send_message(self, content, *, visibility_timeout=None, time_to_live=None, timeout=None, **kwargs):
        self._record("send_message", (content,), {})
        self.messages.append(_Msg(id=uuid.uuid4().hex, content=content, inserted_on=self.clock()))

    def receive_messages(
        self, *, messages_per_page=None, visibility_timeout=None, max_messages=None, timeout=None, **kw
    ):
        self._record("receive_messages", (), {"visibility_timeout": visibility_timeout, "max_messages": max_messages})
        now = self.clock()
        out = []
        for m in self.messages:
            if m.visible_at <= now and (max_messages is None or len(out) < max_messages):
                m.dequeue_count += 1
                m.pop_receipt = uuid.uuid4().hex
                m.visible_at = now + (30 if visibility_timeout is None else visibility_timeout)
                out.append(_Msg(**m.__dict__))
        return iter(out)

    def _find(self, message: Any, pop_receipt: str | None) -> _Msg:
        message_id = getattr(message, "id", message)
        receipt = pop_receipt or getattr(message, "pop_receipt", None)
        if receipt is None:
            raise ValueError("pop_receipt must be present")
        for m in self.messages:
            if m.id == message_id:
                if m.pop_receipt != receipt:
                    raise FakeHttpError(400, "PopReceiptMismatch")
                return m
        raise FakeHttpError(404, "MessageNotFound")

    def update_message(self, message, pop_receipt=None, content=None, *, visibility_timeout=None, timeout=None, **kw):
        self._record(
            "update_message", (message,), {"pop_receipt": pop_receipt, "visibility_timeout": visibility_timeout}
        )
        m = self._find(message, pop_receipt)
        m.visible_at = self.clock() + (visibility_timeout or 0)  # the SDK sends 0 when it is omitted
        m.pop_receipt = uuid.uuid4().hex
        return _Msg(**m.__dict__)

    def delete_message(self, message, pop_receipt=None, *, timeout=None, **kw):
        self._record("delete_message", (message,), {"pop_receipt": pop_receipt})
        self.messages.remove(self._find(message, pop_receipt))

    def get_queue_properties(self, *, timeout=None, **kw):
        self._record("get_queue_properties", (), {})
        return type("Props", (), {"approximate_message_count": len(self.messages)})()


class FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def readall(self) -> bytes:
        return self.data

    def readinto(self, stream) -> int:
        stream.write(self.data)
        return len(self.data)


class FakeBlobClient:
    def __init__(self, service: FakeBlobService, container: str, name: str) -> None:
        self.s, self.c, self.n = service, container, name

    def _key(self) -> tuple[str, str]:
        return self.c, self.n

    def upload_blob(self, data, blob_type="BlockBlob", length=None, metadata=None, **kwargs):
        self.s.calls.append(("upload_blob", self._key(), dict(kwargs, length=length)))
        payload = data.read() if hasattr(data, "read") else data
        if isinstance(payload, str):
            payload = payload.encode()
        if self.s.fail_next.get("upload_blob"):
            raise self.s.fail_next.pop("upload_blob")
        self.s.blobs[self._key()] = (bytes(payload), kwargs.get("content_settings"))

    def download_blob(self, offset=None, length=None, *, encoding=None, **kwargs):
        self.s.calls.append(("download_blob", self._key(), dict(kwargs)))
        if self.s.fail_next.get("download_blob"):
            raise self.s.fail_next.pop("download_blob")
        if self._key() not in self.s.blobs:
            raise FakeHttpError(404, "BlobNotFound")
        return FakeDownloader(self.s.blobs[self._key()][0])

    def exists(self, **kwargs):
        return self._key() in self.s.blobs

    def get_blob_properties(self, **kwargs):
        if self.s.fail_next.get("get_blob_properties"):
            raise self.s.fail_next.pop("get_blob_properties")
        if self._key() not in self.s.blobs:
            raise FakeHttpError(404, "BlobNotFound")
        return type("Props", (), {"size": len(self.s.blobs[self._key()][0])})()

    def delete_blob(self, delete_snapshots=None, **kwargs):
        if self._key() not in self.s.blobs:
            raise FakeHttpError(404, "BlobNotFound")
        del self.s.blobs[self._key()]


class FakeContainerClient:
    def __init__(self, service: FakeBlobService, container: str) -> None:
        self.s, self.c = service, container

    def list_blobs(self, name_starts_with=None, include=None, **kwargs):
        return iter(
            [
                type("B", (), {"name": n, "size": len(d[0])})()
                for (c, n), d in sorted(self.s.blobs.items())
                if c == self.c and n.startswith(name_starts_with or "")
            ]
        )


class FakeBlobService:
    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], tuple[bytes, Any]] = {}
        self.calls: list[tuple[str, tuple, dict]] = []
        self.fail_next: dict[str, Exception] = {}

    def get_blob_client(self, container, blob, snapshot=None, *, version_id=None):
        return FakeBlobClient(self, container, blob)

    def get_container_client(self, container):
        return FakeContainerClient(self, container)


# ----------------------------------------------------------------------------------------------------------
# Real SDK clients over a canned wire
# ----------------------------------------------------------------------------------------------------------

HDR = {
    "ETag": '"0x1"',
    "Last-Modified": "Wed, 18 Nov 2026 18:00:00 GMT",
    "x-ms-blob-type": "BlockBlob",
    "x-ms-request-server-encrypted": "true",
}


def _xml_error(status: int, code: str) -> tuple[int, dict, bytes]:
    body = f'<?xml version="1.0"?><Error><Code>{code}</Code><Message>{code}</Message></Error>'
    return status, {"x-ms-error-code": code, "Content-Type": "application/xml"}, body.encode()


def _body(request: Any) -> bytes:
    body = request.body
    if isinstance(body, bytes | bytearray):
        return bytes(body)
    return body.read() if hasattr(body, "read") else b""


@dataclass
class SdkWire:
    """Behaves like the Queue + Blob REST endpoints for the handful of operations the worker uses."""

    queue_name: str = "motion-jobs"
    requests: list[tuple[str, str, dict]] = field(default_factory=list)
    queue: list[dict] = field(default_factory=list)
    blobs: dict[str, bytes] = field(default_factory=dict)
    receipt_seq: int = 0

    def add_message(self, text: str, *, dequeue_count: int = 0) -> str:
        message_id = uuid.uuid4().hex
        self.queue.append({"id": message_id, "text": text, "count": dequeue_count, "receipt": ""})
        return message_id

    def handle(self, request: Any) -> tuple[int, dict, bytes]:
        parsed = urlparse(request.url)
        q = parse_qs(parsed.query)
        path = parsed.path
        self.requests.append((request.method, path, {k: v[0] for k, v in q.items()}))
        if parsed.hostname and ".queue." in parsed.hostname:
            return self._queue(request, path, q)
        return self._blob(request, path, q)

    # -- queue --
    def _queue(self, request: Any, path: str, q: dict) -> tuple[int, dict, bytes]:
        base = f"/{self.queue_name}/messages"
        if request.method == "GET" and path == base:
            wanted = int(q.get("numofmessages", ["1"])[0])
            items = []
            for m in self.queue[:wanted]:
                m["count"] += 1
                self.receipt_seq += 1
                m["receipt"] = f"R{self.receipt_seq}"
                items.append(
                    "<QueueMessage>"
                    f"<MessageId>{m['id']}</MessageId>"
                    "<InsertionTime>Wed, 18 Nov 2026 18:00:00 GMT</InsertionTime>"
                    "<ExpirationTime>Wed, 25 Nov 2026 18:00:00 GMT</ExpirationTime>"
                    f"<PopReceipt>{m['receipt']}</PopReceipt>"
                    "<TimeNextVisible>Wed, 18 Nov 2026 18:10:00 GMT</TimeNextVisible>"
                    f"<DequeueCount>{m['count']}</DequeueCount>"
                    f"<MessageText>{m['text']}</MessageText>"
                    "</QueueMessage>"
                )
            xml = f'<?xml version="1.0" encoding="utf-8"?><QueueMessagesList>{"".join(items)}</QueueMessagesList>'
            return 200, {"Content-Type": "application/xml"}, xml.encode()
        if path.startswith(base + "/"):
            message_id = path.rsplit("/", 1)[1]
            message = next((m for m in self.queue if m["id"] == message_id), None)
            if message is None:
                return _xml_error(404, "MessageNotFound")
            if q.get("popreceipt", [""])[0] != message["receipt"]:
                return _xml_error(400, "PopReceiptMismatch")
            if request.method == "PUT":
                self.receipt_seq += 1
                message["receipt"] = f"R{self.receipt_seq}"
                if q.get("visibilitytimeout", ["0"])[0] == "0":
                    message["receipt"] = ""
                return (
                    204,
                    {"x-ms-popreceipt": f"R{self.receipt_seq}", "x-ms-time-next-visible": HDR["Last-Modified"]},
                    b"",
                )
            if request.method == "DELETE":
                self.queue.remove(message)
                return 204, {}, b""
        return 500, {}, b"unexpected queue request"

    # -- blob --
    def _blob(self, request: Any, path: str, q: dict) -> tuple[int, dict, bytes]:
        method = request.method
        comp = q.get("comp", [""])[0]
        if method == "PUT" and not comp:
            data = _body(request)
            self.blobs[path] = data
            return 201, {**HDR, "Content-MD5": base64.b64encode(hashlib.md5(data).digest()).decode()}, b""
        if method == "PUT" and comp == "block":
            data = _body(request)
            self.blobs.setdefault(path + "#blocks", {})[q["blockid"][0]] = data  # type: ignore[assignment]
            return 201, {"Content-MD5": base64.b64encode(hashlib.md5(data).digest()).decode()}, b""
        if method == "PUT" and comp == "blocklist":
            blocks = self.blobs.pop(path + "#blocks", {})
            ids = re.findall(rb"<Latest>(.*?)</Latest>", _body(request))
            self.blobs[path] = b"".join(blocks[i.decode()] for i in ids)  # type: ignore[index]
            return 201, HDR, b""
        if method == "HEAD":
            if path not in self.blobs:
                return 404, {"x-ms-error-code": "BlobNotFound"}, b""
            headers = {
                **HDR,
                "Content-Length": str(len(self.blobs[path])),
                "Content-Type": "application/octet-stream",
                "x-ms-lease-status": "unlocked",
                "x-ms-lease-state": "available",
                "Accept-Ranges": "bytes",
                "x-ms-creation-time": HDR["Last-Modified"],
            }
            return 200, headers, b""
        if method == "GET" and q.get("restype") == ["container"] and comp == "list":
            prefix = path + "/" + q.get("prefix", [""])[0]
            modified = HDR["Last-Modified"]
            items = "".join(
                f"<Blob><Name>{p[len(path) + 1 :]}</Name><Properties>"
                f"<Creation-Time>{modified}</Creation-Time><Last-Modified>{modified}</Last-Modified><Etag>0x1</Etag>"
                f"<Content-Length>{len(v)}</Content-Length><Content-Type>application/octet-stream</Content-Type>"
                "<BlobType>BlockBlob</BlobType></Properties></Blob>"
                for p, v in sorted(self.blobs.items())
                if p.startswith(prefix) and not p.endswith("#blocks")
            )
            xml = (
                '<?xml version="1.0"?><EnumerationResults ServiceEndpoint="https://acct.blob.core.windows.net/" '
                f'ContainerName="c"><Blobs>{items}</Blobs><NextMarker /></EnumerationResults>'
            )
            return 200, {"Content-Type": "application/xml"}, xml.encode()
        if method == "GET":
            if path not in self.blobs:
                return _xml_error(404, "BlobNotFound")
            data = self.blobs[path]
            headers = {
                **HDR,
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}",
                "Content-Type": "application/octet-stream",
            }
            return 206, headers, data
        if method == "DELETE":
            if path not in self.blobs:
                return _xml_error(404, "BlobNotFound")
            del self.blobs[path]
            return 202, {}, b""
        return 500, {}, b"unexpected blob request"

    def transport(self) -> Any:
        """An azure-core HttpTransport serving this wire. Raises ImportError if azure-core internals moved."""
        import requests
        from azure.core.pipeline._tools import handle_non_stream_rest_response, is_rest
        from azure.core.pipeline.transport import HttpTransport, RequestsTransportResponse
        from azure.core.rest._requests_basic import RestRequestsTransportResponse

        wire = self

        class Transport(HttpTransport):
            def open(self) -> None:
                return None

            def close(self) -> None:
                return None

            def __enter__(self) -> Transport:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

            def send(self, request: Any, **kwargs: Any) -> Any:
                status, headers, body = wire.handle(request)
                response = requests.Response()
                response.status_code, response.reason, response.url = status, "x", request.url
                response.headers.update(headers)
                response.raw = io.BytesIO(body)
                response._content, response._content_consumed = False, False
                if is_rest(request):
                    rest = RestRequestsTransportResponse(request=request, internal_response=response, block_size=4096)
                    if not kwargs.get("stream"):
                        handle_non_stream_rest_response(rest)
                    return rest
                return RequestsTransportResponse(request, response, 4096)

        return Transport()


class StaticTokenCredential:
    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        from azure.core.credentials import AccessToken

        return AccessToken("fake-token", int(time.time()) + 3600)


def write_file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(range(256)) * (size // 256) + bytes(size % 256))
    return path
