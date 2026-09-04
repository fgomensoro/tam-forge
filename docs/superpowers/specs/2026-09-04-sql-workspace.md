# Isolated SQL workspace (#89)

This delivery completes ticket #89 after the merge of PR #147. Completion requires
full acceptance, independent review and all CI checks on the exact merged commit.
No additional backlog tickets are included in this delivery.

## Authority and isolation

The native redesign replaces old React instructions. The six-week Phase 1 design
supersedes old weekday budgets. Activity task snapshots remain authoritative;
this ticket adds no timer or roadmap policy and never changes task definitions.
The other active session owns roadmap transition and release configuration.
Do not edit that work or any recording, audio, recovery, or authentication module.

## Observable result

An owner opens an active SQL activity in SwiftUI, edits SQL, and can run it against
its configured exercise. The backend selects the exercise from the immutable
task ID, never a client-supplied DSN or schema. It returns bounded rows, measured
execution time, exact-result and grain validation, plus an immutable execution
receipt. Query and result remain visible alongside explanation, business meaning,
assistance, the existing output commitment and mandatory self-review. Failed or
unconfigured execution cannot masquerade as successful validation. Manual saved
SQL evidence remains available when the executor is disabled.

## Security boundary

Use the existing asyncpg dependency, PostgreSQL role privileges and a read-only
transaction. Do not treat SQL parsing or a SELECT prefix as the security boundary.
One prepared statement, no client-provided identifiers for application queries.
One execution at a time, 100 ms capacity wait, two-second statement timeout,
250 ms lock timeout, five-second overall connection/execution/cleanup budget,
64 KiB query, 1000 rows, 256 KiB canonical result and at most 32 columns. Read rows
incrementally in batches of at most 25. Close the connection after every run;
rollback on every outcome. No shared runner session survives a query.

Each configured exercise has its own restricted login role and allowlisted
schema. Roles have no superuser, replication, bypass-RLS, role/database creation,
role memberships, server-file/program privileges, ownership, or grants outside
their exercise schema (excluding standard system catalogs). The runtime must
check the connected identity and reject unsafe privilege drift before preparing
learner SQL. The intended production target is a separately provisioned learning
database; no provisioning runs here. CI can establish temporary roles/schemas
inside its already isolated `tamforge_test`, restore grants on teardown, and must
not create a database, start local Docker, or touch real services.

Do not use the application DB credentials as a fallback. Execution is disabled
unless an explicit server-side exercise catalog and DSN environment mapping are
present and valid. DSNs are secret values; public settings/errors never include
them. The example catalog uses synthetic support-ticket data and an explicit
fixture task ID, not guessed production mappings. An operator must provision and
map real exercises separately before enabling them.

## Contracts

Keep runtime contracts in `workspaces/sql_contracts.py`, separate from the driver.
Use frozen Pydantic models with extra fields forbidden:

- `SqlExercise`: `key`, `version` (positive integer), `schema_name`, `role_name`,
  `task_stable_ids` (nonempty tuple), `columns` (unique tuple of 1–32 names),
  `expected_rows` (tuple of rows of string-or-null cells), `grain_columns`
  (nonempty subset of columns), `ordered` (boolean). Identifiers use strict
  lowercase ASCII SQL identifier syntax and bounded lengths. DSN is separate.
- `SqlResult`: `columns`, `rows`, `elapsed_ms`, `row_count`, `result_sha256`,
  `validation` (`matched`, `mismatch`, `wrong_grain`), `exercise_key`,
  `exercise_version`. Booleans/numbers/dates/UUIDs normalize deterministically to
  strings; SQL NULL remains null. Reject unsupported values, nonfinite floats,
  duplicate columns, oversized or ragged results. Hash canonical UTF-8 JSON.
- `SqlExecutionCommand`: `expected_version`, `query`; existing `Idempotency-Key`
  header owns retries. No schema, DSN, owner or expected result in the command.
