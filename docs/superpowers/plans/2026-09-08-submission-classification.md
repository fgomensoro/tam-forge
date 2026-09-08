# Submission Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse any external model submission that lacks a sensitivity scope, a redaction decision and a consent basis, and record every decision in the immutable audit log.

**Architecture:** Scopes derive from `Artifact.artifact_class` through one versioned map, so no row can predate the rule. `RunRequest` carries the classification and its validator refuses the combinations that must never exist. `ModelRunRepository.register`, the only path to an external model, compares the declared scope against the derived one and writes an `AuditEvent` in the same transaction before the run row exists.

**Tech Stack:** Python 3.12, Pydantic v2 (strict, frozen, `extra="forbid"`), SQLAlchemy 2 async, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-submission-classification-design.md`

## Global Constraints

- Issue #103 (E9-I01). Backend only. Do NOT touch `apps/macos` (Swift will not build on this machine), `speech`, or `recordings`.
- **The run header's key list is enforced by a Postgres trigger.** `tamforge_provenance_insert` in `apps/backend/alembic/versions/20260905_0015_model_provenance.py` allowlists exactly: `format, kind, owner_id, invocation_key, activity_id, attempt, prompt, schema_version, rubric_binding, requested_model, sdk_version, cli_version, job_id, predecessor, manifest, manifest_hash`. Any extra key makes every insert fail. The classification therefore MUST be excluded from the header dict built in `ModelRunRepository.register`, and no migration may edit that frozen function.
- The classification is persisted through `AuditEvent`, which is the immutable record the acceptance criteria require. It does not enter `model_runs.canonical_json`.
- New Pydantic models subclass the existing `Contract` base in `agents/contracts.py` (`extra="forbid"`, `frozen=True`).
- Audit metadata uses `AuditMetadataV1` and its closed enums only. Never invent a reason code, and never place content, scope names beyond the closed vocabulary, or diagnostics in an audit row.
- Unit tests use no database. Integration tests use the existing `postgres_integration` marker and do not run in this environment.
- ruff line length 100; mypy strict over `apps/backend/src`.
- uv is not on PATH: use `/Users/frank/.local/bin/uv`, and ALWAYS pass `--no-sync`.
- Never run `make check`, `make macos-check`, or any `xcodebuild` command.

---

### Task 1: Classification vocabulary and submission contract

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/classification.py`
- Modify: `apps/backend/src/tamforge_backend/agents/contracts.py`
- Modify: `apps/backend/tests/integration/agents/test_agent_runtime_migration.py`
- Test: `apps/backend/tests/unit/agents/test_classification.py`

**Interfaces:**
- Consumes: `Contract` and the existing error classes in `agents/contracts.py`.
- Produces: `SensitivityScope`, `ConsentBasis`, `RedactionDecision`, `SCOPE_BY_ARTIFACT_CLASS`, `scope_of`, `most_restrictive`, and `SubmissionClassification`. Task 2 imports all of them.

- [ ] **Step 1: Write the failing classification tests**

Create `apps/backend/tests/unit/agents/test_classification.py`:

