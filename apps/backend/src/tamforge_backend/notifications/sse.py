"""Small content-safe Server-Sent Event codec and polling loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from fastapi import Request

from .schemas import StatusEventResponse
from .service import NotificationService


def parse_last_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError("Last-Event-ID is invalid") from None
    if not 0 <= parsed <= 2**63 - 1:
        raise ValueError("Last-Event-ID is invalid")
    return parsed


def encode_sse_event(event: StatusEventResponse) -> str:
    return f"id: {event.id}\nevent: status\ndata: {event.model_dump_json()}\n\n"


async def status_event_stream(
    *,
    request: Request,
    service: NotificationService,
    owner_id: int,
    after_event_id: int,
    poll_seconds: float = 1.0,
    keepalive_seconds: float = 15.0,
    monotonic: Callable[[], float],
) -> AsyncIterator[str]:
    cursor = after_event_id
    last_emit = monotonic()
    while not await request.is_disconnected():
        events = await service.list_status_events(
            owner_id=owner_id,
            after_event_id=cursor,
            limit=100,
        )
        if events:
            for event in events:
                if event.id <= cursor:
                    continue
                cursor = event.id
                last_emit = monotonic()
                yield encode_sse_event(event)
            continue
        now = monotonic()
        if now - last_emit >= keepalive_seconds:
            last_emit = now
            yield ": keepalive\n\n"
        await asyncio.sleep(poll_seconds)


__all__ = [
    "encode_sse_event",
    "parse_last_event_id",
    "status_event_stream",
]
