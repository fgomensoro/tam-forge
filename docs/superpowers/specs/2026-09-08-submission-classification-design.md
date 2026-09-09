# Data classification, sensitivity scopes, and model-submission audit

Issue #103 (E9-I01), Task 2 of the agents/interviews/operations plan.

Nothing reaches an external model without a sensitivity scope, a redaction decision,
a consent basis, an evidence manifest, and an immutable audit record.

## Scope

This slice classifies artifacts, gates the one path that submits prepared learner text
to an external model, and records the decision. It does not build the redaction preview
or the learner's explicit release approval, which is #83. It does not add retention or
deletion controls, which is #108.

Two pieces already exist and are reused rather than rebuilt: the evidence manifest
pinned on every `ModelRun` (#53), and `AuditEvent`, an append-only table whose
`redacted_metadata` is validated against a closed version-1 contract in both Python and
a database check constraint.

## Sensitivity is derived, not stored

A scope is a function of `Artifact.artifact_class`, held in one versioned map, rather
than a column on `artifacts`. A stored column would let rows predate the rule and fall
back to a silent default, which is the failure mode that matters least in most tables
and most in this one. Deriving it means every artifact has a scope the moment the rule
exists, including rows written before this change.

| Class | Scope | Why |
|---|---|---|
| `original_audio` | `restricted` | Voice biometrics. Never leaves. |
| `export` | `restricted` | The learner's whole record in one object. |
| `transcript` | `redaction_required` | Spontaneous speech carries incidental personal detail. |
| `written_output`, `sql_output`, `case_artifact`, `recall_note` | `releasable` | The work the learner submits precisely so it can be assessed. |
| `analysis` | `releasable` | Model output, not learner input. |

The cost of deriving: an individual artifact cannot be marked more sensitive than its
class without changing the rule. Nothing in the current issue set needs that, and a
per-artifact override is a strictly additive change later.

`case_artifact` is the judgement call. It is the learner's own case write-up, produced
for assessment, so it is releasable like the other written work. It can name a real
employer. If that turns out to matter, it moves to `redaction_required` by editing one
row of the map, and #83's approval flow is what makes that usable.

## The contract refuses a bad submission

`RunRequest` carries the classification, and its validator rejects the combinations
that must never exist: a `restricted` scope at all, a `redaction_required` scope
without both an approved redaction and an explicit release, and any consent basis of
`not_granted`. As with the feedback read gate in #55, the guarantee is a property of
the type, so a caller cannot reach the external model by forgetting a check. Validated
construction is what this covers; `model_construct` skips validators, and the register
boundary already revalidates for exactly that reason.

## The gate runs where release happens

`ModelRunRepository.register` is the only path that sends prepared learner text to an
external model, so it is the single choke point. Before the run row is written it
derives the scope of everything the submission cites and compares it against the
declared scope. A declared scope less restrictive than the derived one refuses the
submission; a reference to a restricted artifact refuses it unconditionally.

The derivation is a pure function over loaded facts, so every rule is unit-testable
without a database, and the repository only applies it.

## The audit records both outcomes

An `AuditEvent` is written in the same transaction, before the run exists, so a refusal
leaves a record as durable as an acceptance. It reuses `AuditMetadataV1` exactly as
`evidence/repository.py` does: closed outcome, closed reason code, bounded counts, and
allowlisted flags. Reasons stay machine-only, so an audit row cannot become a copy of
the content it is protecting.

## Testing

Classification rules and the refusal matrix are unit tests with no database. The
repository wiring, the audit row, and the transaction boundary are integration tests
under the existing `postgres_integration` marker.
