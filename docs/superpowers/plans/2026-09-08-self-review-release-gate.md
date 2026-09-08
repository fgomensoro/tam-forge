# Mandatory Self-Review Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Withhold Reviewer output until the learner's self-review is committed and every cited piece of evidence is available and valid.

**Architecture:** The read contract `FeedbackRead` makes a response carrying analysis outside the `ready` status unconstructible, so withholding is a property of the type rather than a branch each caller must remember. A pure gate function decides release from already-loaded state. Released analyses land in an append-only provenance table that reuses the existing model-run `RunChild` base. One authenticated read endpoint exposes the result.

**Tech Stack:** Python 3.12, Pydantic v2 (strict, frozen, `extra="forbid"`), SQLAlchemy 2 async, Alembic, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-self-review-release-gate-design.md`

## Global Constraints

- Issue #55 (E5-I03). Backend and protocol only. Do not touch `apps/macos` Swift sources, `apps/backend/src/tamforge_backend/speech`, `recordings`, or `scripts/ci`. The one generated exception is `apps/macos/TAMForge/openapi.yaml`, regenerated in Task 4.
- Out of scope, owned by other issues: verdict, the two-strengths/two-corrections rule, rendered Markdown and Attempt B instructions (#57, #58); the 15/60-minute processing clock and SLOs (#63); the job runner that invokes the Reviewer (#67).
- Every new Pydantic model subclasses the existing `_StrictModel` in `packages/protocol/src/tamforge_protocol/agents.py` (`extra="forbid"`, `frozen=True`) or the equivalent `Contract` base in the backend.
- Error strings never carry submitted content, reference detail, or database diagnostics. Withholding reasons are the closed slug vocabulary defined in Task 1 and nothing else.
- `ruff` line length is 100. `mypy` runs strict over `apps/backend/src` and `packages/protocol/src`.
- Unit tests use no database. Run with `/Users/frank/.local/bin/uv run pytest`.
- Do not run `make macos-check` or any `xcodebuild` command.

---

### Task 1: Feedback read contract

**Files:**
- Modify: `packages/protocol/src/tamforge_protocol/agents.py`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Test: `packages/protocol/tests/test_agents.py`

**Interfaces:**
- Consumes: existing `_StrictModel`, `PositiveId`, `Hash`, `EnglishAnalysisV1`, `TAMAnalysisV1` in the same module.
- Produces: `WithheldReason`, `PinnedRecord`, `AnalysisVersions`, `FeedbackRead`. Task 2 imports `WithheldReason`. Task 4 imports `FeedbackRead`, `AnalysisVersions`, `PinnedRecord`.

Do not give `FeedbackRead` a `json_schema_extra` `$id`. The snapshot test `test_versioned_json_schema_snapshot` only covers models with one, and this is an HTTP read contract, not a model output schema.

- [ ] **Step 1: Write the failing contract tests**

Append to `packages/protocol/tests/test_agents.py`:

```python
def feedback(**overrides):
    data = {
        "status": "processing",
        "activity_id": 7,
        "attempt_id": 9,
        "versions": None,
        "english": None,
        "tam": None,
        "withheld_reason": None,
    }
    data.update(overrides)
    return data


def versions():
    return {
        "model_run": {"id": 1, "content_hash": "a" * 64},
        "prompt": {"id": 2, "content_hash": "b" * 64},
        "output_schema": {"id": 3, "content_hash": "c" * 64},
        "rubric_binding": {"id": 4, "content_hash": "d" * 64},
    }


def test_ready_feedback_requires_both_analyses_and_versions():
    from tamforge_protocol.agents import FeedbackRead

    for missing in ("english", "tam", "versions"):
        data = feedback(
            status="ready",
            versions=versions(),
            english=payload(),
            tam=payload("tam"),
        )
        data[missing] = None
        with pytest.raises(ValidationError):
            FeedbackRead.model_validate(data)


def test_ready_feedback_accepts_the_matching_release():
    from tamforge_protocol.agents import FeedbackRead

    read = FeedbackRead.model_validate(
        feedback(status="ready", versions=versions(), english=payload(), tam=payload("tam"))
    )
    assert read.withheld_reason is None
    assert read.english is not None and read.tam is not None


@pytest.mark.parametrize("status", ["processing", "needs_attention"])
@pytest.mark.parametrize("carried", ["english", "tam"])
def test_withheld_feedback_cannot_carry_analysis(status, carried):
    from tamforge_protocol.agents import FeedbackRead

    data = feedback(status=status, withheld_reason="self_review_pending" if status == "needs_attention" else None)
    data[carried] = payload() if carried == "english" else payload("tam")
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(data)


