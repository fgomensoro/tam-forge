from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.scoring import (
    SCORE_QUANTUM,
    WEIGHT_QUANTUM,
    calculate_effective_weight,
)

ROOT = Path(__file__).parents[3]
FIXTURE = ROOT / "apps/macos/TAMForge/App/NativeUIFixtures.swift"


def test_native_evidence_fixture_matches_authoritative_seed_config() -> None:
    bundle = load_config_bundle(ROOT / "config")
    formula = bundle.formula
    troubleshooting = bundle.skill("structured_troubleshooting")
    english = bundle.skill("tam_english")
    rubric = bundle.rubric("portfolio_judgment")

    human_weight = calculate_effective_weight(
        skill_impact=Decimal("1"),
        practice_mode="independent_practice",
        assistance="no_ai",
        evaluator="human_coach",
        difficulty="standard",
        formula=formula,
    ).effective_weight
    self_weight = calculate_effective_weight(
        skill_impact=Decimal("1"),
        practice_mode="independent_practice",
        assistance="no_ai",
        evaluator="self",
        difficulty="standard",
        formula=formula,
    ).effective_weight
    discounted_weight = (human_weight * formula.same_day_repetition_factor).quantize(
        WEIGHT_QUANTUM, rounding=ROUND_HALF_UP
    )
    total_weight = human_weight * 2 + discounted_weight
    estimate = (
        (
            troubleshooting.baseline * formula.prior_weight
            + Decimal("3") * total_weight
        )
        / (formula.prior_weight + total_weight)
    ).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)

    assert human_weight == Decimal("0.617500")
    assert self_weight == Decimal("0.390000")
    assert discounted_weight == Decimal("0.154375")
    assert total_weight == Decimal("1.389375")
    assert estimate == Decimal("2.410")
    assert rubric.version == formula.version == "seed-v1"
    assert rubric.dimensions[0].slug == "impact_risk_assessment"
    assert rubric.dimensions[0].weight == Decimal("0.20")

    source = FIXTURE.read_text(encoding="utf-8")
    baseline_fixture = (
        f'"baseline": english ? "{english.baseline:.3f}" '
        f': "{troubleshooting.baseline:.3f}"'
    )
    final_target_fixture = (
        f'"final_target": english ? "{english.final_target:.3f}" '
        f': "{troubleshooting.final_target:.3f}"'
    )
    effective_weight_fixture = (
        f'let effectiveWeight = selfEvidence ? "{self_weight:.6f}" '
        f': "{human_weight:.6f}"'
    )
    assert baseline_fixture in source
    assert (
        f'"month_one_target": english ? "{english.month_one_target:.3f}" '
        f': "{troubleshooting.month_one_target:.3f}"'
    ) in source
    assert final_target_fixture in source
    assert f'"formula_version": "{formula.version}"' in source
    assert f'"rubric_slug": "{rubric.slug}", "rubric_version": "{rubric.version}"' in source
    assert f'"estimated_level": "{estimate:.3f}"' in source
    assert f'"month_one_target_gap": "{troubleshooting.month_one_target - estimate:.3f}"' in source
    assert f'"final_target_gap": "{troubleshooting.final_target - estimate:.3f}"' in source
    assert f'"total_effective_weight": "{total_weight:.6f}"' in source
    assert effective_weight_fixture in source

    event_source = source.split("private func evidenceEvent", maxsplit=1)[1]
    assert '"dimension_score_id"' in event_source
    assert '"score": 3.0' in event_source
    assert '"weight": 0.2' in event_source
    assert '"dimension_slug"' not in event_source
    assert '"observations"' not in event_source
