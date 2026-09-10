"""FastAPI dependency wiring for the private object store."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from ..config import Settings
from .ports import ObjectStore
from .s3 import S3ObjectStore


def create_object_store(settings: Settings) -> ObjectStore:
    """Build the configured store. Separate from the dependency so the application
    lifespan can build one without a request, for the ingest health heartbeat."""
    return S3ObjectStore(
        endpoint_url=settings.object_store_endpoint,
        region=settings.object_store_region,
        addressing_style=settings.object_store_addressing_style,
        bucket=settings.object_store_bucket,
        access_key=settings.object_store_access_key.get_secret_value(),
        secret_key=settings.object_store_secret_key.get_secret_value(),
        max_upload_bytes=settings.object_store_max_upload_bytes,
        memory_spool_bytes=settings.object_store_memory_spool_bytes,
        max_concurrent_uploads=settings.object_store_max_concurrent_uploads,
    )


def get_object_store(request: Request) -> ObjectStore:
    configured = getattr(request.app.state, "object_store", None)
    if configured is not None:
        return cast(ObjectStore, configured)
    store = create_object_store(cast(Settings, request.app.state.settings))
    request.app.state.object_store = store
    return store
