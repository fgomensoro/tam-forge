"""A dropped database connection must leave a roadmap route as a 503 problem.

`SqlAlchemyRoadmapRepository` is the only place a `SQLAlchemyError` can be
recognised for what it is. Above it nothing catches one: `api.register_routes`
installs a handler per domain error type and none for SQLAlchemy's, and
`observability.middleware` re-raises, so an untranslated failure reaches
Starlette's own server-error handling as a plain-text 500 instead of the
`application/problem+json` 503 the roadmap routes declare. These tests pin the
translation at that boundary and the status the translated error is rendered
with.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.roadmaps.contracts import ParsedRoadmap
from tamforge_backend.roadmaps.ports import ImportApproval, RoadmapStorageUnavailable
from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
from tamforge_backend.roadmaps.routes import roadmap_problem_response

EMPTY_ROADMAP = ParsedRoadmap(
    schema_version=1,
    roadmap_version="2026.01",
    tasks=(),
    contracts=(),
    resources=(),
    exit_criteria=(),
    normalized_hash="00" * 32,
)


def _dropped_connection() -> OperationalError:
    """A statement failure carrying exactly what must not reach the client."""
    return OperationalError(
        "SELECT roadmap_imports.idempotency_key FROM roadmap_imports WHERE owner_id = %(id)s",
        {"id": 1},
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
            lambda repository: repository.find_duplicate_import(
                owner_id=1, source_key="core", idempotency_key="k", package_hash="ab" * 32
            ),
            id="find_duplicate_import",
        ),
        pytest.param(
            lambda repository: repository.create_staged_import(
                owner_id=1,
                source_key="core",
                source_name="Core",
                source_kind="zip",
                package_hash="ab" * 32,
                object_key="roadmaps/1/core.zip",
                idempotency_key="k",
            ),
            id="create_staged_import",
        ),
        pytest.param(
            lambda repository: repository.begin_validation(owner_id=1, import_id=7),
            id="begin_validation",
        ),
        pytest.param(
            lambda repository: repository.finish_validation(
                owner_id=1, import_id=7, validation_report={}, semantic_diff={}
            ),
            id="finish_validation",
        ),
        pytest.param(
            lambda repository: repository.reject_validation(
                owner_id=1, import_id=7, validation_report={}, failure_code="schema_invalid"
            ),
            id="reject_validation",
        ),
        pytest.param(
            lambda repository: repository.get_import(owner_id=1, import_id=7),
            id="get_import",
        ),
        pytest.param(
            lambda repository: repository.latest_normalized_payload(owner_id=1, source_id=3),
            id="latest_normalized_payload",
        ),
        pytest.param(
            lambda repository: repository.approve_import(
                ImportApproval(
                    owner_id=1,
                    import_id=7,
                    parsed=EMPTY_ROADMAP,
                    manifest={},
                    raw_payload={},
                    mirror_required=False,
                )
            ),
            id="approve_import",
        ),
        pytest.param(
            lambda repository: repository.get_version(owner_id=1, version_id=5),
            id="get_version",
        ),
        pytest.param(
            lambda repository: repository.list_versions(owner_id=1),
            id="list_versions",
        ),
        pytest.param(
            lambda repository: repository.begin_mirror(owner_id=1, version_id=5),
            id="begin_mirror",
        ),
        pytest.param(
            lambda repository: repository.finish_mirror(
                owner_id=1, version_id=5, mirror_ref="abc123"
            ),
            id="finish_mirror",
        ),
        pytest.param(
            lambda repository: repository.fail_mirror(
                owner_id=1, version_id=5, error_code="write_failed"
            ),
            id="fail_mirror",
        ),
        pytest.param(
            lambda repository: repository.activate_version(owner_id=1, version_id=5),
            id="activate_version",
        ),
    ],
)
def test_a_dropped_connection_surfaces_as_unavailable_rather_than_a_raw_database_error(
    call: Callable[[SqlAlchemyRoadmapRepository], Awaitable[object]],
) -> None:
    """Every public method owes its caller a domain error, not SQLAlchemy's.

    All fourteen are on a live request path, and each one used to let the raw
    `SQLAlchemyError` out. The chain is suppressed because the rejected
    statement and its bound parameters travel on that error, and the problem
    handler renders whatever reaches it.
    """

    async def exercise() -> None:
        repository = SqlAlchemyRoadmapRepository(DroppedConnectionSession())

        with pytest.raises(RoadmapStorageUnavailable) as excinfo:
            await call(repository)

        assert excinfo.value.__suppress_context__ is True
        assert excinfo.value.__cause__ is None

    asyncio.run(exercise())


class FailingCommitSession:
    """Every statement lands; the commit `transaction_scope` issues is what drops.

    This is why the translation wraps `transaction_scope` from outside rather
    than sitting inside the block: the commit runs on the way out of the
    block, so a translation placed within it would never see this failure.
    """

    def __init__(self) -> None:
        self.row = SimpleNamespace(
            id=7,
            owner_id=1,
            source_id=3,
            package_hash=bytes.fromhex("ab" * 32),
            object_key="roadmaps/1/core.zip",
            status="staged",
            validation_report={},
            semantic_diff={},
            idempotency_key="k",
            failure_code=None,
            started_at=None,
        )

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FailingCommitSession]:
        yield self
        raise _dropped_connection()

    async def execute(self, statement: object) -> object:
        del statement
        return SimpleNamespace(first=lambda: (self.row, "core"))

    async def flush(self) -> None:
        return None


def test_a_failing_commit_surfaces_as_unavailable_rather_than_a_raw_database_error() -> None:
    """A write that only fails at commit is the same outage to the caller."""

    async def exercise() -> None:
        repository = SqlAlchemyRoadmapRepository(FailingCommitSession())

        with pytest.raises(RoadmapStorageUnavailable) as excinfo:
            await repository.begin_validation(owner_id=1, import_id=7)

        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_an_unavailable_store_is_rendered_as_the_roadmap_503_problem() -> None:
    """The translated error has to reach the client as the declared 503.

    Translating at the repository buys nothing if the handler still falls
    through to its 500 default, so the mapping is pinned alongside the
    `ObjectStoreError` it shares a status and code with.
    """
    response = roadmap_problem_response(RoadmapStorageUnavailable())

    assert response.status_code == 503
    assert response.media_type == "application/problem+json"
    assert b"roadmap_storage_unavailable" in response.body
