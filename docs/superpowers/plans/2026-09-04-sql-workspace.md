# Isolated SQL workspace implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete #89 with an isolated SQL executor, immutable execution evidence,
and native SQL controls over the existing activity workflow.

**Architecture:** Closed contracts and restricted PostgreSQL driver first; then
owner-scoped durable API; then native typed client and UI. PostgreSQL privileges
enforce isolation, and original activity/output/self-review remain canonical.

**Tech Stack:** Python 3.12+, asyncpg, FastAPI, SQLAlchemy/Alembic, Swift 6/SwiftUI.

**Spec:** `docs/superpowers/specs/2026-09-04-sql-workspace.md`

## Global Constraints

- Native SwiftUI only; no React/Node/local Python/local PostgreSQL distribution.
- Do not edit roadmap transition/release, recording, recovery or authentication.
- Activity task snapshots own timing; no old weekday budgets reintroduced.
- No local Docker, Xcode, hardware capture, production provisioning or model calls.
- Existing isolated CI PostgreSQL is allowed; no test database creation.
- No app DB credential fallback, no raw SQL/DSN/results in logs or safe errors.
- Query 64 KiB; 1000 rows; canonical result 256 KiB; 32 columns; fetch batch 25.
- One execution; capacity wait 100 ms; statement timeout 2 seconds; lock timeout
  250 ms; whole connection/execution/cleanup budget 5 seconds.
- Database receipt committed before success; same-key replay cannot rerun SQL.
- A ticket is complete only after review and all CI gates pass on exact HEAD.

### Task 1: Bounded result contracts and restricted PostgreSQL driver

**Files:**
- Create `apps/backend/src/tamforge_backend/workspaces/__init__.py`
- Create `apps/backend/src/tamforge_backend/workspaces/sql_contracts.py`
- Create `apps/backend/src/tamforge_backend/workspaces/sql_runner.py`
- Create `apps/backend/src/tamforge_backend/workspaces/sql_settings.py`
- Create `apps/backend/tests/unit/workspaces/__init__.py`
- Create `apps/backend/tests/unit/workspaces/test_sql_contracts.py`
- Create `apps/backend/tests/unit/workspaces/test_sql_runner.py`
- Create `apps/backend/tests/integration/workspaces/test_sql_runner.py`
- Create `docs/runbooks/sql-learning-runner.md`
- Create `config/sql-exercises.example.json`

**Interfaces:** Produces frozen `SqlExercise` and `SqlResult`,
`build_sql_result(exercise, columns, rows, elapsed_ms) -> SqlResult`,
`SqlRunner` protocol with async `run(exercise, query) -> SqlResult`,
`PostgresSqlRunner` concrete implementation and safe `SqlRunnerError` carrying
only a closed `code`. `SqlExerciseCatalog` resolves by task stable ID and provides
the separate secret DSN per exercise. Constructor injection allows tests to
provide catalogs and external connectors; no package-global database connection.

- [ ] Write and run failing golden contract tests using real result validation:

```python
exercise = SqlExercise(
    key="support_counts", version=1,
    schema_name="learning_support", role_name="tamforge_learning_runner_support",
    task_stable_ids=("fixture.sql.support-counts",),
    columns=("account_id", "ticket_count"),
    expected_rows=(("a", "2"), ("b", "1")),
    grain_columns=("account_id",), ordered=False,
)
matched = build_sql_result(exercise, ("account_id", "ticket_count"),
                           (("b", 1), ("a", 2)), 12)
assert matched.validation == "matched"
assert matched.row_count == 2
wrong = build_sql_result(exercise, ("account_id", "ticket_count"),
                         (("a", 2), ("a", 1)), 12)
assert wrong.validation == "wrong_grain"
```

  Also test changed counts/columns, ordered mismatch, duplicates and NULL grain,
  UTF-8 size limits, rows/columns limits, nonfinite/unsupported cells, invalid
  identifiers, unknown exercise, duplicate task assignment, invalid DSN user and
  absent settings. Errors must never echo their input.

