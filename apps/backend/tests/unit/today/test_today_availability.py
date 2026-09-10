"""A failed Today session call is a closed 503, not a raw plain-text 500."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.today.schemas import DailyCloseCommand, EvidenceManifest

COMMAND = DailyCloseCommand(
    evidence_confirmed=True,
    evidence_manifest=EvidenceManifest(activity_ids=(4,)),
    strongest_output="wrote the day up while it was still fresh",
    repeated_mistake="left the timer running through the break",
    unfinished_classification="none",
    unfinished_requirement=None,
)


def _dropped_connection() -> OperationalError:
    return OperationalError(
        "SELECT learner_settings.timezone FROM learner_settings WHERE owner_id = $1",
        {"owner_id": 7},
        Exception("connection lost"),
    )


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
        rows: tuple[object, ...] = (),
    ) -> None:
        self._statement_error = statement_error
        self._commit_error = commit_error
        self._rows = list(rows)

    def begin(self) -> _Transaction:
        return _Transaction(self._commit_error)

    async def scalar(self, statement: object) -> object:
        del statement
        if self._statement_error is not None:
            raise self._statement_error
        return self._rows.pop(0)

    async def rollback(self) -> None:
        return None


@pytest.mark.anyio
async def test_a_failing_today_read_surfaces_as_unavailable_rather_than_a_raw_database_error() -> (
    None
):
    """`load_today` owes its callers a domain error, not SQLAlchemy's.

    Every statement it issues is on a live request path: the Today read runs on
    each workspace load. A dropped connection or statement timeout used to leave
    the raw `SQLAlchemyError` in place, and nothing above it catches that.
    `api.register_routes` installs a handler per domain error type and none for
    SQLAlchemy's, and `OperationalMiddleware` re-raises, so the failure reached
    Starlette's own server-error handling as a plain-text 500 instead of the
    `application/problem+json` the Today routes declare.
    """
    from tamforge_backend.today.repository import SqlAlchemyTodayRepository
    from tamforge_backend.today.routes import today_problem_response
    from tamforge_backend.today.service import TodayUnavailable

    session = _StubSession(statement_error=_dropped_connection())
    repository = SqlAlchemyTodayRepository(session)  # type: ignore[arg-type]

    with pytest.raises(TodayUnavailable) as caught:
        await repository.load_today(owner_id=7, local_date=date(2026, 8, 24))

    # Content-free chain: the rejected statement and its bound parameters never
    # ride along on the error the owner is allowed to see.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True

    response = today_problem_response(caught.value)
    assert response.status_code == 503
    assert response.media_type == "application/problem+json"


@pytest.mark.anyio
async def test_a_failing_close_commit_is_translated_the_same_way_a_failing_statement_is() -> None:
    """The guard sits outside `transaction_scope`, so the commit is covered too.

    `transaction_scope` commits on the way out of the context, after the last
    statement has already succeeded. A guard inside it would translate every
    read and write and still let a lost connection at commit time escape
    untranslated. This exercises the shortest committing path: a replayed close
    returns its recorded response without writing anything, so the commit is the
    only thing left to fail.
    """
    from tamforge_backend.today.repository import SqlAlchemyTodayRepository
    from tamforge_backend.today.service import TodayUnavailable

    session = _StubSession(
        commit_error=_dropped_connection(),
        rows=(
            SimpleNamespace(id=12, day_type="standard", status="closed"),
            SimpleNamespace(
                id=9,
                study_day_id=12,
                evidence_confirmed=True,
                evidence_manifest=COMMAND.evidence_manifest.model_dump(mode="json"),
                strongest_output=COMMAND.strongest_output,
                repeated_mistake=COMMAND.repeated_mistake,
                unfinished_classification=COMMAND.unfinished_classification,
                unfinished_requirement=COMMAND.unfinished_requirement,
                correction_count=0,
                closed_at=datetime(2026, 8, 24, 23, tzinfo=UTC),
            ),
        ),
    )
    repository = SqlAlchemyTodayRepository(session)  # type: ignore[arg-type]

    with pytest.raises(TodayUnavailable):
        await repository.close_day(
            owner_id=7,
            local_date=date(2026, 8, 24),
            command=COMMAND,
            idempotency_key="close-2026-08-24",
        )