def test_reason_presence_follows_the_status():
    from tamforge_protocol.agents import FeedbackRead

    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(feedback(status="needs_attention"))
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(feedback(status="processing", withheld_reason="self_review_pending"))
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(
            feedback(
                status="ready",
                versions=versions(),
                english=payload(),
                tam=payload("tam"),
                withheld_reason="self_review_pending",
            )
        )
    assert FeedbackRead.model_validate(feedback(status="needs_attention", withheld_reason="evidence_unavailable")).status == "needs_attention"


def test_ready_feedback_rejects_analysis_from_another_attempt():
    from tamforge_protocol.agents import FeedbackRead

    other = payload("tam")
    other["attempt_id"] = 99
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(
            feedback(status="ready", versions=versions(), english=payload(), tam=other)
        )


def test_withheld_reason_vocabulary_is_closed():
    from tamforge_protocol.agents import FeedbackRead

    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(feedback(status="needs_attention", withheld_reason="because"))
```

The existing `payload()` helper in this file builds a valid analysis dict; read it before writing these tests and pass whatever `activity_id`/`attempt_id` it produces through `feedback()` so the identity assertions line up. If `payload()` hardcodes ids that differ from 7 and 9, use its ids in `feedback()` rather than editing the helper.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/frank/.local/bin/uv run pytest packages/protocol/tests/test_agents.py -q`
Expected: FAIL with `ImportError: cannot import name 'FeedbackRead'`.

- [ ] **Step 3: Implement the contract**

Append to `packages/protocol/src/tamforge_protocol/agents.py`:

```python
WithheldReason = Literal[
    "self_review_pending",
    "evidence_unavailable",
    "evidence_out_of_manifest",
    "version_mismatch",
    "forbidden_source",
]


class PinnedRecord(_StrictModel):
    """One immutable provenance row identified by id and content hash."""

    id: PositiveId
    content_hash: Hash


class AnalysisVersions(_StrictModel):
    model_run: PinnedRecord
    prompt: PinnedRecord
    output_schema: PinnedRecord
    rubric_binding: PinnedRecord


class FeedbackRead(_StrictModel):
    """Analysis is unconstructible outside `ready`, so withholding cannot be bypassed."""

    status: Literal["processing", "needs_attention", "ready"]
    activity_id: PositiveId
    attempt_id: PositiveId
    versions: AnalysisVersions | None = None
    english: EnglishAnalysisV1 | None = None
    tam: TAMAnalysisV1 | None = None
    withheld_reason: WithheldReason | None = None

    @model_validator(mode="after")
    def release_gate(self) -> Self:
        if self.status != "ready":
            if self.english is not None or self.tam is not None or self.versions is not None:
                raise ValueError("withheld feedback must not carry analysis or versions")
            if (self.status == "needs_attention") != (self.withheld_reason is not None):
                raise ValueError("only needs_attention carries a withholding reason")
            return self
        if self.english is None or self.tam is None or self.versions is None:
            raise ValueError("ready feedback requires both analyses and their versions")
        if self.withheld_reason is not None:
            raise ValueError("ready feedback cannot carry a withholding reason")
        for analysis in (self.english, self.tam):
            if (analysis.activity_id, analysis.attempt_id) != (self.activity_id, self.attempt_id):
                raise ValueError("released analysis must identify the read attempt")
        return self
```

Then extend `packages/protocol/src/tamforge_protocol/__init__.py`:

```python
"""Shared protocol package for TAM Forge services."""

from .agents import (
    AnalysisVersions,
    EnglishAnalysisV1,
    FeedbackRead,
    PinnedRecord,
    TAMAnalysisV1,
    WithheldReason,
)

__all__ = [
    "AnalysisVersions",
    "EnglishAnalysisV1",
    "FeedbackRead",
    "PinnedRecord",
    "TAMAnalysisV1",
    "WithheldReason",
]
__version__ = "0.1.0"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/Users/frank/.local/bin/uv run pytest packages/protocol/tests/ -q`
Expected: PASS, including the pre-existing analysis tests.

- [ ] **Step 5: Lint and typecheck**

Run: `/Users/frank/.local/bin/uv run ruff check packages/protocol && /Users/frank/.local/bin/uv run mypy packages/protocol/src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/agents.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_agents.py
git commit -m "feat(protocol): make withheld feedback unable to carry analysis"
```

---

