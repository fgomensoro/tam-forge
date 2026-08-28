# TAM Forge

TAM Forge is a private, single-user learning workspace for Technical Account
Manager interview practice.

## Local development

Install the toolchains and workspace dependencies:

```bash
make install
```

Run the default unit checks (Docker is not required):

```bash
make check
```

This runs backend lint/type checks and unit tests, web lint/type checks/tests/build,
the generated OpenAPI-client drift guard, and the tracked secret/audio policy check.
Every default Make target is non-Docker.

Regenerate the checked-in web API types only when the backend contract changes:

```bash
uv run python scripts/ci/check_openapi.py --write
uv run python scripts/ci/check_openapi.py
```

The optional `compose.dev.yml` provides local PostgreSQL/pgvector and a pinned
MinIO release for later local integration work. It is never started by the
default Make targets and is not a production deployment configuration.

Database schemas are created, upgraded, downgraded, and removed only through
Alembic migrations. Direct `Base.metadata.create_all()` and `drop_all()` calls
are guarded so tests and application code cannot emit a partial parallel schema.

## Production object-storage gates

Before enabling production traffic, create a known canary object through the
authenticated application path, then use an independent client with no object-store
credentials to issue both `HEAD` and `GET` requests for it. Deployment remains blocked
unless both requests return `403` and the Hetzner control plane confirms that the
bucket has no public policy or ACL. This is a live provider check; the Moto contract
test covers the same access expectation locally but cannot prove production policy.

At-rest encryption and recovery-key ownership require a separate approved
architecture decision and are not configured by the local object-store adapter.

## Isolated integration and browser verification

Integration and browser checks require the explicitly isolated `tamforge_test`
database. They never create a database and never start Docker implicitly:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  make integration

TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  make e2e
```

The browser journey uses `scripts/dev/seed_foundation_demo.py`. That helper
refuses to run outside `TAMFORGE_ENV=test`, refuses any database other than the
local `tamforge_test`, and creates only a hashed, short-lived test session. It
does not add a test-login endpoint to the application.

GitHub Actions runs six isolated gates: backend unit checks, web checks,
PostgreSQL integration tests, the Chromium learning journey, OpenAPI drift, and
tracked secret/audio policy. CI receives no production credentials and does not
deploy or merge anything.

## GitHub planning catalog

The approved milestones, labels, epics, and child issues are declared in
`docs/project/github-issues.yml`. Previewing the catalog is safe and is the
default behavior:

```bash
uv run python scripts/github/sync_issues.py \
  --repo fgomensoro/tam-forge \
  --manifest docs/project/github-issues.yml \
  --dry-run
```

Before `origin` points to the private target repository, that command plans
against an offline empty state and does not invoke GitHub. Once the verified
private remote is configured, it reads all open and closed planning records.

Applying is an external write and must only happen after separately confirming
the authenticated GitHub account, immutable owner ID, and private personal
repository:

```bash
uv run python scripts/github/sync_issues.py \
  --repo fgomensoro/tam-forge \
  --manifest docs/project/github-issues.yml \
  --apply
```

Apply never deletes or closes issues, never reopens closed managed issues, and
never removes unrelated labels. Re-run the dry-run after an apply; it should
report zero planned creates or updates.