```python
"""Derived sensitivity and the submission combinations that must never exist."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_every_artifact_class_has_a_scope():
    from tamforge_backend.agents.classification import SCOPE_BY_ARTIFACT_CLASS
    from tamforge_backend.learning.models import Artifact

    allowed = next(
        constraint.sqltext.text
        for constraint in Artifact.__table__.constraints
        if getattr(constraint, "name", None) == "artifact_class_allowed"
    )
    classes = set(__import__("re").findall(r"'([a-z_]+)'", allowed))
    assert classes == set(SCOPE_BY_ARTIFACT_CLASS)


@pytest.mark.parametrize(
    "artifact_class,scope",
    [
        ("original_audio", "restricted"),
        ("export", "restricted"),
        ("transcript", "redaction_required"),
        ("written_output", "releasable"),
        ("sql_output", "releasable"),
        ("case_artifact", "releasable"),
        ("recall_note", "releasable"),
        ("analysis", "releasable"),
    ],
)
def test_scope_of_known_classes(artifact_class, scope):
    from tamforge_backend.agents.classification import SensitivityScope, scope_of

    assert scope_of(artifact_class) is SensitivityScope(scope)


def test_an_unknown_class_is_restricted_rather_than_releasable():
    from tamforge_backend.agents.classification import SensitivityScope, scope_of

    assert scope_of("something_new") is SensitivityScope.RESTRICTED


def test_most_restrictive_wins():
    from tamforge_backend.agents.classification import SensitivityScope, most_restrictive

    assert most_restrictive([]) is SensitivityScope.RELEASABLE
    assert (
        most_restrictive([SensitivityScope.RELEASABLE, SensitivityScope.REDACTION_REQUIRED])
        is SensitivityScope.REDACTION_REQUIRED
    )
    assert (
        most_restrictive([SensitivityScope.REDACTION_REQUIRED, SensitivityScope.RESTRICTED])
        is SensitivityScope.RESTRICTED
    )


def releasable(**overrides):
    data = {
        "scope": "releasable",
        "redaction": "not_required",
        "consent": "learner_submission",
    }
    data.update(overrides)
    return data


def test_a_releasable_learner_submission_is_accepted():
    from tamforge_backend.agents.classification import SubmissionClassification

    assert SubmissionClassification.model_validate(releasable()).scope.value == "releasable"


def test_restricted_content_is_never_submittable():
    from tamforge_backend.agents.classification import SubmissionClassification

    for extra in ({}, {"redaction": "approved", "consent": "explicit_release"}):
        with pytest.raises(ValidationError):
            SubmissionClassification.model_validate(releasable(scope="restricted", **extra))


def test_redaction_required_needs_both_approval_and_explicit_release():
    from tamforge_backend.agents.classification import SubmissionClassification

    for redaction, consent in [
        ("not_required", "explicit_release"),
        ("pending", "explicit_release"),
        ("approved", "learner_submission"),
    ]:
        with pytest.raises(ValidationError):
            SubmissionClassification.model_validate(
                releasable(scope="redaction_required", redaction=redaction, consent=consent)
            )
    SubmissionClassification.model_validate(
        releasable(scope="redaction_required", redaction="approved", consent="explicit_release")
    )


def test_withheld_consent_is_never_submittable():
    from tamforge_backend.agents.classification import SubmissionClassification

    with pytest.raises(ValidationError):
        SubmissionClassification.model_validate(releasable(consent="not_granted"))


def test_a_releasable_scope_cannot_claim_a_redaction_it_did_not_need():
    from tamforge_backend.agents.classification import SubmissionClassification

    for redaction in ("pending", "approved"):
        with pytest.raises(ValidationError):
            SubmissionClassification.model_validate(releasable(redaction=redaction))


def test_run_request_requires_a_classification():
    from tamforge_backend.agents.contracts import RunRequest

    with pytest.raises((ValidationError, ValueError)):
        RunRequest.model_validate({"owner_id": 1})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/frank/.local/bin/uv run --no-sync pytest apps/backend/tests/unit/agents/test_classification.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tamforge_backend.agents.classification'`.

- [ ] **Step 3: Implement the classification module**

Create `apps/backend/src/tamforge_backend/agents/classification.py`:

```python
"""Sensitivity derived from artifact class, and the submissions it permits.

A scope is a function of the artifact's class rather than a stored column, so every
artifact carries one the moment this rule exists, including rows written before it.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from .contracts import Contract, InvalidProvenance


class SensitivityScope(StrEnum):
    RELEASABLE = "releasable"
    REDACTION_REQUIRED = "redaction_required"
    RESTRICTED = "restricted"


class ConsentBasis(StrEnum):
    LEARNER_SUBMISSION = "learner_submission"
    EXPLICIT_RELEASE = "explicit_release"
    NOT_GRANTED = "not_granted"


class RedactionDecision(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"


# Ordered least to most restrictive. Position is the comparison.
_ORDER = (
    SensitivityScope.RELEASABLE,
    SensitivityScope.REDACTION_REQUIRED,
    SensitivityScope.RESTRICTED,
)

SCOPE_BY_ARTIFACT_CLASS = {
    "original_audio": SensitivityScope.RESTRICTED,
    "export": SensitivityScope.RESTRICTED,
    "transcript": SensitivityScope.REDACTION_REQUIRED,
    "written_output": SensitivityScope.RELEASABLE,
    "sql_output": SensitivityScope.RELEASABLE,
    "case_artifact": SensitivityScope.RELEASABLE,
    "recall_note": SensitivityScope.RELEASABLE,
    "analysis": SensitivityScope.RELEASABLE,
}


def scope_of(artifact_class: str) -> SensitivityScope:
    """An unrecognised class is restricted. A new class must be classified to be sent."""
    return SCOPE_BY_ARTIFACT_CLASS.get(artifact_class, SensitivityScope.RESTRICTED)


def most_restrictive(scopes: Iterable[SensitivityScope]) -> SensitivityScope:
    return max(scopes, key=_ORDER.index, default=SensitivityScope.RELEASABLE)


class SubmissionClassification(Contract):
    """The combinations that must never reach an external model cannot be constructed."""

    scope: SensitivityScope
    redaction: RedactionDecision
    consent: ConsentBasis

    @model_validator(mode="after")
    def permitted(self) -> Self:
        if self.scope is SensitivityScope.RESTRICTED:
            raise InvalidProvenance()
        if self.consent is ConsentBasis.NOT_GRANTED:
            raise InvalidProvenance()
        if self.scope is SensitivityScope.REDACTION_REQUIRED:
            if (
                self.redaction is not RedactionDecision.APPROVED
                or self.consent is not ConsentBasis.EXPLICIT_RELEASE
            ):
                raise InvalidProvenance()
        elif self.redaction is not RedactionDecision.NOT_REQUIRED:
            raise InvalidProvenance()
        return self
```

