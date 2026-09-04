# Issue 109: private operational observability

Base: `origin/main` at `b7c9878`. Isolated branch:
`codex/issue-109-observability`. No roadmap, native, recording, storage,
authentication, or migration edits belong in this worktree.

Acceptance follows issue #109 and Task 27 of the operations plan:

- Construct logs from closed event/field vocabularies; never serialize request
  bodies, URLs, headers, exception messages, or arbitrary label values.
- Bound metric cardinality and memory. Keep suspension, missed speech deadlines,
  and overdue incomplete runs out of successful composite SLO samples.
- Keep liveness independent of readiness. Probe the database within a timeout;
  expose capability degradation and stale/missing observations explicitly.
- Require existing owner authentication for detailed health and metrics.
- Reuse the existing five-type notification allowlist and durable outbox
  deduplication. Health reads never enqueue reminders or trigger work.
- Preserve the native API contract; operational endpoints are excluded from the
  generated client schema.

Implementation order: failing privacy/metrics/health tests, isolated operational
modules, minimal application wiring, runbook, focused regression verification.
No Docker, Xcode, hardware capture, deployment, or production probes.

Future speech, Claude, backup, export, and retention producers do not exist yet.
Their observation contracts must be tested now, but their live integration must
remain visibly unverified; missing evidence must never become a green metric.
Do not close #109 on the strength of synthetic producer evidence alone.

## Verification, 2026-09-04

- 135 focused observability, notifications, authentication and liveness tests pass.
- Ruff and strict mypy pass on the changed implementation.
- Native OpenAPI remains unchanged; repository secret/audio policy and whitespace
  checks pass. No native build, Docker, external service or production drill ran.
- Streaming regression proves upload input is not pre-read and SSE output is not
  buffered. A saturated metrics registry cannot fail the application request.
- #109 remains open for real ingest/capability producers and live acceptance.

## Pre-merge review corrections

The independent review of `5479c6f` found that rewriting Uvicorn access records
broke its stock formatter, and INFO-level rejected WebSocket logs retained raw
targets. Access records are now suppressed in favor of middleware events; every
Uvicorn error-logger level is reduced to safe structured data. Regressions use
the stock formatter and WebSocket diagnostic shapes. The application explicitly
enables its own logger during lifespan and restores its prior state, fixing the
full-suite failure after Alembic configures logging.

Fresh verification after these corrections: 1121 backend/protocol/CI-script tests
passed, 2 integration-marked tests deselected; full-source Ruff and strict mypy
(99 source files) passed. CI and renewed exact-commit review still gate merge.