### Task 2: Release gate

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/roles/__init__.py`
- Create: `apps/backend/src/tamforge_backend/agents/roles/reviewer.py`
- Test: `apps/backend/tests/unit/agents/roles/test_reviewer.py`

**Interfaces:**
- Consumes: `WithheldReason`, `EnglishAnalysisV1`, `TAMAnalysisV1`, `EvidenceReference`, `AttemptTextReference`, `ScoredDimension` from `tamforge_protocol.agents`.
- Produces: `ArtifactFact`, `ReleaseInput`, `RELEASABLE_ACTIVITY_STATES`, and `evaluate_release(*, english, tam, state) -> WithheldReason | None`. Task 4 calls `evaluate_release` and builds `ReleaseInput`.

The gate performs no I/O. The caller loads state; the gate only decides. This is what keeps every rule unit-testable without Postgres.

- [ ] **Step 1: Write the failing gate tests**

Create `apps/backend/tests/unit/agents/roles/test_reviewer.py`. Reuse the analysis fixtures from `packages/protocol/tests/test_agents.py` by writing local builders rather than importing test modules:

```python
"""Pure release decisions for prepared Reviewer output."""

from __future__ import annotations

import pytest
from tamforge_protocol.agents import (
    ArtifactTextReference,
    AttemptTextReference,
    EnglishAnalysisV1,
    TAMAnalysisV1,
)

ATTEMPT_HASH = "a" * 64
ARTIFACT_HASH = "b" * 64
ENGLISH_UNAVAILABLE = {
    "fluency": {
        "availability": "unavailable",
        "score": None,
        "reason_code": "speech_pipeline_unavailable",
        "explanation": "Speech pipeline is not installed.",
    },
    "pronunciation_intelligibility": {
        "availability": "unavailable",
        "score": None,
        "reason_code": "pronunciation_not_measured",
        "explanation": "Calibrated diagnostic did not run.",
    },
    "listening": {
        "availability": "not_applicable",
        "score": None,
        "reason_code": "written_source",
        "explanation": "Written submission has no listening evidence.",
    },
}


def attempt_reference(attempt_id=9, commitment=ATTEMPT_HASH):
    return AttemptTextReference(
        kind="attempt_text",
        attempt_id=attempt_id,
        commitment_sha256=commitment,
        json_pointer="/output/draft_markdown",
        start_codepoint=0,
        end_codepoint=4,
    )


def artifact_reference(artifact_id=3, immutable_version=1, sha256=ARTIFACT_HASH):
    return ArtifactTextReference(
        kind="artifact_text",
        artifact_id=artifact_id,
        immutable_version=immutable_version,
        sha256=sha256,
        text_kind="written",
        start_codepoint=0,
        end_codepoint=4,
    )


def scored(reference):
    return {
        "availability": "scored",
        "score": 3,
        "rationale": "Supported by prepared text.",
        "observations": [
            {
                "statement": "The answer named the customer impact.",
                "attribution": "observed_content",
                "availability": "available",
                "confidence": "0.8",
                "references": [reference.model_dump(mode="json")],
            }
        ],
    }


def unscored():
    return {
        "availability": "not_applicable",
        "score": None,
        "reason_code": "not_exercised",
        "explanation": "This dimension was not exercised.",
    }


def english(reference=None):
    reference = attempt_reference() if reference is None else reference
    dimensions = {
        "communication_effectiveness": scored(reference),
        "accuracy": unscored(),
        "vocabulary": unscored(),
        **ENGLISH_UNAVAILABLE,
    }
    return EnglishAnalysisV1.model_validate(
        {
            "analysis_kind": "english_analysis",
            "schema_version": "english-analysis-v1",
            "source_mode": "written",
            "activity_id": 7,
            "attempt_id": 9,
            "config_version_key": "seed-v1",
            "rubric_slug": "tam_case",
            "rubric_version": "seed-v1",
            "dimensions": dimensions,
        }
    )


def tam(reference=None, rubric_version="seed-v1"):
    reference = attempt_reference() if reference is None else reference
    keys = (
        "correctness",
        "structure",
        "relevance",
        "customer_judgment",
        "technical_reasoning",
        "business_framing",
        "trade_offs",
        "audience_adaptation",
        "decision_quality",
    )
    dimensions = {key: unscored() for key in keys}
    dimensions["correctness"] = scored(reference)
    return TAMAnalysisV1.model_validate(
        {
            "analysis_kind": "tam_analysis",
            "schema_version": "tam-analysis-v1",
            "activity_id": 7,
            "attempt_id": 9,
            "config_version_key": "seed-v1",
            "rubric_slug": "tam_case",
            "rubric_version": rubric_version,
            "dimensions": dimensions,
        }
    )


