## Outcome

Implements the approved TAM Forge safe foundation as a private, single-user,
roadmap-driven learning workspace. The original curriculum remains immutable and
versioned; independent attempts, self-review, evidence, and notifications remain
separate durable records.

Approved plan: `docs/superpowers/plans/2026-08-25-tam-forge-01-foundation-learning.md`

## Scope

- Single-owner GitHub authentication and fail-closed runtime configuration
- PostgreSQL/Alembic foundations and private immutable object-storage boundary
- Versioned Obsidian roadmap import, semantic diff, explicit approval, private
  mirror state, and activation
- Today workspace, resumable timers, closed-source recall, immutable Attempt A,
  mandatory self-review, and correction boundaries
- Versioned evidence ledger, reproducible skill estimates, Portfolio Judgment,
  actionable notifications, and resumable status delivery
- End-to-end/failure-atomicity coverage, generated API drift detection, and CI

## Non-goals

- No production deployment or Hetzner mutation
- No merge without explicit owner approval
- No Claude API billing fallback; future agent work remains subscription-only
- No direct Mac recorder, transcription worker, or Agent SDK runtime in this slice
- No iPhone Voice Memo ingestion and no DataNest-derived content

## Data and migrations

- Alembic remains the only schema lifecycle mechanism.
- Roadmap snapshots and evidence are append-only/versioned; retries are idempotent.
- Original source evidence is never overwritten by analysis or reanalysis.

## Privacy and security

- Exact immutable numeric owner allowlist with hashed browser session and CSRF tokens
- Same-origin mutation checks and private object-store contracts
- Test authentication bootstrap is process-only, requires `TAMFORGE_ENV=test`, and
  refuses any database except local `tamforge_test`
- CI has `contents: read`, no production credentials, and rejects tracked source
  audio, object data, private keys, and common provider-token patterns

## Verification

- `make check`: 23 bootstrap checks, 912 non-integration Python tests, 35 web
  tests, lint, typecheck, production build, OpenAPI drift guard, and repository
  policy guard passed.
- PostgreSQL/pgvector integration: 24 tests passed.
- Chromium end-to-end: the complete Month 1 import, activation, Today,
  closed-source Attempt A, self-review, evidence, and notification journey passed.
- Local Compose services were removed after verification and Docker Desktop was
  closed.

## Issues

- Implements the M0 safe-foundation issues represented by
  `docs/project/github-issues.yml`, including E1-I02.
