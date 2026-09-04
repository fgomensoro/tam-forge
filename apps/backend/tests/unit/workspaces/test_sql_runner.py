from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from asyncpg.cursor import BaseCursor
from asyncpg.transaction import Transaction
from tamforge_backend.workspaces.sql_contracts import SqlRunnerError
from tamforge_backend.workspaces.sql_runner import PostgresSqlRunner
from tamforge_backend.workspaces.sql_settings import SqlExerciseCatalog

from .test_sql_contracts import exercise


class Connection:
    """External wire transport; real asyncpg transaction state and cursor guard."""

    def __init__(
        self,
        *,
        rows=(("a", 2), ("b", 1)),
        columns=("account_id", "ticket_count"),
        safe=True,
        failure=None,
        pause=None,
        close_failure=False,
        rollback_pause=None,
        start_failure=None,
    ):
        self.rows = list(rows)
        self.columns = columns
        self.safe = safe
        self.failure = failure
        self.pause = pause
        self.close_failure = close_failure
        self.rollback_pause = rollback_pause
        self.start_failure = start_failure
        self.events = []
        self.closed = False
        self.in_transaction = False
        self.prepared = None
        self._top_xact = None
        self._pool_release_ctr = 0
        self._protocol = SimpleNamespace(is_in_transaction=lambda: self.in_transaction)

    def transaction(self, *, readonly):
        return Transaction(self, isolation=None, readonly=readonly, deferrable=False)

    async def execute(self, sql, *args):
        sql = sql.removesuffix(";")
        self.events.append((sql, args))
        if sql == "BEGIN READ ONLY":
            self.in_transaction = True
            if self.start_failure:
                raise self.start_failure
        elif sql == "ROLLBACK":
            if self.rollback_pause:
                await self.rollback_pause.wait()
            self.in_transaction = False
        return "OK"

    async def fetchval(self, sql, *args):
        self.events.append((sql, args))
        return self.safe

    async def prepare(self, sql):
        assert self.in_transaction
        self.prepared = sql
        if self.pause:
            await self.pause.wait()
        if self.failure:
            raise self.failure
        connection = self

        class Statement:
            def get_attributes(self):
                return tuple(SimpleNamespace(name=name) for name in connection.columns)

            async def cursor(self):
                # SQL BEGIN alone does not establish the driver's _top_xact.
                BaseCursor._check_ready(
                    SimpleNamespace(_connection=connection, _state=SimpleNamespace(closed=False))
                )
                return connection

        return Statement()

    async def fetch(self, count):
        assert 1 <= count <= 25
        assert self.in_transaction
        rows, self.rows = self.rows[:count], self.rows[count:]
        return rows

    async def close(self, *, timeout):
        self.events.append(("close", ()))
        if self.close_failure:
            raise OSError("connection-secret")
        self.closed = True
        self.in_transaction = False

    def terminate(self):
        self.events.append(("terminate", ()))
        self.closed = True
        self.in_transaction = False

    def is_closed(self):
        return self.closed


def runner_for(connection: Connection) -> PostgresSqlRunner:
    ex = exercise()
    catalog = SqlExerciseCatalog(
        exercises=(ex,),
        dsns={ex.key: "postgresql://tamforge_learning_runner_support:secret@localhost/learning"},
    )

    async def connect(dsn, **kwargs):
        assert kwargs["timeout"] <= 5
        return connection

    return PostgresSqlRunner(catalog, connector=connect)


def test_driver_transaction_allows_cursor_and_result_validation() -> None:
    connection = Connection()
    query = "SELECT '; learner-marker' AS account_id, 2 AS ticket_count"
    result = asyncio.run(runner_for(connection).run(exercise(), query))
    assert result.validation == "matched"
    assert result.rows == (("a", "2"), ("b", "1"))
    assert connection.prepared == query
    assert all("learner-marker" not in sql for sql, _ in connection.events)
    assert connection.events[0][0] == "BEGIN READ ONLY"
    assert connection.events[-2:] == [("ROLLBACK", ()), ("close", ())]
    assert connection.closed and not connection.in_transaction


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"safe": False}, "unsafe_configuration"),
        ({"failure": TimeoutError("query-secret")}, "timeout"),
        ({"failure": ValueError("query-secret")}, "rejected_query"),
        ({"columns": ()}, "rejected_query"),
        ({"columns": tuple(f"c{i}" for i in range(33))}, "result_too_large"),
        ({"rows": (("a", "é" * 131072),)}, "result_too_large"),
        ({"rows": tuple((str(i), i) for i in range(1001))}, "result_too_large"),
        ({"rows": (("a", float("nan")),)}, "invalid_result"),
    ],
)
def test_failure_is_safe_and_always_rolls_back_and_closes(options: dict, code: str) -> None:
    connection = Connection(**options)
    with pytest.raises(SqlRunnerError) as caught:
        asyncio.run(runner_for(connection).run(exercise(), "SELECT learner-secret"))
    assert str(caught.value) == code
    assert caught.value.__cause__ is None
    assert connection.closed and not connection.in_transaction
    assert ("ROLLBACK", ()) in connection.events
    if not connection.safe:
        assert connection.prepared is None


