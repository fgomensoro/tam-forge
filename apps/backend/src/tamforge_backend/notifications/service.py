"""Owner-scoped notification reads, read receipts, and status events."""

from __future__ import annotations

from typing import Protocol

from .schemas import NotificationPage, NotificationResponse, StatusEventResponse


class NotificationError(Exception):
    """Base safe notification workflow error."""


class NotificationNotFound(NotificationError):
    """The owner-scoped notification does not exist."""


class NotificationInvalidRequest(NotificationError):
    """The notification request is outside bounded policy."""


class NotificationStore(Protocol):
    async def list_notifications(
        self,
        *,
        owner_id: int,
        cursor: int | None,
        limit: int,
    ) -> NotificationPage: ...

    async def mark_read(
        self, *, owner_id: int, notification_id: int
    ) -> NotificationResponse: ...

    async def list_status_events(
        self,
        *,
        owner_id: int,
        after_event_id: int,
        limit: int,
    ) -> tuple[StatusEventResponse, ...]: ...


class NotificationService:
    """Validate pagination and preserve owner scope on every call."""

    def __init__(self, store: NotificationStore) -> None:
        self._store = store

    async def list_notifications(
        self,
        *,
        owner_id: int,
        cursor: int | None,
        limit: int,
    ) -> NotificationPage:
        self._page(owner_id=owner_id, cursor=cursor, limit=limit)
        return await self._store.list_notifications(
            owner_id=owner_id,
            cursor=cursor,
            limit=limit,
        )

    async def mark_read(
        self, *, owner_id: int, notification_id: int
    ) -> NotificationResponse:
        if owner_id <= 0 or notification_id <= 0:
            raise NotificationInvalidRequest("notification identity is invalid")
        return await self._store.mark_read(
            owner_id=owner_id,
            notification_id=notification_id,
        )

    async def list_status_events(
        self,
        *,
        owner_id: int,
        after_event_id: int,
        limit: int = 100,
    ) -> tuple[StatusEventResponse, ...]:
        if owner_id <= 0 or after_event_id < 0 or not 1 <= limit <= 100:
            raise NotificationInvalidRequest("status event cursor is invalid")
        return await self._store.list_status_events(
            owner_id=owner_id,
            after_event_id=after_event_id,
            limit=limit,
        )

    @staticmethod
    def _page(*, owner_id: int, cursor: int | None, limit: int) -> None:
        if owner_id <= 0 or (cursor is not None and cursor <= 0):
            raise NotificationInvalidRequest("notification cursor is invalid")
        if not 1 <= limit <= 100:
            raise NotificationInvalidRequest("notification page limit is invalid")


__all__ = [
    "NotificationError",
    "NotificationInvalidRequest",
    "NotificationNotFound",
    "NotificationService",
    "NotificationStore",
]