def state(**overrides):
    from tamforge_backend.agents.roles.reviewer import ArtifactFact, ReleaseInput

    defaults = {
        "activity_state": "ai_processing",
        "self_review_committed": True,
        "attempt_commitment_sha256": ATTEMPT_HASH,
        "manifest": (attempt_reference(),),
        "rubric_slug": "tam_case",
        "rubric_version": "seed-v1",
        "linked_artifacts": {
            3: ArtifactFact(immutable_version=1, sha256=ARTIFACT_HASH, artifact_class="written_output")
        },
    }
    defaults.update(overrides)
    return ReleaseInput(**defaults)


def test_release_passes_when_self_review_and_evidence_hold():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert evaluate_release(english=english(), tam=tam(), state=state()) is None


def test_uncommitted_self_review_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(self_review_committed=False))
        == "self_review_pending"
    )


@pytest.mark.parametrize("activity_state", ["active", "output_committed", "paused", "incomplete"])
def test_activity_before_self_review_completion_withholds(activity_state):
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(activity_state=activity_state))
        == "self_review_pending"
    )


def test_rubric_version_disagreement_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(rubric_version="seed-v2"), state=state())
        == "version_mismatch"
    )


def test_reference_outside_the_run_manifest_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(manifest=()))
        == "evidence_out_of_manifest"
    )


def test_attempt_reference_with_a_stale_commitment_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    stale = attempt_reference(commitment="c" * 64)
    assert (
        evaluate_release(
            english=english(stale), tam=tam(stale), state=state(manifest=(stale,))
        )
        == "evidence_unavailable"
    )


def test_artifact_reference_with_a_changed_hash_withholds():
    from tamforge_backend.agents.roles.reviewer import ArtifactFact, evaluate_release

    reference = artifact_reference()
    withheld = evaluate_release(
        english=english(reference),
        tam=tam(reference),
        state=state(
            manifest=(reference,),
            linked_artifacts={
                3: ArtifactFact(
                    immutable_version=1, sha256="e" * 64, artifact_class="written_output"
                )
            },
        ),
    )
    assert withheld == "evidence_unavailable"


def test_unlinked_artifact_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    reference = artifact_reference()
    assert (
        evaluate_release(
            english=english(reference),
            tam=tam(reference),
            state=state(manifest=(reference,), linked_artifacts={}),
        )
        == "evidence_unavailable"
    )


def test_original_audio_evidence_withholds():
    from tamforge_backend.agents.roles.reviewer import ArtifactFact, evaluate_release

    reference = artifact_reference()
    withheld = evaluate_release(
        english=english(reference),
        tam=tam(reference),
        state=state(
            manifest=(reference,),
            linked_artifacts={
                3: ArtifactFact(
                    immutable_version=1, sha256=ARTIFACT_HASH, artifact_class="original_audio"
                )
            },
        ),
    )
    assert withheld == "forbidden_source"
```

Do not add an `__init__.py` to the test directory. The existing unit test packages have none; `pythonpath = ["."]` and rootdir-relative collection already handle it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/frank/.local/bin/uv run pytest apps/backend/tests/unit/agents/roles/test_reviewer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tamforge_backend.agents.roles'`.

- [ ] **Step 3: Implement the gate**

Create `apps/backend/src/tamforge_backend/agents/roles/__init__.py` as an empty file (match the existing empty `agents/__init__.py`).

Create `apps/backend/src/tamforge_backend/agents/roles/reviewer.py`:

