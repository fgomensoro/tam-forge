"""A dropped database connection must leave a notification route as a 503 problem.

`SqlAlchemyNotificationRepository` is the only place a `SQLAlchemyError` can be
recognised for what it is. Above it nothing catches one: `api.register_routes`
installs a handler per domain error type and none for SQLAlchemy's, and
`observability.middleware` re-raises, so an untranslated failure reaches
Starlette's own server-error handling as a plain-text 500 instead of the
`application/problem+json` the notification routes declare. These tests pin the
translation at that boundary and the status the translated error is rendered
with.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.notifications.repository import SqlAlchemyNotificationRepository
from tamforge_backend.notifications.routes import notification_problem_response
from tamforge_backend.notifications.service import NotificationStorageUnavailable


def _dropped_connection() -> OperationalError:
    """A statement failure carrying exactly what must not reach the client."""
    return OperationalError(
        "SELECT notifications.id FROM notifications WHERE notifications.owner_id = %(owner_id)s",
        {"owner_id": 1},
        Exception("server closed the connection unexpectedly"),
    )


class DroppedConnectionSession:
    """An `AsyncSession` whose every statement fails the way a lost link does.

    `begin` yields without committing so that the statement failure inside the
    block is the error under test rather than a commit failure on the way out;
    `FailingCommitSession` covers the commit separately. `rollback` fails too:
    the read methods issue one after their SELECT, and a connection that just
    dropped cannot serve that either.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[DroppedConnectionSession]:
        self.calls.append("begin")
        yield self

    async def scalar(self, statement: object) -> object:
        del statement
        self.calls.append("scalar")
        raise _dropped_connection()

    async def scalars(self, statement: object) -> object:
        del statement
        self.calls.append("scalars")
        raise _dropped_connection()

    async def execute(self, statement: object) -> object:
        del statement
        self.calls.append("execute")
        raise _dropped_connection()

    async def rollback(self) -> None:
        self.calls.append("rollback")
        raise _dropped_connection()


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda repository: repository.deliver_outbox(limit=10),
            id="deliver_outbox",
        ),
        pytest.param(
            lambda repository: repository.list_notifications(owner_id=1, cursor=None, limit=20),
            id="list_notifications",
        ),
        pytest.param(
            lambda repository: repository.mark_read(owner_id=1, notification_id=5),
            id="mark_read",
        ),
        pytest.param(
            lambda repository: repository.list_status_events(
                owner_id=1, after_event_id=0, limit=20
            ),
            id="list_status_events",
        ),
    ],
)
def test_a_dropped_connection_surfaces_as_unavailable_rather_than_a_raw_database_error(
    call: Callable[[SqlAlchemyNotificationRepository], Awaitable[object]],
) -> None:
    """Every public method owes its caller a domain error, not SQLAlchemy's.

    The chain is suppressed because the rejected statement and its bound
    parameters travel on that error, and the problem handler renders whatever
    reaches it.
    """

    async def exercise() -> None:
        repository = SqlAlchemyNotificationRepository(DroppedConnectionSession())

        with pytest.raises(NotificationStorageUnavailable) as excinfo:
            await call(repository)

        assert excinfo.value.__suppress_context__ is True
        assert excinfo.value.__cause__ is None

    asyncio.run(exercise())


class FailingCommitSession:
    """Every statement lands; the commit `transaction_scope` issues is what drops.

    This is why the translation wraps `transaction_scope` from outside rather
    than sitting inside the block: the commit runs on the way out of the block,
    so a translation placed within it would never see this failure.
    """

    def __init__(self) -> None:
        self.row = SimpleNamespace(
            id=5,
            owner_id=1,
            notification_type="feedback_ready",
            subject_kind="activity",
            subject_id=3,
            created_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
            read_at=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
        )

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FailingCommitSession]:
        yield self
        raise _dropped_connection()

    async def scalar(self, statement: object) -> object:
        del statement
        return self.row


def test_a_failing_commit_surfaces_as_unavailable_rather_than_a_raw_database_error() -> None:
    """A write that only fails at commit is the same outage to the caller."""

    async def exercise() -> None:
        repository = SqlAlchemyNotificationRepository(FailingCommitSession())

        with pytest.raises(NotificationStorageUnavailable) as excinfo:
            await repository.mark_read(owner_id=1, notification_id=5)

        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_an_unavailable_store_is_rendered_as_the_notification_503_problem() -> None:
    """Translating at the repository buys nothing if the handler still 500s."""
    response = notification_problem_response(NotificationStorageUnavailable())

    assert response.status_code == 503
    assert response.media_type == "application/problem+json"
    assert b"notification_storage_unavailable" in response.body