- `SqlExecutionResponse`: `execution_id`, `activity_id`, `query`, `query_sha256`, `result`.
  The query is the exact immutable submitted text, bounded to 64 KiB, available
  only through owner-scoped receipts. History can therefore show the query that
  produced each result after reopening, without replacing a current draft.
- `SqlExecutionHistory`: bounded list of the most recent execution receipts.

Validation compares exact columns and all rows (multiplicity preserved; ordering
only when configured). Grain checks uniqueness of the configured composite key,
including deterministic handling of NULL. Do not truncate and call it matched.
Synthetic golden example: columns `(account_id, ticket_count)`, expected rows
`((a, 2), (b, 1))`, grain `(account_id)`, unordered; reversed row order matches,
duplicate `a` is `wrong_grain`, changed count is `mismatch`.

## Persistence and API

Add one append-only `sql_executions` model/migration with owner+activity composite
FK, immutable task/exercise version, query, query hash, canonical result JSON text/hash, measured
elapsed time, created timestamp, idempotency key and request digest. Bound stored
payloads. Unique owner/activity/idempotency; same request replay returns the
same receipt and cannot execute SQL again, different input conflicts. Database
triggers and ORM guards reject updates/deletes. Do not fork activities, attempts,
timers, self-review, or the existing output contract.

`POST /api/v1/activities/{activity_id}/sql-executions` requires the existing owner
and mutation/CSRF dependency. It checks ownership, active state, SQL block and
expected version before running the driver; serializes against activity commands
and commits its immutable receipt before returning success. Failures leave no
partial receipt. `GET` on the same path is owner-scoped, bounded to 20 recent
receipts within a 1 MiB encoded response budget, and does not execute SQL. Omit
oldest receipts that exceed the budget, never truncate a receipt or its result.
Canonical JSON text storage preserves the exact result byte bound without
JSONB rendering overhead. Missing/unsafe configuration returns a fixed
503 reason; invalid query/result or rejected SQL returns safe 422; capacity
exhaustion returns safe 429; stale state/idempotency mismatch returns 409. All
responses/errors are no-store and never serialize raw driver exceptions.

Use a small `SqlRunner` protocol with async `run(exercise, query) -> SqlResult`
and the concrete PostgreSQL driver, allowing route/service tests to substitute
only the external database executor. Persist through real application database
resources in CI; pure unit policy and driver-boundary tests must not start DBs.
Regenerate native OpenAPI after API changes and verify drift.

## Native integration

Extend `ActivityAPI` with SQL execution/history methods and a default unavailable
implementation so existing fixtures retain manual SQL capture. `LiveActivityAPI`
implements those methods through the existing typed transport and generated
schemas. Add small SQL-specific models/view-model and a panel in the existing
activity workspace. Keep session authentication and app service wiring intact.

UI states: not configured, idle, running, result, safe error. Disable Run for
blank SQL, inactive activity, or an in-flight run. Bind the receipt to the submitted
query; do not silently attach it to an edited query. Retries reuse the request
key only for the identical request. Preserve query/explanation on errors and
support history after reopening. Do not auto-commit learner output or self-review.
Display execution validation distinctly from learner explanations and assessment
scores. No hints, AI submission, external SQL tool, or live deployment in #89.

## Verification and release

Local: focused Python contracts/security tests, lint/mypy, Swift parse if useful,
OpenAPI drift. CI: actual restricted-role PostgreSQL tests for successful SELECT,
cross-exercise/application denial, server-file/program denial, timeout, multiple
statement rejection, row/byte limits and rollback/connection closure. API tests
prove owner isolation, idempotency and immutable persistence. Native tests prove
input retention, request/receipt binding, disabled states and live request encoding.
All existing backend, integration, E2E, OpenAPI, secret and native gates must pass.

References for the driver boundary:
- https://www.postgresql.org/docs/16/sql-set-transaction.html
- https://www.postgresql.org/docs/16/ddl-priv.html
- https://magicstack.github.io/asyncpg/current/api/index.html