```python
"""Pure publication decisions. Loading state is the caller's job, deciding is ours."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tamforge_protocol.agents import (
    AttemptTextReference,
    EnglishAnalysisV1,
    EvidenceReference,
    ScoredDimension,
    TAMAnalysisV1,
    WithheldReason,
    _Analysis,
)

# Publication is possible only once the learner's own reflection is on record.
RELEASABLE_ACTIVITY_STATES = frozenset(
    {"self_review_complete", "ai_processing", "feedback_ready", "correction_due"}
)
FORBIDDEN_ARTIFACT_CLASSES = frozenset({"original_audio"})


@dataclass(frozen=True, slots=True)
class ArtifactFact:
    """The stored identity of one artifact already linked to the analysed attempt."""

    immutable_version: int
    sha256: str
    artifact_class: str


@dataclass(frozen=True, slots=True)
class ReleaseInput:
    activity_state: str
    self_review_committed: bool
    attempt_commitment_sha256: str
    manifest: tuple[EvidenceReference, ...]
    rubric_slug: str
    rubric_version: str
    linked_artifacts: Mapping[int, ArtifactFact]


def _cited_references(analysis: _Analysis) -> tuple[EvidenceReference, ...]:
    references: list[EvidenceReference] = []
    for dimension in analysis.dimensions.values():
        if isinstance(dimension, ScoredDimension):
            for observation in dimension.observations:
                references.extend(observation.references)
    return tuple(references)


def _reference_withholding(
    reference: EvidenceReference, analysis: _Analysis, state: ReleaseInput
) -> WithheldReason | None:
    if isinstance(reference, AttemptTextReference):
        if (
            reference.attempt_id != analysis.attempt_id
            or reference.commitment_sha256 != state.attempt_commitment_sha256
        ):
            return "evidence_unavailable"
        return None
    fact = state.linked_artifacts.get(reference.artifact_id)
    if (
        fact is None
        or fact.immutable_version != reference.immutable_version
        or fact.sha256 != reference.sha256
    ):
        return "evidence_unavailable"
    if fact.artifact_class in FORBIDDEN_ARTIFACT_CLASSES:
        return "forbidden_source"
    return None


def evaluate_release(
    *, english: EnglishAnalysisV1, tam: TAMAnalysisV1, state: ReleaseInput
) -> WithheldReason | None:
    """Return None to release, or the closed reason the output stays withheld."""
    if not state.self_review_committed or state.activity_state not in RELEASABLE_ACTIVITY_STATES:
        return "self_review_pending"
    manifest = frozenset(state.manifest)
    for analysis in (english, tam):
        if (analysis.rubric_slug, analysis.rubric_version) != (
            state.rubric_slug,
            state.rubric_version,
        ):
            return "version_mismatch"
        for reference in _cited_references(analysis):
            if reference not in manifest:
                return "evidence_out_of_manifest"
            withheld = _reference_withholding(reference, analysis, state)
            if withheld is not None:
                return withheld
    return None
```

If importing the private `_Analysis` from the protocol trips `ruff` or reads badly, widen the two helper signatures to `EnglishAnalysisV1 | TAMAnalysisV1` instead of adding a public alias to the protocol package. Do not rename `_Analysis`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/Users/frank/.local/bin/uv run pytest apps/backend/tests/unit/agents/ -q`
Expected: PASS, including the pre-existing provenance tests.

- [ ] **Step 5: Lint and typecheck**

Run: `/Users/frank/.local/bin/uv run ruff check apps/backend && /Users/frank/.local/bin/uv run mypy apps/backend/src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/roles apps/backend/tests/unit/agents/roles
git commit -m "feat(agents): decide Reviewer release from self-review and cited evidence"
```

---

### Task 3: Publication storage

**Files:**
- Modify: `apps/backend/src/tamforge_backend/agents/models.py`
- Create: `apps/backend/alembic/versions/20260908_0016_analysis_publications.py`
- Test: `apps/backend/tests/unit/agents/test_analysis_publication_model.py`

**Interfaces:**
- Consumes: the existing `RunChild` base and `_child_checks` helper in `agents/models.py`.
- Produces: `AnalysisPublication`, added to `RECORD_TYPES`. Task 4 reads and writes this table.

This table carries the `trg_*_immutable` trigger only. It deliberately does not carry `tamforge_provenance_insert`, whose body validates the run/context/event chain by table name and has no branch for this table. Content validity is the gate's job (Task 2); byte identity is enforced by the inherited `hash_matches` and `canonical_bytes` constraints.

- [ ] **Step 1: Write the failing model test**

Create `apps/backend/tests/unit/agents/test_analysis_publication_model.py`:

```python
"""Table shape and immutability wiring for published analyses."""

from __future__ import annotations

import pytest


def test_publication_is_registered_as_immutable_provenance():
    from tamforge_backend.agents.models import RECORD_TYPES, AnalysisPublication

    assert AnalysisPublication in RECORD_TYPES


def test_publication_is_one_row_per_run_and_kind():
    from tamforge_backend.agents.models import AnalysisPublication

    table = AnalysisPublication.__table__
    assert table.name == "analysis_publications"
    unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("run_id", "analysis_kind") in unique


def test_publication_rejects_mutation():
    from tamforge_backend.agents.contracts import ImmutableVersionConflict
    from tamforge_backend.agents.models import reject_mutation

    with pytest.raises(ImmutableVersionConflict):
        reject_mutation()


