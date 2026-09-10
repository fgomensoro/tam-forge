"""A dropped database connection must leave an auth route as a 503 problem.

`SqlAlchemyAuthRepository` is the only place a `SQLAlchemyError` can be
recognised for what it is. Above it nothing catches one: `api.register_routes`
installs a handler per domain error type and none for SQLAlchemy's, and
`observability.middleware` re-raises, so an untranslated failure reaches
Starlette's own server-error handling as a plain-text 500 instead of the
`application/problem+json` the auth routes declare. The reads on this repository
also back every authenticated route in the service, so the same outage decided
what a learner saw on any request, not just a sign-in.

These tests pin the translation at that boundary and the status the translated
error is rendered with.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.auth.repository import SqlAlchemyAuthRepository
from tamforge_backend.auth.routes import problem_response
from tamforge_backend.auth.service import AuthStorageUnavailable

TOKEN_HASH = b"\x11" * 32
CSRF_HASH = b"\x22" * 32


def _dropped_connection() -> OperationalError:
    """A statement failure carrying exactly what must not reach the client."""
    return OperationalError(
        "SELECT auth_sessions.id FROM auth_sessions WHERE auth_sessions.token_hash = %(hash)s",
        {"hash": TOKEN_HASH},
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
            lambda repository: repository.create_owner_session(
                github_user_id=1,
                github_login="learner",
                token_hash=TOKEN_HASH,
                csrf_hash=CSRF_HASH,
                session_ttl=timedelta(hours=8),
            ),
            id="create_owner_session",
        ),
        pytest.param(
            lambda repository: repository.find_active_session(TOKEN_HASH),
            id="find_active_session",
        ),
        pytest.param(
            lambda repository: repository.is_session_active(5),
            id="is_session_active",
        ),
        pytest.param(
            lambda repository: repository.find_session_for_logout(TOKEN_HASH),
            id="find_session_for_logout",
        ),
        pytest.param(
            lambda repository: repository.revoke_session(TOKEN_HASH),
            id="revoke_session",
        ),
        pytest.param(
            lambda repository: repository.create_native_oauth_flow(
                state_hash=TOKEN_HASH,
                pkce_challenge="challenge",
                flow_ttl=timedelta(minutes=10),
            ),
            id="create_native_oauth_flow",
        ),
        pytest.param(
            lambda repository: repository.consume_native_oauth_flow(TOKEN_HASH),
            id="consume_native_oauth_flow",
        ),
        pytest.param(
            lambda repository: repository.create_native_exchange(
                github_user_id=1,
                github_login="learner",
                code_hash=TOKEN_HASH,
                pkce_challenge="challenge",
                exchange_ttl=timedelta(minutes=5),
            ),
            id="create_native_exchange",
        ),
        pytest.param(
            lambda repository: repository.consume_native_exchange_and_create_session(
                code_hash=TOKEN_HASH,
                pkce_challenge="challenge",
                access_token_hash=TOKEN_HASH,
                refresh_token_hash=CSRF_HASH,
                access_ttl=timedelta(minutes=30),
                refresh_ttl=timedelta(days=30),
            ),
            id="consume_native_exchange_and_create_session",
        ),
        pytest.param(
            lambda repository: repository.rotate_native_refresh_token(
                refresh_token_hash=CSRF_HASH,
                new_access_token_hash=TOKEN_HASH,
                new_refresh_token_hash=CSRF_HASH,
                access_ttl=timedelta(minutes=30),
                refresh_ttl=timedelta(days=30),
            ),
            id="rotate_native_refresh_token",
        ),
        pytest.param(
            lambda repository: repository.find_active_native_session(TOKEN_HASH),
            id="find_active_native_session",
        ),
        pytest.param(
            lambda repository: repository.is_native_session_active(5),
            id="is_native_session_active",
        ),
        pytest.param(
            lambda repository: repository.revoke_native_session(CSRF_HASH),
            id="revoke_native_session",
        ),
    ],
)
def test_a_dropped_connection_surfaces_as_unavailable_rather_than_a_raw_database_error(
    call: Callable[[SqlAlchemyAuthRepository], Awaitable[object]],
) -> None:
    """Every public method owes its caller a domain error, not SQLAlchemy's.

    All thirteen are on a live request path, and each one used to let the raw
    `SQLAlchemyError` out. The chain is suppressed because the rejected
    statement and its bound parameters travel on that error, and the problem
    handler renders whatever reaches it. For this repository those parameters
    are session and refresh token hashes.
    """

    async def exercise() -> None:
        repository = SqlAlchemyAuthRepository(DroppedConnectionSession())

        with pytest.raises(AuthStorageUnavailable) as excinfo:
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

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FailingCommitSession]:
        yield self
        raise _dropped_connection()

    async def execute(self, statement: object) -> object:
        del statement
        return None


def test_a_failing_commit_surfaces_as_unavailable_rather_than_a_raw_database_error() -> None:
    """A revocation that only fails at commit is the same outage to the caller."""

    async def exercise() -> None:
        repository = SqlAlchemyAuthRepository(FailingCommitSession())

        with pytest.raises(AuthStorageUnavailable) as excinfo:
            await repository.revoke_session(TOKEN_HASH)

        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_an_unavailable_store_is_rendered_as_the_auth_503_problem() -> None:
    """The outage shares the 503 `auth_unavailable` problem already published.

    A client can neither tell nor act on the difference between an auth store
    that is unreachable and an auth deployment that is misconfigured, so the
    outage reuses that code rather than publishing a second one.
    """
    response = problem_response(AuthStorageUnavailable())

    assert response.status_code == 503
    assert response.media_type == "application/problem+json"
    assert b"auth_unavailable" in response.body