Then add the field to `RunRequest` in `agents/contracts.py`, importing `SubmissionClassification` at the bottom of the imports to avoid a cycle (classification imports `Contract` from contracts, so the import must go the other way: declare the field with a forward reference, or move `SubmissionClassification` into `contracts.py` instead). **Prefer moving the three enums and `SubmissionClassification` into `agents/contracts.py`** if the cycle is awkward; keep `SCOPE_BY_ARTIFACT_CLASS`, `scope_of` and `most_restrictive` in `classification.py`. Adjust the test imports if you do, and say so in your report.

`RunRequest` gains:

```python
    classification: SubmissionClassification
```

- [ ] **Step 4: Fix the existing integration test's RunRequest construction**

`apps/backend/tests/integration/agents/test_agent_runtime_migration.py` builds `RunRequest` objects that now lack a required field. Add the classification to each construction site:

```python
        classification=SubmissionClassification(
            scope=SensitivityScope.RELEASABLE,
            redaction=RedactionDecision.NOT_REQUIRED,
            consent=ConsentBasis.LEARNER_SUBMISSION,
        ),
```

Grep for `RunRequest(` in that file and cover every occurrence. Do not change what those tests assert.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
/Users/frank/.local/bin/uv run --no-sync pytest apps/backend/tests/unit/agents -q
/Users/frank/.local/bin/uv run --no-sync ruff check .
/Users/frank/.local/bin/uv run --no-sync mypy apps/backend/src
```

Expected: all clean. The integration tests are deselected here; they are not runnable in this environment.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents apps/backend/tests/unit/agents/test_classification.py apps/backend/tests/integration/agents/test_agent_runtime_migration.py
git commit -m "feat(agents): refuse submissions that lack scope, redaction, and consent"
```

---

### Task 2: Gate and audit at the submission boundary

**Files:**
- Modify: `apps/backend/src/tamforge_backend/agents/model_runs.py`
- Test: `apps/backend/tests/unit/agents/test_classification.py` (extend)
- Test: `apps/backend/tests/integration/agents/test_agent_runtime_migration.py` (extend)

**Interfaces:**
- Consumes: everything Task 1 produced, plus `ActivityArtifactLink` and `Artifact` from `..learning.models`, and `AuditEvent` plus `AuditMetadataV1`, `AuditOutcome`, `AuditReasonCode`, `AuditCountKey`, `AuditFlagKey` from the auth package. Read how `evidence/repository.py` writes an `AuditEvent` around line 815 and follow it exactly.
- Produces: `derive_submission_scope`, and the audit behaviour in `register`.

- [ ] **Step 1: Write the failing derivation tests**

Append to `apps/backend/tests/unit/agents/test_classification.py`:

```python
def test_derived_scope_is_the_most_restrictive_cited_class():
    from tamforge_backend.agents.classification import SensitivityScope, derive_submission_scope

    assert derive_submission_scope([]) is SensitivityScope.RELEASABLE
    assert derive_submission_scope(["written_output"]) is SensitivityScope.RELEASABLE
    assert (
        derive_submission_scope(["written_output", "transcript"])
        is SensitivityScope.REDACTION_REQUIRED
    )
    assert (
        derive_submission_scope(["written_output", "original_audio"])
        is SensitivityScope.RESTRICTED
    )


def test_a_declared_scope_may_not_understate_the_derived_one():
    from tamforge_backend.agents.classification import (
        ConsentBasis,
        RedactionDecision,
        SensitivityScope,
        SubmissionClassification,
        understates,
    )

    declared = SubmissionClassification(
        scope=SensitivityScope.RELEASABLE,
        redaction=RedactionDecision.NOT_REQUIRED,
        consent=ConsentBasis.LEARNER_SUBMISSION,
    )
    assert understates(declared, SensitivityScope.RELEASABLE) is False
    assert understates(declared, SensitivityScope.REDACTION_REQUIRED) is True
    assert understates(declared, SensitivityScope.RESTRICTED) is True
```

- [ ] **Step 2: Run to verify RED**

Run: `/Users/frank/.local/bin/uv run --no-sync pytest apps/backend/tests/unit/agents/test_classification.py -q`
Expected: FAIL with `ImportError: cannot import name 'derive_submission_scope'`.

