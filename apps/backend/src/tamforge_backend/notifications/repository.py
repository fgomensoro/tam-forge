"""PostgreSQL notification delivery, read receipts, and resumable events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..learning.models import LearnerSetting
from ..models.base import utc_now
from .models import Notification, OutboxEvent
from .policy import notification_candidate_from_event
from .schemas import (
    DeliveryBatch,
    NotificationPage,
    NotificationResponse,
    StatusEventResponse,
)
from .service import NotificationInvalidRequest, NotificationNotFound


class SqlAlchemyNotificationRepository:
    """Consume outbox rows exactly once and expose owner-scoped read models."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._clock = clock

    async def deliver_outbox(self, *, limit: int = 100) -> DeliveryBatch:
        if not 1 <= limit <= 100:
            raise NotificationInvalidRequest("delivery batch limit is invalid")
        now = self._now()
        published: list[int] = []
        notifications: list[int] = []
        async with transaction_scope(self._session):
            events = tuple(
                (
                    await self._session.scalars(
                        select(OutboxEvent)
                        .where(OutboxEvent.published_at.is_(None))
                        .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            timezone_by_owner: dict[int, str] = {}
            for event in events:
                timezone = timezone_by_owner.get(event.owner_id)
                if timezone is None:
                    timezone = await self._learner_timezone(event.owner_id)
                    timezone_by_owner[event.owner_id] = timezone
                candidate = notification_candidate_from_event(
                    event_type=event.event_type,
                    aggregate_type=event.aggregate_type,
                    subject_id=cast(int, event.payload["subject_id"]),
                    occurred_at=event.occurred_at,
                    timezone=timezone,
                )
                if candidate is not None:
                    notification = Notification(
                        owner_id=event.owner_id,
                        notification_type=candidate.notification_type,
                        subject_kind=candidate.subject_kind,
                        subject_id=candidate.subject_id,
                        created_at=max(now, event.occurred_at),
                        read_at=None,
                    )
                    self._session.add(notification)
                    await self._session.flush()
                    notifications.append(notification.id)
                await self._session.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == event.id)
                    .values(attempts=event.attempts + 1, published_at=max(now, event.occurred_at))
                )
                published.append(event.id)
        return DeliveryBatch(
            published_event_ids=tuple(published),
            notification_ids=tuple(notifications),
        )

    async def list_notifications(
        self,
        *,
        owner_id: int,
        cursor: int | None,
        limit: int,
    ) -> NotificationPage:
        query = select(Notification).where(Notification.owner_id == owner_id)
        if cursor is not None:
            query = query.where(Notification.id < cursor)
        rows = tuple(
            (
                await self._session.scalars(
                    query.order_by(Notification.id.desc()).limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        result = NotificationPage(
            items=tuple(self._notification_response(item) for item in selected),
            next_cursor=selected[-1].id if has_more and selected else None,
        )
        await self._session.rollback()
        return result

    async def mark_read(
        self, *, owner_id: int, notification_id: int
    ) -> NotificationResponse:
        now = self._now()
        async with transaction_scope(self._session):
            item = await self._session.scalar(
                select(Notification)
                .where(Notification.owner_id == owner_id)
                .where(Notification.id == notification_id)
                .with_for_update()
            )
            if item is None:
                raise NotificationNotFound("notification was not found")
            if item.read_at is None:
                item_id = item.id
                await self._session.execute(
                    update(Notification)
                    .where(Notification.id == item_id)
                    .values(read_at=max(now, item.created_at))
                )
                await self._session.refresh(item)
            return self._notification_response(item)

    async def list_status_events(
        self,
        *,
        owner_id: int,
        after_event_id: int,
        limit: int,
    ) -> tuple[StatusEventResponse, ...]:
        rows = tuple(
            (
                await self._session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.owner_id == owner_id)
                    .where(OutboxEvent.published_at.is_not(None))
                    .where(OutboxEvent.id > after_event_id)
                    .order_by(OutboxEvent.id)
                    .limit(limit)
                )
            ).all()
        )
        result = tuple(
            StatusEventResponse(
                id=item.id,
                event_type=item.event_type,
                aggregate_type=item.aggregate_type,
                aggregate_id=item.aggregate_id,
                subject_id=cast(int, item.payload["subject_id"]),
                related_id=cast(int | None, item.payload.get("related_id")),
                occurred_at=item.occurred_at,
            )
            for item in rows
        )
        await self._session.rollback()
        return result

    async def _learner_timezone(self, owner_id: int) -> str:
        value = await self._session.scalar(
            select(LearnerSetting.timezone)
            .where(LearnerSetting.owner_id == owner_id)
            .limit(1)
        )
        return value or "UTC"

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise NotificationInvalidRequest("repository clock must be timezone-aware")
        return now

    @staticmethod
    def _notification_response(item: Notification) -> NotificationResponse:
        return NotificationResponse(
            id=item.id,
            notification_type=item.notification_type,  # type: ignore[arg-type]
            subject_kind=item.subject_kind,  # type: ignore[arg-type]
            subject_id=item.subject_id,
            created_at=item.created_at,
            read_at=item.read_at,
        )


__all__ = ["SqlAlchemyNotificationRepository"]
