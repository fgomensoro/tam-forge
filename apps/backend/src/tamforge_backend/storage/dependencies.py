"""FastAPI dependency wiring for the private object store."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from ..config import Settings
from .ports import ObjectStore
from .s3 import S3ObjectStore


def get_object_store(request: Request) -> ObjectStore:
    configured = getattr(request.app.state, "object_store", None)
    if configured is not None:
        return cast(ObjectStore, configured)
    settings = cast(Settings, request.app.state.settings)
    store = S3ObjectStore(
        endpoint_url=settings.object_store_endpoint,
        region=settings.object_store_region,
        bucket=settings.object_store_bucket,
        access_key=settings.object_store_access_key.get_secret_value(),
        secret_key=settings.object_store_secret_key.get_secret_value(),
        max_upload_bytes=settings.object_store_max_upload_bytes,
        memory_spool_bytes=settings.object_store_memory_spool_bytes,
    )
    request.app.state.object_store = store
    return store
