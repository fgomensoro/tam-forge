"""What a finished case leaves behind for a later portfolio judgment to read."""

from __future__ import annotations

from dataclasses import fields

import pytest
from tamforge_backend.agents.model_runs import LEARNER_FIELDS
from tamforge_backend.workspaces.portfolio import (
    COMPOSITE_MAX,
    DIMENSION_MAX,
    PORTFOLIO_DIMENSIONS,
    PortfolioError,
    PortfolioItem,
    PortfolioScore,
    prioritize,
    reprioritize,
    rescore,
)
from tamforge_protocol.workspaces import CaseCommitment


def test_the_triage_material_survives_redaction() -> None:
    """Portfolio triage reasons over risk and decisions, so both must reach a reviewer.

    They only do if the redaction allowlist knows their field names. A case that
    records its risks in a field the allowlist has never heard of leaves the later
    judgment with nothing to weigh, and nothing about that failure is loud.
    """
    for field in ("risks", "decisions", "unresolved_questions"):
        assert field in LEARNER_FIELDS["case"]
        assert field in CaseCommitment.model_fields


def test_risks_and_decisions_are_lists_rather_than_one_paragraph() -> None:
    # Triage compares items across cases. A single prose blob cannot be compared,
    # counted, or carried into a priority ordering without being parsed first.
    for field in ("risks", "decisions"):
        annotation = str(CaseCommitment.model_fields[field].annotation)
        assert "tuple" in annotation


# Issue #96: the approved 0-20 dimensions, the rationale that produced a score, and
# reprioritization when the evidence changes.



def score(**overrides: object) -> PortfolioScore:
    data: dict[str, object] = {
        "impact": 3,
        "risk": 2,
        "time_sensitivity": 2,
        "workaround_gap": 1,
        "strategic_context": 2,
        "rationale": "Two accounts affected, a workaround exists, renewal is in March.",
        "diagnostic_confidence": "medium",
    }
    data.update(overrides)
    return PortfolioScore(**data)  # type: ignore[arg-type]


def item(item_id: str = "inc-1", account: str = "Northwind", **overrides: object) -> PortfolioItem:
    return PortfolioItem(
        item_id=item_id,
        account=account,
        score=overrides.pop("score", score()),  # type: ignore[arg-type]
        action=overrides.pop("action", "work_now"),  # type: ignore[arg-type]
    )


def test_the_composite_runs_from_zero_to_twenty_over_five_dimensions() -> None:
    assert len(PORTFOLIO_DIMENSIONS) == 5
    assert DIMENSION_MAX == 4
    assert COMPOSITE_MAX == 20

    assert score(**{name: 0 for name in PORTFOLIO_DIMENSIONS}).composite == 0
    assert score(**{name: 4 for name in PORTFOLIO_DIMENSIONS}).composite == COMPOSITE_MAX
    assert score().composite == 10


def test_a_stored_total_cannot_disagree_with_its_dimensions() -> None:
    # It is derived, so there is no total to set and nothing to contradict.
    assert "composite" not in {field.name for field in fields(PortfolioScore)}
    with pytest.raises(TypeError):
        score(composite=20)


@pytest.mark.parametrize("dimension", PORTFOLIO_DIMENSIONS)
def test_every_dimension_stays_on_the_same_scale(dimension: str) -> None:
    for bad in (-1, DIMENSION_MAX + 1, 2.5, True):
        with pytest.raises(PortfolioError, match=dimension):
            score(**{dimension: bad})


def test_every_dimension_points_the_same_way() -> None:
    # The workaround factor is a gap rather than a quality: a good workaround makes a
    # problem less urgent, and mixing directions inside one sum breaks the composite.
    assert "workaround_gap" in PORTFOLIO_DIMENSIONS
    assert "workaround_quality" not in PORTFOLIO_DIMENSIONS
    covered = score(workaround_gap=0).composite
    exposed = score(workaround_gap=4).composite
    assert exposed > covered


def test_a_score_carries_the_reasoning_that_produced_it() -> None:
    assert score().rationale
    with pytest.raises(PortfolioError, match="reasoning"):
        score(rationale="   ")


def test_the_largest_account_is_not_priority_one_by_arithmetic() -> None:
    # Account size is not a dimension at all, so it cannot lift a composite.
    assert not any("account" in dimension for dimension in PORTFOLIO_DIMENSIONS)

    loud = item("inc-1", "Enormous Corp", score=score(**{name: 1 for name in PORTFOLIO_DIMENSIONS}))
    quiet = item("inc-2", "Two Person Startup", score=score(impact=4, risk=4, time_sensitivity=4))

    assert [entry.account for entry in prioritize([loud, quiet])] == [
        "Two Person Startup",
        "Enormous Corp",
    ]


def test_ties_break_on_the_item_id_so_ordering_is_reproducible() -> None:
    first = item("inc-1", "A")
    second = item("inc-2", "B")

    assert prioritize([second, first]) == (first, second)
    assert prioritize([first, second]) == (first, second)


def test_an_item_appears_once_in_a_portfolio() -> None:
    with pytest.raises(PortfolioError, match="appears once"):
        prioritize([item("inc-1"), item("inc-1", "Other")])


def test_rescoring_leaves_the_original_untouched() -> None:
    before = item()
    after = rescore(before, score(time_sensitivity=4, rationale="The deadline moved up."))

    assert before.score.time_sensitivity == 2
    assert after.score.time_sensitivity == 4
    assert after.score.rationale == "The deadline moved up."


def test_changed_evidence_reprioritizes_the_queue() -> None:
    low = item("inc-1", "Northwind", score=score(**{name: 1 for name in PORTFOLIO_DIMENSIONS}))
    high = item("inc-2", "Contoso", score=score(impact=4, risk=3))
    assert [entry.item_id for entry in prioritize([low, high])] == ["inc-2", "inc-1"]

    escalated = rescore(
        low, score(**{name: 4 for name in PORTFOLIO_DIMENSIONS}, rationale="Data loss confirmed.")
    )
    assert [entry.item_id for entry in reprioritize([low, high], rescored=escalated)] == [
        "inc-1",
        "inc-2",
    ]


def test_reprioritizing_something_not_in_the_portfolio_is_refused() -> None:
    with pytest.raises(PortfolioError, match="not in this portfolio"):
        reprioritize([item("inc-1")], rescored=item("inc-9"))


def test_doing_nothing_on_purpose_is_a_triage_decision() -> None:
    from typing import get_args

    from tamforge_backend.workspaces.portfolio import TriageAction

    # A queue that only reacts never gets ahead, so protected proactive work and
    # communicating without acting are both recordable outcomes.
    assert set(get_args(TriageAction)) == {
        "work_now",
        "delegate",
        "escalate",
        "communicate_and_wait",
        "protected_proactive",
    }
    assert item(action="protected_proactive").action == "protected_proactive"
