"""Actual restricted-role cases. Run only in CI's existing tamforge_test database."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@asynccontextmanager
async def restricted_database(test_database_url: str):
    import asyncpg
    from sqlalchemy.engine import make_url
    from tamforge_backend.workspaces.sql_contracts import SqlExercise
    from tamforge_backend.workspaces.sql_settings import SqlExerciseCatalog

    # The shared fixture validates tamforge_test before any connection is made.
    url = make_url(test_database_url).set(drivername="postgresql")
    assert url.database == "tamforge_test"
    admin = await asyncpg.connect(url.render_as_string(hide_password=False))
    suffix = uuid4().hex[:12]
    schema, other, role = f"sql_learning_{suffix}", f"sql_private_{suffix}", f"sql_runner_{suffix}"
    password = uuid4().hex
    restore: list[str] = []
    role_created = False
    try:
        await admin.execute("SET search_path = pg_catalog")
        # Record each effective PUBLIC ACL before revocation. GRANT restoration
        # preserves the original privilege set, including originally default ACLs.
        # Do not touch owners, named grantees, grant options, or default-ACL policy.
        changes = await admin.fetch("""
            SELECT pg_catalog.format('REVOKE %s ON SCHEMA %I FROM PUBLIC',
                                     a.privilege_type, n.nspname) AS revoke,
                   pg_catalog.format('GRANT %s ON SCHEMA %I TO PUBLIC',
                                     a.privilege_type, n.nspname) AS restore
            FROM pg_catalog.pg_namespace n,
                 LATERAL pg_catalog.aclexplode(COALESCE(n.nspacl,
                     pg_catalog.acldefault('n', n.nspowner))) a
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND a.grantee = 0
            UNION ALL
            SELECT pg_catalog.format('REVOKE EXECUTE ON ROUTINE %s FROM PUBLIC',
                                     p.oid::pg_catalog.regprocedure),
                   pg_catalog.format('GRANT EXECUTE ON ROUTINE %s TO PUBLIC',
                                     p.oid::pg_catalog.regprocedure)
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace,
                 LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,
                     pg_catalog.acldefault('f', p.proowner))) a
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND a.grantee = 0
            UNION ALL
            SELECT pg_catalog.format('REVOKE %s ON DATABASE %I FROM PUBLIC',
                                     a.privilege_type, d.datname),
                   pg_catalog.format('GRANT %s ON DATABASE %I TO PUBLIC',
                                     a.privilege_type, d.datname)
            FROM pg_catalog.pg_database d,
                 LATERAL pg_catalog.aclexplode(COALESCE(d.datacl,
                     pg_catalog.acldefault('d', d.datdba))) a
            WHERE d.datname = pg_catalog.current_database() AND a.grantee = 0
              AND a.privilege_type IN ('CREATE', 'TEMPORARY')
        """)
        for change in changes:
            # Add restoration before the mutation, including uncertain outcomes.
            restore.append(change["restore"])
            await admin.execute(change["revoke"])
        await admin.execute(
            f"CREATE ROLE {role} LOGIN PASSWORD '{password}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        role_created = True
        await admin.execute(f"GRANT CONNECT ON DATABASE tamforge_test TO {role}")
        await admin.execute(f"CREATE SCHEMA {schema}")
        await admin.execute(f"CREATE SCHEMA {other}")
        await admin.execute(f"CREATE TABLE {schema}.counts (account_id text, ticket_count integer)")
        # Exercise both sequence and non-sequence catalog rows in every audit.
        await admin.execute(f"CREATE SEQUENCE {schema}.private_sequence")
        await admin.execute(f"INSERT INTO {schema}.counts VALUES ('a', 2), ('b', 1)")
        await admin.execute(f"CREATE TABLE {other}.secrets (value text)")
        await admin.execute(f"INSERT INTO {other}.secrets VALUES ('private')")
        await admin.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
        await admin.execute(f"GRANT SELECT ON {schema}.counts TO {role}")
        exercise = SqlExercise(
            key="support_counts",
            version=1,
            schema_name=schema,
            role_name=role,
            task_stable_ids=("fixture.sql.support-counts",),
            columns=("account_id", "ticket_count"),
            expected_rows=(("a", "2"), ("b", "1")),
            grain_columns=("account_id",),
            ordered=False,
        )
        dsn = url.set(username=role, password=password).render_as_string(hide_password=False)
        catalog = SqlExerciseCatalog(exercises=(exercise,), dsns={exercise.key: dsn})
        yield admin, exercise, catalog, other
    finally:
        try:
            # Each cleanup action is independent; a failure must not skip ACL restoration.
            errors = []
            cleanup = [
                f"DROP SCHEMA IF EXISTS {schema} CASCADE",
                f"DROP SCHEMA IF EXISTS {other} CASCADE",
            ]
            if role_created:
                cleanup.extend([f"DROP OWNED BY {role}", f"DROP ROLE {role}"])
            cleanup.extend(reversed(restore))
            for sql in cleanup:
                try:
                    await admin.execute(sql)
                except Exception as error:
                    errors.append(error)
            if errors:
                raise AssertionError("SQL integration fixture cleanup failed") from errors[0]
        finally:
            await admin.close()


def test_restricted_role_execution_and_cleanup(test_database_url: str) -> None:
    from tamforge_backend.workspaces.sql_contracts import SqlRunnerError
    from tamforge_backend.workspaces.sql_runner import PostgresSqlRunner

    async def scenario():
        async with restricted_database(test_database_url) as (admin, ex, catalog, other):
            runner = PostgresSqlRunner(catalog)
            result = await runner.run(
                ex, "SELECT account_id, ticket_count FROM counts ORDER BY 1 DESC"
            )
            assert result.validation == "matched"
            assert result.rows == (("b", "1"), ("a", "2"))
            # The system-read baseline must retain ordinary public metadata.
            assert (await runner.run(ex, "SELECT relname FROM pg_catalog.pg_class LIMIT 1")).rows
            assert (
                await runner.run(ex, "SELECT table_name FROM information_schema.tables LIMIT 1")
            ).rows
            # pg_subscription permits selected columns but keeps subconninfo private.
            assert (
                await runner.run(ex, "SELECT oid FROM pg_catalog.pg_subscription LIMIT 1")
            ).columns == ("oid",)
            # A semicolon in a literal is legal; server preparation owns statement cardinality.
            assert (
                await runner.run(ex, "SELECT ';' AS account_id, 1 AS ticket_count")
            ).row_count == 1
            cases = [
                (f"SELECT * FROM {other}.secrets", "rejected_query"),
                ("SELECT * FROM public.owners", "rejected_query"),
                ("SELECT pg_read_file('/etc/passwd')", "rejected_query"),
                ("SELECT pg_read_binary_file('/etc/passwd')", "rejected_query"),
                ("COPY (SELECT 1) TO PROGRAM 'true'", "rejected_query"),
                ("COPY (SELECT 1) TO '/tmp/tamforge-sql-forbidden'", "rejected_query"),
                ("SELECT pg_sleep(3)", "timeout"),
                ("SELECT 1; SELECT 2", "rejected_query"),
                (
                    "SELECT 'a' AS account_id, repeat('é', 131072) AS ticket_count",
                    "result_too_large",
                ),
                (
                    "SELECT i AS account_id, i AS ticket_count FROM generate_series(1,1001) i",
                    "result_too_large",
                ),
                ("SELECT " + ",".join(f"1 AS c{i}" for i in range(33)), "result_too_large"),
                ("UPDATE counts SET ticket_count=9 RETURNING *", "rejected_query"),
                ("CREATE TEMP TABLE bad AS SELECT 1", "rejected_query"),
            ]
            for query, code in cases:
                with pytest.raises(SqlRunnerError) as caught:
                    await runner.run(ex, query)
                assert caught.value.code == code
                assert str(caught.value) == code
                # A previous aborted session never affects the next run.
                assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"
            assert (
                await admin.fetchval(f"SELECT sum(ticket_count) FROM {ex.schema_name}.counts") == 3
            )
            # This setting is session-scoped; rollback/close removes it even after success.
            await runner.run(ex, "SELECT set_config('application_name', 'learner-marker', false)")
            assert (
                await runner.run(ex, "SELECT current_setting('application_name') AS name")
            ).rows == (("tamforge_sql_learning",),)
            for _ in range(30):
                sessions = await admin.fetchval(
                    "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE usename=$1",
                    ex.role_name,
                )
                if sessions == 0:
                    break
                await asyncio.sleep(0.01)
            assert sessions == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "drift",
    [
        "identity",
        "superuser",
        "createdb",
        "createrole",
        "replication",
        "bypassrls",
        "membership",
        "schema",
        "table",
        "column",
        "public_table",
        "sequence",
        "public_sequence",
        "function",
        "public_function",
        "own_function",
        "view",
        "ownership",
        "write",
        "temporary",
        "server_file",
        "parameter",
        "tablespace",
    ],
)
def test_privilege_drift_fails_closed_before_learner_sql(
    test_database_url: str, drift: str
) -> None:
    import asyncpg
    from tamforge_backend.workspaces.sql_contracts import SqlRunnerError
    from tamforge_backend.workspaces.sql_runner import PostgresSqlRunner

    async def scenario():
        async with restricted_database(test_database_url) as (admin, ex, catalog, other):
            role, schema = ex.role_name, ex.schema_name
            # A broken audit must fail here, never satisfy the negative assertion.
            assert (
                await PostgresSqlRunner(catalog).run(ex, "SELECT * FROM counts")
            ).validation == "matched"
            revert = None
            if drift in {"superuser", "createdb", "createrole", "replication", "bypassrls"}:
                await admin.execute(f"ALTER ROLE {role} {drift.upper()}")
            elif drift == "membership":
                await admin.execute(f"GRANT pg_read_all_data TO {role}")
            elif drift == "schema":
                await admin.execute(f"GRANT USAGE ON SCHEMA {other} TO {role}")
            elif drift in {"table", "public_table", "column"}:
                recipient = "PUBLIC" if drift == "public_table" else role
                privilege = "SELECT(value)" if drift == "column" else "SELECT"
                await admin.execute(f"GRANT {privilege} ON {other}.secrets TO {recipient}")
            elif drift in {"sequence", "public_sequence"}:
                recipient = "PUBLIC" if drift == "public_sequence" else role
                await admin.execute(
                    f"GRANT USAGE ON SEQUENCE {schema}.private_sequence TO {recipient}"
                )
            elif drift in {"function", "public_function", "own_function"}:
                target = schema if drift == "own_function" else other
                await admin.execute(
                    f"CREATE FUNCTION {target}.read_secret() RETURNS text "
                    "LANGUAGE sql SECURITY DEFINER AS 'SELECT ''private''::text'"
                )
                if drift != "public_function":
                    await admin.execute(
                        f"REVOKE ALL ON FUNCTION {target}.read_secret() FROM PUBLIC"
                    )
                    if drift == "function":
                        await admin.execute(
                            f"GRANT EXECUTE ON FUNCTION {target}.read_secret() TO {role}"
                        )
            elif drift == "view":
                await admin.execute(f"CREATE VIEW {schema}.leak AS SELECT * FROM {other}.secrets")
                await admin.execute(f"GRANT SELECT ON {schema}.leak TO {role}")
            elif drift == "ownership":
                await admin.execute(f"ALTER TABLE {other}.secrets OWNER TO {role}")
            elif drift == "write":
                await admin.execute(f"GRANT UPDATE ON {schema}.counts TO {role}")
            elif drift == "temporary":
                await admin.execute(f"GRANT TEMPORARY ON DATABASE tamforge_test TO {role}")
            elif drift == "server_file":
                await admin.execute(
                    f"GRANT EXECUTE ON FUNCTION pg_catalog.pg_read_file(text) TO {role}"
                )
                revert = f"REVOKE EXECUTE ON FUNCTION pg_catalog.pg_read_file(text) FROM {role}"
            elif drift == "parameter":
                await admin.execute(f"GRANT SET ON PARAMETER session_preload_libraries TO {role}")
            elif drift == "tablespace":
                await admin.execute(f"GRANT CREATE ON TABLESPACE pg_default TO {role}")

            connector = asyncpg.connect
            if drift == "identity":

                async def connector(_dsn, **kwargs):
                    from sqlalchemy.engine import make_url

                    url = make_url(test_database_url).set(drivername="postgresql")
                    return await asyncpg.connect(
                        url.render_as_string(hide_password=False), **kwargs
                    )

            try:
                with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
                    await PostgresSqlRunner(catalog, connector=connector).run(
                        ex,
                        "SELECT 1/0 AS marker_that_must_not_run",
                    )
            finally:
                if revert:
                    await admin.execute(revert)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("relation", "column"),
    [
        ("pg_catalog.pg_authid", "rolpassword"),
        ("pg_catalog.pg_statistic", "stavalues1"),
        ("pg_catalog.pg_subscription", "subconninfo"),
        ("pg_catalog.pg_user_mapping", "umoptions"),
        ("information_schema._pg_user_mappings", "umoptions"),
    ],
)
@pytest.mark.parametrize("public", [False, True], ids=["direct", "public"])
@pytest.mark.parametrize("column_only", [False, True], ids=["table", "column"])
def test_private_system_relation_grant_fails_closed(
    test_database_url: str, relation: str, column: str, public: bool, column_only: bool
) -> None:
    from tamforge_backend.workspaces.sql_contracts import SqlRunnerError
    from tamforge_backend.workspaces.sql_runner import PostgresSqlRunner

    async def scenario():
        async with restricted_database(test_database_url) as (admin, ex, catalog, _other):
            runner = PostgresSqlRunner(catalog)
            assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"
            recipient = "PUBLIC" if public else ex.role_name
            privilege = f"SELECT ({column})" if column_only else "SELECT"
            # Do not revoke a pre-existing privilege on shared system objects.
            if column_only:
                assert not await admin.fetchval(
                    "SELECT pg_catalog.has_column_privilege("
                    "$1::name, $2::text, $3::text, 'SELECT')",
                    recipient.lower(),
                    relation,
                    column,
                )
            else:
                assert not await admin.fetchval(
                    "SELECT pg_catalog.has_table_privilege($1::name, $2::text, 'SELECT')",
                    recipient.lower(),
                    relation,
                )
            # Table-level REVOKE also removes column grants (e.g. pg_subscription).
            # Preserve PUBLIC's existing column SELECTs using supported GRANTs.
            column_restores = await admin.fetch(
                """
                SELECT pg_catalog.format('GRANT SELECT (%I) ON %s TO PUBLIC',
                                         att.attname, att.attrelid::pg_catalog.regclass) AS sql
                FROM pg_catalog.pg_attribute att,
                     LATERAL pg_catalog.aclexplode(att.attacl) acl
                WHERE att.attrelid = $1::text::pg_catalog.regclass AND acl.grantee = 0
                  AND acl.privilege_type = 'SELECT' AND $2 AND NOT $3
                """,
                relation,
                public,
                column_only,
            )
            try:
                await admin.execute(f"GRANT {privilege} ON {relation} TO {recipient}")
                with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
                    await runner.run(ex, "SELECT 1/0 AS marker_that_must_not_run")
            finally:
                errors = []
                cleanup = [f"REVOKE {privilege} ON {relation} FROM {recipient}"]
                cleanup.extend(restore["sql"] for restore in column_restores)
                for sql in cleanup:
                    try:
                        await admin.execute(sql)
                    except Exception as error:
                        errors.append(error)
                if errors:
                    raise AssertionError("System relation ACL restoration failed") from errors[0]
            assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"
            assert (
                await runner.run(ex, "SELECT oid FROM pg_catalog.pg_subscription LIMIT 1")
            ).columns == ("oid",)

    asyncio.run(scenario())


@pytest.mark.parametrize("schema", ["pg_catalog", "information_schema"])
@pytest.mark.parametrize("public", [False, True], ids=["direct", "public"])
def test_system_schema_create_grant_fails_closed(
    test_database_url: str, schema: str, public: bool
) -> None:
    from tamforge_backend.workspaces.sql_contracts import SqlRunnerError
    from tamforge_backend.workspaces.sql_runner import PostgresSqlRunner

    async def scenario():
        async with restricted_database(test_database_url) as (admin, ex, catalog, _other):
            runner = PostgresSqlRunner(catalog)
            assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"
            recipient = "PUBLIC" if public else ex.role_name
            assert not await admin.fetchval(
                "SELECT pg_catalog.has_schema_privilege($1::name, $2::text, 'CREATE')",
                recipient.lower(),
                schema,
            )
            try:
                await admin.execute(f"GRANT CREATE ON SCHEMA {schema} TO {recipient}")
                with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
                    await runner.run(ex, "SELECT 1/0 AS marker_that_must_not_run")
            finally:
                await admin.execute(f"REVOKE CREATE ON SCHEMA {schema} FROM {recipient}")
            assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("relation", "column"),
    [("pg_catalog.pg_class", "relname"), ("information_schema.sql_features", "feature_name")],
)
@pytest.mark.parametrize("privilege", ["UPDATE", "UPDATE ({column})", "SELECT"])
def test_public_system_metadata_write_or_grant_option_fails_closed(
    test_database_url: str, relation: str, column: str, privilege: str
) -> None:
    from tamforge_backend.workspaces.sql_contracts import SqlRunnerError
    from tamforge_backend.workspaces.sql_runner import PostgresSqlRunner

    async def scenario():
        async with restricted_database(test_database_url) as (admin, ex, catalog, _other):
            runner = PostgresSqlRunner(catalog)
            assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"
            grant = privilege.format(column=column)
            option = " WITH GRANT OPTION" if privilege == "SELECT" else ""
            # This fresh role has no direct catalog ACLs; DROP OWNED also cleans them up.
            try:
                await admin.execute(f"GRANT {grant} ON {relation} TO {ex.role_name}{option}")
                with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
                    await runner.run(ex, "SELECT 1/0 AS marker_that_must_not_run")
            finally:
                await admin.execute(f"REVOKE {grant} ON {relation} FROM {ex.role_name}")
            assert (await runner.run(ex, "SELECT * FROM counts")).validation == "matched"

    asyncio.run(scenario())
