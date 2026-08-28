"""Owner scoping, idempotent read, and resumable status-stream tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


class _FakeNotificationStore:
    def __init__(self):  # type: ignore[no-untyped-def]
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_notifications(self, **values):  # type: ignore[no-untyped-def]
        from tamforge_backend.notifications.schemas import NotificationPage

        self.calls.append(("list", values))
        return NotificationPage(items=(), next_cursor=None)

    async def mark_read(self, **values):  # type: ignore[no-untyped-def]
        from tamforge_backend.notifications.schemas import NotificationResponse

        self.calls.append(("read", values))
        now = datetime(2026, 8, 29, 12, tzinfo=UTC)
        return NotificationResponse(
            id=values["notification_id"],
            notification_type="feedback_ready",
            subject_kind="activity",
            subject_id=7,
            created_at=now,
            read_at=now,
        )

    async def list_status_events(self, **values):  # type: ignore[no-untyped-def]
        from tamforge_backend.notifications.schemas import StatusEventResponse

        self.calls.append(("events", values))
        return (
            StatusEventResponse(
                id=12,
                event_type="activity.feedback_ready",
                aggregate_type="activity",
                aggregate_id=7,
                subject_id=7,
                related_id=None,
                occurred_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
            ),
        )


@pytest.mark.anyio
async def test_notification_service_forwards_owner_scope_and_idempotent_reads() -> None:
    from tamforge_backend.notifications.service import NotificationService

    store = _FakeNotificationStore()
    service = NotificationService(store)
    await service.list_notifications(owner_id=3, cursor=20, limit=10)
    first = await service.mark_read(owner_id=3, notification_id=7)
    second = await service.mark_read(owner_id=3, notification_id=7)

    assert first == second
    assert store.calls == [
        ("list", {"owner_id": 3, "cursor": 20, "limit": 10}),
        ("read", {"owner_id": 3, "notification_id": 7}),
        ("read", {"owner_id": 3, "notification_id": 7}),
    ]


@pytest.mark.anyio
async def test_status_events_resume_strictly_after_last_event_id() -> None:
    from tamforge_backend.notifications.service import NotificationService

    store = _FakeNotificationStore()
    events = await NotificationService(store).list_status_events(
        owner_id=3,
        after_event_id=11,
        limit=100,
    )

    assert tuple(item.id for item in events) == (12,)
    assert store.calls == [
        (
            "events",
            {"owner_id": 3, "after_event_id": 11, "limit": 100},
        )
    ]


def test_sse_encoding_is_monotonic_content_safe_and_resumable() -> None:
    from tamforge_backend.notifications.schemas import StatusEventResponse
    from tamforge_backend.notifications.sse import encode_sse_event, parse_last_event_id

    event = StatusEventResponse(
        id=12,
        event_type="activity.feedback_ready",
        aggregate_type="activity",
        aggregate_id=7,
        subject_id=7,
        related_id=None,
        occurred_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
    )
    encoded = encode_sse_event(event)

    assert encoded.startswith("id: 12\nevent: status\ndata: ")
    assert "activity.feedback_ready" in encoded
    assert "transcript" not in encoded
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("11") == 11
    with pytest.raises(ValueError, match="Last-Event-ID"):
        parse_last_event_id("-1")