- [ ] Implement the declared contracts, deterministic normalization and hashing,
  catalog resolution, and safe settings. Read catalog location from explicit
  `TAMFORGE_SQL_EXERCISE_CATALOG`; read DSN mappings from
  `TAMFORGE_SQL_EXERCISE_DSNS` JSON keyed by exercise key. Missing configuration
  represents disabled execution. Catalog input has `catalog_version: 1` and
  `exercises: [...]`; reject unknown fields and ambiguous task mappings.

- [ ] Write failing driver boundary tests for timeout, busy capacity, duplicate
  statements, unsafe role identity/grants, rollback/close after success/failure,
  and no interpolation of learner SQL into application SQL. Use a narrow external
  connection double only when testing transport cancellation/cleanup; validate
  returned result behavior rather than asserting a mock exists.

- [ ] Implement the driver in this exact order: acquire bounded capacity; resolve
  secret DSN; connect with timeout; begin read-only transaction; set fixed timeout
  and validated search-path values; verify role identity/capabilities/memberships
  and forbidden schema/table/function privileges; prepare the single learner
  query; reject non-row/over-wide output; stream and validate within limits;
  rollback and close in finally; release capacity. Return only a complete result.
  Keep cleanup cancellation-safe and never leave a reusable query session.

- [ ] Add actual CI PostgreSQL tests using `test_database_url`. Create only
  temporary schemas/roles inside `tamforge_test` via its admin test connection,
  restore ACLs and drop those test objects in finally. Test own-schema SELECT,
  denied application/other-exercise access, denied server-file/program operations,
  timeout, oversized/multiple statements and rollback. Mark integration so local
  unit runs cannot open DBs. No privileged production commands run here.

- [ ] Document manual provisioning expectations and the synthetic example catalog,
  with execution disabled until explicit configuration and safe grants exist.
  The runbook is not an automatic provisioning script.

- [ ] Verify and commit:

```sh
PYTHONPATH=apps/backend/src:packages/protocol/src uv run python -m pytest apps/backend/tests/unit/workspaces -q
uv run ruff check apps/backend/src/tamforge_backend/workspaces apps/backend/tests/unit/workspaces apps/backend/tests/integration/workspaces
PYTHONPATH=apps/backend/src:packages/protocol/src uv run mypy apps/backend/src/tamforge_backend/workspaces
git diff --check
```

### Task 2: Owner-scoped immutable execution receipts and routes

**Files:**
- Create `apps/backend/src/tamforge_backend/workspaces/models.py`
- Create `apps/backend/src/tamforge_backend/workspaces/sql_service.py`
- Create `apps/backend/src/tamforge_backend/workspaces/routes.py`
- Create `apps/backend/alembic/versions/20260904_0014_sql_executions.py`
- Modify `apps/backend/src/tamforge_backend/models/__init__.py`
- Modify `apps/backend/src/tamforge_backend/api.py`
- Modify `apps/macos/TAMForge/openapi.yaml` through the generator checker
- Create `apps/backend/tests/unit/workspaces/test_sql_routes.py`
- Create `apps/backend/tests/unit/workspaces/test_sql_execution_schema.py`
- Create `apps/backend/tests/integration/workspaces/test_sql_execution_api.py`

**Interfaces:** Consumes Task 1 contracts/catalog/runner. Produces
`SqlExecutionCommand`, `SqlExecutionResponse`, `SqlExecutionHistory` as described
in the spec, `SqlExecutionService` with async `execute(owner_id, activity_id,
command, idempotency_key)` and `history(owner_id, activity_id)`, plus
`get_sql_execution_service` FastAPI dependency. Wire a lifecycle-safe process
runner, not a new runner/semaphore per request.

- [ ] Write failing schema and route tests: cross-owner denial, missing owner,
  stale version, inactive/non-SQL activity, invalid/oversized query, catalog
  mismatch, unavailable configuration, fixed error responses, no-store and
  CSRF. Auth and DB dependencies may be replaced only at the external boundary.

