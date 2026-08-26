# TAM Forge Foundation and Learning Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the private single-user TAM Forge foundation that can import the immutable Month 1 roadmap, instantiate protected study days, run every required task through a universal evidence workspace, and show an inspectable evidence-based Today experience.

**Architecture:** Use a uv + pnpm monorepo with a modular FastAPI backend, React/Vite web client, PostgreSQL 16 as the canonical state store, and a narrow S3-compatible object-store port. Keep domain rules pure and independently tested; routes call application services, services call repositories/ports, and all externally visible mutations are authenticated, idempotent, and audited.

**Tech Stack:** Python 3.12, uv workspaces, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, asyncpg, Authlib/httpx, boto3, PostgreSQL 16 + pgvector, React, TypeScript, Vite, React Router, TanStack Query, Zod, pnpm, Vitest, Testing Library, MSW, Playwright, Ruff, mypy, pytest, Hypothesis, GitHub Actions.

---

## Scope and execution boundaries

This child plan owns:

- monorepo and CI bootstrap;
- the idempotent GitHub issue-planning synchronizer and initial private-repository creation;
- backend/web foundations;
- Alembic revisions 0001 through 0005 reserved below;
- GitHub OAuth restricted to the configured immutable owner ID;
- object-storage abstraction;
- roadmap package validation, immutable snapshots, versioning, semantic diff, GitHub mirror, approval, and activation;
- universal activities, immutable outputs, self-review, timers, and scheduling/time protection;
- the canonical skill/evidence formula, versioned mappings, Portfolio Judgment, ledger, and snapshots;
- Today, minimal corrections/interviews read models, notifications, outbox, and status streaming;
- web routes for roadmap administration, Today, universal workspace, evidence ledger, and notifications.

This child plan does not implement:

- the macOS recorder, WebSocket PCM ingest, or audio durability protocol;
- transcription, pronunciation execution, or speech metrics;
- Claude Agent SDK roles, analysis, or persistent agent memory;
- full opportunity/interview workflows;
- production server rebuild, Gastos deletion, Caddy, backups, or deployment.

Forward-compatible corrections and interviews tables contain only the fields Today needs. Later plans extend behavior without rewriting these IDs or relationships.

## Mandatory execution guardrails

- Do not run any Docker, Docker Compose, or Testcontainers command locally until the user gives explicit approval in that execution turn. The default unit-test commands below never start Docker.
- Integration tests require TEST_DATABASE_URL. When it is absent they skip; they must never autostart Testcontainers.
- Do not touch either Hetzner server in this plan.
- Do not remove Gastos or change Lamas.
- Do not create paid services or paid API usage.
- Do not commit secrets, uploaded roadmap snapshots, database dumps, or object-store credentials to the application branch. Approved roadmap sources may be written only by the mirror adapter to the private roadmap-snapshots branch required by the design.
- Do not modify the Obsidian vault. Initial imports read a user-uploaded folder/ZIP only.
- Do not merge a pull request without explicit user approval.

## Locked repository layout

~~~text
.
├── apps/
│   ├── backend/
│   │   ├── alembic/
│   │   │   └── versions/
│   │   ├── src/tamforge_backend/
│   │   │   ├── auth/
│   │   │   ├── evidence/
│   │   │   ├── jobs/
│   │   │   ├── learning/
│   │   │   ├── notifications/
│   │   │   ├── roadmaps/
│   │   │   ├── storage/
│   │   │   └── today/
│   │   └── tests/
│   └── web/
│       ├── src/
│       └── tests/
├── packages/
│   └── protocol/
│       ├── src/tamforge_protocol/
│       └── tests/
├── config/
│   ├── tam-skills.yaml
│   ├── tam-exercise-types.yaml
│   ├── tam-rubrics.yaml
│   └── tam-roadmap-task-map.yaml
├── docs/project/github-issues.yml
├── scripts/github/
├── compose.dev.yml
├── pyproject.toml
├── package.json
└── pnpm-workspace.yaml
~~~

## API conventions

- Prefix all HTTP routes with /api/v1 except /healthz and OAuth callbacks.
- Use UUID strings at API boundaries and UTC timestamptz in PostgreSQL.
- Use the learner's configured IANA timezone for study dates.
- Mutation requests require the opaque session cookie plus X-CSRF-Token.
- Return RFC 9457-style problem JSON with stable error codes.
- Require Idempotency-Key for retriable import, activity, artifact, self-review, and notification mutations.
- Generate apps/web/src/api/schema.d.ts from the backend OpenAPI document; do not hand-maintain duplicate response interfaces.

## Task 1: Bootstrap the uv + pnpm monorepo

**Files:**

- Create: .editorconfig
- Create: .gitignore
- Create: .env.example
- Create: README.md
- Create: pyproject.toml
- Create: uv.lock
- Create: package.json
- Create: pnpm-workspace.yaml
- Create: pnpm-lock.yaml
- Create: Makefile
- Create: compose.dev.yml
- Create: apps/backend/pyproject.toml
- Create: apps/backend/src/tamforge_backend/__init__.py
- Create: apps/backend/src/tamforge_backend/main.py
- Create: apps/backend/src/tamforge_backend/api.py
- Create: apps/backend/src/tamforge_backend/config.py
- Create: apps/backend/tests/unit/test_health.py
- Create: packages/protocol/pyproject.toml
- Create: packages/protocol/src/tamforge_protocol/__init__.py
- Create: packages/protocol/tests/test_package.py
- Create: apps/web/package.json
- Create: apps/web/index.html
- Create: apps/web/tsconfig.json
- Create: apps/web/vite.config.ts
- Create: apps/web/src/main.tsx
- Create: apps/web/src/App.tsx
- Create: apps/web/src/app.css
- Create: apps/web/tests/App.test.tsx
- Create: apps/web/tests/setup.ts

- [ ] **Step 1: Add workspace manifests and safe defaults**

Confirm the local project is a Git worktree before the first commit:

~~~bash
git rev-parse --show-toplevel
~~~

If that reports that no repository exists, initialize this exact project directory once and verify the resulting root before continuing:

~~~bash
git init -b main
git rev-parse --show-toplevel
~~~

Expected root: /Users/frank/Documents/ChatGPT/TAM Project. Do not initialize a parent directory.

Configure the root uv workspace with members apps/backend and packages/protocol. Configure pytest so the default command excludes the integration marker. Configure pnpm with apps/web as a workspace member. Add .gitignore entries for .env, .venv, node_modules, dist, coverage, .pytest_cache, .mypy_cache, .ruff_cache, local object data, audio, spools, and .superpowers.

The default Makefile targets must be non-Docker:

~~~make
install:
	uv sync --all-packages --all-extras
	pnpm install

test:
	uv run pytest -m "not integration"
	pnpm --filter @tam-forge/web test -- --run

check:
	uv run ruff check .
	uv run mypy apps/backend/src packages/protocol/src
	uv run pytest -m "not integration"
	pnpm --filter @tam-forge/web lint
	pnpm --filter @tam-forge/web typecheck
	pnpm --filter @tam-forge/web test -- --run
~~~

compose.dev.yml may define PostgreSQL/pgvector and MinIO, but no default command may invoke it.

- [ ] **Step 2: Write the failing backend and frontend smoke tests**

~~~python
from fastapi.testclient import TestClient

from tamforge_backend.main import create_app


def test_health_is_explicit_and_contains_no_secret_data() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tam-forge-backend"}
~~~

~~~tsx
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

it("renders the private TAM Forge shell in English", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "TAM Forge" })).toBeVisible();
  expect(screen.getByText("Loading your study workspace…")).toBeVisible();
});
~~~

- [ ] **Step 3: Install dependencies and verify the tests fail for missing implementations**

Run:

~~~bash
uv sync --all-packages --all-extras
pnpm install
uv run pytest apps/backend/tests/unit/test_health.py packages/protocol/tests/test_package.py -q
pnpm --filter @tam-forge/web test -- --run tests/App.test.tsx
~~~

Expected: backend import/health assertion and frontend App assertion fail; neither command starts Docker.

- [ ] **Step 4: Implement the minimal package and app shells**

The backend factory must accept later dependency overrides and expose only health at this stage:

~~~python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="TAM Forge API", version="0.1.0")

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "tam-forge-backend"}

    return app


app = create_app()
~~~

The initial React shell must be English-only, semantic, and contain no product data.

- [ ] **Step 5: Run unit checks**

Run:

~~~bash
uv run pytest apps/backend/tests/unit/test_health.py packages/protocol/tests/test_package.py -q
pnpm --filter @tam-forge/web test -- --run tests/App.test.tsx
uv run ruff check apps/backend packages/protocol
uv run mypy apps/backend/src packages/protocol/src
pnpm --filter @tam-forge/web typecheck
~~~

Expected: all commands pass; Docker remains stopped.

- [ ] **Step 6: Commit the bootstrap**

~~~bash
git add .editorconfig .gitignore .env.example README.md pyproject.toml uv.lock package.json pnpm-workspace.yaml pnpm-lock.yaml Makefile compose.dev.yml apps/backend apps/web packages/protocol
git commit -m "chore: bootstrap tam forge monorepo"
~~~

## Task 2: Add idempotent GitHub planning sync and create the private repository

**Files:**

- Create: docs/project/github-issues.yml
- Track: docs/superpowers/specs/2026-08-25-tam-forge-product-architecture-design.md
- Track: docs/superpowers/plans/2026-08-25-tam-forge-master-implementation-plan.md
- Track: docs/superpowers/plans/2026-08-25-tam-forge-01-foundation-learning.md
- Track: docs/superpowers/plans/2026-08-25-tam-forge-02-recording-speech.md
- Track: docs/superpowers/plans/2026-08-25-tam-forge-03-agents-interviews-operations.md
- Create: scripts/github/__init__.py
- Create: scripts/github/sync_issues.py
- Create: scripts/github/tests/__init__.py
- Create: scripts/github/tests/test_sync_issues.py
- Modify: pyproject.toml
- Modify: README.md

The master implementation plan is the canonical issue catalog. Transcribe that catalog into docs/project/github-issues.yml without inventing or dropping issues.

- [ ] **Step 1: Write failing manifest and idempotency tests**

The manifest schema must contain stable keys, labels, milestones, epics, children, dependencies, acceptance criteria, privacy impact, and verification commands.

~~~yaml
version: 1
repository: fgomensoro/tam-forge
labels:
  - {name: "type:epic", color: "5319E7", description: "Parent delivery epic"}
milestones:
  - {key: foundation, title: "01 Foundation and learning workspace"}
issues:
  - key: EPIC-01
    title: "Epic: Foundation and learning workspace"
    milestone: foundation
    labels: ["type:epic"]
    children: ["FOUND-01"]
    body: "Outcome, scope, and acceptance criteria from the approved plans."
  - key: FOUND-01
    title: "Bootstrap the TAM Forge monorepo"
    epic: EPIC-01
    milestone: foundation
    labels: ["type:feature"]
    depends_on: []
    acceptance: ["Backend and web smoke tests pass."]
    verification: ["make check"]
~~~

The test must run the synchronizer twice against a fake GitHub client and prove the second run is a no-op:

~~~python
def test_second_apply_is_idempotent(manifest_path, fake_github):
    first = sync_manifest(manifest_path, fake_github, apply=True)
    second = sync_manifest(manifest_path, fake_github, apply=True)
    assert first.created
    assert second.created == []
    assert second.updated == []
~~~

Also test:

- dry-run performs no writes;
- the hidden marker <!-- tam-forge-key: KEY --> identifies issues even after title edits;
- labels/milestones are upserted;
- epic bodies receive deterministic child checklists and child bodies receive deterministic parent/dependency links;
- a removed manifest item is reported but never auto-closed;
- malformed keys or dangling epic/dependency references fail before any API call.

- [ ] **Step 2: Run the tests to verify failure**

Run:

~~~bash
uv run pytest scripts/github/tests/test_sync_issues.py -q
~~~

Expected: FAIL because the manifest loader and synchronizer do not exist.

- [ ] **Step 3: Implement the dry-run-first synchronizer**

Use a GhClient protocol around gh api subprocess calls. Keep planning and application separate:

~~~python
class GhClient(Protocol):
    def list_labels(self) -> list[dict[str, object]]: ...
    def list_milestones(self) -> list[dict[str, object]]: ...
    def list_issues(self) -> list[dict[str, object]]: ...
    def create(self, resource: str, payload: dict[str, object]) -> dict[str, object]: ...
    def update(self, resource: str, number: int, payload: dict[str, object]) -> dict[str, object]: ...


def sync_manifest(path: Path, client: GhClient, *, apply: bool) -> SyncPlan:
    manifest = load_and_validate(path)
    current = load_current_state(client)
    plan = build_sync_plan(manifest, current)
    if apply:
        apply_sync_plan(plan, client)
    return plan
~~~

The CLI defaults to --dry-run and requires explicit --apply. Never delete, close, or relabel unrelated issues.

- [ ] **Step 4: Run synchronizer tests and dry-run locally**

Run:

~~~bash
uv run pytest scripts/github/tests/test_sync_issues.py -q
uv run python scripts/github/sync_issues.py --repo fgomensoro/tam-forge --manifest docs/project/github-issues.yml --dry-run
~~~

Expected: tests pass; dry-run prints planned labels, milestones, epics, and children without changing GitHub.

- [ ] **Step 5: Commit the planning synchronizer**

~~~bash
git add docs/project/github-issues.yml docs/superpowers/specs docs/superpowers/plans scripts/github pyproject.toml README.md
git commit -m "feat: add idempotent github planning sync"
~~~

- [ ] **Step 6: Verify the authenticated GitHub owner before external writes**

Run only after this implementation plan is approved:

~~~bash
gh auth status
gh api user --jq .login
~~~

Expected: authenticated account is exactly fgomensoro. Stop if it is any company account or a different personal account.

- [ ] **Step 7: Create or verify the private repository and push**

First inspect:

~~~bash
gh repo view fgomensoro/tam-forge --json nameWithOwner,isPrivate,defaultBranchRef
~~~

Expected alternatives:

- If not found, create it:

~~~bash
gh repo create fgomensoro/tam-forge --private --source=. --remote=origin --push
~~~

- If found, require nameWithOwner fgomensoro/tam-forge and isPrivate true before setting/verifying origin and pushing.

Never create the repository under a company organization.

- [ ] **Step 8: Apply the approved issue catalog and prove idempotency**

Run:

~~~bash
uv run python scripts/github/sync_issues.py --repo fgomensoro/tam-forge --manifest docs/project/github-issues.yml --dry-run
uv run python scripts/github/sync_issues.py --repo fgomensoro/tam-forge --manifest docs/project/github-issues.yml --apply
uv run python scripts/github/sync_issues.py --repo fgomensoro/tam-forge --manifest docs/project/github-issues.yml --dry-run
~~~

Expected: first dry-run shows planned writes, apply creates/updates them, final dry-run reports no changes. Save the output in the task handoff, not as a committed secret-bearing artifact.

- [ ] **Step 9: Start the feature branch for the remaining foundation work**

After the initial main branch is pushed and the issue catalog is synchronized:

~~~bash
git switch -c feat/foundation-learning-workspace
git status --short --branch
~~~

Expected: the branch is feat/foundation-learning-workspace and the worktree is clean. All remaining tasks in this plan commit to this branch.

## Task 3: Establish backend configuration, database sessions, and Alembic

**Files:**

- Create: apps/backend/alembic.ini
- Create: apps/backend/alembic/env.py
- Create: apps/backend/alembic/script.py.mako
- Create: apps/backend/src/tamforge_backend/database.py
- Create: apps/backend/src/tamforge_backend/models/__init__.py
- Create: apps/backend/src/tamforge_backend/models/base.py
- Create: apps/backend/tests/unit/test_config.py
- Create: apps/backend/tests/integration/conftest.py
- Create: apps/backend/tests/integration/test_migrations.py
- Create: scripts/dev/ensure_test_database.sh
- Create: scripts/dev/tests/test_ensure_test_database.py
- Modify: apps/backend/src/tamforge_backend/config.py
- Modify: apps/backend/src/tamforge_backend/main.py
- Modify: apps/backend/pyproject.toml
- Modify: .env.example

- [ ] **Step 1: Write failing settings tests**

Test that production settings reject missing secrets, object-store/GitHub secrets are represented as SecretStr, CORS is deny-by-default, cookie security defaults true outside tests, and the single authorized GitHub user ID is numeric.

~~~python
def test_production_rejects_missing_owner_id(monkeypatch):
    monkeypatch.setenv("TAMFORGE_ENV", "production")
    monkeypatch.delenv("TAMFORGE_GITHUB_USER_ID", raising=False)
    with pytest.raises(ValidationError):
        Settings()
~~~

- [ ] **Step 2: Write a non-autostarting integration fixture and migration test**

The fixture must skip when TEST_DATABASE_URL is absent:

~~~python
@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required; tests never autostart Docker")
    return url
~~~

The migration test upgrades to head, verifies alembic_version, downgrades to base, and upgrades again.

Also write fake-only tests for `scripts/dev/ensure_test_database.sh`. The idempotent helper creates only `tamforge_test` after an approved local PostgreSQL container starts, and refuses non-loopback hosts or database names other than `tamforge_test`. Its tests use fakes and never invoke Docker.

- [ ] **Step 3: Run unit tests and verify expected failures/skips**

Run:

~~~bash
uv run pytest apps/backend/tests/unit/test_config.py scripts/dev/tests/test_ensure_test_database.py -q
uv run pytest apps/backend/tests/integration/test_migrations.py -q
~~~

Expected: settings/helper tests fail before implementation; integration test skips with the exact TEST_DATABASE_URL message. Docker remains stopped.

- [ ] **Step 4: Implement settings, async engine/session factory, metadata, and Alembic**

Use one Settings instance per app lifespan and dependency injection for tests. Configure SQLAlchemy with pool_pre_ping, explicit transaction boundaries, UTC timestamps, and naming conventions for reversible constraints. Alembic env imports the shared Base.metadata and accepts DATABASE_URL with asyncpg translated to a synchronous migration driver where required.

- [ ] **Step 5: Pass unit tests**

Run:

~~~bash
uv run pytest apps/backend/tests/unit/test_config.py scripts/dev/tests/test_ensure_test_database.py -q
uv run ruff check apps/backend/src/tamforge_backend/config.py apps/backend/src/tamforge_backend/database.py apps/backend/alembic
uv run mypy apps/backend/src/tamforge_backend
~~~

Expected: PASS.

- [ ] **Step 6: Run migration harness only after explicit Docker approval**

This step can start Docker and must pause for fresh approval immediately before execution; without that approval, no Docker command in this group may run:

~~~bash
set -e
cleanup_and_verify() {
  original_status=$1
  set +e
  docker compose -f compose.dev.yml down --remove-orphans
  running_ids=$(docker compose -f compose.dev.yml ps --status running --quiet)
  ps_status=$?
  verification_status=0
  if [ "$ps_status" -ne 0 ] || [ -n "$running_ids" ]; then
    docker compose -f compose.dev.yml ps --status running
    verification_status=1
  fi
  trap - EXIT INT TERM
  if [ "$verification_status" -ne 0 ]; then
    exit 1
  fi
  exit "$original_status"
}
on_exit() { cleanup_and_verify "$?"; }
on_int() { cleanup_and_verify 130; }
on_term() { cleanup_and_verify 143; }
trap on_exit EXIT
trap on_int INT
trap on_term TERM
docker compose -f compose.dev.yml up -d postgres
bash scripts/dev/ensure_test_database.sh
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/test_migrations.py -q
exit 0
~~~

Expected: PASS and an empty final `ps --status running`. Every normal, failing, INT, and TERM exit runs `down --remove-orphans` then a fail-closed running-service check; any remaining service/container or failed check exits 1, otherwise the original failure status is preserved. Traps are removed only after that check. If approval is not granted, leave the integration test skipped and rely on the later CI PostgreSQL service.

- [ ] **Step 7: Commit database foundations**

~~~bash
git add .env.example apps/backend scripts/dev/ensure_test_database.sh scripts/dev/tests/test_ensure_test_database.py
git commit -m "feat: add backend database foundation"
~~~

## Task 4: Add Alembic 20260825_0001 identity and sessions

**Files:**

- Create: apps/backend/alembic/versions/20260825_0001_identity_sessions.py
- Create: apps/backend/src/tamforge_backend/auth/__init__.py
- Create: apps/backend/src/tamforge_backend/auth/models.py
- Create: apps/backend/tests/integration/test_0001_identity_sessions.py
- Modify: apps/backend/src/tamforge_backend/models/__init__.py

The revision must create:

- owners: id, immutable github_user_id unique, current github_login, created_at, updated_at;
- auth_sessions: id, owner_id, token_hash unique, csrf_hash, expires_at, revoked_at, last_seen_at, created_at;
- command_receipts: owner, command scope, idempotency key, request hash, result/status payload, created_at, and expiry with unique owner/scope/key;
- audit_events: optional owner, actor kind/subject hash, action, aggregate type/ID, request/idempotency correlation, redacted metadata, and occurred_at; append-only at the application boundary;
- pgcrypto and vector extensions when available;
- indexes for session lookup/expiry;
- restrictive foreign keys and no cascade that could erase owner evidence later.

- [ ] **Step 1: Write the failing schema contract**

Assert exact table/column names, uniqueness of github_user_id/token_hash and owner/scope/idempotency key, request-hash conflict detection, append-only audit behavior, timestamptz usage, restrictive foreign key behavior, and successful downgrade/upgrade.

- [ ] **Step 2: Run it with TEST_DATABASE_URL**

Run only against an already approved/running PostgreSQL:

~~~bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/test_0001_identity_sessions.py -q
~~~

Expected: FAIL because revision 0001 is absent. If no database is running, expected result is SKIP; do not start Docker implicitly.

- [ ] **Step 3: Implement models and reversible migration**

Use explicit check/unique constraints and downgrade objects in dependency-safe reverse order. Never store the raw session or CSRF token.

- [ ] **Step 4: Run unit/static checks and approved integration**

Run:

~~~bash
uv run ruff check apps/backend/src/tamforge_backend/auth apps/backend/alembic/versions/20260825_0001_identity_sessions.py
uv run mypy apps/backend/src/tamforge_backend/auth
~~~

When PostgreSQL is available, rerun the exact integration test. Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/alembic/versions/20260825_0001_identity_sessions.py apps/backend/src/tamforge_backend/auth apps/backend/src/tamforge_backend/models apps/backend/tests/integration/test_0001_identity_sessions.py
git commit -m "feat: add owner and session schema"
~~~

## Task 5: Add Alembic 20260825_0002 curriculum and roadmap versions

**Files:**

