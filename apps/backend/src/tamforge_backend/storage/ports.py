"""Object-storage application port."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from .models import PresignedRequest, PresignPutRequest, StoredObject


class ObjectStore(Protocol):
    async def put_immutable(
        self,
        *,
        key: str,
        body: AsyncIterator[bytes],
        sha256: str,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject: ...

    async def stat(self, key: str) -> StoredObject | None: ...

    def open(self, key: str) -> AbstractAsyncContextManager[AsyncIterator[bytes]]: ...

    async def presign_put(self, request: PresignPutRequest) -> PresignedRequest: ...

    async def presign_get(self, key: str, *, expires_seconds: int) -> str: ...
