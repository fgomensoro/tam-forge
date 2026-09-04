# SQL learning runner

Execution is disabled until an operator explicitly configures both a validated
exercise catalog and separate learning-database credentials. The application
database URL is never a fallback. This document describes manual provisioning
expectations; it is not a provisioning script. No real dataset, credentials, or
production task mapping is supplied by the example.

## Configuration

`TAMFORGE_SQL_EXERCISE_CATALOG` is the absolute path to a JSON file with
`catalog_version: 1` and `exercises`. The synthetic example is
`config/sql-exercises.example.json`: two accounts with ticket counts `a=2`, `b=1`,
mapped only to `fixture.sql.support-counts`. Operators must provision their own
data and map immutable real task stable IDs before enabling a production exercise.
Each exercise has a unique key, schema, and login role. A task cannot map to two
exercises. Changing the expected result or dataset requires a new exercise version.

`TAMFORGE_SQL_EXERCISE_DSNS` is a secret JSON object keyed by exercise key. Every
configured exercise needs exactly one DSN; extra mappings are rejected. Supply
these values through the service's secret manager. Use a PostgreSQL URL with an
explicit host, database, and the exact configured role as username. The only
accepted URL option is `sslmode=require`, `verify-ca`, or `verify-full`; use
`verify-full` and a trusted certificate for production. Driver/user/options
overrides are rejected. Do not put DSNs in catalogs, client requests, logs, or
source control. Invalid settings return closed errors that contain no DSN/input.

Absent either setting leaves execution disabled. A malformed, ambiguous, or
unsafe configuration fails closed. Manual SQL evidence remains independently
available. A configured example is not evidence of a usable production mapping.

## Required PostgreSQL boundary

Use a separately provisioned PostgreSQL 16 learning database with synthetic/non-sensitive data,
resource isolation, and trusted administrative ownership. Application credentials
and application data must not be present in this database. Keep PostgreSQL updated
and control extension installation and changes to schema objects/ACLs. Do not
change privileges concurrently with learner executions: the audit detects drift
before each prepared statement, not privileged administrative changes afterward.

Provision each exercise's login with no superuser, replication, bypass-RLS,
database/role creation, role memberships, object ownership, foreign-server access,
large-object access, or server-file/program privileges. Grant only database
CONNECT, USAGE on its exercise schema, and SELECT on its ordinary exercise tables,
without grant options. There must be no write or column-level write privileges,
sequence privileges, database CREATE/TEMPORARY, or grants outside that schema.
Ordinary publicly readable `pg_catalog` and `information_schema` metadata remains
available; extra system-relation reads, writes, grant options, and system-schema
CREATE or USAGE grant options fail the audit.

