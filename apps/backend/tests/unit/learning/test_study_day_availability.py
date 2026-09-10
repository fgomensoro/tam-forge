"""A failed study day session call is a closed 503, not a raw plain-text 500."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError


def _dropped_connection() -> OperationalError:
    return OperationalError(
        "SELECT learner_settings.timezone FROM learner_settings WHERE owner_id = $1",
        {"owner_id": 7},
        Exception("connection lost"),
    )


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _Transaction:
    """A `session.begin()` stand-in that can fail the way a lost commit does."""

    def __init__(self, commit_error: BaseException | None) -> None:
        self._commit_error = commit_error

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None and self._commit_error is not None:
            raise self._commit_error
        return False


class _StubSession:
    """Just enough `AsyncSession` to fail one statement, or the commit after it."""

    def __init__(
        self,
        *,
        statement_error: BaseException | None = None,
        commit_error: BaseException | None = None,
        setting: object = None,
    ) -> None:
        self._statement_error = statement_error
        self._commit_error = commit_error
        self._setting = setting

    def begin(self) -> _Transaction:
        return _Transaction(self._commit_error)

    async def execute(self, statement: object) -> _Result:
        del statement
        if self._statement_error is not None:
            raise self._statement_error
        return _Result(self._setting)


@pytest.mark.anyio
async def test_a_failing_statement_surfaces_as_unavailable_rather_than_a_raw_database_error() -> (
    None
):
    """`ensure_current_day` owes its callers a domain error, not SQLAlchemy's.

    Every statement it issues is on a live request path -- Today materializes
    the current study day on each read through `SqlAlchemyTodayRepository`,
    which catches `StudyDayNotReady` and nothing else. A dropped connection or
    statement timeout used to leave the raw `SQLAlchemyError` in place, and
    nothing above it catches that: `api.register_routes` installs a handler per
    domain error type and none for SQLAlchemy's, and `OperationalMiddleware`
    re-raises, so the failure reached Starlette's own server-error handling as
    a plain-text 500 instead of the `application/problem+json` 503 the routes
    declare.
    """
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.learning.routes import activity_problem_response
    from tamforge_backend.learning.service import ActivityUnavailable

    session = _StubSession(statement_error=_dropped_connection())
    service = StudyDayService(session)  # type: ignore[arg-type]

    with pytest.raises(ActivityUnavailable) as caught:
        await service.ensure_current_day(
            owner_id=7, at=datetime(2026, 8, 24, 19, tzinfo=UTC)
        )

    # Content-free chain: the rejected statement and its bound parameters never
    # ride along on the error the owner is allowed to see.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True

    response = activity_problem_response(caught.value)
    assert response.status_code == 503
    assert response.media_type == "application/problem+json"


@pytest.mark.anyio
async def test_a_failing_commit_is_translated_the_same_way_a_failing_statement_is() -> None:
    """The guard sits outside `transaction_scope`, so the commit is covered too.

    `transaction_scope` commits on the way out of the context, after the last
    statement has already succeeded. A guard inside it would translate every
    read and write and still let a lost connection at commit time escape
    untranslated. This exercises the shortest committing path: a Sunday has no
    curriculum day, so the method returns before writing anything and the
    commit is the only thing left to fail.
    """
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.learning.service import ActivityUnavailable

    session = _StubSession(
        commit_error=_dropped_connection(),
        setting=SimpleNamespace(
            timezone="America/Los_Angeles",
            study_start_date=date(2026, 8, 24),
            active_roadmap_version_id=None,
        ),
    )
    service = StudyDayService(session)  # type: ignore[arg-type]

    with pytest.raises(ActivityUnavailable):
        await service.ensure_current_day(
            owner_id=7, at=datetime(2026, 8, 30, 19, tzinfo=UTC)
        )
