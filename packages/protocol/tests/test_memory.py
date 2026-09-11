"""What the system may remember, and why none of it can be edited in place."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from tamforge_protocol.memory import (
    KINDS_NEVER_APPROVED,
    LEDGER_KINDS,
    EvidenceLink,
    MemoryError,
    MemoryLedger,
    MemoryRevision,
    Provenance,
)

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)
EVIDENCE = (EvidenceLink(kind="activity", reference_id=8),)


def revision(**overrides: object) -> MemoryRevision:
    data: dict[str, object] = {
        "memory_id": 1,
        "revision_id": 100,
        "revision_number": 1,
        "kind": "semantic",
        "scope": "global",
        "claim": "Prefers worked examples before abstract rules.",
        "confidence": 0.7,
        "sensitivity": "routine",
        "visible_to": frozenset({"tutor", "coach"}),
        "evidence": EVIDENCE,
        "provenance": Provenance(author="tutor", model_run_id=3),
        "valid_from": NOW,
        "approval": "approved",
        "recorded_at": NOW,
    }
    data.update(overrides)
    return MemoryRevision.model_validate(data)


# --- what a revision must carry ---------------------------------------------------------


def test_the_four_ledger_kinds_and_no_working_memory() -> None:
    assert LEDGER_KINDS == frozenset({"episodic", "semantic", "hypothesis", "procedural"})
    with pytest.raises(ValidationError):
        revision(kind="working")


def test_a_claim_without_evidence_is_refused() -> None:
    with pytest.raises(ValidationError, match="no evidence is an opinion"):
        revision(evidence=())


def test_a_revision_carries_confidence_sensitivity_and_role_scope() -> None:
    r = revision(confidence=0.4, sensitivity="personal", visible_to=frozenset({"coach"}))
    assert (r.confidence, r.sensitivity, r.visible_to) == (0.4, "personal", frozenset({"coach"}))
    with pytest.raises(ValidationError):
        revision(confidence=1.5)
    with pytest.raises(ValidationError, match="nobody can act on"):
        revision(visible_to=frozenset())


def test_a_scoped_memory_names_its_scope_and_a_global_one_names_nothing() -> None:
    assert revision(scope="opportunity", scope_reference_id=4).scope_reference_id == 4
    with pytest.raises(ValidationError, match="must name which opportunity"):
        revision(scope="opportunity")
    with pytest.raises(ValidationError, match="points at nothing"):
        revision(scope="global", scope_reference_id=4)


def test_a_learner_statement_has_no_model_run_behind_it() -> None:
    assert Provenance(author="learner").model_run_id is None
    with pytest.raises(ValidationError, match="no model run"):
        Provenance(author="learner", model_run_id=3)


def test_a_hypothesis_is_never_approved_into_a_fact() -> None:
    assert KINDS_NEVER_APPROVED == frozenset({"hypothesis"})
    assert revision(kind="hypothesis", approval="proposed").approval == "proposed"
    with pytest.raises(ValidationError, match="guess"):
        revision(kind="hypothesis", approval="approved")


def test_an_episode_never_expires() -> None:
    with pytest.raises(ValidationError, match="never becomes false"):
        revision(kind="episodic", expires_at=NOW + timedelta(days=1))


def test_validity_and_expiry_run_forward() -> None:
    with pytest.raises(ValidationError, match="valid_to"):
        revision(valid_to=NOW)
    with pytest.raises(ValidationError, match="expires_at"):
        revision(expires_at=NOW - timedelta(seconds=1))


# --- immutability and versioning ---------------------------------------------------------


def test_a_revision_cannot_be_mutated_in_place() -> None:
    r = revision()
    with pytest.raises(ValidationError):
        r.claim = "Something else"


def test_revision_ids_are_permanent_and_never_rewritten() -> None:
    ledger = MemoryLedger().append(revision())
    with pytest.raises(MemoryError, match="cannot be rewritten"):
        ledger.append(revision(claim="Rewritten under the same id"))


def test_a_later_revision_supersedes_the_current_one_and_keeps_the_old_one_readable() -> None:
    first = revision()
    second = revision(
        revision_id=101, revision_number=2, supersedes_revision_id=100, confidence=0.9
    )
    ledger = MemoryLedger().append(first).append(second)

    current = ledger.current(1)
    assert current == second
    assert ledger.history(1) == (first, second)
    assert current is not None and current.supersedes_revision_id == first.revision_id


def test_append_returns_a_new_ledger_and_leaves_the_old_one_untouched() -> None:
    empty = MemoryLedger()
    grown = empty.append(revision())
    assert empty.revisions == ()
    assert len(grown.revisions) == 1


def test_supersession_must_name_the_current_revision_not_an_older_one() -> None:
    ledger = (
        MemoryLedger()
        .append(revision())
        .append(revision(revision_id=101, revision_number=2, supersedes_revision_id=100))
    )
    with pytest.raises(MemoryError, match="not an older one"):
        ledger.append(revision(revision_id=102, revision_number=3, supersedes_revision_id=100))
    with pytest.raises(MemoryError, match="expected revision 3"):
        ledger.append(revision(revision_id=102, revision_number=4, supersedes_revision_id=101))


def test_first_revisions_supersede_nothing_and_later_ones_must() -> None:
    with pytest.raises(ValidationError, match="nothing to supersede"):
        revision(supersedes_revision_id=99)
    with pytest.raises(ValidationError, match="must name the revision it supersedes"):
        revision(revision_number=2)
    with pytest.raises(MemoryError, match="starts at revision 1"):
        MemoryLedger().append(revision(revision_number=2, supersedes_revision_id=99))


def test_a_memory_keeps_its_kind_across_revisions() -> None:
    ledger = MemoryLedger().append(revision(kind="procedural"))
    with pytest.raises(MemoryError, match="different memory"):
        ledger.append(
            revision(
                kind="semantic", revision_id=101, revision_number=2, supersedes_revision_id=100
            )
        )


def test_a_contradiction_is_an_explicit_link_to_a_revision_in_the_ledger() -> None:
    ledger = MemoryLedger().append(revision())
    contradicting = revision(
        memory_id=2,
        revision_id=200,
        claim="Prefers rules first.",
        contradicts_revision_ids=frozenset({100}),
    )
    current = ledger.append(contradicting).current(2)
    assert current is not None and current.contradicts_revision_ids == frozenset({100})
    with pytest.raises(MemoryError, match="not in the ledger"):
        ledger.append(
            revision(memory_id=3, revision_id=300, contradicts_revision_ids=frozenset({999}))
        )


# --- visibility is decided before retrieval ---------------------------------------------


def test_visibility_filters_by_role_approval_and_time() -> None:
    ledger = (
        MemoryLedger()
        .append(revision())
        .append(revision(memory_id=2, revision_id=200, visible_to=frozenset({"analyst"})))
        .append(revision(memory_id=3, revision_id=300, approval="proposed"))
        .append(revision(memory_id=4, revision_id=400, expires_at=NOW + timedelta(hours=1)))
        .append(revision(memory_id=5, revision_id=500, valid_to=NOW + timedelta(hours=1)))
    )

    now = ledger.visible(role="coach", at=NOW)
    assert [r.memory_id for r in now] == [1, 4, 5]

    later = ledger.visible(role="coach", at=NOW + timedelta(hours=2))
    assert [r.memory_id for r in later] == [1]


def test_a_role_never_sees_above_its_sensitivity_ceiling() -> None:
    ledger = (
        MemoryLedger()
        .append(revision(sensitivity="routine"))
        .append(revision(memory_id=2, revision_id=200, sensitivity="personal"))
        .append(revision(memory_id=3, revision_id=300, sensitivity="real_interview"))
    )
    assert [r.memory_id for r in ledger.visible(role="coach", at=NOW)] == [1]
    assert [r.memory_id for r in ledger.visible(role="coach", at=NOW, ceiling="personal")] == [1, 2]
    assert [
        r.memory_id for r in ledger.visible(role="coach", at=NOW, ceiling="real_interview")
    ] == [
        1,
        2,
        3,
    ]


def test_visibility_returns_only_the_current_revision_of_each_memory() -> None:
    ledger = (
        MemoryLedger()
        .append(revision(confidence=0.5))
        .append(
            revision(revision_id=101, revision_number=2, supersedes_revision_id=100, confidence=0.9)
        )
    )
    (only,) = ledger.visible(role="coach", at=NOW)
    assert (only.revision_id, only.confidence) == (101, 0.9)


def test_visibility_can_be_narrowed_to_one_scope() -> None:
    ledger = (
        MemoryLedger()
        .append(revision())
        .append(revision(memory_id=2, revision_id=200, scope="opportunity", scope_reference_id=4))
        .append(revision(memory_id=3, revision_id=300, scope="opportunity", scope_reference_id=5))
    )
    scoped = ledger.visible(role="coach", at=NOW, scope="opportunity", scope_reference_id=4)
    assert [r.memory_id for r in scoped] == [2]


def test_the_ledger_exposes_no_way_to_write_a_revision_back() -> None:
    ledger = MemoryLedger().append(revision())
    with pytest.raises(ValidationError):
        ledger.revisions = ()
    assert not any(name in ("update", "edit", "replace", "delete") for name in dir(MemoryLedger))
