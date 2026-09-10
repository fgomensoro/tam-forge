"""A dropped database connection must leave an evidence route as a 503 problem.

`SqlAlchemyEvidenceRepository` is the only place a `SQLAlchemyError` can be
recognised for what it is. Above it nothing catches one: `api.register_routes`
installs a handler per domain error type and none for SQLAlchemy's, and
`observability.middleware` re-raises, so an untranslated failure reaches
Starlette's own server-error handling as a plain-text 500 instead of the
`application/problem+json` the evidence routes declare. These tests pin the
translation at that boundary and the status the translated error is rendered
with.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import NoReturn

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
from tamforge_backend.evidence.routes import evidence_problem_response
from tamforge_backend.evidence.schemas import (
    DimensionEvaluationInput,
    EvidenceEvaluationCommand,
    RecordEvaluationResponse,
)
from tamforge_backend.evidence.service import EvidenceStorageUnavailable

REQUEST_HASH = b"\x33" * 32

COMMAND = EvidenceEvaluationCommand(
    activity_id=10,
    attempt_id=20,
    config_version_key="seed-v1",
    exercise_type="incident_triage",
    mapping_version="seed-v1",
    formula_version="seed-v1",
    rubric_slug="tam_core",
    rubric_version="seed-v1",
    practice_mode="independent_practice",
    assistance="no_ai",
    evaluator="ai_rubric_reviewer",
    difficulty="standard",
    ai_role="reviewer",
    evaluated_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    transcript_available=False,
    audio_available=False,
    written_english_available=False,
    scored_recording=False,
    dimensions=(
        DimensionEvaluationInput(
            dimension_slug="impact_risk_assessment",
            availability="scored",
            score=Decimal("4"),
        ),
    ),
)

REPLAYED = RecordEvaluationResponse(
    evaluation_id=1,
    activity_id=10,
    attempt_id=20,
    evidence_event_ids=(),
    snapshot_ids=(),
    portfolio_score_id=None,
    replayed=True,
)


def _never_prepared(context: object) -> NoReturn:
    """`record_atomic` fails on its first statement, long before it scores."""
    del context
    raise AssertionError("scoring must not run once the store has dropped")


def _dropped_connection() -> OperationalError:
    """A statement failure carrying exactly what must not reach the client."""
    return OperationalError(
        "SELECT owners.id FROM owners WHERE owners.id = %(owner_id)s FOR UPDATE",
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

    async def flush(self) -> None:
        self.calls.append("flush")
        raise _dropped_connection()

    async def rollback(self) -> None:
        self.calls.append("rollback")
        raise _dropped_connection()

    def add(self, instance: object) -> None:
        del instance
        self.calls.append("add")


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda repository: repository.record_atomic(
                owner_id=1,
                idempotency_key="evidence-1",
                request_hash=REQUEST_HASH,
                command=COMMAND,
                prepare=_never_prepared,
            ),
            id="record_atomic",
        ),
        pytest.param(
            lambda repository: repository.list_skills(owner_id=1),
            id="list_skills",
        ),
        pytest.param(
            lambda repository: repository.get_skill(owner_id=1, skill_slug="tam_core"),
            id="get_skill",
        ),
        pytest.param(
            lambda repository: repository.list_skill_evidence(
                owner_id=1, skill_slug="tam_core", cursor=None, limit=20
            ),
            id="list_skill_evidence",
        ),
        pytest.param(
            lambda repository: repository.list_activity_evidence(
                owner_id=1, activity_id=10, cursor=None, limit=20
            ),
            id="list_activity_evidence",
        ),
        pytest.param(
            lambda repository: repository.portfolio_history(owner_id=1, cursor=None, limit=20),
            id="portfolio_history",
        ),
    ],
)
def test_a_dropped_connection_surfaces_as_unavailable_rather_than_a_raw_database_error(
    call: Callable[[SqlAlchemyEvidenceRepository], Awaitable[object]],
) -> None:
    """Every public method owes its caller a domain error, not SQLAlchemy's.

    All six are on a live request path, and each one used to let the raw
    `SQLAlchemyError` out. The chain is suppressed because the rejected
    statement and its bound parameters travel on that error, and the problem
    handler renders whatever reaches it.
    """

    async def exercise() -> None:
        repository = SqlAlchemyEvidenceRepository(DroppedConnectionSession())

        with pytest.raises(EvidenceStorageUnavailable) as excinfo:
            await call(repository)

        assert excinfo.value.__suppress_context__ is True
        assert excinfo.value.__cause__ is None

    asyncio.run(exercise())


class FailingCommitSession:
    """Every statement lands; the commit `transaction_scope` issues is what drops.

    This is why the translation wraps `transaction_scope` from outside rather
    than sitting inside the block: the commit runs on the way out of the block,
    so a translation placed within it would never see this failure. The rows
    below take `record_atomic` down its replay path, which returns a stored
    receipt from inside the block without writing anything.
    """

    def __init__(self) -> None:
        self.reads = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FailingCommitSession]:
        yield self
        raise _dropped_connection()

    async def scalar(self, statement: object) -> object:
        del statement
        self.reads += 1
        if self.reads == 1:
            return 1
        return SimpleNamespace(
            request_hash=REQUEST_HASH,
            result_payload=REPLAYED.model_dump(mode="json"),
        )


def test_a_failing_commit_surfaces_as_unavailable_rather_than_a_raw_database_error() -> None:
    """A write that only fails at commit is the same outage to the caller."""

    async def exercise() -> None:
        repository = SqlAlchemyEvidenceRepository(FailingCommitSession())

        with pytest.raises(EvidenceStorageUnavailable) as excinfo:
            await repository.record_atomic(
                owner_id=1,
                idempotency_key="evidence-1",
                request_hash=REQUEST_HASH,
                command=COMMAND,
                prepare=_never_prepared,
            )

        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_an_unavailable_store_is_rendered_as_the_evidence_503_problem() -> None:
    """Translating at the repository buys nothing if the handler still 500s."""
    response = evidence_problem_response(EvidenceStorageUnavailable())

    assert response.status_code == 503
    assert response.media_type == "application/problem+json"
    assert b"evidence_storage_unavailable" in response.body
