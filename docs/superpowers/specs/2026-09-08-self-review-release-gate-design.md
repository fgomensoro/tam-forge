# Mandatory self-review release gate

Issue #55 (E5-I03), Task 7 of the agents/interviews/operations plan.

Reviewer output stays withheld until the learner's self-review is committed and
every piece of evidence the analysis cites is available and valid.

## Scope

This slice delivers the release gate and the read contract only. It does not
define feedback content. Verdict, the two-strengths/two-corrections rule,
rendered Markdown and Attempt B instructions belong to #57 and #58. The
15/60-minute processing clock and its SLOs belong to #63. The job runner that
actually invokes the Reviewer belongs to #67.

The pieces this slice depends on already exist: immutable prompt, output schema,
rubric and model-run provenance from #53; the separate `EnglishAnalysisV1` and
`TAMAnalysisV1` contracts from #54; and the `output_committed →
self_review_complete → ai_processing → feedback_ready` activity state machine.

## The gate lives in the type

`FeedbackRead` is a frozen model whose validator makes a response carrying
analysis outside the `ready` status unconstructible. Withholding is therefore
not a branch a caller can forget, bypass through `model_construct`, or lose when
a second reader is added later.

The alternative considered was a check inside the read service. It was rejected
because it protects one code path rather than the contract, and the eventual
callers of this contract are the job runner (#67) and the native client, neither
of which exists yet to be audited.

## Components

### Read contract

`packages/protocol/src/tamforge_protocol/agents.py` gains:

- `FeedbackStatus`: `processing`, `needs_attention`, `ready`.
- `AnalysisVersions`: the pinned prompt, output schema, rubric binding and model
  run identified by id and content hash.
- `FeedbackRead`: status, activity and attempt ids, versions, optional `english`
  and `tam` analyses, and an optional closed-vocabulary `withheld_reason`.

Validation rules:

- `ready` requires both analyses present and no withheld reason.
- `processing` and `needs_attention` require both analyses absent.
- `needs_attention` requires a withheld reason; the other two forbid one.

No object URLs, no audio references, no free text beyond what the analysis
contracts already bound.

### Release gate

`apps/backend/src/tamforge_backend/agents/roles/reviewer.py` holds a pure
function that receives already-loaded state and returns either a release or a
withholding reason. It performs no I/O, so every rule is unit-testable without a
database.

It withholds when:

- no self-review row exists for the attempt, or the activity has not reached
  `self_review_complete`
- an evidence reference cited by an observation is absent from the model run's
  context manifest
- an `AttemptTextReference` names a different attempt than the analysis, or
  carries a commitment hash that does not match the attempt
- a cited artifact is not linked to that activity and attempt, or its
  `immutable_version` or `content_hash` does not match the reference
- a cited artifact is classified `original_audio`
- the prompt, output schema or rubric versions inside the analysis disagree with
  the versions pinned on the model run

Reasons are closed slugs: `self_review_pending`, `evidence_unavailable`,
`evidence_out_of_manifest`, `version_mismatch`, `forbidden_source`. They never
carry submitted content, database diagnostics or reference detail, so a withheld
response cannot become a side channel for the material it is withholding.

### Publication storage

`AnalysisPublication` extends the existing `RunChild` provenance base in
`agents/models.py`, so it inherits canonical-JSON bytes, a database-verified
content hash, and the update/delete rejection listeners that already guard model
runs. One row per `(run_id, analysis_kind)`. Migration `0016` adds the table.

Storing the published analysis is what allows a `ready` response to carry real
content, and it retires the placeholder in `evidence/repository.py` that
currently rejects observation references because analysis storage is absent.

### Read endpoint

`analysis/repository.py` loads publication state; `analysis/routes.py` exposes
`GET /api/v1/activities/{activity_id}/attempts/{attempt_id}/feedback`,
authenticated and owner-scoped, with the same `no-store` response headers the
evidence endpoints use. There is no service layer between them, because it would
only forward calls.

## Data flow

Publication: the producer supplies a validated analysis and its model run. The
gate runs against loaded state. On release the row is written; on withholding
nothing is written and the activity stays in `ai_processing`.

Read: absent publication yields `processing`. A recorded withholding yields
`needs_attention` with its reason. A publication yields `ready` with content.

## Testing

- `packages/protocol/tests/test_agents.py`: the status/analysis/reason
  combinations the validator must reject, and the two it must accept.
- `apps/backend/tests/unit/agents/roles/test_reviewer.py`: one failing case per
  withholding reason, plus the release path.
- `apps/backend/tests/unit/analysis/test_feedback_routes.py`: HTTP contract
  through `TestClient` with a stubbed repository, following
  `test_evidence_routes.py`. No database.

Adding the route regenerates `apps/macos/TAMForge/openapi.yaml`, which
`scripts/ci/check_openapi.py` produces. No Swift source changes.
