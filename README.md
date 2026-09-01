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

This runs Compose safety, backend lint/type checks and unit tests, native-only OpenAPI
drift, repository policy, and the native macOS check when Xcode is available. Every
default Make target is non-Docker and has no Node runtime requirement.

## Native macOS shell

The SwiftUI app shell lives in `apps/macos` and requires Xcode 26.6 for local
development. Its local build configuration uses the `TAM Forge Local Development`
identity; signing material is never committed. Run its focused build and unit checks
with:

```bash
make macos-check
```

Local native checks default to two build jobs for the 8 GB Mac. To reuse a
task-specific cache, pass
`MACOS_BUILD_ARGUMENTS='-jobs 2 -derivedDataPath /tmp/tamforge-native-batch-01'`
to `make macos-check` or `make check`; do not run native builds concurrently.

When Xcode is available, `make check` includes the same non-Docker native check.
The GitHub Actions macOS job tests the unsigned CI build path separately.

The macOS target generates its Swift request and response types at build time from
`apps/macos/TAMForge/openapi.yaml`; generated Swift files remain in Xcode's build
directory and are never hand-copied into the repository. The same command checks
that native input when the backend contract changes:

```bash
uv run python scripts/ci/check_openapi.py --write
uv run python scripts/ci/check_openapi.py
```

The native target pins the official Apple OpenAPI generator, runtime, and
URLSession transport in the Xcode project and `Package.resolved`. CI passes
`-skipPackagePluginValidation` only because that build-tool plugin is exactly
pinned and resolved; this permits its noninteractive Xcode invocation.

The current FastAPI contract still declares browser session-cookie parameters.
The Apple generator reports those unsupported cookie parameters while producing
the remaining typed client. The backend accepts exactly one browser cookie or
native bearer credential; mixed credentials fail closed. Browser mutations keep
Origin and CSRF checks, while native mutations skip those browser-only checks only
after bearer validation.

Native GitHub login uses `ASWebAuthenticationSession`, PKCE S256, a short-lived
one-time exchange code, a 15-minute memory-only access token, and a rotating
30-day refresh token stored as a device-only generic Keychain item. PostgreSQL
stores token hashes only. The GitHub OAuth application keeps the HTTPS backend
callback `/api/v1/auth/callback`; the backend then returns the bounded exchange
code through `tamforge://auth/callback`. Optional TTL overrides are documented in
`.env.example`. See `docs/security/native-auth-threat-model.md` for controls,
residual risks, and production gates.

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

## Isolated integration and durable backend verification

Integration and durable backend E2E checks require the explicitly isolated `tamforge_test`
database. They never create a database and never start Docker implicitly:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  make integration

TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
TAMFORGE_OBJECT_STORE_ENDPOINT=http://127.0.0.1:9000 \
TAMFORGE_OBJECT_STORE_BUCKET=tam-forge-parity-test \
TAMFORGE_OBJECT_STORE_ACCESS_KEY=tamforge \
TAMFORGE_OBJECT_STORE_SECRET_KEY=tamforge-local \
  make e2e
```

`make e2e` and CI invoke
`apps/backend/tests/integration/foundation/test_month1_workspace.py` directly. That
test creates its own durable journey state. `scripts/dev/seed_foundation_demo.py` is
a separate data-only helper for explicitly requested isolated seed preparation; it
refuses to run outside `TAMFORGE_ENV=test`, refuses any database other than the local
`tamforge_test`, and does not emit browser cookies or add a test-login endpoint.

GitHub Actions runs seven isolated gates: native macOS build/unit checks, native UI,
backend unit checks, PostgreSQL integration tests, durable backend E2E, native OpenAPI
drift, and tracked secret/audio policy. CI receives no production credentials and does
not deploy or merge anything.

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