System reads use a positive baseline, not the current PUBLIC grants. For catalog
tables and columns, the baseline is PUBLIC SELECT recorded by initdb in
[`pg_init_privs`](https://www.postgresql.org/docs/16/catalog-pg-init-privs.html)
with `privtype = 'i'`; extension initial grants do not qualify. Table and column
grants to the runner or PUBLIC must be SELECT without a grant option, covered by
an initial table-level read or the same initial column-level read. For example,
the standard public columns of `pg_subscription` remain readable while a grant
on its `subconninfo` column, `pg_authid`, or `pg_authid.rolpassword` is refused.
Missing initial read privileges fail closed.

PostgreSQL 16 creates `information_schema` after recording those initial ACLs.
The runner therefore has one explicit list of all 62 PUBLIC SELECT relations from
the upstream
[`REL_16_15` information-schema script](https://github.com/postgres/postgres/blob/REL_16_15/src/backend/catalog/information_schema.sql),
also restricted to built-in object OIDs below 16384. Private helper views and
later-created relations cannot gain read access through new grants. The audit
requires PostgreSQL major version 16; a major upgrade requires baseline review,
an updated supported-version check, and the real PostgreSQL integration matrix
before execution can resume. Preserve trusted ownership and the initdb baseline;
this is an ACL-drift boundary, not protection against a malicious database
administrator or administrator changes to system object definitions.

The runtime evaluates effective privileges, including `PUBLIC`. Default PostgreSQL
grants generally require explicit administrative adjustment in the dedicated
learning database: remove PUBLIC TEMPORARY, PUBLIC USAGE/CREATE on non-system
schemas such as `public`, and PUBLIC EXECUTE on non-system functions. Remove any
PUBLIC table/column/sequence grants outside the exercise. Revoking a direct role
grant does not negate an inherited PUBLIC grant. Review default privileges for
future objects as well as current grants.

Keep exercise schemas to ordinary tables and built-in PostgreSQL data types. The
runtime rejects access to views, materialized views, foreign tables, cross-schema
inheritance/partitions, and functions in the exercise schema, even functions whose
EXECUTE privilege was revoked. These can expose other owners' authority or invoke
code indirectly through operators. Non-system executable functions and extension
functions installed in system schemas also fail the audit. Do not install custom
casts/operators/type codecs or untrusted extensions in the learning database;
PostgreSQL privileges do not make arbitrary administrator-installed code safe.

One serving process must share one `PostgresSqlRunner` instance. Its capacity is
one execution with a 100 ms wait; additional processes need equivalent shared
admission control at deployment. Limit database role connections and provision
PostgreSQL statement/memory/workload limits as additional operational controls.
This task creates no databases, roles, or grants outside its CI fixture.

## Execution and results

Every run opens a new asyncpg connection, begins a read-only transaction, sets a
two-second statement timeout and 250 ms lock timeout, fixes the search path, and
audits connected identity and grants before preparing the learner's query. Only
one PostgreSQL prepared statement is accepted; SQL prefixes/parsing are not the
security boundary. SQL is passed separately to `prepare`, never interpolated into
application SQL. The runner also imposes a two-second wall-clock query budget and
a five-second connection/execution/cleanup budget, reserving cleanup time.

Queries are limited to 64 KiB of UTF-8. Results have at most 32 columns, 1000 rows,
and 256 KiB of canonical UTF-8 JSON for `columns` and `rows`. The driver fetches
batches of at most 25 and rejects excess rows/bytes immediately; it never returns a
partial result. asyncpg must receive/decode an individual PostgreSQL DataRow before
Python can validate its size. The canonical byte cap is a response/storage bound,
not a hard bound on server allocation, client buffers, or process RSS. A huge single
cell can allocate substantially more memory before rejection; production enablement
requires the separately provisioned resource boundary described above.

Values normalize to strings: lowercase booleans, deterministic numeric text,
ISO date/time text and canonical UUID text; SQL NULL remains null. Unsupported
types, nonfinite numbers, duplicate columns, and ragged rows are rejected.
Decimals retain their value without ambient-context rounding and drop trailing
fractional zeros. Numeric strings are compared exactly (for example float `2.0`
differs from integer `2`). Composite grain keys must be unique and non-NULL.
Validation preserves row multiplicity and checks order only when the exercise
requires it. The SHA-256 digest covers compact UTF-8 JSON with keys `columns`,
then `rows`; it preserves the actual returned order independently of validation.

All outcomes attempt rollback and close, with synchronous connection termination
if graceful cleanup fails or times out. Caller cancellation cannot interrupt
cleanup. No connection is pooled or reusable after a run, and a cleanup failure
cannot produce a successful result. Fixed errors include disabled/unknown exercise,
unsafe configuration, unavailable, busy, timeout, invalid/rejected query, invalid
result, and result too large. Do not serialize underlying database exceptions.

## Verification

Pure unit tests never connect to a database. PostgreSQL tests are marked
`integration` and use the existing `test_database_url` fixture, which requires an
explicit `TEST_DATABASE_URL` for `tamforge_test`. No Docker or database creation
occurs. CI temporarily creates schemas/login roles in that database and adjusts
PUBLIC ACLs, restoring the original effective privilege sets and dropping temporary
objects in `finally`, including on assertion failures. Default NULL ACLs may become
explicit equivalent ACLs through GRANT restoration; no direct catalog writes occur.
Run these cases serially without concurrent migrations or other ACL-mutating tests.
Every negative privilege-drift case first completes a matching own-schema query
before changing grants or identity, so an audit exception cannot masquerade as a
successful rejection. Catalog cases cover direct/PUBLIC table and column reads,
system-schema CREATE, writes and grant options, and ordinary metadata access.
Restoration also preserves pre-existing PUBLIC column grants when a table-level
REVOKE would remove them.

Relevant upstream contracts: [PostgreSQL read-only transactions](https://www.postgresql.org/docs/16/sql-set-transaction.html),
[effective privileges and PUBLIC](https://www.postgresql.org/docs/16/ddl-priv.html), and
[asyncpg prepared statements/cursors/connection cleanup](https://magicstack.github.io/asyncpg/current/api/index.html).
