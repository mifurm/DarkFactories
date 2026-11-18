"""Azure transport of the motion protocol: Storage Queue (jobs) + Blob Storage (inputs / outputs), Entra ID only — no keys, no connection strings.

Studio's identity holds *Storage Queue Data Message Sender* and *Storage Blob Data Contributor*; the GPU worker (no ingress, scale-to-zero by a KEDA
queue rule) holds *Queue Data Message Processor* and Blob Data Contributor. Real-Azure behaviour is covered by the deployed smoke test; the protocol
itself is unit-tested against in-memory fakes of ``QueueClient`` / ``BlobServiceClient``.
"""

from __future__ import annotations

import json
from typing import Any

from . import wire
from .queue_client import QueueMotionClient

MESSAGE_TTL_S = 3600  # a job message nobody collected within an hour is stale (Studio gave up long before): it must not wake the GPU later


class AzureTransport:
    name = "azure"

    def __init__(self, queue: Any, blobs: Any, in_container: str = wire.IN_PREFIX, out_container: str = wire.OUT_PREFIX) -> None:
        self._queue = queue
        self._blobs = blobs
        self._in = in_container
        self._out = out_container

    async def put_input(self, job_id: str, name: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        blob = self._blobs.get_blob_client(container=self._in, blob=f"{job_id}/{name}")
        await blob.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))

    async def get_output(self, job_id: str, name: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        blob = self._blobs.get_blob_client(container=self._out, blob=f"{job_id}/{name}")
        try:
            stream = await blob.download_blob()
            return bytes(await stream.readall())
        except ResourceNotFoundError:
            return None

    async def delete_output(self, job_id: str, name: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            await self._blobs.get_blob_client(container=self._out, blob=f"{job_id}/{name}").delete_blob()
        except ResourceNotFoundError:
            return

    async def enqueue(self, message: dict[str, Any]) -> None:
        await self._queue.send_message(json.dumps(message), time_to_live=MESSAGE_TTL_S)

    async def queue_depth(self) -> int:
        props = await self._queue.get_queue_properties()
        return int(getattr(props, "approximate_message_count", 0) or 0)  # counts messages being processed too

    async def close(self) -> None:
        for client in (self._queue, self._blobs):
            close = getattr(client, "close", None)
            if close is not None:
                await close()


class AzureMotionClient(QueueMotionClient):
    """Queue + blob motion backend (``MOTION_MODE=azure``)."""

    def __init__(self, transport: AzureTransport, *, model: str = wire.MODEL_ID, revision: str = wire.MODEL_REVISION, **kw: Any) -> None:
        super().__init__(transport, name="azure", model=model, revision=revision, license=wire.MODEL_LICENSES.get(model, ""), host=wire.HOST_AZURE, **kw)

    @classmethod
    def from_settings(cls, settings: Any, credential: Any) -> AzureMotionClient:
        from azure.storage.blob.aio import BlobServiceClient
        from azure.storage.queue.aio import QueueClient

        queue = QueueClient(account_url=settings.motion_queue_url, queue_name=settings.motion_queue_name, credential=credential)
        blobs = BlobServiceClient(account_url=settings.motion_blob_account_url_or_default, credential=credential)
        transport = AzureTransport(queue, blobs, settings.motion_in_container, settings.motion_out_container)
        return cls(transport, model=settings.motion_model, revision=settings.motion_model_revision or wire.MODEL_REVISION)
