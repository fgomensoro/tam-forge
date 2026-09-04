# Operational health and content-safe telemetry

## Endpoints

- `GET /healthz`: process liveness only. Its existing response is unchanged.
- `GET /readyz`: `200` when database and ingest durability are healthy, otherwise
  `503`. Returns only `ok`, `degraded`, or `unready`, with no component details.
- `GET /ops/status`: component state and fixed reason codes; requires the same
  owner cookie or native bearer authentication as the application.
- `GET /ops/metrics`: Prometheus text exposition, also owner authenticated.

All new responses are `Cache-Control: no-store`. These infrastructure endpoints
are excluded from the native OpenAPI client. They never trigger jobs, write
evidence, send notifications, retry operations, or restart services.

The database probe performs only `SELECT 1`, bounded to one second including
connection checkout. No object-store write or paid API call is made by a probe.
Liveness must remain the restart probe: Claude quota/auth problems, transcription
failure, or a stale backup should not restart-loop independent study.

## Missing evidence is not health

`app.state.operational_health.report(component, status, reason)` accepts only the
fixed enums in `observability/health.py`. Observations expire after 60 seconds
using a monotonic clock. Never refresh an observation merely because it was read.
`unknown/not_observed` and `unknown/stale` must remain visible until the owning
producer provides fresh evidence. Ingest is critical, so missing ingest evidence
refuses readiness even while liveness remains green.

Current live wiring: database probe, request totals/duration, safe request events,
Uvicorn access-log suppression of all targets/peer data, and sanitization of all
Uvicorn error-logger levels (including rejected WebSocket handshakes).
There is **no production ingest health producer yet**. `/readyz` therefore stays
unready by default; do not attach it to a production traffic gate until the ingest
owner wires a real, approved durability check. Never mark ingest healthy from
configuration presence, an upload attempt, or `SELECT 1` alone.

Speech, Claude, backup, resource, export, and retention observations are also
unwired and remain unknown. Their owning issues must provide current evidence.
This change is the isolated operational foundation for #109; full producer
integration and live acceptance remain open.

## Safe metrics and producer integration

Use `app.state.operational_metrics.observe(name, value, **labels)` for a committed
operational outcome. Names and label values are closed vocabularies in
`observability/metrics.py`; arbitrary IDs, company names, text, URLs and model names
are rejected. Samples are aggregated, never retained. Registries hold at most
4096 series per process. A full registry rejects new series; HTTP telemetry drops
that measurement without failing the request. Counters reset on process restart.
They are diagnostic signals, not durable audit or release evidence.

The defined contracts cover ingest ACK, queue depth/age, job duration/error,
speech deadlines, composite 15/60-minute outcomes, quota/auth capability state,
backup age/verification, disk/RAM, export/import integrity, recoverable deletion,
interviewer latency, and allowed notification counts. Absent samples mean
**unobserved**, not zero or success. For `capability_state`, use 1 only for a current
healthy observation and 0 for a current failure; expiration and missing evidence
must be read from `/ops/status`. Do not keep exporting an expired healthy gauge.

Call `record_composite` with an approved deadline and disjoint active/suspension
durations that sum to wall duration. Quota/auth/service/memory suspension yields
`needs_attention`; a speech-stage miss yields `failed`; overdue unfinished work
yields `overdue`. None count as `succeeded`. Producers must enforce exactly-once
reporting in their durable workflow and emit outstanding-run gauges separately;
repeated scrapes must never call this helper to increment counters.

## Responding to degraded capabilities

- `claude/quota` or `claude/auth`: pause only dependent AI work, preserve source
  evidence, expose NeedsAttention, and use the existing authorized authentication
  workflow. Never fall back to API credentials or a paid model automatically.
- `speech/processing_failure` or `resources/memory_pressure`: keep work resumable
  and preserve originals; the speech owner controls the single-job retry policy.
- `ingest/durability_failure`: refuse readiness. Inspect owner-authorized durable
  state before retrying; never acknowledge an unverified original or delete spool.
- `backup/stale` or `resources/disk_pressure`: require operational attention before
  data loss. Do not fabricate restore evidence or auto-delete recordings.
- `export/integrity_failure` or a retention error: stop the affected workflow and
  preserve recoverability. Health reads cannot approve destructive action.

Detailed diagnostics stay in owner-authorized application records. Journal events
are built through `safe_event`; never pass raw exception strings to it. Keep SQL
echo, HTTP wire debugging, request-body logging, and third-party debug handlers
disabled. The installed Uvicorn filters do not sanitize arbitrary third-party
loggers or an independently configured reverse proxy.

## Notifications and verification

Reuse `notifications/policy.py` and the durable outbox delivery mechanism. Only
feedback ready, correction due, upcoming real interview, Saturday assessment,
and processing failure requiring action are allowed. Sunday correction reminders
and engagement/streak prompts stay suppressed; background feedback can complete.
Scraping these endpoints must never produce duplicate notifications.

Focused local verification (no external services):

```sh
PYTHONPATH=apps/backend/src:packages/protocol/src uv run python -m pytest \
  apps/backend/tests/unit/observability \
  apps/backend/tests/unit/notifications \
  apps/backend/tests/security/test_log_redaction.py \
  apps/backend/tests/unit/auth/test_access_logging.py \
  apps/backend/tests/unit/test_health.py -q
```

Live producer wiring, production reverse-proxy log policy, and real degradation
drills remain required before closing #109. Synthetic unit evidence does not
prove a configured production service, backup, or SLO.