def test_multiple_statement_transport_rejection_is_safe() -> None:
    import asyncpg

    connection = Connection(failure=asyncpg.PostgresSyntaxError("cannot insert multiple commands"))
    with pytest.raises(SqlRunnerError, match="^rejected_query$"):
        asyncio.run(runner_for(connection).run(exercise(), "SELECT 1; SELECT 2"))
    assert connection.closed


@pytest.mark.parametrize("query", ["", "   ", "SELECT \x00secret", "é" * 32769, "\ud800"])
def test_bad_query_is_rejected_before_connection(query: str) -> None:
    connection = Connection()
    with pytest.raises(SqlRunnerError, match="^invalid_query$"):
        asyncio.run(runner_for(connection).run(exercise(), query))
    assert not connection.events


def test_busy_runner_does_not_open_second_connection() -> None:
    async def scenario():
        release = asyncio.Event()
        connection = Connection(pause=release)
        runner = runner_for(connection)
        first = asyncio.create_task(runner.run(exercise(), "SELECT 1"))
        await asyncio.sleep(0)
        with pytest.raises(SqlRunnerError, match="^busy$"):
            await runner.run(exercise(), "SELECT 2")
        release.set()
        assert (await first).validation == "matched"
        assert sum(sql == "BEGIN READ ONLY" for sql, _ in connection.events) == 1

    asyncio.run(scenario())


def test_cancelled_query_cleans_up_and_releases_capacity() -> None:
    async def scenario():
        connection = Connection(pause=asyncio.Event())
        runner = runner_for(connection)
        task = asyncio.create_task(runner.run(exercise(), "SELECT 1"))
        while connection.prepared is None:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.closed and not connection.in_transaction
        assert ("ROLLBACK", ()) in connection.events
        # An invalid query receives its own error, rather than stale busy state.
        with pytest.raises(SqlRunnerError, match="^invalid_query$"):
            await runner.run(exercise(), "")

    asyncio.run(scenario())


def test_repeated_cancellation_cannot_interrupt_cleanup() -> None:
    async def scenario():
        cleanup_release = asyncio.Event()
        connection = Connection(pause=asyncio.Event(), rollback_pause=cleanup_release)
        task = asyncio.create_task(runner_for(connection).run(exercise(), "SELECT 1"))
        while connection.prepared is None:
            await asyncio.sleep(0)
        task.cancel()
        while ("ROLLBACK", ()) not in connection.events:
            await asyncio.sleep(0)
        task.cancel()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.closed and not connection.in_transaction

    asyncio.run(scenario())


def test_cleanup_failure_terminates_connection_and_returns_no_result() -> None:
    connection = Connection(close_failure=True)
    with pytest.raises(SqlRunnerError, match="^unavailable$"):
        asyncio.run(runner_for(connection).run(exercise(), "SELECT 1"))
    assert connection.closed and not connection.in_transaction
    assert connection.events[-1] == ("terminate", ())


def test_overall_timeout_includes_transport_and_cleanup(monkeypatch) -> None:
    import tamforge_backend.workspaces.sql_runner as module

    monkeypatch.setattr(module, "_WORK_SECONDS", 0.02)

    async def scenario():
        connection = Connection(pause=asyncio.Event())
        with pytest.raises(SqlRunnerError, match="^timeout$"):
            await runner_for(connection).run(exercise(), "SELECT 1")
        assert connection.closed and not connection.in_transaction

    asyncio.run(scenario())


def test_connect_failure_does_not_leak_dsn_and_releases_capacity() -> None:
    async def scenario():
        ex = exercise()
        catalog = SqlExerciseCatalog(
            exercises=(ex,),
            dsns={
                ex.key: "postgresql://tamforge_learning_runner_support:secret@localhost/learning"
            },
        )

        async def connect(dsn, **kwargs):
            raise OSError(dsn)

        runner = PostgresSqlRunner(catalog, connector=connect)
        for _ in range(2):
            with pytest.raises(SqlRunnerError) as caught:
                await runner.run(ex, "SELECT 1")
            assert str(caught.value) == "unavailable"
            assert caught.value.__cause__ is None

    asyncio.run(scenario())


def test_stuck_rollback_has_bounded_cleanup_and_returns_no_success() -> None:
    async def scenario():
        connection = Connection(rollback_pause=asyncio.Event())
        started = asyncio.get_running_loop().time()
        with pytest.raises(SqlRunnerError, match="^unavailable$"):
            await runner_for(connection).run(exercise(), "SELECT 1")
        assert connection.closed and not connection.in_transaction
        assert asyncio.get_running_loop().time() - started < 1

    asyncio.run(scenario())


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_transaction_start_closes_uncertain_session_and_releases_capacity(cancelled) -> None:
    async def scenario():
        failure = asyncio.CancelledError() if cancelled else OSError("start-secret")
        connection = Connection(start_failure=failure)
        runner = runner_for(connection)
        expected = asyncio.CancelledError if cancelled else SqlRunnerError
        with pytest.raises(expected):
            await runner.run(exercise(), "SELECT 1")
        assert connection.closed and not connection.in_transaction
        assert connection.prepared is None
        with pytest.raises(SqlRunnerError, match="^invalid_query$"):
            await runner.run(exercise(), "")

    asyncio.run(scenario())
