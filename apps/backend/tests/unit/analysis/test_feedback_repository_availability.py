"""A dropped database connection must leave a feedback route as a 503 problem.

`FeedbackRepository` is the only place a `SQLAlchemyError` can be recognised for
what it is. Above it nothing catches one: `api.register_routes` installs a
handler per domain error type and none for SQLAlchemy's, and
`observability.middleware` re-raises, so an untranslated failure reaches
Starlette's own server-error handling as a plain-text 500 instead of the
`application/problem+json` the feedback route declares. These tests pin the
translation at that boundary and the status the translated error is rendered
with.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.analysis.repository import FeedbackRepository, FeedbackStorageUnavailable
from tamforge_backend.analysis.routes import feedback_problem_response


def _dropped_connection() -> OperationalError:
    """A statement failure carrying exactly what must not reach the client."""
    return OperationalError(
        "SELECT attempts.id FROM attempts WHERE attempts.owner_id = %(owner_id)s",
        {"owner_id": 1},
        Exception("server closed the connection unexpectedly"),
    )


class DroppedConnectionSession:
    """An `AsyncSession` whose every statement fails the way a lost link does."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def scalar(self, statement: object) -> object:
        del statement
        self.calls.append("scalar")
        raise _dropped_connection()

    async def execute(self, statement: object) -> object:
        del statement
        self.calls.append("execute")
        raise _dropped_connection()


def test_a_dropped_connection_surfaces_as_unavailable_rather_than_a_raw_database_error() -> None:
    """The one public read owes its caller a domain error, not SQLAlchemy's.

    The chain is suppressed because the rejected statement and its bound
    parameters travel on that error, and the problem handler renders whatever
    reaches it.
    """

    async def exercise() -> None:
        repository = FeedbackRepository(DroppedConnectionSession())

        with pytest.raises(FeedbackStorageUnavailable) as excinfo:
            await repository.feedback(owner_id=1, activity_id=2, attempt_id=3)

        assert excinfo.value.__suppress_context__ is True
        assert excinfo.value.__cause__ is None

    asyncio.run(exercise())


def test_an_unavailable_store_is_rendered_as_the_feedback_503_problem() -> None:
    """Translating at the repository buys nothing if the handler still 500s."""
    response = feedback_problem_response(FeedbackStorageUnavailable())

    assert response.status_code == 503
    assert response.media_type == "application/problem+json"
    assert b"feedback_storage_unavailable" in response.body