- [ ] **Step 3: Implement the two helpers**

Append to `agents/classification.py`:

```python
def derive_submission_scope(artifact_classes: Iterable[str]) -> SensitivityScope:
    """The submission is as sensitive as the most sensitive thing it cites."""
    return most_restrictive(scope_of(item) for item in artifact_classes)


def understates(declared: SubmissionClassification, derived: SensitivityScope) -> bool:
    return _ORDER.index(declared.scope) < _ORDER.index(derived)
```

- [ ] **Step 4: Wire the gate and the audit into `register`**

In `ModelRunRepository.register`, inside the existing `async with self.session.begin():` block and **before** `self.session.add(run)`:

1. Load the artifact classes linked to this activity and attempt:

```python
                linked = (
                    await self.session.scalars(
                        select(Artifact.artifact_class)
                        .join(
                            ActivityArtifactLink,
                            (ActivityArtifactLink.owner_id == Artifact.owner_id)
                            & (ActivityArtifactLink.artifact_id == Artifact.id),
                        )
                        .where(
                            ActivityArtifactLink.owner_id == request.owner_id,
                            ActivityArtifactLink.activity_instance_id == request.activity_id,
                            ActivityArtifactLink.attempt_id == request.attempt.id,
                        )
                    )
                ).all()
```

2. Compare and refuse. Write the refusal audit before raising, so a refusal is as durable as an acceptance:

```python
                derived = derive_submission_scope(linked)
                if understates(request.classification, derived):
                    self._audit(request, accepted=False)
                    await self.session.flush()
                    raise InvalidProvenance()
```

3. On the accepted path, write the acceptance audit next to the run insert.

Add the private writer, following `evidence/repository.py`:

```python
    def _audit(self, request: RunRequest, *, accepted: bool) -> None:
        self.session.add(
            AuditEvent(
                owner_id=request.owner_id,
                actor_kind="system",
                actor_subject_hash=sha256(
                    f"model-submission:{request.owner_id}".encode()
                ).digest(),
                action="model_run.submitted" if accepted else "model_run.refused",
                aggregate_type="activity",
                aggregate_id=str(request.activity_id),
                request_correlation_hash=None,
                idempotency_correlation_hash=sha256(request.invocation_key.encode()).digest(),
                redacted_metadata=AuditMetadataV1(
                    outcome=AuditOutcome.SUCCEEDED if accepted else AuditOutcome.DENIED,
                    reason_code=(
                        AuditReasonCode.NONE if accepted else AuditReasonCode.UNAUTHORIZED
                    ),
                    counts={AuditCountKey.ATTEMPTED: 1},
                    flags={
                        AuditFlagKey.AUTHORIZED: accepted,
                        AuditFlagKey.REDACTED: True,
                    },
                ).to_payload(),
            )
        )
```

**Critical:** the header dict built a few lines below uses `request.model_dump(mode="json", exclude={"context"})`. Change it to `exclude={"context", "classification"}`. The Postgres trigger `tamforge_provenance_insert` allowlists the header's keys, and an extra `classification` key makes every insert fail. Do not edit that trigger.

Note that `register` wraps its body in `except (SQLAlchemyError, ValidationError): raise InvalidProvenance()`. Make sure the refusal path's `InvalidProvenance` is not swallowed or re-wrapped into something less precise, and that the audit row is flushed inside the transaction that the raise then rolls back — if the rollback discards it, write the refusal audit in its own session transaction instead and say so in your report.

- [ ] **Step 5: Extend the integration test**

In `apps/backend/tests/integration/agents/test_agent_runtime_migration.py`, add one test asserting that a submission whose declared scope understates the linked artifacts is refused, and that an `AuditEvent` row with `action="model_run.refused"` exists afterwards. Follow the file's existing fixture and session style exactly. These tests do not run in this environment; correctness is by inspection and by CI.

- [ ] **Step 6: Run the full local gate**

```bash
/Users/frank/.local/bin/uv run --no-sync ruff check .
/Users/frank/.local/bin/uv run --no-sync mypy apps/backend/src packages/protocol/src
/Users/frank/.local/bin/uv run --no-sync pytest -m "not integration" -q
/Users/frank/.local/bin/uv run --no-sync python scripts/ci/check_openapi.py
/Users/frank/.local/bin/uv run --no-sync python scripts/ci/check_repository_policy.py
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents apps/backend/tests
git commit -m "feat(agents): gate and audit every external model submission"
```

---

## Execution order

Task 2 consumes Task 1's vocabulary and contract. They run in series. Do not dispatch them in parallel: implementers in this worktree share one `.venv` and one git index.