def test_migration_creates_the_table_and_its_immutability_trigger():
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    source = (
        root / "apps/backend/alembic/versions/20260908_0016_analysis_publications.py"
    ).read_text()
    assert "CREATE TABLE analysis_publications" in source
    assert "trg_analysis_publications_immutable" in source
    assert 'down_revision = "20260905_0015_model_provenance"' in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/frank/.local/bin/uv run pytest apps/backend/tests/unit/agents/test_analysis_publication_model.py -q`
Expected: FAIL with `ImportError: cannot import name 'AnalysisPublication'`.

- [ ] **Step 3: Add the model**

In `apps/backend/src/tamforge_backend/agents/models.py`, after `class AgentToolCall(RunChild)`:

```python
class AnalysisPublication(RunChild):
    """One released analysis. Rows appear only after the release gate passes."""

    __tablename__ = "analysis_publications"
    __table_args__ = _child_checks("analysis_publications", limit=1048576) + (
        UniqueConstraint(
            "run_id", "analysis_kind", name="uq_analysis_publications_run_kind"
        ),
        CheckConstraint(
            "analysis_kind IN ('english_analysis', 'tam_analysis')",
            name="analysis_kind_allowed",
        ),
    )
    analysis_kind: Mapped[str] = mapped_column(
        Text,
        Computed("canonical_json::jsonb->'analysis'->>'analysis_kind'", persisted=True),
        nullable=False,
    )
```

Then add `AnalysisPublication` to the `RECORD_TYPES` tuple so it inherits the update/delete listeners.

- [ ] **Step 4: Write the migration**

Create `apps/backend/alembic/versions/20260908_0016_analysis_publications.py`:

```python
"""Append-only storage for analyses that passed the self-review release gate."""

from alembic import op

revision = "20260908_0016_analysis_publications"
down_revision = "20260905_0015_model_provenance"
branch_labels = None
depends_on = None

TABLE = r"""
CREATE TABLE analysis_publications (
    analysis_kind TEXT GENERATED ALWAYS AS (canonical_json::jsonb->'analysis'->>'analysis_kind')
        STORED NOT NULL,
    run_id BIGINT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_analysis_publications PRIMARY KEY (id),
    CONSTRAINT uq_analysis_publications_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_analysis_publications_id_positive CHECK (id > 0),
    CONSTRAINT ck_analysis_publications_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_analysis_publications_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_analysis_publications_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 1048576),
    CONSTRAINT ck_analysis_publications_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_analysis_publications_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT ck_analysis_publications_analysis_kind_allowed CHECK (analysis_kind IN
        ('english_analysis', 'tam_analysis')),
    CONSTRAINT uq_analysis_publications_run_kind UNIQUE (run_id, analysis_kind),
    CONSTRAINT fk_analysis_publications_owner_id_model_runs FOREIGN KEY(owner_id, run_id)
        REFERENCES model_runs (owner_id, id),
    CONSTRAINT fk_analysis_publications_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)
"""


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(
        "CREATE TRIGGER trg_analysis_publications_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON public.analysis_publications "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.tamforge_provenance_immutable()"
    )


def downgrade() -> None:
    op.drop_table("analysis_publications")
```

Before writing this file, confirm `20260905_0015_model_provenance` is still the migration head: run `ls apps/backend/alembic/versions/` and check that no revision has it as `down_revision`. If one does, chain onto that head instead and say so in your report.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/Users/frank/.local/bin/uv run pytest apps/backend/tests/unit/agents/ -q`
Expected: PASS.

- [ ] **Step 6: Lint and typecheck**

Run: `/Users/frank/.local/bin/uv run ruff check apps/backend && /Users/frank/.local/bin/uv run mypy apps/backend/src`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/models.py apps/backend/alembic/versions/20260908_0016_analysis_publications.py apps/backend/tests/unit/agents/test_analysis_publication_model.py
git commit -m "feat(agents): store released analyses as append-only provenance"
```

---

### Task 4: Feedback read endpoint

**Files:**
- Create: `apps/backend/src/tamforge_backend/analysis/__init__.py`
- Create: `apps/backend/src/tamforge_backend/analysis/repository.py`
- Create: `apps/backend/src/tamforge_backend/analysis/routes.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Modify: `apps/macos/TAMForge/openapi.yaml` (regenerated, never hand-edited)
- Test: `apps/backend/tests/unit/analysis/test_feedback_routes.py`

**Interfaces:**
- Consumes: `FeedbackRead`, `AnalysisVersions`, `PinnedRecord` (Task 1), `AnalysisPublication` (Task 3), plus the existing `get_authenticated_owner`, `get_db_session`, and `ProblemResponse`. It does **not** call Task 2's `evaluate_release`: this slice has no producer, and the gate runs at publication time, which #67 owns.
- Produces: `FeedbackRepository`, `get_feedback_repository`, `router`, `feedback_exception_handler`, and the errors `FeedbackNotFound` / `FeedbackError`.

Follow `evidence/routes.py` exactly for the authenticated read shape, the `no-store` headers, and the problem-response handler. The unit test stubs the repository through `dependency_overrides`, so no database is involved.

- [ ] **Step 1: Write the failing route tests**

