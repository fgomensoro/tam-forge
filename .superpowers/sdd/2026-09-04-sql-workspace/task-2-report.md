# Task 2 report: owner-scoped SQL execution receipts

## Commits

- Implementation: `35ef34231f4f2ed6a558446b804103dc0fdf0c41`
- Base: `29fb20919fe1307ed983327f1e9e68b8a35c796e`

## Delivered behavior

- Added an append-only `sql_executions` model and Alembic revision
  `20260904_0014_sql_executions`, based on the inspected `0013` head.
- Bound every receipt to the owner/activity composite key, immutable task mapping
  snapshot, exercise key/version, exact query text/hash, exact canonical
  `{columns,rows}` JSON text/hash, result metadata, request digest, idempotency
  key, and creation time.
- Added PostgreSQL checks for UTF-8 query/result hash integrity, canonical result
  shape, row/column limits, row-count agreement, query and idempotency bounds,
  plus an UPDATE/DELETE rejection trigger. Matching ORM listeners reject all
  mapped mutations and deletes.
- Added transactional `SqlExecutionService.execute` and `history`. Execution
  locks the owner-scoped activity row, checks a receipt and its full request
  digest before current-state/configuration policy, and therefore replays after
  activity progression or runner reconfiguration. New runs require the current
  active SQL activity/version and resolve the catalog only from
  `task_stable_id_snapshot`.
- Added authenticated POST and GET routes with existing CSRF/auth dependencies,
  fixed secret-safe problems, and no-store responses. One catalog/runner is
  created per app without opening an exercise database. Invalid catalog setup
  leaves execution unavailable without preventing app startup, receipt replay,
  or history.
- History returns the newest complete receipt prefix, capped at 20 items and at
  1 MiB for the complete encoded JSON envelope. It never truncates a query or
  result.
- Regenerated `apps/macos/TAMForge/openapi.yaml` with the exact response fields
  from the approved spec, including immutable query text and its 64 KiB length
  declaration.
- Updated the existing linear Alembic-head regression in
  `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` from `0013` to
  `0014`. This was the only pre-existing test changed, and it was directly
  required by the new migration.

## TDD evidence

1. Added schema and route tests first. The first valid red run reported 15
   feature failures and 1 unrelated pass because the model, service, routes,
   and migration did not exist.
2. Implemented the minimal model/service/route/migration slice. The focused
   suite progressed to 8 failures/8 passes, then 1 failure/15 passes, then 16
   passes.
3. Added database hash/shape constraint expectations first. The targeted test
   failed on the four missing checks before the matching ORM and migration
   checks were added; it then passed 4/4.
4. The broader backend unit run exposed the stale `0013` head assertion with
   919 passes and 1 failure. After the directly caused update, the complete unit
   suite passed.

## Local verification

All commands used the required source path where Python imports were involved.

- `PYTHONPATH=apps/backend/src:packages/protocol/src uv run python -m pytest apps/backend/tests/unit -q`
  - `920 passed, 2 deselected`; one existing Starlette/httpx deprecation warning.
- `uv run ruff check apps/backend/src/tamforge_backend/workspaces apps/backend/tests/unit/workspaces apps/backend/tests/integration/workspaces apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/alembic/versions/20260904_0014_sql_executions.py apps/backend/tests/unit/roadmaps/test_curriculum_schema.py`
  - passed.
- `PYTHONPATH=apps/backend/src:packages/protocol/src uv run mypy apps/backend/src/tamforge_backend/workspaces apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/models/__init__.py`
  - passed for 9 source files.
- `PYTHONPATH=apps/backend/src:packages/protocol/src uv run python scripts/ci/check_openapi.py`
  - native OpenAPI input matches the backend schema.
- `PYTHONPATH=apps/backend/src:packages/protocol/src uv run alembic -c apps/backend/alembic.ini heads`
  - exactly `20260904_0014_sql_executions (head)`.
- `PYTHONPATH=apps/backend/src:packages/protocol/src uv run python -m pytest apps/backend/tests/integration/workspaces/test_sql_execution_api.py --collect-only -m integration -q`
  - 1 CI-only PostgreSQL test collected.
- `git diff --check`
  - passed.

## CI-only PostgreSQL coverage and remaining gate

`apps/backend/tests/integration/workspaces/test_sql_execution_api.py` uses the
existing validated `test_database_url` fixture and real API/application
persistence. It covers owner isolation and the composite FK, immutable trigger,
same-key replay without rerunning the injected executor, conflicting payload,
replay after state progression and missing configuration, stale/inactive/non-SQL
and unmapped activities, failed-run rollback, exact 64 KiB query plus exact
256 KiB canonical result persistence, and the complete 1 MiB history envelope.

Per the task constraint, this PostgreSQL test was collected but not executed
locally. It does not create a database or start Docker. Task 2 remains gated on
the coordinator running this integration test in the existing isolated CI
fixture against the exact implementation commit.

