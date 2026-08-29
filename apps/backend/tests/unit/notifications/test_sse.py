"""Focused status-stream session-liveness tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tamforge_backend.notifications.schemas import StatusEventResponse
from tamforge_backend.notifications.sse import status_event_stream


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class EventService:
    def __init__(self) -> None:
        self.calls: list[dict[str, int]] = []

    async def list_status_events(self, **values: int) -> tuple[StatusEventResponse, ...]:
        self.calls.append(values)
        return (_event(1), _event(2))


class SessionGate:
    def __init__(self, states: list[bool]) -> None:
        self.states = states
        self.calls = 0

    async def is_active(self) -> bool:
        self.calls += 1
        return self.states.pop(0)


@pytest.mark.anyio
@pytest.mark.parametrize("reason", ["expiry", "revocation"])
async def test_open_status_stream_stops_before_more_events_when_session_becomes_inactive(
    reason: str,
) -> None:
    del reason
    service = EventService()
    session = SessionGate([True, True, False])
    stream = status_event_stream(
        request=ConnectedRequest(),  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        owner_id=7,
        after_event_id=0,
        session_is_active=session.is_active,
        monotonic=lambda: 0.0,
    )

    assert "id: 1" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    assert session.calls == 3
    assert service.calls == [{"owner_id": 7, "after_event_id": 0, "limit": 100}]


def _event(identifier: int) -> StatusEventResponse:
    return StatusEventResponse(
        id=identifier,
        event_type="processing",
        aggregate_type="activity",
        aggregate_id=7,
        subject_id=7,
        related_id=None,
        occurred_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