- [ ] Add the append-only model and migration over the inspected Alembic head.
  Store query/result, hashes, immutable exercise/task versions, owner/activity,
  request digest, idempotency key and timestamp. Match ORM/check constraints,
  owner/activity composite FK and unique request identity. Trigger UPDATE/DELETE
  rejection and register model in the central registry.

- [ ] Implement transactional service with owner-scoped activity lock and receipt
  lookup. Replay compares the complete original request digest first and returns
  saved receipt even after activity progresses. New execution requires current
  active SQL activity and matching expected version. Bind catalog to immutable
  `task_stable_id_snapshot`. Keep all external errors safe. Commit receipt before
  returning; rollback no partial row on any failure. Existing activity timers,
  attempts, commitment and self-review are not duplicated or modified.

- [ ] Add authenticated POST and GET routes from the spec. GET returns at most
  20 most recent receipts; no raw pagination SQL or caller owner fields. Add fixed
  exception mapping and dependency wiring, and regenerate OpenAPI with:

```sh
PYTHONPATH=apps/backend/src:packages/protocol/src uv run python scripts/ci/check_openapi.py --write
```

- [ ] Integration tests through real API/DB prove persistence, owner FK, mutation
  trigger, same-key replay without rerunning the injected executor, conflicting
  payload, state change after receipt, failed execution rollback and bounded
  history. Use existing test fixture setup patterns, never create DBs.

- [ ] Run focused unit, lint, mypy, OpenAPI and migration static checks; commit.
  CI runs the real PostgreSQL tests before the ticket can complete.

### Task 3: Native SQL execution panel and durable result history

**Files:**
- Create `apps/macos/TAMForge/Features/Activities/SqlExecutionModels.swift`
- Create `apps/macos/TAMForge/Features/Activities/SqlExecutionModel.swift`
- Create `apps/macos/TAMForge/Features/Activities/SqlExecutionPanel.swift`
- Modify `apps/macos/TAMForge/Features/Activities/ActivityWorkspaceModel.swift`
- Modify `apps/macos/TAMForge/Features/Activities/LiveActivityAPI.swift`
- Modify `apps/macos/TAMForge/Features/Activities/ActivityWorkspaceView.swift`
- Modify `apps/macos/TAMForge.xcodeproj/project.pbxproj` for new sources/tests
- Create native model and transport regression tests under `apps/macos/TAMForgeTests`
- Update `docs/runbooks/sql-learning-runner.md` with native user workflow

**Interfaces:** Extend `ActivityAPI` with async SQL execution/history functions
using Task 2 generated schemas mapped to small Sendable Swift result types;
provide a default unavailable implementation for existing fixtures. Existing
LiveActivityAPI transport remains the sole authenticated network boundary.
`SqlExecutionModel` owns in-flight request key/query binding and bounded history;
the existing workspace owns learner drafts and commits them as before.

- [ ] Write native regressions before implementation: blank/inactive run refusal,
  one in-flight request, stable retry key, edited-query invalidation, preserving
  draft on network/503/conflict, history reopening and no auto-commit/self-review.
  Transport tests verify exact endpoint, JSON fields, idempotency header and
  bounded typed response, using the established URLProtocol fixture approach.

- [ ] Implement model and client. Do not construct a second auth/session flow.
  Keep query/result strings out of logs and preserve native response size limits.
  Display mismatch/wrong-grain as validation outcomes, never a competency score.

- [ ] Add a SQL-only panel below the existing SQL editor: Run, busy state, fixed
  unavailable/error copy, validation/time/rows and bounded recent results. Do not
  overwrite an edited query with a previous receipt. Preserve explanation,
  business meaning, assistance and existing commit/self-review controls.

- [ ] Register source/test files in the Xcode project. Run only lightweight
  Swift parsing locally; all native compilation/unit/UI validation runs in CI.
  Run backend regression checks and OpenAPI drift, then commit.

- [ ] Obtain whole-branch review and all seven green CI gates for the exact head;
  merge through GitHub, verify the merge commit, and only then close #89/count 1.
