"""One-shot restricted PostgreSQL executions. Privileges are the security boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

from .sql_contracts import (
    MAX_QUERY_BYTES,
    ResultRows,
    SqlExercise,
    SqlResult,
    build_sql_result,
)
from .sql_contracts import SqlRunnerError as SqlRunnerError
from .sql_settings import SqlExerciseCatalog

_OVERALL_SECONDS = 5.0
_WORK_SECONDS = 4.5  # Reserve the last 500 ms for rollback/close, then terminate.
_CAPACITY_WAIT_SECONDS = 0.1
_STATEMENT_SECONDS = 2.0
_BATCH_ROWS = 25

# All catalog references are qualified. has_*_privilege includes effective PUBLIC
# grants and column grants; checking only explicit ACL entries would be unsafe.
# This deliberately permits only ordinary exercise tables, not executable schema
# objects, owner-rights views, foreign tables, or cross-schema inheritance.
_AUDIT_SQL = """
SELECT COALESCE((
 SELECT
   current_user = $1 AND session_user = $1 AND r.rolcanlogin
   AND NOT (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls)
   AND pg_catalog.current_setting('transaction_read_only') = 'on'
   AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member = r.oid)
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_shdepend d
     WHERE d.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass
       AND d.refobjid = r.oid AND d.deptype = 'o'
   )
   AND NOT pg_catalog.has_database_privilege(
     r.oid, pg_catalog.current_database(), 'CREATE,TEMPORARY')
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_parameter_acl p
     CROSS JOIN LATERAL pg_catalog.aclexplode(p.paracl) a
     WHERE a.grantee IN (0, r.oid)
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_tablespace t
     WHERE pg_catalog.has_tablespace_privilege(r.oid, t.oid, 'CREATE')
   )
   AND EXISTS (
     SELECT 1 FROM pg_catalog.pg_namespace n
     WHERE n.nspname = $2 AND pg_catalog.has_schema_privilege(r.oid, n.oid, 'USAGE')
       AND NOT pg_catalog.has_schema_privilege(r.oid, n.oid, 'CREATE,USAGE WITH GRANT OPTION')
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_namespace n
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', $2)
       AND pg_catalog.has_schema_privilege(r.oid, n.oid, 'USAGE,CREATE')
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_class c
     JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
       AND (
         pg_catalog.has_table_privilege(
           r.oid, c.oid,
           'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,SELECT WITH GRANT OPTION')
         OR pg_catalog.has_any_column_privilege(r.oid, c.oid, 'INSERT,UPDATE,REFERENCES')
         OR pg_catalog.has_any_column_privilege(r.oid, c.oid, 'SELECT WITH GRANT OPTION')
         OR ((n.nspname <> $2 OR c.relkind NOT IN ('r', 'p')) AND (
           pg_catalog.has_table_privilege(r.oid, c.oid, 'SELECT')
           OR pg_catalog.has_any_column_privilege(r.oid, c.oid, 'SELECT')))
       )
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_class c
     WHERE c.relkind = 'S'
       AND pg_catalog.has_sequence_privilege(r.oid, c.oid, 'USAGE,SELECT,UPDATE')
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_proc p
     JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = $2 OR (
       pg_catalog.has_function_privilege(r.oid, p.oid, 'EXECUTE') AND (
         n.nspname NOT IN ('pg_catalog', 'information_schema')
         OR p.prosecdef OR p.oid >= 16384
         OR p.proname ~ '^(pg_(read_(binary_)?file|stat_file|ls_.*|file_.*)|lo_(import|export))$'
       )
     )
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_inherits i
     JOIN pg_catalog.pg_class parent ON parent.oid = i.inhparent
     JOIN pg_catalog.pg_namespace pn ON pn.oid = parent.relnamespace
     JOIN pg_catalog.pg_class child ON child.oid = i.inhrelid
     JOIN pg_catalog.pg_namespace cn ON cn.oid = child.relnamespace
     WHERE pn.nspname = $2 AND (cn.nspname <> $2 OR child.relkind = 'f')
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_largeobject_metadata l
     CROSS JOIN LATERAL pg_catalog.aclexplode(
       COALESCE(l.lomacl, pg_catalog.acldefault('L', l.lomowner))) a
     WHERE a.grantee IN (0, r.oid)
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_foreign_data_wrapper f
     WHERE pg_catalog.has_foreign_data_wrapper_privilege(r.oid, f.oid, 'USAGE')
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_catalog.pg_foreign_server s
     WHERE pg_catalog.has_server_privilege(r.oid, s.oid, 'USAGE')
   )
 FROM pg_catalog.pg_roles r WHERE r.rolname = $1
), false)
"""


class SqlRunner(Protocol):
    async def run(self, exercise: SqlExercise, query: str) -> SqlResult: ...


class _Attribute(Protocol):
    @property
    def name(self) -> str: ...


class _Cursor(Protocol):
    async def fetch(self, n: int) -> Sequence[Sequence[object]]: ...


class _Statement(Protocol):
    def get_attributes(self) -> Sequence[_Attribute]: ...
    def cursor(self) -> Awaitable[_Cursor]: ...


class _Connection(Protocol):
    async def execute(self, query: str, *args: object) -> object: ...
    async def fetchval(self, query: str, *args: object) -> object: ...
    async def prepare(self, query: str) -> _Statement: ...
    async def close(self, *, timeout: float) -> None: ...
    def terminate(self) -> None: ...
    def is_closed(self) -> bool: ...


def _check_query(query: str) -> None:
    try:
        valid = (
            isinstance(query, str)
            and bool(query.strip())
            and "\x00" not in query
            and len(query) <= MAX_QUERY_BYTES
            and len(query.encode("utf-8")) <= MAX_QUERY_BYTES
        )
    except UnicodeError:
        valid = False
    if not valid:
        raise SqlRunnerError("invalid_query")


async def _destroy_connection(connection: _Connection, deadline: float) -> bool:
    """Bound cleanup itself; termination is synchronous if graceful I/O fails."""
    loop = asyncio.get_running_loop()
    clean = True
    try:
        try:
            async with asyncio.timeout_at(min(deadline, loop.time() + 0.3)):
                await connection.execute("ROLLBACK")
        except Exception:
            clean = False
        try:
            remaining = max(0.0, deadline - loop.time())
            async with asyncio.timeout(remaining):
                await connection.close(timeout=remaining)
        except Exception:
            clean = False
    finally:
        if not connection.is_closed():
            clean = False
            with suppress(Exception):
                connection.terminate()
    return clean


async def _shield_cleanup(connection: _Connection, deadline: float) -> bool:
    cleanup = asyncio.create_task(_destroy_connection(connection, deadline))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # A second client cancellation must not strand the rollback task.
            cancelled = True
    result = cleanup.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class PostgresSqlRunner:
    """Inject one instance per serving process; every run opens a fresh session."""

    def __init__(
        self,
        catalog: SqlExerciseCatalog,
        *,
        connector: Callable[..., Awaitable[_Connection]] = asyncpg.connect,
    ) -> None:
        self._catalog = catalog
        self._connector = connector
        self._capacity = asyncio.Lock()

    async def run(self, exercise: SqlExercise, query: str) -> SqlResult:
        try:
            async with asyncio.timeout(_CAPACITY_WAIT_SECONDS):
                await self._capacity.acquire()
        except TimeoutError:
            raise SqlRunnerError("busy") from None
        loop = asyncio.get_running_loop()
        started = loop.time()
        connection: _Connection | None = None
        result: SqlResult | None = None
        error: SqlRunnerError | None = None
        stage = "configuration"
        try:
            async with asyncio.timeout_at(started + _WORK_SECONDS):
                dsn = self._catalog.dsn_for(exercise)
                _check_query(query)
                stage = "connect"
                connection = await self._connector(
                    dsn,
                    timeout=1.5,
                    command_timeout=_STATEMENT_SECONDS,
                    statement_cache_size=0,
                    server_settings={
                        "application_name": "tamforge_sql_learning",
                        "search_path": "pg_catalog",
                    },
                )
                stage = "audit"
                await connection.execute("BEGIN READ ONLY")
                await connection.execute("SET LOCAL statement_timeout = '2s'")
                await connection.execute("SET LOCAL lock_timeout = '250ms'")
                await connection.execute("SET LOCAL idle_in_transaction_session_timeout = '2s'")
                await connection.execute(
                    "SELECT pg_catalog.set_config('search_path', $1, true)",
                    f'pg_catalog, "{exercise.schema_name}"',
                )
                if (
                    await connection.fetchval(
                        _AUDIT_SQL,
                        exercise.role_name,
                        exercise.schema_name,
                    )
                    is not True
                ):
                    raise SqlRunnerError("unsafe_configuration")
                stage = "query"
                async with asyncio.timeout(_STATEMENT_SECONDS):
                    # PostgreSQL's extended protocol accepts one statement. Do
                    # not split/rewrite SQL or interpolate it into wrapper SQL.
                    statement = await connection.prepare(query)
                    columns = tuple(attribute.name for attribute in statement.get_attributes())
                    if not columns:
                        raise SqlRunnerError("rejected_query")
                    bounded = ResultRows(columns)
                    cursor = await statement.cursor()
                    while batch := await cursor.fetch(_BATCH_ROWS):
                        for row in batch:
                            bounded.append(row)
                    result = build_sql_result(
                        exercise,
                        columns,
                        bounded.rows,
                        int((loop.time() - started) * 1000),
                    )
        except SqlRunnerError as exc:
            error = exc
        except (TimeoutError, asyncpg.QueryCanceledError):
            error = SqlRunnerError("timeout")
        except Exception:
            error = SqlRunnerError(
                "unsafe_configuration"
                if stage == "audit"
                else "rejected_query"
                if stage == "query"
                else "unavailable",
            )
        finally:
            try:
                if connection is not None and not await _shield_cleanup(
                    connection,
                    started + _OVERALL_SECONDS,
                ):
                    error = error or SqlRunnerError("unavailable")
            finally:
                self._capacity.release()
        if error is not None:
            raise error from None
        if result is None:
            raise SqlRunnerError("unavailable")
        return result