Create `apps/backend/tests/unit/analysis/test_feedback_routes.py`:

```python
"""HTTP contract for the gated feedback read."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.main import create_app
from tamforge_protocol.agents import FeedbackRead

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=APPROVED_GITHUB_USER_ID,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubFeedbackRepository:
    def __init__(self, read: FeedbackRead | None = None) -> None:
        self.read = read or FeedbackRead(status="processing", activity_id=7, attempt_id=9)
        self.calls: list[tuple[int, int, int]] = []

    async def feedback(self, *, owner_id: int, activity_id: int, attempt_id: int) -> FeedbackRead:
        self.calls.append((owner_id, activity_id, attempt_id))
        return self.read


def client(repository):
    from tamforge_backend.analysis.routes import get_feedback_repository

    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_feedback_repository] = lambda: repository
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app)


def test_processing_feedback_carries_no_analysis():
    repository = StubFeedbackRepository()
    response = client(repository).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["english"] is None and body["tam"] is None
    assert repository.calls == [(1, 7, 9)]


def test_withheld_feedback_reports_only_a_closed_reason():
    repository = StubFeedbackRepository(
        FeedbackRead(
            status="needs_attention",
            activity_id=7,
            attempt_id=9,
            withheld_reason="self_review_pending",
        )
    )
    body = client(repository).get("/api/v1/activities/7/attempts/9/feedback").json()
    assert body["withheld_reason"] == "self_review_pending"
    assert body["english"] is None and body["tam"] is None


def test_feedback_read_is_never_stored_by_a_cache():
    response = client(StubFeedbackRepository()).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.headers["Cache-Control"] == "no-store"


def test_missing_attempt_is_a_problem_document():
    from tamforge_backend.analysis.repository import FeedbackNotFound

    class Missing(StubFeedbackRepository):
        async def feedback(self, *, owner_id, activity_id, attempt_id):
            raise FeedbackNotFound()

    response = client(Missing()).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "feedback_not_found"


def test_unauthenticated_read_is_rejected():
    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    assert TestClient(app).get("/api/v1/activities/7/attempts/9/feedback").status_code in (401, 403)
```

`APPROVED_GITHUB_USER_ID` is `102269369` and lives in `tamforge_backend.config`. `apps/backend/tests/unit/evidence/test_evidence_routes.py` is the reference for the owner fixture and the `dependency_overrides` shape.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/Users/frank/.local/bin/uv run pytest apps/backend/tests/unit/analysis/ -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tamforge_backend.analysis'`.

- [ ] **Step 3: Implement the repository**

Create `apps/backend/src/tamforge_backend/analysis/__init__.py` as an empty file.

Create `apps/backend/src/tamforge_backend/analysis/repository.py`. It loads the newest model run for the attempt, its published analyses, and builds the `FeedbackRead`:

```python
"""Owner-scoped reads of gated feedback. Publication authority lives in the gate."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_protocol.agents import (
    AnalysisVersions,
    EnglishAnalysisV1,
    FeedbackRead,
    PinnedRecord,
    TAMAnalysisV1,
)

from ..agents.models import AnalysisPublication, ModelRun
from ..agents.prompt_registry import verified
from ..learning.models import ActivityInstance, Attempt


class FeedbackError(Exception):
    """Base safe feedback read error."""


class FeedbackNotFound(FeedbackError):
    """The owner has no such activity and attempt."""


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def feedback(
        self, *, owner_id: int, activity_id: int, attempt_id: int
    ) -> FeedbackRead:
        attempt = await self.session.scalar(
            select(Attempt.id)
            .join(
                ActivityInstance,
                (ActivityInstance.owner_id == Attempt.owner_id)
                & (ActivityInstance.id == Attempt.activity_instance_id),
            )
            .where(
                Attempt.owner_id == owner_id,
                Attempt.id == attempt_id,
                Attempt.activity_instance_id == activity_id,
            )
        )
        if attempt is None:
            raise FeedbackNotFound()
        run = await self.session.scalar(
            select(ModelRun)
            .where(
                ModelRun.owner_id == owner_id,
                ModelRun.activity_id == activity_id,
                ModelRun.attempt_id == attempt_id,
            )
            .order_by(ModelRun.id.desc())
            .limit(1)
        )
        if run is None:
            return FeedbackRead(
                status="processing", activity_id=activity_id, attempt_id=attempt_id
            )
        published = {
            row.analysis_kind: json.loads(verified(row).canonical_json)["analysis"]
            for row in (
                await self.session.scalars(
                    select(AnalysisPublication).where(
                        AnalysisPublication.owner_id == owner_id,
                        AnalysisPublication.run_id == run.id,
                    )
                )
            ).all()
        }
        if {"english_analysis", "tam_analysis"} - published.keys():
            return FeedbackRead(
                status="processing", activity_id=activity_id, attempt_id=attempt_id
            )
        header = json.loads(verified(run).canonical_json)
        return FeedbackRead(
            status="ready",
            activity_id=activity_id,
            attempt_id=attempt_id,
            versions=AnalysisVersions(
                model_run=PinnedRecord(id=run.id, content_hash=run.content_hash.hex()),
                prompt=PinnedRecord(**header["prompt"]),
                output_schema=PinnedRecord(**header["schema_version"]),
                rubric_binding=PinnedRecord(**header["rubric_binding"]),
            ),
            english=EnglishAnalysisV1.model_validate(published["english_analysis"]),
            tam=TAMAnalysisV1.model_validate(published["tam_analysis"]),
        )
```

