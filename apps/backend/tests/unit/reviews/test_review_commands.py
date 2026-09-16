"""A review becomes one ledger command: rubric scores split across the mapped skills."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from tamforge_backend.agents.roles.reviewer import ReviewOutcome
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.reviews.service import (
    ReviewInvalid,
    assign_dimensions,
    build_evidence_command,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"
BUNDLE = load_config_bundle(CONFIG_DIR)
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _outcome() -> ReviewOutcome:
    return ReviewOutcome.model_validate(
        {
            "verdict": "Solid.",
            "dimensions": [
                {"slug": d.slug, "score": "3", "rationale": "ok", "evidence": "q"}
                for d in BUNDLE.rubric("tam_block").dimensions
            ],
            "strengths": [{"statement": "a"}, {"statement": "b"}],
            "corrections": [
                {"statement": "c", "instruction": "x"},
                {"statement": "d", "instruction": "y"},
            ],
            "next_practice": "again",
        }
    )


def _loaded(exercise: str, *, markdown: str | None = None) -> SimpleNamespace:
    output = {"draft_markdown": "text"}
    return SimpleNamespace(
        activity=SimpleNamespace(id=30, owner_id=1),
        definition=SimpleNamespace(exercise_type=exercise),
        attempt=SimpleNamespace(
            id=40,
            original_text=json.dumps(
                {
                    "task_context": {"exercise_type": exercise, "mapping_version": "seed-v1"},
                    "output": output,
                }
            ),
            original_markdown=markdown,
            original_sql=None,
            assistance_mode="none",
        ),
    )


def test_dimensions_are_shared_round_robin_and_never_reused() -> None:
    dims = ("a", "b", "c", "d", "e", "f")
    assert assign_dimensions(dims, ("s1", "s2")) == {"s1": ("a", "c", "e"), "s2": ("b", "d", "f")}
    assert assign_dimensions(dims, ("s1", "s2", "s3", "s4")) == {
        "s1": ("a", "e"),
        "s2": ("b", "f"),
        "s3": ("c",),
        "s4": ("d",),
    }
    assert assign_dimensions(dims, ()) == {}
    assert assign_dimensions(("a",), ("s1", "s2")) == {}


def test_the_command_carries_the_rubric_scores_and_one_subset_per_mapped_skill() -> None:
    exercise = BUNDLE.exercise("integration_diagram_and_explanation")
    command = build_evidence_command(
        loaded=_loaded(exercise.slug, markdown="# note"),  # type: ignore[arg-type]
        bundle=BUNDLE,
        config_version_key=BUNDLE.version_key,
        outcome=_outcome(),
        output={"draft_markdown": "text"},
        evaluated_at=NOW,
    )

    assert command.rubric_slug == "tam_block" and command.evaluator == "ai_rubric_reviewer"
    assert command.assistance == "ai_after_committed_attempt" and command.ai_role == "reviewer"
    assert command.practice_mode == exercise.evidence_mode
    assert command.written_english_available is True
    assert {d.dimension_slug for d in command.dimensions} == {
        d.slug for d in BUNDLE.rubric("tam_block").dimensions
    }
    assert all(d.score == Decimal("3") for d in command.dimensions)
    mapped = {impact.skill_slug for impact in exercise.impacts}
    assert {s.skill_slug for s in command.skill_dimension_subsets} <= mapped
    assigned = [slug for s in command.skill_dimension_subsets for slug in s.dimension_slugs]
    assert len(assigned) == len(set(assigned))


def test_an_attempt_without_a_task_context_or_a_known_exercise_cannot_be_recorded() -> None:
    loaded = _loaded("integration_diagram_and_explanation")
    loaded.attempt.original_text = json.dumps({"output": {"x": "y"}})
    with pytest.raises(ReviewInvalid, match="task context"):
        build_evidence_command(
            loaded=loaded,
            bundle=BUNDLE,
            config_version_key="k",  # type: ignore[arg-type]
            outcome=_outcome(),
            output={},
            evaluated_at=NOW,
        )
    with pytest.raises(ReviewInvalid, match="not in the configuration"):
        build_evidence_command(
            loaded=_loaded("no_such_exercise"),
            bundle=BUNDLE,
            config_version_key="k",  # type: ignore[arg-type]
            outcome=_outcome(),
            output={},
            evaluated_at=NOW,
        )