- Create: apps/backend/alembic/versions/20260825_0002_curriculum.py
- Create: apps/backend/src/tamforge_backend/roadmaps/__init__.py
- Create: apps/backend/src/tamforge_backend/roadmaps/models.py
- Create: apps/backend/tests/integration/test_0002_curriculum.py
- Modify: apps/backend/src/tamforge_backend/models/__init__.py

The revision must create:

- roadmap_sources;
- roadmap_imports with staged package hash, object key, status, validation report, semantic diff, idempotency key, and failure fields;
- roadmap_versions with source/version/month, predecessor, content hash, object key, manifest, normalized payload, immutable lifecycle timestamps, mirror status/ref/error, and state;
- curriculum_nodes with version-scoped stable IDs, hierarchy, ordinal, source path/anchor;
- task_definitions with version-scoped stable IDs, exercise type/mapping version, objective, timebox, block, required flag, output/pass/evidence JSON, source references, and allowed AI role;
- resources, pass_criteria, exit_criteria;
- month_exit_reviews used by the next-month activation gate.

Required constraints:

- unique source/content hash prevents duplicate logical imports;
- stable IDs are unique inside one roadmap version, not globally;
- exactly one active roadmap version through a partial unique index;
- historical rows use RESTRICT, not cascading deletion;
- state/mirror values use named check constraints so downgrade is reversible.

- [ ] **Step 1: Write failing schema and invariant tests**

Test duplicate import rejection, one-active-version enforcement, predecessor linkage, version-scoped task IDs, and full downgrade.

- [ ] **Step 2: Run the focused integration test**

~~~bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/test_0002_curriculum.py -q
~~~

Expected: FAIL before migration; SKIP rather than Docker autostart when TEST_DATABASE_URL is absent.

- [ ] **Step 3: Implement models and migration**

Store raw/normalized roadmap data as immutable JSONB plus relational task rows. Do not store the Obsidian absolute path as a runtime dependency; canonical_path is provenance only.

- [ ] **Step 4: Run checks**

Run unit/static checks, then the focused integration test when PostgreSQL is available. Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/alembic/versions/20260825_0002_curriculum.py apps/backend/src/tamforge_backend/roadmaps apps/backend/src/tamforge_backend/models apps/backend/tests/integration/test_0002_curriculum.py
git commit -m "feat: add versioned curriculum schema"
~~~

## Task 6: Add Alembic 20260825_0003 study activities

**Files:**

- Create: apps/backend/alembic/versions/20260825_0003_study_activities.py
- Create: apps/backend/src/tamforge_backend/learning/__init__.py
- Create: apps/backend/src/tamforge_backend/learning/models.py
- Create: apps/backend/tests/integration/test_0003_study_activities.py
- Modify: apps/backend/src/tamforge_backend/models/__init__.py

The revision must create:

- learner_settings with owner, IANA timezone, study start date, and active roadmap;
- study_days with local date, roadmap version, planned/focused minutes, day type, status, and unique owner/date;
- activity_instances with task/version snapshots, state, attempt kind, assistance mode, classification, timebox, source-hidden flag, optimistic version, and lifecycle timestamps;
- activity_timer_sessions with start, last heartbeat, pause/end, counted seconds, and unique idempotency key;
- attempts with immutable original text/Markdown/SQL payload, audience, prompt, assistance, commitment hash/time, and A/B relation;
- artifacts as the shared content-addressed source/derived object catalog with owner, object key, hash, content type, original filename, byte size, artifact class, encryption metadata, lineage, and immutable version;
- activity_artifact_links joining an activity/attempt to a shared artifact without making the artifact catalog activity-specific;
- self_reviews with required structured answers and self-score separate from external scores;
- adaptive_changes with what/why/evidence/objective and explicit coverage/time impact;
- daily_closes with evidence confirmation, strongest output, repeated mistake, unfinished classification, and correction count.

Constraints must reject Attempt C, mutation of committed attempt identity, duplicate timer commands, more than one open timer per activity, and more than one activity per task/study day unless explicitly versioned as a replacement.

- [ ] **Step 1: Write the failing schema/state persistence tests**

Assert table contracts, Attempt C rejection, shared Artifact reuse, append-only attempt/artifact-link relationships, optimistic version presence, and restrictive historical foreign keys.

- [ ] **Step 2: Run the focused test**

~~~bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/test_0003_study_activities.py -q
~~~

Expected: FAIL before implementation or SKIP without an explicit database.

- [ ] **Step 3: Implement models and reversible migration**

Use text + named check constraints for states so application enums remain explicit and migration downgrade remains safe. Add indexes for owner/date, study-day/order, state, pending self-review, and active timers.

- [ ] **Step 4: Run static and integration checks**

Expected: all focused checks pass.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/alembic/versions/20260825_0003_study_activities.py apps/backend/src/tamforge_backend/learning apps/backend/src/tamforge_backend/models apps/backend/tests/integration/test_0003_study_activities.py
git commit -m "feat: add study activity schema"
~~~

## Task 7: Add Alembic 20260825_0004 evidence and scoring history

**Files:**

- Create: apps/backend/alembic/versions/20260825_0004_evidence_scoring.py
- Create: apps/backend/src/tamforge_backend/evidence/__init__.py
- Create: apps/backend/src/tamforge_backend/evidence/models.py
- Create: apps/backend/tests/integration/test_0004_evidence_scoring.py
- Modify: apps/backend/src/tamforge_backend/models/__init__.py

The revision must create:

- config_seed_versions;
- competencies with immutable slug and configurable targets;
- exercise_type_versions and exercise_skill_mappings;
- rubric_versions and rubric_dimensions;
- rubric_evaluations and rubric_dimension_scores;
- skill_evidence_events with all raw factors, formula version, qualifying flag/reason, performance score, effective weight, and explanation;
- skill_snapshots with estimate, confidence, trend, recency, target gaps, contributing-event manifest, and snapshot date;
- portfolio_judgment_scores with seven component values, total 0–20, history, and trend basis.

Do not store one mutable current score on competencies as the source of truth. Snapshots are reproducible derived records and evidence events remain inspectable.

- [ ] **Step 1: Write failing schema tests**

Assert all fourteen competency rows can coexist, evidence links one skill per row, one rubric evaluation can create multiple independently scored child events, portfolio total is constrained to 0–20, and all formula/config versions are mandatory.

- [ ] **Step 2: Run the focused migration test**

Run against explicit TEST_DATABASE_URL. Expected: FAIL before implementation or SKIP without a database.

- [ ] **Step 3: Implement models and migration**

Use Numeric rather than float for stored weights/scores. Preserve raw factor values alongside effective weight so future formula versions never rewrite history.

- [ ] **Step 4: Run checks**

Expected: migration upgrade/downgrade and schema contracts pass.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/alembic/versions/20260825_0004_evidence_scoring.py apps/backend/src/tamforge_backend/evidence apps/backend/src/tamforge_backend/models apps/backend/tests/integration/test_0004_evidence_scoring.py
git commit -m "feat: add evidence ledger schema"
~~~

## Task 8: Add Alembic 20260825_0005 Today read models, notifications, and outbox

**Files:**

- Create: apps/backend/alembic/versions/20260825_0005_today_read_models.py
- Create: apps/backend/src/tamforge_backend/notifications/__init__.py
- Create: apps/backend/src/tamforge_backend/notifications/models.py
- Create: apps/backend/src/tamforge_backend/today/__init__.py
- Create: apps/backend/src/tamforge_backend/today/models.py
- Create: apps/backend/tests/integration/test_0005_today_read_models.py
- Modify: apps/backend/src/tamforge_backend/models/__init__.py

The revision must create:

- corrections: owner, source activity/evidence, priority 1–2, status, due date, compact instruction, and future Attempt B link;
- interviews: owner, company, role, stage, starts_at, expected duration, status, and privacy/permission summary only;
- activity_processing_statuses: activity, state, progress label, last error category, and updated_at;
- notifications with one of feedback_ready, correction_due, upcoming_real_interview, saturday_assessment, processing_failure_requires_action;
- outbox_events with aggregate, event type, JSON payload, occurred/published timestamps, attempts, and idempotency key;
- background_jobs with kind, versioned payload, priority, state, idempotency key, available_at, attempt/max-attempt counts, lease owner/expiry, typed error category/details, and lifecycle timestamps;
- notification_delivery_cursor for resumable SSE.

These are forward-compatible read foundations. Do not implement AI corrections or the full interview lifecycle here.

- [ ] **Step 1: Write failing schema tests**

Assert only two active priority slots per owner/day through service-enforced tests plus supporting indexes, allowed notification types, unique outbox/job idempotency, lease expiry/reclaim constraints, and non-cascading links to evidence.

- [ ] **Step 2: Run the focused migration test**

Run against explicit TEST_DATABASE_URL. Expected: FAIL before implementation or SKIP.

- [ ] **Step 3: Implement models and migration**

Index Today query paths: correction status/due, interview starts_at, pending self-review, processing state, notification unread/created, and outbox unpublished/occurred.

- [ ] **Step 4: Run checks**

Expected: migration round trip and schema contract pass.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/alembic/versions/20260825_0005_today_read_models.py apps/backend/src/tamforge_backend/notifications apps/backend/src/tamforge_backend/today apps/backend/src/tamforge_backend/models apps/backend/tests/integration/test_0005_today_read_models.py
git commit -m "feat: add today and notification schema"
~~~

## Task 9: Implement GitHub OAuth and single-owner sessions

**Files:**

- Create: apps/backend/src/tamforge_backend/auth/schemas.py
- Create: apps/backend/src/tamforge_backend/auth/ports.py
- Create: apps/backend/src/tamforge_backend/auth/github.py
- Create: apps/backend/src/tamforge_backend/auth/crypto.py
- Create: apps/backend/src/tamforge_backend/auth/repository.py
- Create: apps/backend/src/tamforge_backend/auth/service.py
- Create: apps/backend/src/tamforge_backend/auth/routes.py
- Create: apps/backend/src/tamforge_backend/auth/dependencies.py
- Create: apps/backend/tests/unit/auth/test_service.py
- Create: apps/backend/tests/unit/auth/test_crypto.py
- Create: apps/backend/tests/unit/auth/test_csrf.py
- Create: apps/backend/tests/integration/auth/test_routes.py
- Modify: apps/backend/src/tamforge_backend/api.py
- Modify: apps/backend/src/tamforge_backend/main.py
- Modify: apps/backend/src/tamforge_backend/config.py

Authentication contract:

- GET /api/v1/auth/login creates a cryptographically random OAuth state and redirects to GitHub.
- GET /api/v1/auth/callback verifies state, exchanges code, fetches GitHub /user, compares the numeric id to TAMFORGE_GITHUB_USER_ID, and rejects every other identity before creating a local owner/session.
- GET /api/v1/auth/session returns owner display fields plus a CSRF token only to the authenticated browser.
- POST /api/v1/auth/logout revokes the current session and clears cookies.
- The session cookie contains an opaque random token; PostgreSQL stores only its SHA-256 hash.
- Cookies are HttpOnly, Secure outside test, SameSite=Lax, and scoped narrowly.
- Every state-changing application route requires X-CSRF-Token whose hash is bound to the session.
- OAuth tokens are used only for the callback identity lookup and are not retained.

- [ ] **Step 1: Write failing owner-allowlist and session tests**

~~~python
async def test_rejects_valid_github_login_with_wrong_immutable_id():
    github = FakeGitHubUser(id=999, login="lookalike")
    service = AuthService(owner_github_id=123, github=gateway(github), sessions=fake_sessions())
    with pytest.raises(ForbiddenIdentity):
        await service.complete_login(code="code", state="valid", state_cookie="valid")


