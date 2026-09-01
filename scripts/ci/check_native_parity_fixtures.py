"""Validate the one shared native parity scenario against backend contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "native-parity" / "foundation-journey-v1.json"


class FixtureError(ValueError):
    """The shared fixture drifted from its source package or public contracts."""


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FixtureError("native parity fixture must be a JSON object")
    return value


def validate_fixture(value: dict[str, Any], *, root: Path = ROOT) -> None:
    from tamforge_backend.evidence.confidence import SkillEvidence, estimate_skill
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.schemas import (
        PortfolioHistoryResponse,
        SkillListResponse,
    )
    from tamforge_backend.evidence.scoring import calculate_effective_weight
    from tamforge_backend.learning.schemas import ActivityDetailResponse
    from tamforge_backend.notifications.schemas import NotificationPage
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.parser import parse_roadmap
    from tamforge_backend.roadmaps.routes import (
        RoadmapImportResponse,
        RoadmapVersionResponse,
    )
    from tamforge_backend.today.schemas import TodayResponse

    if set(value) != {
        "schema_version",
        "scenario_id",
        "fixed_now",
        "source_package",
        "responses",
        "journey",
    }:
        raise FixtureError("native parity fixture top-level fields drifted")
    if value["schema_version"] != 1 or value["scenario_id"] != "native-foundation-month1-v1":
        raise FixtureError("native parity fixture identity is invalid")

    source = _object(value["source_package"], "source_package")
    package_path = root / _text(source.get("path"), "source_package.path")
    try:
        package = package_path.read_bytes()
    except OSError as exc:
        raise FixtureError("native parity source package is unavailable") from exc
    if source.get("byte_length") != len(package):
        raise FixtureError("native parity source package byte length drifted")
    if source.get("sha256") != hashlib.sha256(package).hexdigest():
        raise FixtureError("native parity source package digest drifted")

    responses = _object(value["responses"], "responses")
    expected_responses = {
        "roadmap_import",
        "roadmap_version",
        "today",
        "activity",
        "notifications",
        "skills",
        "portfolio",
    }
    if set(responses) != expected_responses:
        raise FixtureError("native parity response records drifted")
    roadmap_import = RoadmapImportResponse.model_validate(responses["roadmap_import"])
    roadmap_version = RoadmapVersionResponse.model_validate(responses["roadmap_version"])
    today = TodayResponse.model_validate(responses["today"])
    activity = ActivityDetailResponse.model_validate(responses["activity"])
    notifications = NotificationPage.model_validate(responses["notifications"])
    skills = SkillListResponse.model_validate(responses["skills"])
    portfolio = PortfolioHistoryResponse.model_validate(responses["portfolio"])

    bundle = load_config_bundle(root / "config")
    with inspect_zip_stream((package,)) as inspected:
        if not inspected.accepted:
            raise FixtureError("native parity source package is not accepted")
        parsed = parse_roadmap(
            files={
                item.manifest.path: item.staged_path.read_bytes()
                for item in inspected.files
            },
            config=bundle,
        )
    expected_reading = next(
        (
            item
            for item in parsed.tasks
            if item.week == 1 and item.day == 1 and item.block == "technical_learning"
        ),
        None,
    )
    report = roadmap_import.validation_report
    summary = _object(roadmap_import.semantic_diff.get("summary"), "semantic_diff.summary")
    if (
        expected_reading is None
        or roadmap_version.version_key != parsed.roadmap_version
        or today.roadmap.version_key != parsed.roadmap_version
        or report
        != {
            "schema_version": 1,
            "accepted": True,
            "normalized_hash": parsed.normalized_hash,
            "task_count": len(parsed.tasks),
            "resource_count": len(parsed.resources),
            "exit_criterion_count": len(parsed.exit_criteria),
            "issues": [],
        }
        or summary
        != {
            "added": (
                len(parsed.tasks)
                + len(parsed.contracts)
                + len(parsed.resources)
                + len(parsed.exit_criteria)
            ),
            "changed": 0,
            "removed": 0,
            "unchanged": 0,
        }
    ):
        raise FixtureError("native parity roadmap projection drifted")

    reading = next((item for item in today.tasks if item.block == "technical_learning"), None)
    if (
        today.local_date.isoformat() != value["fixed_now"][:10]
        or today.total_planned_minutes != 240
        or reading is None
        or reading.timebox_minutes != 45
        or reading.activity_id != activity.id
        or reading.objective != activity.task_contract.objective
        or activity.task_contract.block != "technical_learning"
        or reading.roadmap_order != expected_reading.order
        or reading.stable_id != expected_reading.stable_id
        or reading.objective != expected_reading.objective
        or tuple((item.path, item.anchor) for item in reading.source_references)
        != ((expected_reading.source_path, expected_reading.source_heading),)
        or tuple(reading.required_output) != expected_reading.required_output
        or tuple(reading.pass_criteria) != expected_reading.pass_criteria
        or tuple(reading.evidence_requirements) != expected_reading.evidence_requirements
        or reading.allowed_ai_role != expected_reading.allowed_ai_role
        or activity.task_contract.exercise_type != expected_reading.exercise_type
        or activity.task_contract.mapping_version != expected_reading.mapping_version
        or tuple(step.model_dump(mode="json") for step in activity.task_contract.procedure)
        != tuple(step.to_dict() for step in expected_reading.procedure)
        or tuple(activity.task_contract.constraints) != expected_reading.constraints
    ):
        raise FixtureError("native parity Today/activity relationship drifted")

    journey = _object(value["journey"], "journey")
    if journey.get("activity_states") != [
        "ready",
        "active",
        "paused",
        "active",
        "output_committed",
        "self_review_complete",
    ]:
        raise FixtureError("native parity activity progression drifted")
    output = _object(journey.get("output"), "journey.output")
    if (
        output.get("kind") != "reading"
        or output.get("prompt") != reading.objective
        or output.get("time_limit_minutes") != 45
        or len(output.get("key_ideas", [])) != 3
    ):
        raise FixtureError("native parity independent output drifted")
    review = _object(journey.get("self_review"), "journey.self_review")
    if review.get("self_score") != 3 or set(review) != {
        "main_answer",
        "did_well",
        "structure_weakness",
        "vague_points",
        "hesitation_points",
        "change_next",
        "self_score",
    }:
        raise FixtureError("native parity mandatory self-review drifted")
    troubleshooting = bundle.skill("structured_troubleshooting")
    english = bundle.skill("tam_english")
    formula = bundle.formula
    full_weight = calculate_effective_weight(
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
    as_of = datetime.fromisoformat(value["fixed_now"])
    event_specs = (
        (9, timedelta(minutes=60), True, full_weight),
        (10, timedelta(minutes=50), True, full_weight),
        (50, timedelta(minutes=40), True, full_weight),
        (39, timedelta(minutes=80), False, self_weight),
        (49, timedelta(minutes=70), False, self_weight),
    )
    synthetic_evidence = tuple(
        SkillEvidence(
            event_id=event_id,
            performance_score=Decimal("3"),
            effective_weight=weight,
            qualifying_for_level=qualifying,
            exercise_type="troubleshooting_case",
            scenario_key="native-parity-five-event-history",
            occurred_at=as_of - age,
            practice_mode="independent_practice",
            attempt_kind="attempt_a",
            reviewed_artifact=False,
            scored_recording=False,
        )
        for event_id, age, qualifying, weight in event_specs
    )
    estimate = estimate_skill(
        baseline=troubleshooting.baseline,
        month_one_target=troubleshooting.month_one_target,
        final_target=troubleshooting.final_target,
        events=synthetic_evidence,
        formula=formula,
        as_of=as_of,
    )
    evidence_by_id = {item.event_id: item for item in synthetic_evidence}
    expected_manifest = [
        {
            "event_id": item.event_id,
            "effective_weight": f"{item.used_weight:.6f}",
            "inclusion_code": item.inclusion,
        }
        for item in estimate.weight_manifest
    ]
    expected_manifest.extend(
        {
            "event_id": item.event_id,
            "effective_weight": "0.000",
            "inclusion_code": (
                "excluded_outside_window"
                if item.qualifying_for_level
                else "excluded_nonqualifying"
            ),
        }
        for item in sorted(
            (evidence_by_id[item] for item in estimate.excluded_event_ids),
            key=lambda item: (item.occurred_at, str(item.event_id)),
            reverse=True,
        )
    )
    trend_basis_code = (
        "no_qualifying_evidence"
        if not estimate.contributing_event_ids
        else "too_few_events"
    ) if estimate.trend.code == "insufficient_evidence" else estimate.trend.code
    expected_skills = {
        "items": [
            {
                "slug": troubleshooting.slug,
                "name": troubleshooting.name,
                "baseline": f"{troubleshooting.baseline:.3f}",
                "month_one_target": f"{troubleshooting.month_one_target:.3f}",
                "final_target": f"{troubleshooting.final_target:.3f}",
                "latest_snapshot": {
                    "id": 71,
                    "formula_version": estimate.formula_version,
                    "snapshot_date": value["fixed_now"][:10],
                    "estimated_level": f"{estimate.estimate:.3f}",
                    "confidence": estimate.confidence.code,
                    "trend": estimate.trend.code,
                    "recency": (
                        "no_qualifying_evidence"
                        if estimate.recency.code == "no_evidence"
                        else estimate.recency.code
                    ),
                    "baseline_target_gap": (
                        f"{troubleshooting.baseline - estimate.estimate:.3f}"
                    ),
                    "month_one_target_gap": f"{estimate.month_one_target_gap:.3f}",
                    "final_target_gap": f"{estimate.final_target_gap:.3f}",
                    "total_effective_weight": f"{estimate.total_effective_weight:.6f}",
                    "qualifying_event_count": estimate.qualifying_event_count,
                    "exercise_type_count": estimate.confidence.exercise_type_count,
                    "last_strong_evidence_date": (
                        None
                        if estimate.last_strong_evidence_at is None
                        else estimate.last_strong_evidence_at.date().isoformat()
                    ),
                    "manifest": expected_manifest,
                    "confidence_basis": {
                        "schema_version": 1,
                        "basis_code": estimate.confidence.basis_code,
                        "event_ids": list(estimate.confidence.event_ids),
                    },
                    "trend_basis": {
                        "schema_version": 1,
                        "basis_code": trend_basis_code,
                        "event_ids": list(estimate.trend.event_ids),
                    },
                },
            },
            {
                "slug": english.slug,
                "name": english.name,
                "baseline": f"{english.baseline:.3f}",
                "month_one_target": f"{english.month_one_target:.3f}",
                "final_target": f"{english.final_target:.3f}",
                "latest_snapshot": None,
            },
        ]
    }
    if skills.model_dump(mode="json") != expected_skills:
        raise FixtureError("native parity assessed skill lineage drifted")
    exercise_type = activity.task_contract.exercise_type
    if exercise_type is None:
        raise FixtureError("native parity activity exercise type is missing")
    exercise = bundle.exercise(exercise_type)
    if portfolio.items or "portfolio_judgment" in exercise.composite_metric_weights:
        raise FixtureError("native parity portfolio relationship drifted")
    if (
        not notifications.items
        or notifications.items[0].notification_type != "feedback_ready"
        or notifications.items[0].read_at is not None
    ):
        raise FixtureError("native parity unread feedback notification drifted")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FixtureError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FixtureError(f"{label} must be non-empty text")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    arguments = parser.parse_args()
    try:
        validate_fixture(load_fixture(arguments.path))
    except (FixtureError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"native parity fixture invalid: {exc}") from None
    print(f"Native parity fixture is valid: {arguments.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