The run header stores its pins as `{"id": ..., "content_hash": ...}` (see `PinnedVersion` in `agents/contracts.py`). Confirm the exact key names by reading a registered header in `agents/model_runs.py` before relying on `PinnedRecord(**header[...])`; if they differ, map the fields explicitly rather than renaming anything in the provenance payload.

This slice has no producer writing publications or withholding records, so `needs_attention` is reachable only through the contract and the gate, not yet through this repository. Do not invent a producer here; #67 owns it.

- [ ] **Step 4: Implement the route**

Create `apps/backend/src/tamforge_backend/analysis/routes.py`:

```python
"""Authenticated read-only gated feedback endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_protocol.agents import FeedbackRead

from ..auth.dependencies import get_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .repository import FeedbackNotFound, FeedbackRepository

router = APIRouter(prefix="/api/v1", tags=["analysis"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_feedback_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackRepository:
    return FeedbackRepository(session)


@router.get(
    "/activities/{activity_id}/attempts/{attempt_id}/feedback", response_model=FeedbackRead
)
async def read_feedback(
    response: Response,
    repository: Annotated[FeedbackRepository, Depends(get_feedback_repository)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    activity_id: Annotated[int, Path(ge=1)],
    attempt_id: Annotated[int, Path(ge=1)],
) -> FeedbackRead:
    result = await repository.feedback(
        owner_id=owner.owner_id, activity_id=activity_id, attempt_id=attempt_id
    )
    _prevent_storage(response)
    return result


def feedback_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, FeedbackNotFound):
        status, code, title = 404, "feedback_not_found", "Feedback not found"
    else:
        status, code, title = 500, "feedback_error", "Feedback read failed"
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=title + ".",
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(), status_code=status, media_type="application/problem+json"
    )
    _prevent_storage(response)
    return response


async def feedback_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return feedback_problem_response(exc)


__all__ = ["feedback_exception_handler", "get_feedback_repository", "router"]
```

Then wire it in `apps/backend/src/tamforge_backend/api.py`: import `router as analysis_router`, `feedback_exception_handler` and `FeedbackError`, add `app.include_router(analysis_router)` after `evidence_router`, and register `app.add_exception_handler(FeedbackError, feedback_exception_handler)` alongside the other handlers. Keep imports alphabetically grouped the way the file already does.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/Users/frank/.local/bin/uv run pytest apps/backend/tests/unit/analysis/ -q`
Expected: PASS.

- [ ] **Step 6: Regenerate the native OpenAPI document**

Run: `/Users/frank/.local/bin/uv run python scripts/ci/check_openapi.py --write`. Never hand-edit `apps/macos/TAMForge/openapi.yaml`.

Then run: `/Users/frank/.local/bin/uv run python scripts/ci/check_openapi.py`
Expected: clean.

- [ ] **Step 7: Full backend and protocol suite, lint, typecheck, policy**

```bash
/Users/frank/.local/bin/uv run ruff check .
/Users/frank/.local/bin/uv run mypy apps/backend/src packages/protocol/src
/Users/frank/.local/bin/uv run pytest -m "not integration"
/Users/frank/.local/bin/uv run python scripts/ci/check_repository_policy.py
```

Expected: all clean. Do not run `make check`; it invokes `xcodebuild`, which this task must not touch.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/tamforge_backend/analysis apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/analysis apps/macos/TAMForge/openapi.yaml
git commit -m "feat(analysis): expose feedback only through the release gate"
```

---

## Execution order

Tasks 1 and 3 are independent: they touch disjoint files (`packages/protocol/` versus `agents/models.py` plus a new migration) and neither reads the other's output. Run them in parallel.

Task 2 consumes Task 1's `WithheldReason`. Task 4 consumes all three. Both run in series after their inputs land.