async def test_stores_only_hashes_for_session_and_csrf():
    result = await owner_service().issue_session(owner_id=OWNER_ID)
    persisted = result.persisted_session
    assert result.raw_session_token.encode() not in persisted.token_hash
    assert result.raw_csrf_token.encode() not in persisted.csrf_hash
~~~

Also test expired/revoked session rejection, state mismatch, logout idempotency, Origin/CSRF enforcement, secure cookie attributes, and login comparison by numeric ID rather than username/email.

- [ ] **Step 2: Run tests to verify failure**

~~~bash
uv run pytest apps/backend/tests/unit/auth -q
~~~

Expected: FAIL because auth ports/service do not exist.

- [ ] **Step 3: Implement the pure auth service and GitHub gateway**

Use Authlib/httpx only inside the GitHub adapter. Keep session issuance and owner comparison pure enough to test without HTTP. Use secrets.token_urlsafe(32), hmac.compare_digest, SHA-256 token hashes, bounded session expiry, and explicit revocation.

- [ ] **Step 4: Implement routes and authentication dependencies**

The dependency must return AuthenticatedOwner and never accept owner IDs from request bodies. Add a production-only startup check that refuses wildcard CORS or insecure cookies.

- [ ] **Step 5: Run unit tests**

~~~bash
uv run pytest apps/backend/tests/unit/auth -q
uv run ruff check apps/backend/src/tamforge_backend/auth apps/backend/tests/unit/auth
uv run mypy apps/backend/src/tamforge_backend/auth
~~~

Expected: PASS.

- [ ] **Step 6: Write and run authenticated route integration tests**

Use explicit TEST_DATABASE_URL and respx for GitHub HTTP. Verify unauthorized identities leave no owner/session rows and logout revokes the database session.

Expected: PASS when PostgreSQL is available; SKIP without it.

- [ ] **Step 7: Commit**

~~~bash
git add apps/backend/src/tamforge_backend/auth apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/main.py apps/backend/src/tamforge_backend/config.py apps/backend/tests/unit/auth apps/backend/tests/integration/auth
git commit -m "feat: add single-owner github authentication"
~~~

## Task 10: Add the immutable object-store port and S3 adapter

**Files:**

- Create: apps/backend/src/tamforge_backend/storage/__init__.py
- Create: apps/backend/src/tamforge_backend/storage/models.py
- Create: apps/backend/src/tamforge_backend/storage/ports.py
- Create: apps/backend/src/tamforge_backend/storage/fake.py
- Create: apps/backend/src/tamforge_backend/storage/s3.py
- Create: apps/backend/src/tamforge_backend/storage/dependencies.py
- Create: apps/backend/tests/unit/storage/test_contract.py
- Create: apps/backend/tests/unit/storage/test_s3_adapter.py
- Modify: apps/backend/src/tamforge_backend/config.py
- Modify: .env.example

The port is intentionally small:

