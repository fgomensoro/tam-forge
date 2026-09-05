# Model provenance persistence

Revision `20260905_0015_model_provenance` adds seven append-only tables. It does not
execute models/tools or publish assessments. `BackgroundJob` continues to own
scheduling; each actual invocation gets a distinct durable invocation key.

## Repository boundary

`PromptRegistry(session)` publishes exact prompt bytes and deterministic schema
JSON, returning the existing record only for identical owner/key/version/content.
`publish_analysis_schemas(owner_id=...)` registers the #54 English and TAM schema
snapshots under their actual `$id` URNs and `v1`. Schema publication requires an
exact `$id` matching the requested key; there is no fallback schema selection.
`lookup(owner_id=..., content_hash=..., kind="prompt"|"schema")` returns all matching
verified versions, ordered by ID, because different version keys may contain the
same content.

`bind_rubric(owner_id=..., rubric_id=...)` addresses an existing rubric. PostgreSQL
extracts its release entry and checks name, scope, scale and every dimension's
ordinal, key, name, weight, maximum and availability against the persisted rows.
Before binding, PostgreSQL also recomputes the original config digest from its
stored complete payload. The frozen legacy byte rules are UTF-8, sorted object
keys, compact separators and preserved array order; Decimal configuration values
remain JSON strings. The accepted legacy value domain includes strings, booleans,
null, arrays, objects and integer JSON numbers. Fractional numeric storage is
rejected rather than normalized into a new historical hash. This full-payload
verification uses the existing 8 MiB config bound, not the smaller run-envelope
bound. The binding pins the verified original config hash and extracted definition
hash. It never changes historical rubric/config rows, substitutes a release, or creates weights.

`ModelRunRepository.register(RunRequest(...))` atomically writes a frozen header
and 1–64 context rows. Every pinned version includes both row ID and SHA256 hex.
The owner and activity locks serialize registration with the existing learning
boundary. Same owner/invocation key and original request replays; changed input
raises `ImmutableVersionConflict`. Job and same-activity predecessor links are
optional. The repository owns its transaction: use a session without an active
transaction and keep `expire_on_commit=False` when returning ORM records.

`append_event(owner_id=..., run_hash=..., expected_sequence=..., expected_state=...,
event=Lifecycle(...))` accepts registered → running → succeeded/failed/cancelled,
and failure/cancellation directly from registered. The header represents sequence
0/registered. Event sequences start at 1. Running requires an observed resolved
model and SDK or CLI version. Terminal records cannot be followed, timestamps
come from the database, elapsed milliseconds cannot decrease, and success cannot
leave pending tools. Failure categories and retry disposition are bounded enums.

`append_tool(..., expected_sequence=..., audit=ToolAudit(...))` uses an independent
run-wide sequence. Each call key has one request followed by at most one terminal
result while the run is running. Its version, registered schema hash and ordered
context ordinals must match the request. Failures and cancellations remain visible;
a failed/cancelled run may retain pending tool requests. Audit metadata accepts only
call/tool identifiers, versions, hashes, context ordinals, counts, elapsed time,
phase and typed error category. It accepts no raw argument/result body, credentials,
URLs or learner text. Tool schema hashes resolve to the owner's schema registry.

`read(owner_id=..., run_hash=...)` returns the header, complete ordered context,
lifecycle events and tool audit. Missing/invalid/conflicting records raise the
closed `ProvenanceError` subclasses; repository errors contain no raw SQL or input.

## Byte domains (hash format 1)

Every digest is SHA256 stored as 32 bytes, rendered as lowercase hex in envelopes.
For `prompt_versions`, `canonical_json` holds the exact prompt UTF-8 text despite
its shared storage column name. No whitespace, newline or Unicode normalization
occurs. Prompt and schema content is limited to 1 MiB UTF-8. NUL and unpaired
surrogates cannot be represented by PostgreSQL UTF-8 text and are rejected.

For schema and all other records, `canonical_json` contains deterministic JSON:
UTF-8, object keys in Unicode code-point order (PostgreSQL `C` collation), preserved
array order, no insignificant whitespace, JSON string escaping with Unicode kept
literal, booleans/null unchanged, finite numbers in plain decimal with trailing
fractional zeroes removed and negative zero represented as `0`. Python accepts
numbers with decimal exponent magnitude at most 1000 and nesting at most 64;
record byte limits apply in both layers. SHA256 is over those stored UTF-8 bytes,
without a hidden prefix. Non-content envelopes also contain `format: 1` and a
`kind` discriminator. Database CHECKs recompute canonical bytes and actual digests.

Binding envelopes include owner, config ID/hash, rubric ID/hash and the verified
release entry. Context envelopes include owner, activity, ordinal, reason, profile,
source version/hash, exact AttemptTextReference and prepared-input hash. Header
manifests are ordered arrays of context-envelope hashes; `manifest_hash` is SHA256
of that canonical array. The header includes the original request fields and that
manifest. Event/tool envelopes include owner, run hash, sequence and the typed
payload. Thus tool hashes identify the persisted redacted audit envelope, never
omitted raw tool inputs or outputs.

Generated row IDs and creation timestamps are excluded from each row's digest.
Pinned reference IDs intentionally remain inside envelopes. A context hash is
reusable across invocations of the same exact context: its parent run ID is outside
the digest to avoid a circular run/manifest hash. A run's invocation key prevents
identical requests at different execution times collapsing into one invocation.

## Committed learner text only

The initial profile is `committed-attempt-text-v1`, source version 1. Its only
source is `Attempt.original_text`, a committed JSON envelope. Context pins both
the stored commitment SHA256 and SHA256 of the exact original-text bytes. The
commitment hash is the existing learning ledger's hash (including linked artifact
commitments); it is not replaced by the original-text digest.

PostgreSQL independently checks owner/activity/attempt identity, envelope version,
source digest, pointer and range, then hashes the selected decoded string slice.
The selection preserves Unicode code points; end is exclusive. Only the locked
learner-field allowlist in `agents/model_runs.py` is accepted. An array requires
one exact nonnegative decimal index without leading zeroes. Ranges must be nonempty
and fit the selected string. Prompt, audience, facts, instructions and other task
metadata cannot become learner evidence. Artifact references and external source
resolution are unsupported; there is no trusted-caller bypass.

Deferred constraints require the header manifest to equal every context row at
commit, in contiguous ordinal order with no repeated evidence reference. This
allows atomic aggregate creation while rejecting missing rows or later additions.
All seven tables reject UPDATE, DELETE and TRUNCATE in PostgreSQL; ORM mapper hooks
also reject updates/deletes. Composite FKs and INSERT guards verify association
and pinned hashes even when SQL bypasses the repositories.

## Verification

Local work uses unit tests, Ruff, mypy, OpenAPI comparison, Alembic offline SQL and
integration collection only. Never start local databases, containers or providers
for this ticket. Existing CI supplies PostgreSQL 16 at the approved test boundary.

```sh
PYTHONPATH=apps/backend/src:packages/protocol/src uv run python -m pytest apps/backend/tests/unit/agents apps/backend/tests/unit/testing -q
PYTHONPATH=apps/backend/src:packages/protocol/src uv run python -m pytest apps/backend/tests/integration/agents --collect-only -m postgres_integration --strict-markers -q
# In the existing CI database environment only:
scripts/run-plan-03-integration.sh apps/backend/tests/integration/agents
```

The gate requires explicit paths and `TEST_DATABASE_URL`, validates exactly the
existing `127.0.0.1:54329/tamforge_test` boundary, uses strict markers, and rejects
empty collection, skips, collection failures and incomplete pass counts. It prints
counts, never credentials. CI retains every existing integration test and runs
these double-marked cases once through the gate. Tests create attempts through
`ActivityService`; isolated schema cleanup avoids forcing evolved activity states
through historical downgrade constraints. Revision-only downgrade leaves earlier
objects intact and upgrade can recreate all provenance objects.