~~~python
class ObjectStore(Protocol):
    async def put_immutable(
        self,
        *,
        key: str,
        body: AsyncIterator[bytes],
        sha256: str,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject: ...

    async def stat(self, key: str) -> StoredObject | None: ...
    async def open(self, key: str) -> AsyncContextManager[AsyncIterator[bytes]]: ...
    async def presign_put(self, request: PresignPutRequest) -> PresignedRequest: ...
    async def presign_get(self, key: str, *, expires_seconds: int) -> str: ...
~~~

Object keys are server-generated and scoped by artifact class/owner/logical ID/hash. No API accepts an arbitrary bucket/key from the browser.

- [ ] **Step 1: Write a reusable contract test**

Run the same assertions against InMemoryObjectStore and the moto-backed S3 adapter:

- identical key + checksum is idempotent;
- identical key + different checksum raises ObjectConflict;
- metadata includes SHA-256 and byte length;
- private objects require a signed request;
- signed links have a bounded expiry;
- key traversal and control characters are rejected;
- reads stream and do not require loading a whole roadmap/archive into memory.

- [ ] **Step 2: Run tests to verify failure**

~~~bash
uv run pytest apps/backend/tests/unit/storage -q
~~~

Expected: FAIL because the port/adapters do not exist. Moto is in-process and does not start Docker.

- [ ] **Step 3: Implement the in-memory adapter, then the S3-compatible adapter**

Use boto3 behind anyio.to_thread.run_sync so blocking SDK calls do not block the FastAPI event loop. Set endpoint URL, region, bucket, access key, and secret through Settings. Never log credentials or signed URLs.

- [ ] **Step 4: Run tests and type checks**

~~~bash
uv run pytest apps/backend/tests/unit/storage -q
uv run ruff check apps/backend/src/tamforge_backend/storage apps/backend/tests/unit/storage
uv run mypy apps/backend/src/tamforge_backend/storage
~~~

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add .env.example apps/backend/src/tamforge_backend/config.py apps/backend/src/tamforge_backend/storage apps/backend/tests/unit/storage
git commit -m "feat: add immutable object storage port"
~~~

## Task 11: Seed and validate skills, mappings, rubrics, and Month 1 task map

**Files:**

- Create: config/tam-skills.yaml
- Create: config/tam-exercise-types.yaml
- Create: config/tam-rubrics.yaml
- Create: config/tam-roadmap-task-map.yaml
- Create: apps/backend/src/tamforge_backend/evidence/config_models.py
- Create: apps/backend/src/tamforge_backend/evidence/config_loader.py
- Create: apps/backend/src/tamforge_backend/evidence/seed.py
- Create: apps/backend/src/tamforge_backend/cli.py
- Create: apps/backend/tests/unit/evidence/test_config_loader.py
- Create: apps/backend/tests/unit/evidence/test_seed_config.py
- Create: apps/backend/tests/fixtures/config/invalid-mapping.yaml
- Modify: apps/backend/pyproject.toml

The checked-in YAML is an auditable default. PostgreSQL becomes runtime truth after an idempotent seed command. Every seed stores its SHA-256/config version; changed config creates a new immutable version and never rewrites evidence using an old version.

- [ ] **Step 1: Write failing validation tests**

Tests must require:

- exactly fourteen skill slugs and exact baseline/Month 1/final targets from specification Section 9.5;
- every exercise type and weight from the complete normative seed mapping in specification Section 9.7;
- all referenced competency slugs exist;
- official_reading, company_product_research, and application_or_outreach have no skill impacts;
- TAM English conditional impacts require produced spoken/written English;
- dynamic domain/story impacts require the precommit selector and allowlist;
- gauntlet children reference existing exercise types and mapping versions;
- Portfolio Judgment dimensions total exactly 20;
- formula factors and qualifying rules match specification Section 9.6;
- duplicate slugs, unknown tags, weights outside the permitted range, or dangling references fail with source location.

~~~python
def test_normative_seed_contract(config_bundle):
    assert len(config_bundle.skills) == 14
    assert config_bundle.exercise("official_reading").skill_impacts == {}
    assert sum(item.maximum for item in config_bundle.portfolio.dimensions) == 20
    assert config_bundle.exercise("full_tam_gauntlet").component_scoring_required is True
~~~

- [ ] **Step 2: Run tests to verify failure**

~~~bash
uv run pytest apps/backend/tests/unit/evidence/test_config_loader.py -q
~~~

Expected: FAIL because config/schema files do not exist.

- [ ] **Step 3: Transcribe the approved normative configuration**

Copy the fourteen skills and the complete exercise mapping from specification Sections 9.5–9.7 without abbreviation. Define tam-roadmap-task-map.yaml with stable Month 1 task IDs, source-relative path/heading, exercise type, block/order, required flag, exact timebox, required output, pass/evidence contract, and mapping version. Do not infer a mapping from title text at runtime.

- [ ] **Step 4: Implement strict Pydantic loaders**

Reject unknown fields. Normalize Decimal weights, compute a canonical JSON hash, and return a fully linked immutable bundle.

- [ ] **Step 5: Run config tests**

~~~bash
uv run pytest apps/backend/tests/unit/evidence/test_config_loader.py -q
~~~

Expected: PASS, including an assertion covering every normative exercise type.

- [ ] **Step 6: Write the failing idempotent seed test**

Seed twice and assert the second execution inserts nothing; then change a fixture mapping version and assert a new immutable config version is inserted without mutating old mappings/evidence.

- [ ] **Step 7: Implement and test the seed command**

Command:

~~~bash
uv run python -m tamforge_backend.cli seed-config --config-dir config --dry-run
~~~

Expected without a database: validated summary only. With explicit TEST_DATABASE_URL and --apply: exact inserted/no-op counts.

- [ ] **Step 8: Commit**

~~~bash
git add config apps/backend/src/tamforge_backend/evidence apps/backend/src/tamforge_backend/cli.py apps/backend/tests/unit/evidence apps/backend/tests/fixtures/config apps/backend/pyproject.toml
git commit -m "feat: add versioned tam scoring configuration"
~~~

## Task 12: Validate roadmap archives and build immutable manifests

**Files:**

- Create: apps/backend/src/tamforge_backend/roadmaps/package.py
- Create: apps/backend/src/tamforge_backend/roadmaps/manifest.py
- Create: apps/backend/src/tamforge_backend/roadmaps/schemas.py
- Create: apps/backend/tests/unit/roadmaps/test_package.py
- Create: apps/backend/tests/unit/roadmaps/test_manifest.py
- Create: apps/backend/tests/fixtures/roadmaps/minimal-month/README.md
- Create: apps/backend/tests/fixtures/roadmaps/minimal-month/Week 1.md
- Create: apps/backend/tests/fixtures/roadmaps/minimal-month/sql/setup.sql

Security and determinism rules:

- accept either a streamed ZIP or a streamed browser-selected folder file set with normalized relative paths; use a server-side directory abstraction only in tests and never accept an arbitrary server path from the API;
- reject absolute paths, .. traversal, symlinks, duplicate normalized paths, case-collisions, unsupported file types, decompression bombs, encrypted ZIP members, too many members, and oversized total/uncompressed files;
- normalize relative paths to POSIX NFC;
- hash each original byte stream and the sorted manifest;
- preserve original bytes, filename, size, media type, and path;
- do not rewrite Markdown, SQL, or templates;
- stream to a bounded temporary file/object-store upload rather than retaining the archive in RAM.

- [ ] **Step 1: Write failing archive safety tests**

Include malicious traversal, duplicate, case collision, oversized member, symlink metadata, and valid nested SQL/template cases for both ZIP and browser-folder entry adapters. The same files imported through either adapter must produce the same canonical manifest/content hash.

- [ ] **Step 2: Run tests to verify failure**

~~~bash
uv run pytest apps/backend/tests/unit/roadmaps/test_package.py apps/backend/tests/unit/roadmaps/test_manifest.py -q
~~~

Expected: FAIL because package/manifest builders do not exist.

- [ ] **Step 3: Implement bounded package inspection and canonical manifest**

Return ValidationIssue records with stable code, path, severity, and human-readable message. A rejected package remains a staged import record later but cannot be approved.

- [ ] **Step 4: Run tests**

Expected: PASS; use a test asserting two differently ordered ZIPs with identical files produce the same content hash.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/tests/unit/roadmaps apps/backend/tests/fixtures/roadmaps
git commit -m "feat: add safe roadmap package manifests"
~~~

## Task 13: Parse the explicit Month 1 task map and produce semantic diffs

**Files:**

- Create: apps/backend/src/tamforge_backend/roadmaps/parser.py
- Create: apps/backend/src/tamforge_backend/roadmaps/diff.py
- Create: apps/backend/src/tamforge_backend/roadmaps/contracts.py
- Create: apps/backend/tests/unit/roadmaps/test_parser.py
- Create: apps/backend/tests/unit/roadmaps/test_diff.py
- Create: apps/backend/tests/fixtures/roadmaps/month-v1.zip
- Create: apps/backend/tests/fixtures/roadmaps/month-v2.zip
- Create: apps/backend/tests/fixtures/roadmaps/expected-month-v1.json

- [ ] **Step 1: Write failing parser contract tests**

For every task-map row, assert the source path and heading exist and the parser emits:

- exact stable task ID;
- month/week/day/block/order;
- objective and source references;
- timebox and required flag;
- exercise/mapping version;
- output/pass/evidence contracts;
- allowed AI role.

Reject missing headings/resources, duplicate task IDs, invalid weekday totals, Sunday tasks, Saturday totals over 120, unknown exercise versions, and references outside the package.

- [ ] **Step 2: Write failing semantic-diff tests**

Diff normalized task/resource/pass/exit structures, not raw Markdown lines. Assert stable categories added, removed, changed, unchanged and field-level before/after values. Reordered files/headings without semantic change must not appear changed.

- [ ] **Step 3: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/roadmaps/test_parser.py apps/backend/tests/unit/roadmaps/test_diff.py -q
~~~

Expected: FAIL before implementation.

- [ ] **Step 4: Implement parser and diff as pure functions**

The parser follows the reviewed task map. It may validate Markdown headings but must never ask an LLM or infer exercise mappings from prose.

- [ ] **Step 5: Run tests and validate the real task map offline**

~~~bash
uv run pytest apps/backend/tests/unit/roadmaps/test_parser.py apps/backend/tests/unit/roadmaps/test_diff.py -q
uv run python -m tamforge_backend.cli validate-roadmap-map --config config/tam-roadmap-task-map.yaml
~~~

Expected: PASS and a deterministic summary of mapped Month 1 tasks/timeboxes.

- [ ] **Step 6: Commit**

~~~bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/tests/unit/roadmaps apps/backend/tests/fixtures/roadmaps
git commit -m "feat: parse and diff versioned roadmaps"
~~~

## Task 14: Implement staged roadmap import, snapshot, mirror, approval, and activation

**Files:**

- Create: apps/backend/src/tamforge_backend/roadmaps/ports.py
- Create: apps/backend/src/tamforge_backend/roadmaps/repository.py
- Create: apps/backend/src/tamforge_backend/roadmaps/github_mirror.py
- Create: apps/backend/src/tamforge_backend/roadmaps/service.py
- Create: apps/backend/src/tamforge_backend/roadmaps/routes.py
- Create: apps/backend/tests/unit/roadmaps/test_service.py
- Create: apps/backend/tests/unit/roadmaps/test_github_mirror.py
- Create: apps/backend/tests/integration/roadmaps/test_import_flow.py
- Modify: apps/backend/src/tamforge_backend/api.py
- Modify: apps/backend/src/tamforge_backend/config.py
- Modify: .env.example

Use a separate fine-grained repository token for roadmap mirroring. The OAuth login token is never reused. Mirror approved snapshots to branch roadmap-snapshots under roadmaps/imports/{roadmap-version-id}/ with source files plus manifest.json.

Endpoints:

- POST /api/v1/roadmap-imports
- GET /api/v1/roadmap-imports/{id}
- POST /api/v1/roadmap-imports/{id}/approve
- POST /api/v1/roadmap-imports/{id}/mirror/retry
- GET /api/v1/roadmap-versions
- POST /api/v1/roadmap-versions/{id}/activate

- [ ] **Step 1: Write failing service tests**

Prove:

- duplicate package/idempotency key returns the same staged import;
- only Staged -> Validated -> Previewed -> ApprovedImported -> Upcoming -> ExplicitlyActivated -> Superseded transitions are accepted, with validation failure remaining visible and no skipped approval/activation state;
- invalid package remains staged with exact issues and cannot approve;
- snapshot is put immutably before approved version persistence;
- approval persists normalized rows and exact source hash/version;
- mirror success stores commit/ref;
- mirror failure stores failure and is retryable without duplicate version;
- runtime reads PostgreSQL/object storage and does not depend on GitHub;
- Month 2 activation fails before Month 1 exit review and succeeds after it;
- activating a new version supersedes only future work; existing activities keep their version;
- no operation writes the Obsidian vault.

- [ ] **Step 2: Run tests to verify failure**

~~~bash
uv run pytest apps/backend/tests/unit/roadmaps/test_service.py apps/backend/tests/unit/roadmaps/test_github_mirror.py -q
~~~

Expected: FAIL.

- [ ] **Step 3: Implement ports, repository, and orchestration**

Application order for approval:

1. load validated package/manifest;
2. put immutable snapshot to object storage;
3. in one database transaction create RoadmapVersion, parsed nodes/tasks/resources/criteria, and outbox event;
4. attempt GitHub mirror outside the database transaction;
5. persist mirror result;
6. leave mirror failure visible/retryable.

Activation is a separate authenticated command and never follows approval automatically.

- [ ] **Step 4: Implement the GitHub mirror adapter**

Use deterministic content paths and hidden version markers. Never force-push, rewrite history, or modify the main branch. Tests use respx/fake client; no GitHub write occurs in unit tests.

- [ ] **Step 5: Add authenticated routes and problem responses**

Use streaming multipart upload with a configured maximum, owner auth, CSRF, and Idempotency-Key. Accept an explicit package_kind of zip or folder_entries; folder entries include browser-supplied normalized relative paths and pass through the same package safety rules. Return validation/diff/mirror state in typed schemas.

- [ ] **Step 6: Run unit and integration tests**

~~~bash
uv run pytest apps/backend/tests/unit/roadmaps -q
~~~

Expected: unit PASS. Run the integration test only with explicit TEST_DATABASE_URL; expected PASS or SKIP.

- [ ] **Step 7: Commit**

~~~bash
git add .env.example apps/backend/src/tamforge_backend/roadmaps apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/config.py apps/backend/tests/unit/roadmaps apps/backend/tests/integration/roadmaps
git commit -m "feat: add versioned roadmap import workflow"
~~~

## Task 15: Implement deterministic scheduling and time protection

**Files:**

- Create: apps/backend/src/tamforge_backend/learning/time_policy.py
- Create: apps/backend/src/tamforge_backend/learning/scheduling.py
- Create: apps/backend/src/tamforge_backend/learning/repository.py
- Create: apps/backend/tests/unit/learning/test_time_policy.py
- Create: apps/backend/tests/unit/learning/test_scheduling.py
- Create: apps/backend/tests/integration/learning/test_study_day_creation.py

- [ ] **Step 1: Write failing property and example tests**

Cover:

- weekday target 240, acceptable 225–255, hard-stop recommendation at 255;
- Saturday maximum 120;
- Sunday creates no study day/tasks, catch-up, or study reminder;
- async processing contributes zero focused minutes;
- finishing early is allowed only when required outputs/pass conditions are satisfied;
- real-interview minutes replace relevant blocks rather than stack on top;
- correction warm-up schedules exactly one carryover type;
- required unfinished work replaces a lower-priority adaptive task;
- useful enters retrieval; optional drops; superseded links stronger interview evidence;
- no reschedule exceeds future day limits;
- study day creation is idempotent per owner/local date;
- all time decisions use learner_settings.timezone, including DST transitions.

~~~python
@given(st.dates())
def test_sunday_never_creates_study_work(local_date):
    assume(local_date.weekday() == 6)
    assert build_day(local_date, active_roadmap()).tasks == ()
    assert build_day(local_date, active_roadmap()).planned_minutes == 0
~~~

- [ ] **Step 2: Run tests to verify failure**

~~~bash
uv run pytest apps/backend/tests/unit/learning/test_time_policy.py apps/backend/tests/unit/learning/test_scheduling.py -q
~~~

Expected: FAIL.

- [ ] **Step 3: Implement pure policies and idempotent StudyDay service**

The roadmap supplies tasks/time; the scheduler validates and instantiates it. It never creates filler work. Store task-definition snapshots so later roadmap versions cannot change an existing day.

- [ ] **Step 4: Run unit and integration tests**

Unit expected PASS. Integration expected PASS with explicit database or SKIP.

- [ ] **Step 5: Commit**

~~~bash
git add apps/backend/src/tamforge_backend/learning apps/backend/tests/unit/learning apps/backend/tests/integration/learning
git commit -m "feat: enforce study scheduling and time limits"
~~~

## Task 16: Implement activity state transitions and resumable focused timers

**Files:**

- Create: apps/backend/src/tamforge_backend/learning/enums.py
- Create: apps/backend/src/tamforge_backend/learning/state_machine.py
- Create: apps/backend/src/tamforge_backend/learning/timers.py
- Create: apps/backend/src/tamforge_backend/learning/schemas.py
- Create: apps/backend/src/tamforge_backend/learning/service.py
- Create: apps/backend/src/tamforge_backend/learning/routes.py
- Create: apps/backend/tests/unit/learning/test_state_machine.py
- Create: apps/backend/tests/unit/learning/test_timers.py
- Create: apps/backend/tests/integration/learning/test_activity_commands.py
- Modify: apps/backend/src/tamforge_backend/api.py

Endpoints:

- GET /api/v1/activities/{id}
- POST /api/v1/activities/{id}/start
- POST /api/v1/activities/{id}/pause
- POST /api/v1/activities/{id}/resume
- POST /api/v1/activities/{id}/heartbeat
- POST /api/v1/activities/{id}/classify-incomplete

- [ ] **Step 1: Write the state-transition table as failing parameterized tests**

Allow only:

~~~text
Ready -> Active
Active -> Paused | OutputCommitted | Incomplete
Paused -> Active | Incomplete
OutputCommitted -> SelfReviewComplete
SelfReviewComplete -> AIProcessing
AIProcessing -> FeedbackReady
FeedbackReady -> CorrectionDue
CorrectionDue -> Demonstrated | NeedsWork
~~~

The last four states are forward-compatible for later analysis plans; this task exposes no client command that fabricates AI results.

Reject skipped self-review, edits after output commitment, Attempt C, state changes with stale optimistic version, and starting work on Sunday/after a closed day.

- [ ] **Step 2: Write timer failure tests**

The server counts only bounded heartbeat deltas, caps a missing heartbeat gap, prevents two open timers, ignores duplicate idempotency keys, survives reload, and returns the 255-minute hard-stop recommendation without automatically extending work.

- [ ] **Step 3: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/learning/test_state_machine.py apps/backend/tests/unit/learning/test_timers.py -q
~~~

Expected: FAIL.

- [ ] **Step 4: Implement pure transition/timer logic and transactional commands**

Use optimistic locking on activity_instances.version. Heartbeat commands carry client sequence/idempotency but server timestamps remain authoritative.

- [ ] **Step 5: Add authenticated routes and integration tests**

Verify a timer resumes after a new API client fetch and a duplicate heartbeat never increases focused time twice.

- [ ] **Step 6: Run tests and commit**

~~~bash
uv run pytest apps/backend/tests/unit/learning -q
git add apps/backend/src/tamforge_backend/learning apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/learning apps/backend/tests/integration/learning
git commit -m "feat: add resumable activity state and timers"
~~~

## Task 17: Implement immutable outputs, artifact upload, and mandatory self-review

**Files:**

- Create: apps/backend/src/tamforge_backend/learning/artifacts.py
- Create: apps/backend/src/tamforge_backend/learning/contracts.py
- Create: apps/backend/tests/unit/learning/test_activity_contracts.py
- Create: apps/backend/tests/unit/learning/test_output_commit.py
- Create: apps/backend/tests/integration/learning/test_universal_workspace.py
- Modify: apps/backend/src/tamforge_backend/learning/schemas.py
- Modify: apps/backend/src/tamforge_backend/learning/service.py
- Modify: apps/backend/src/tamforge_backend/learning/routes.py

Endpoints:

- POST /api/v1/activities/{id}/artifacts/presign
- POST /api/v1/activities/{id}/artifacts/confirm
- POST /api/v1/activities/{id}/commit-output
- POST /api/v1/activities/{id}/self-review
- POST /api/v1/activities/{id}/source-visibility

- [ ] **Step 1: Write failing contract tests for every universal activity type**

Test reading, SQL, TAM case, writing, and career pipeline:

- reading requires three ideas, one boundary/failure, one TAM/customer example, and one unresolved question after source hide;
- SQL stores query, result, explanation/business meaning, timing, self-review, and assistance; AI remains locked before commit/timeout;
- case stores canonical prompt/facts, questions, assumptions, notes, artifact, decisions, risks, and unresolved questions;
- writing stores audience/action/facts/unknowns/tone/limit and one immutable Attempt A;
- pipeline requires a concrete artifact/action plus company/role/stage/next action;
- every task keeps prompt, audience, time limit, exercise/mapping version, and roadmap/task version.

- [ ] **Step 2: Write failing immutability and self-review tests**

Prove:

- output hash changes are rejected after commit;
- a new version never overwrites the committed original;
- object confirmation verifies key, expected hash, byte length, and ownership;
- arbitrary browser object keys are rejected;
- self-review cannot occur before commit;
- AIProcessing cannot start before self-review;
- self-score remains separate from rubric score;
- duplicate commit/self-review commands return the same result.

- [ ] **Step 3: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/learning/test_activity_contracts.py apps/backend/tests/unit/learning/test_output_commit.py -q
~~~

Expected: FAIL.

- [ ] **Step 4: Implement minimal contract validators and artifact coordinator**

Presign only server-generated keys. Confirmation calls ObjectStore.stat before creating immutable artifact metadata. Commit the attempt/output/artifact manifest and state transition in one database transaction.

- [ ] **Step 5: Add routes and integration flow**

Integration scenario: start task, heartbeat, upload/confirm artifact, commit, attempt edit and receive conflict, submit self-review, reload and see SelfReviewComplete.

- [ ] **Step 6: Run tests and commit**

~~~bash
uv run pytest apps/backend/tests/unit/learning -q
git add apps/backend/src/tamforge_backend/learning apps/backend/tests/unit/learning apps/backend/tests/integration/learning
git commit -m "feat: add universal evidence workspace backend"
~~~

## Task 18: Implement the reproducible evidence and Portfolio Judgment calculators

**Files:**

- Create: apps/backend/src/tamforge_backend/evidence/scoring.py
- Create: apps/backend/src/tamforge_backend/evidence/qualification.py
- Create: apps/backend/src/tamforge_backend/evidence/confidence.py
- Create: apps/backend/src/tamforge_backend/evidence/trend.py
- Create: apps/backend/src/tamforge_backend/evidence/portfolio.py
- Create: apps/backend/tests/unit/evidence/test_performance_score.py
- Create: apps/backend/tests/unit/evidence/test_qualification.py
- Create: apps/backend/tests/unit/evidence/test_skill_estimate.py
- Create: apps/backend/tests/unit/evidence/test_confidence_trend_recency.py
- Create: apps/backend/tests/unit/evidence/test_portfolio_judgment.py
- Create: apps/backend/tests/unit/evidence/test_scoring_properties.py
- Modify: apps/backend/src/tamforge_backend/evidence/__init__.py

- [ ] **Step 1: Write failing performance and effective-weight tests**

Cover the approved versioned formula exactly:

~~~text
performanceScore =
  weightedSum(rubricDimensionScore * rubricDimensionWeight)
  / sum(rubricDimensionWeight)

effectiveEvidenceWeight =
  exerciseSkillImpact
  * practiceModeFactor
  * aiIndependenceFactor
  * evaluatorConfidenceFactor
  * difficultyFactor
~~~

Use Decimal throughout. Assert the result remains on 0–4, factor values come from the selected formula version, exposure has zero effective weight, AI after commitment has factor 1.00, and configured outlier caps are deterministic. Reject unknown factors, a zero dimension-weight denominator, scores outside 0–4, and dynamic impacts absent from the precommit allowlist.

- [ ] **Step 2: Write failing total-order qualification tests**

Parameterize every mode, assistance, evaluator, and attempt combination. An event qualifies only when all of these are true:

- it is rubric-scored;
- mode is independent_practice, timed_assessment, mock_interview, or real_interview;
- assistance is no_ai or ai_after_committed_attempt;
- independent practice is Attempt A;
- any required precommit domain/story competency selector is present and allowed.

Prove Attempt B only changes A/B comparison and correction status, guided/hinted/co-created/generated work never affects level/confidence/trend/recency, AI acting only as Interviewer is not coaching assistance, official reading and pipeline activity have zero score impact, and transfer qualifies only as a later Attempt A in a different scenario.

- [ ] **Step 3: Write failing estimator, diversity, confidence, trend, and recency tests**

Test the baseline prior at weight 2.0 plus the latest 12 qualifying events. For an equivalent skill/exercise/scenario/date grouping, only the first two receive full weight and later repetitions are explicitly discounted. One event cannot create mastery or collapse an established estimate.

Evaluate confidence in this exact order:

1. High: total effective weight at least 7, at least three exercise types, a timed assessment or mock in the prior 21 days, and a reviewed artifact or scored recording.
2. Else Medium: total effective weight at least 3, at least two exercise types, and an independent attempt.
3. Else Low.

Test Improving, Stable, Declining, and Insufficient evidence using the formula version's thresholds over latest three versus preceding three qualifying events. Test Fresh at 0–7 days, Aging at 8–21, and Stale above 21. Absence of recent practice must never become Declining.

- [ ] **Step 4: Write failing Portfolio Judgment tests**

Score independent dimensions within their fixed maxima and total 0–20:

~~~text
Impact and risk assessment                 0-4
Explicit prioritization                    0-3
Delegation and ownership                   0-3
Communication control for every customer   0-3
Protection of proactive work               0-2
Evidence-based reprioritization             0-3
English clarity                            0-2
~~~

Prove Portfolio Judgment is not a fifteenth skill, has its own estimate/history/trend, and the same portfolio attempt creates separately scored underlying skill events through the versioned portfolio_triage mapping. Integrated gauntlets must accept only concrete versioned child exercise references and must never copy one overall score to every child.

- [ ] **Step 5: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/evidence/test_performance_score.py apps/backend/tests/unit/evidence/test_qualification.py apps/backend/tests/unit/evidence/test_skill_estimate.py apps/backend/tests/unit/evidence/test_confidence_trend_recency.py apps/backend/tests/unit/evidence/test_portfolio_judgment.py apps/backend/tests/unit/evidence/test_scoring_properties.py -q
~~~

Expected: FAIL because the calculators do not exist.

- [ ] **Step 6: Implement pure calculators with inspectable result objects**

Return the estimate plus contributing, excluded, and discounted event IDs; raw/effective weights; formula version; confidence/trend bases; target gap; last strong-evidence date; and portfolio component scores. Do not query PostgreSQL or call a model in these pure functions.

- [ ] **Step 7: Run focused tests and commit**

~~~bash
uv run pytest apps/backend/tests/unit/evidence -q
uv run ruff check apps/backend/src/tamforge_backend/evidence apps/backend/tests/unit/evidence
uv run mypy apps/backend/src/tamforge_backend/evidence
git add apps/backend/src/tamforge_backend/evidence apps/backend/tests/unit/evidence
git commit -m "feat: add reproducible evidence scoring"
~~~

## Task 19: Persist the evidence ledger, estimates, and immutable formula lineage

**Files:**

- Create: apps/backend/src/tamforge_backend/evidence/schemas.py
- Create: apps/backend/src/tamforge_backend/evidence/repository.py
- Create: apps/backend/src/tamforge_backend/evidence/service.py
- Create: apps/backend/src/tamforge_backend/evidence/routes.py
- Create: apps/backend/tests/unit/evidence/test_service.py
- Create: apps/backend/tests/integration/evidence/test_ledger.py
- Create: apps/backend/tests/integration/evidence/test_estimate_snapshot.py
- Modify: apps/backend/src/tamforge_backend/api.py
- Modify: apps/backend/src/tamforge_backend/evidence/models.py

Read endpoints:

- GET /api/v1/skills
- GET /api/v1/skills/{skill_slug}
- GET /api/v1/skills/{skill_slug}/evidence
- GET /api/v1/activities/{activity_id}/evidence
- GET /api/v1/portfolio-judgment

- [ ] **Step 1: Write failing unit tests for atomic evidence creation**

The service input references an immutable committed attempt, exercise type/mapping/formula/rubric versions, raw dimension scores, evaluator, confidence, mode, assistance, difficulty, artifact/transcript/audio availability, and the precommit selectors. Assert:

- self-score is stored separately and never substituted for rubric evidence;
- each mapped competency receives its own event and dimension subset;
- dynamic impacts are accepted only from an allowlisted field saved before output commitment;
- conditional TAM English applies only when spoken or written English evidence exists;
- duplicate evaluator/idempotency input returns the original ledger entries;
- missing or mismatched immutable versions fail closed;
- a nonqualifying event remains visible but cannot change a qualifying snapshot.

- [ ] **Step 2: Write failing integration tests for ledger lineage**

In one transaction, store evaluation, rubric dimensions, SkillEvidenceEvents, PortfolioEvidence when relevant, recalculated SkillEstimateSnapshots, an AuditEvent, and an OutboxEvent. Force a snapshot write failure and prove none of those rows commits. Re-run the same idempotency key and prove there are no duplicates.

Every snapshot response must expose formula version, contributing/excluded/discounted events, effective weights, confidence/trend bases, target gap, last strong-evidence date, and the exact evidence IDs from which it is reproducible.

- [ ] **Step 3: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/evidence/test_service.py -q
~~~

Expected: FAIL because the service and repository do not exist.

- [ ] **Step 4: Implement repository and transactional service**

Keep the write service callable by later reviewer/analyst workers without exposing an owner route that fabricates AI evaluation. Public routes in this task are authenticated read-only ledger views. Enforce stable ordering and cursor pagination.

- [ ] **Step 5: Run unit tests and approved integration tests**

~~~bash
uv run pytest apps/backend/tests/unit/evidence -q
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/evidence -q
~~~

Expected: unit tests pass. Run the second command only after explicit local Docker/PostgreSQL approval; it passes against the migrated test database and never starts a container itself.

- [ ] **Step 6: Commit the evidence ledger**

~~~bash
git add apps/backend/src/tamforge_backend/evidence apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/evidence apps/backend/tests/integration/evidence
git commit -m "feat: persist inspectable evidence ledger"
~~~

## Task 20: Add the durable job primitive, actionable notifications, outbox delivery, and status streaming

**Files:**

- Create: apps/backend/src/tamforge_backend/jobs/__init__.py
- Create: apps/backend/src/tamforge_backend/jobs/schemas.py
- Create: apps/backend/src/tamforge_backend/jobs/repository.py
- Create: apps/backend/src/tamforge_backend/jobs/service.py
- Create: apps/backend/tests/unit/jobs/test_policy.py
- Create: apps/backend/tests/integration/jobs/test_leases.py
- Create: apps/backend/src/tamforge_backend/notifications/policy.py
- Create: apps/backend/src/tamforge_backend/notifications/repository.py
- Create: apps/backend/src/tamforge_backend/notifications/service.py
- Create: apps/backend/src/tamforge_backend/notifications/routes.py
- Create: apps/backend/src/tamforge_backend/notifications/sse.py
- Create: apps/backend/tests/unit/notifications/test_policy.py
- Create: apps/backend/tests/unit/notifications/test_service.py
- Create: apps/backend/tests/integration/notifications/test_outbox_delivery.py
- Create: apps/backend/tests/integration/notifications/test_sse_resume.py
- Modify: apps/backend/src/tamforge_backend/api.py

Endpoints:

- GET /api/v1/notifications
- POST /api/v1/notifications/{notification_id}/read
- GET /api/v1/events

- [ ] **Step 1: Write failing notification-policy tests**

Allow only feedback_ready, correction_due, upcoming_real_interview, saturday_assessment, and processing_failure_requires_action. Reject streak, engagement, generic inactivity, catch-up, and Sunday study reminders at both command and persistence boundaries. Test learner timezone at Saturday/Sunday boundaries.

- [ ] **Step 2: Write failing durable-job policy and lease tests**

Prove enqueue idempotency, deterministic priority/FIFO selection, lease acquisition with SKIP LOCKED semantics, lease expiry/reclaim, heartbeat extension, bounded attempts, RetryWait scheduling, typed terminal NeedsAttention failures, cancellation, and crash safety. A worker crash cannot mark unfinished work successful, and a duplicate job command returns the existing logical job. Keep handlers out of this foundation task; later plans register recording, speech, and AI handlers against this primitive.

- [ ] **Step 3: Write failing delivery and resume tests**

Prove:

- an outbox consumer creates at most one notification for a domain event;
- a worker lease expiry permits safe retry;
- only the owner can read/mark read;
- duplicate mark-read commands are idempotent;
- SSE supports Last-Event-ID, monotonically ordered event IDs, keepalive comments, disconnect cleanup, and no cross-session data;
- a restarted API can resume from PostgreSQL without Redis.

- [ ] **Step 4: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/jobs apps/backend/tests/unit/notifications -q
~~~

Expected: FAIL.

- [ ] **Step 5: Implement the job repository, notification policy, PostgreSQL outbox poller, and SSE route**

Use bounded database polling with cancellation-safe waits. Do not introduce Redis. The job service owns enqueue/claim/heartbeat/complete/retry/fail commands but runs no domain handler yet. Store notification delivery state before emitting and expose processing status changes through the same ordered event stream.

- [ ] **Step 6: Run tests and commit**

~~~bash
uv run pytest apps/backend/tests/unit/jobs apps/backend/tests/unit/notifications -q
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/jobs apps/backend/tests/integration/notifications -q
git add apps/backend/src/tamforge_backend/jobs apps/backend/src/tamforge_backend/notifications apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/jobs apps/backend/tests/unit/notifications apps/backend/tests/integration/jobs apps/backend/tests/integration/notifications
git commit -m "feat: add durable jobs and status notifications"
~~~

Expected: unit tests pass. The integration command is approval-gated as described above.

## Task 21: Build the deterministic Today read model and daily close

**Files:**

- Create: apps/backend/src/tamforge_backend/today/schemas.py
- Create: apps/backend/src/tamforge_backend/today/repository.py
- Create: apps/backend/src/tamforge_backend/today/service.py
- Create: apps/backend/src/tamforge_backend/today/routes.py
- Create: apps/backend/tests/unit/today/test_continue_priority.py
- Create: apps/backend/tests/unit/today/test_today_service.py
- Create: apps/backend/tests/integration/today/test_today_api.py
- Modify: apps/backend/src/tamforge_backend/api.py

Endpoints:

- GET /api/v1/today?date=YYYY-MM-DD
- POST /api/v1/today/{date}/close

- [ ] **Step 1: Write failing read-model tests for every required field**

Assert the response shows the active roadmap version/week/day, required blocks, total planned minutes, at most two active corrections, scheduled interviews, self-reviews awaiting completion, analyses ready/needs attention, and exactly one primary Continue action when work exists. Each task card must include objective, timebox, source/case, required output, pass criteria, allowed AI role, and evidence requirements.

Sunday returns an explicit Off day, zero tasks, zero study reminders, and no Continue action. Saturday never plans over 120 minutes. Weekdays retain the exact 240-minute structure and 225–255 acceptable/hard-stop policy. Finishing early with all required outputs/pass conditions produces Close day, not invented work.

- [ ] **Step 2: Write failing Continue-priority tests**

Select one action deterministically in this order:

1. the one scheduled correction warm-up due now;
2. an Active or Paused activity;
3. an OutputCommitted activity awaiting mandatory self-review;
4. the next required Ready activity in roadmap order;
5. feedback/analysis ready for review;
6. daily close when required work and pass conditions are complete.

Tie-break by roadmap order then immutable ID. Never schedule all correction types; there are at most two corrections for tomorrow and exactly one warm-up carryover activity. Upcoming interviews appear but do not silently rewrite the roadmap.

- [ ] **Step 3: Write failing daily-close tests**

Require scorecard/evidence confirmation, strongest output, repeated mistake, unfinished-work classification, and no more than two selected corrections. Apply Required/Useful/Optional/Superseded consequences without extending future days or adding catch-up.

- [ ] **Step 4: Run focused tests**

~~~bash
uv run pytest apps/backend/tests/unit/today -q
~~~

Expected: FAIL.

- [ ] **Step 5: Implement one aggregate query/service and authenticated routes**

Avoid N+1 queries. Calculate all date boundaries in the learner timezone and return source timestamps plus an ETag/read-model version so the web client can refresh safely after SSE events.

- [ ] **Step 6: Run tests and commit**

~~~bash
uv run pytest apps/backend/tests/unit/today -q
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest apps/backend/tests/integration/today -q
git add apps/backend/src/tamforge_backend/today apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/today apps/backend/tests/integration/today
git commit -m "feat: add protected today study model"
~~~

Expected: unit tests pass. Run the integration command only against an explicitly approved test PostgreSQL instance.

## Task 22: Establish the authenticated React application shell

**Files:**

- Create: apps/web/src/api/client.ts
- Create: apps/web/src/api/schema.d.ts
- Create: apps/web/src/api/queryClient.ts
- Create: apps/web/src/auth/AuthProvider.tsx
- Create: apps/web/src/auth/ProtectedRoute.tsx
- Create: apps/web/src/components/AppShell.tsx
- Create: apps/web/src/components/ActiveRoleBadge.tsx
- Create: apps/web/src/pages/LoginPage.tsx
- Create: apps/web/src/pages/NotFoundPage.tsx
- Create: apps/web/tests/auth/AuthProvider.test.tsx
- Create: apps/web/tests/auth/ProtectedRoute.test.tsx
- Create: apps/web/tests/api/client.test.ts
- Modify: apps/web/src/App.tsx
- Modify: apps/web/src/main.tsx
- Modify: apps/web/src/app.css
- Modify: apps/web/package.json

- [ ] **Step 1: Write failing client/auth tests with MSW**

Test logged-out redirect, GitHub sign-in link, callback error display, authenticated shell, logout, expired-session recovery, credentials/include, CSRF on mutations, RFC problem rendering, and no token in localStorage/sessionStorage. The shell must show the active AI role whenever a later workflow supplies one; no role may be implicit.

- [ ] **Step 2: Run focused tests**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/auth tests/api/client.test.ts
~~~

Expected: FAIL.

- [ ] **Step 3: Generate the API types and implement the minimal shell**

~~~bash
uv run uvicorn tamforge_backend.main:app --app-dir apps/backend/src --host 127.0.0.1 --port 8000
pnpm --filter @tam-forge/web exec openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.d.ts
~~~

Run the first command in a separate local terminal and stop it after generation. Commit the generated schema. Implement keyboard-visible focus, semantic landmarks, responsive single-column task flow, and English-only product copy.

- [ ] **Step 4: Run web checks and commit**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/auth tests/api/client.test.ts
pnpm --filter @tam-forge/web typecheck
pnpm --filter @tam-forge/web lint
git add apps/web
git commit -m "feat: add authenticated web application shell"
~~~

## Task 23: Build the staged roadmap import, diff, approval, and activation UI

**Files:**

- Create: apps/web/src/features/roadmaps/api.ts
- Create: apps/web/src/features/roadmaps/RoadmapImportPage.tsx
- Create: apps/web/src/features/roadmaps/PackagePicker.tsx
- Create: apps/web/src/features/roadmaps/ValidationReport.tsx
- Create: apps/web/src/features/roadmaps/SemanticDiff.tsx
- Create: apps/web/src/features/roadmaps/ActivationGate.tsx
- Create: apps/web/tests/roadmaps/RoadmapImportPage.test.tsx
- Create: apps/web/tests/roadmaps/SemanticDiff.test.tsx
- Modify: apps/web/src/App.tsx

- [ ] **Step 1: Write failing workflow tests**

Using MSW, cover ZIP selection, browser-folder selection with preserved relative paths, upload progress, exact validation errors, immutable source manifest/hashes, semantic time/coverage/pass-criteria/assignment differences, approval audit note, GitHub mirror status/retry, activation, and cancel. Prove equivalent ZIP/folder inputs preview the same content hash, invalid or unapproved imports cannot activate, and Month 2 remains blocked until Month 1 exit review is recorded.

- [ ] **Step 2: Run focused tests**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/roadmaps
~~~

Expected: FAIL.

- [ ] **Step 3: Implement the thin UI over the roadmap APIs**

Do not read the Obsidian filesystem from the browser and do not silently normalize source content. Show immutable version ID, source hash, snapshot state, private GitHub mirror state, validation outcome, semantic diff, approver, and active/superseded state separately.

- [ ] **Step 4: Run tests and commit**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/roadmaps
pnpm --filter @tam-forge/web typecheck
git add apps/web/src/features/roadmaps apps/web/tests/roadmaps apps/web/src/App.tsx
git commit -m "feat: add governed roadmap import workspace"
~~~

## Task 24: Build Today and the universal study activity workspace

**Files:**

- Create: apps/web/src/features/today/api.ts
- Create: apps/web/src/features/today/TodayPage.tsx
- Create: apps/web/src/features/today/TaskCard.tsx
- Create: apps/web/src/features/today/ContinueAction.tsx
- Create: apps/web/src/features/activities/api.ts
- Create: apps/web/src/features/activities/ActivityWorkspacePage.tsx
- Create: apps/web/src/features/activities/ActivityContractPanel.tsx
- Create: apps/web/src/features/activities/SourcePanel.tsx
- Create: apps/web/src/features/activities/UniversalOutputEditor.tsx
- Create: apps/web/src/features/activities/ArtifactUploader.tsx
- Create: apps/web/src/features/activities/SelfReviewForm.tsx
- Create: apps/web/src/features/activities/useResumableTimer.ts
- Create: apps/web/tests/today/TodayPage.test.tsx
- Create: apps/web/tests/activities/ActivityWorkspacePage.test.tsx
- Create: apps/web/tests/activities/useResumableTimer.test.tsx
- Modify: apps/web/src/App.tsx

- [ ] **Step 1: Write failing Today tests**

Assert every required field and task-card contract, exactly one Continue action, two corrections at most, visible interviews/self-reviews/analyses, Sunday Off behavior, Saturday cap, feedback/needs-attention status, and no streak/vanity metric. Verify the screen refreshes the affected query after an SSE status event.

- [ ] **Step 2: Write failing workspace and timer tests**

Cover reading, SQL, TAM case, writing, and pipeline contract fields in the universal editor. Verify:

- current objective, audience, timebox, allowed AI role, evidence requirements, and pass criteria are always visible;
- source hide/reveal state is explicit and reading recall is committed closed-source;
- no AI answer/review control is enabled before output commitment or timeout where allowed;
- heartbeat/pause/resume survives route reload and network retry without double-counting;
- the UI warns at 255 weekday minutes and never extends the plan;
- committed Attempt A becomes read-only and any later edit is a distinct version;
- self-review is mandatory before AIProcessing and self-score is visually separate;
- Attempt C is not offered.

- [ ] **Step 3: Run focused tests**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/today tests/activities
~~~

Expected: FAIL.

- [ ] **Step 4: Implement the Today and activity routes**

Keep specialized editors out of this phase; use contract-driven sections and generic text/JSON/file artifacts. Autosave only mutable working drafts, debounce writes, display last durable save, and require an explicit irreversible commit confirmation. The server remains authoritative for state and focused time.

- [ ] **Step 5: Run web checks and commit**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/today tests/activities
pnpm --filter @tam-forge/web typecheck
pnpm --filter @tam-forge/web lint
git add apps/web/src/features/today apps/web/src/features/activities apps/web/tests/today apps/web/tests/activities apps/web/src/App.tsx
git commit -m "feat: add today and universal study workspace"
~~~

## Task 25: Expose evidence lineage and actionable processing status in the web app

**Files:**

- Create: apps/web/src/features/evidence/api.ts
- Create: apps/web/src/features/evidence/EvidenceLedgerPage.tsx
- Create: apps/web/src/features/evidence/SkillEstimateCard.tsx
- Create: apps/web/src/features/evidence/FormulaBreakdown.tsx
- Create: apps/web/src/features/evidence/PortfolioJudgmentCard.tsx
- Create: apps/web/src/features/notifications/api.ts
- Create: apps/web/src/features/notifications/useStatusEvents.ts
- Create: apps/web/src/features/notifications/NotificationPanel.tsx
- Create: apps/web/src/features/notifications/ProcessingStatus.tsx
- Create: apps/web/tests/evidence/EvidenceLedgerPage.test.tsx
- Create: apps/web/tests/evidence/FormulaBreakdown.test.tsx
- Create: apps/web/tests/notifications/NotificationPanel.test.tsx
- Create: apps/web/tests/notifications/useStatusEvents.test.tsx
- Modify: apps/web/src/components/AppShell.tsx
- Modify: apps/web/src/App.tsx

- [ ] **Step 1: Write failing evidence-display tests**

Render each skill's 0–4 estimate, target gap, confidence, trend, recency, last strong-evidence date, formula/rubric/mapping versions, and expandable contributing/excluded/discounted events with raw/effective weights. Keep the user's self-score distinct. Render Portfolio Judgment on its own 0–20 scale with seven component scores and related underlying skill events. Never display recording count, word count, app time, or streak as progress.

- [ ] **Step 2: Write failing notification/status tests**

Test only the five allowed notification types, mark-read idempotency, processing-state labels, SSE reconnect with Last-Event-ID, query invalidation, keyboard access, and a visible disconnected fallback that continues polling. Prove Sunday has no study reminder and a late/failed analysis never blocks independent work.

- [ ] **Step 3: Run focused tests**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/evidence tests/notifications
~~~

Expected: FAIL.

- [ ] **Step 4: Implement the ledger and status UI**

Use progressive disclosure: lead with demonstrated evidence and the current gap, while keeping every formula input inspectable. Do not add a global gamified score. Sanitize all user-authored Markdown before rendering.

- [ ] **Step 5: Run checks and commit**

~~~bash
pnpm --filter @tam-forge/web test -- --run tests/evidence tests/notifications
pnpm --filter @tam-forge/web typecheck
pnpm --filter @tam-forge/web lint
git add apps/web/src/features/evidence apps/web/src/features/notifications apps/web/tests/evidence apps/web/tests/notifications apps/web/src/components/AppShell.tsx apps/web/src/App.tsx
git commit -m "feat: show evidence lineage and processing status"
~~~

## Task 26: Verify the complete foundation slice and prepare its pull request

**Files:**

- Create: apps/backend/tests/integration/foundation/test_month1_workspace.py
- Create: apps/backend/tests/integration/foundation/test_failure_atomicity.py
- Create: apps/web/playwright.config.ts
- Create: apps/web/e2e/foundation-learning.spec.ts
- Create: apps/web/e2e/support/auth.ts
- Create: scripts/dev/seed_foundation_demo.py
- Create: scripts/ci/check_openapi.py
- Create: .github/workflows/ci.yml
- Create: .github/pull_request_body.md
- Modify: apps/web/package.json
- Modify: Makefile
- Modify: README.md
- Modify: docs/project/github-issues.yml

- [ ] **Step 1: Write the failing backend vertical-slice test**

The integration test must:

1. authenticate as the exact configured owner;
2. upload a validated Month 1 package;
3. persist the immutable object snapshot before the database snapshot reference;
4. preview the semantic diff, explicitly approve, mirror to private GitHub, and activate;
5. instantiate the correct Monday assignments and exact time boxes;
6. start/pause/resume a reading task across sessions;
7. hide its source, commit the required recall artifact, and commit self-review;
8. record rubric evidence through the internal application service;
9. reproduce the skill snapshot from the ledger;
10. expose Today/notification updates without duplicating any command.

Add failure injections after object put, before database commit, during mirror, during output commit, and during snapshot recalculation. Verify the active roadmap and prior evidence remain unchanged, orphan cleanup is safe/idempotent, and retry never duplicates a logical version/activity/evidence event.

- [ ] **Step 2: Write the failing browser flow**

Use a test-only authenticated session fixture that is impossible to enable outside TAMFORGE_ENV=test. Exercise roadmap upload/diff/approval, Today, Continue, timer reload, source hide, universal output commit, mandatory self-review, evidence lineage, and notification read. Assert English copy, semantic headings, keyboard navigation, and no Attempt C/vanity metric/Sunday reminder.

- [ ] **Step 3: Add an OpenAPI drift check**

scripts/ci/check_openapi.py creates the backend schema in memory and compares generated apps/web/src/api/schema.d.ts. CI fails with the exact regeneration command when drift exists.

- [ ] **Step 4: Add CI without relying on developer-machine Docker**

GitHub Actions jobs:

- backend-unit: Ruff, mypy, unit/property tests;
- web: lint, typecheck, Vitest;
- backend-integration: PostgreSQL 16/pgvector service container, migrations, integration tests;
- e2e: migrated PostgreSQL service, backend/web processes, Playwright Chromium;
- openapi: generated-client drift check;
- secret-scan: repository secret patterns and forbidden audio/object artifacts.

Pin action major versions and pnpm/uv/Python/Node versions. Grant contents: read by default and no production credentials. CI service containers are isolated from the user's Mac and do not authorize production deployment.

- [ ] **Step 5: Run the non-Docker verification suite**

~~~bash
make check
uv run pytest apps/backend/tests/unit scripts/github/tests packages/protocol/tests -q
pnpm --filter @tam-forge/web test -- --run
uv run python scripts/ci/check_openapi.py
git status --short
~~~

Expected: all checks pass and only intended source/plan-generated files are present. None of these commands starts Docker.

- [ ] **Step 6: Run integration/E2E only after explicit Docker approval**

After the user explicitly approves Docker use in that execution turn, no Docker command in this group may run without that fresh approval:

~~~bash
set -e
cleanup_and_verify() {
  original_status=$1
  set +e
  docker compose -f compose.dev.yml down --remove-orphans
  running_ids=$(docker compose -f compose.dev.yml ps --status running --quiet)
  ps_status=$?
  verification_status=0
  if [ "$ps_status" -ne 0 ] || [ -n "$running_ids" ]; then
    docker compose -f compose.dev.yml ps --status running
    verification_status=1
  fi
  trap - EXIT INT TERM
  if [ "$verification_status" -ne 0 ]; then
    exit 1
  fi
  exit "$original_status"
}
on_exit() { cleanup_and_verify "$?"; }
on_int() { cleanup_and_verify 130; }
on_term() { cleanup_and_verify 143; }
trap on_exit EXIT
trap on_int INT
trap on_term TERM
docker compose -f compose.dev.yml up -d postgres minio
bash scripts/dev/ensure_test_database.sh
DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  uv run alembic -c apps/backend/alembic.ini upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run pytest -m integration apps/backend/tests/integration -q
pnpm --filter @tam-forge/web exec playwright test e2e/foundation-learning.spec.ts
exit 0
~~~

When Playwright starts a backend process, it uses this same isolated `DATABASE_URL` and `TEST_DATABASE_URL`; it must never inherit the ordinary `.env` `tamforge` database. Expected: migrations, integration tests, and browser flow pass, followed by an empty final `ps --status running`. Every normal, failing, INT, and TERM exit runs `down --remove-orphans` then a fail-closed running-service check; any remaining service/container or failed check exits 1, otherwise the original failure status is preserved. Traps are removed only after that check. If approval is not given, do not run these commands; rely on unit checks and the exact-head GitHub Actions result without representing skipped integration tests as green.

- [ ] **Step 7: Refresh generated API types and issue status, then make the final focused commit**

~~~bash
uv run python scripts/github/sync_issues.py --repo fgomensoro/tam-forge --manifest docs/project/github-issues.yml --dry-run
git add .github/workflows/ci.yml .github/pull_request_body.md Makefile README.md apps/backend/tests/integration/foundation apps/web/playwright.config.ts apps/web/e2e apps/web/package.json apps/web/src/api/schema.d.ts scripts/ci scripts/dev docs/project/github-issues.yml
git commit -m "test: verify foundation learning workspace"
~~~

Expected: issue dry-run reports only the intended catalog/status changes; it performs no GitHub write.

- [ ] **Step 8: Push the feature branch and open a pull request**

~~~bash
git status --short
git log --oneline --decorate -15
git push -u origin feat/foundation-learning-workspace
gh pr create --repo fgomensoro/tam-forge --base main --head feat/foundation-learning-workspace --title "Foundation: roadmap-driven learning workspace" --body-file .github/pull_request_body.md
~~~

Before committing the body file, fill these sections with observed facts: outcome, approved-plan link, scope/non-goals, migrations, privacy/security impact, verification with explicit skipped checks, and issue links. Do not put secrets or source roadmap content in the PR body.

- [ ] **Step 9: Bind review and CI to the exact final head**

~~~bash
git rev-parse HEAD
gh pr view --repo fgomensoro/tam-forge --json number,url,headRefOid,mergeStateStatus,statusCheckRollup,reviewDecision
~~~

Expected: headRefOid equals local HEAD. Wait for all required checks on that exact SHA and address review findings in new focused commits. A missing/skipped check is not green, mergeable is not deployed, and this plan stops before merge. Merge requires explicit user approval.
