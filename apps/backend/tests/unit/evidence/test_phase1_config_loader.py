from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from tamforge_backend.cli import _apply, main as cli_main
from tamforge_backend.evidence.config_loader import (
    ConfigError,
    RoadmapReleaseRegistry,
    load_config_bundle,
)
from tamforge_backend.evidence.config_models import (
    EnglishDimensionPolicyConfig,
    RoadmapCalendarConfig,
    RoadmapProgramConfig,
    Week7PolicyConfig,
)
from tamforge_backend.evidence.seed import SeedConfigError, seed_config

CONFIG_DIR = Path(__file__).parents[5] / "config"
PHASE1_RELEASE_DIR = CONFIG_DIR / "releases" / "phase-1-six-week-v1"

EXPECTED_ROOT_SHA256 = {
    "tam-skills.yaml": "6008a4b157272d3cb62685b647f1cf3dfd889dd79014a40cc9cd86083ea4fecf",
    "tam-exercise-types.yaml": "e0275f1c546f5899954f5e9b66f2f05db5a15d24465ed367acd6f36af8ba0e78",
    "tam-rubrics.yaml": "32767e6393475a6e1c9dda52aa5f638940a38dc7a0881657baeb4b3baba43a00",
    "tam-roadmap-task-map.yaml": "44206a242e9c6b9219b2de7cf27ff709e96e5f553ba4c378d3a83092d03fc814",
}
SCORING_FILES = (
    "tam-skills.yaml",
    "tam-exercise-types.yaml",
    "tam-rubrics.yaml",
)


def _valid_v2_roadmap() -> dict[str, object]:
    queue = [
        {
            "ordinal": ordinal,
            "segment": ((ordinal - 1) // 5) + 1,
            "question_key": f"question_{ordinal:02d}",
            "selection_mode": "ordered",
            "prompt": f"Question {ordinal}",
        }
        for ordinal in range(1, 30)
    ]
    queue.append(
        {
            "ordinal": 30,
            "segment": 6,
            "question_key": "sealed_final_mock",
            "selection_mode": "fixed_event",
            "fixed_local_date": "2026-10-02",
            "prompt": "Run the sealed Phase 1 final mock.",
        }
    )
    english_dimensions = {
        "policy_version": "phase-1-english-v1",
        "aggregate_skill_slug": "tam_english",
        "scale_min": 0,
        "scale_max": 4,
        "unavailable_state": "not_assessed",
        "accent_scored": False,
        "dimensions": [
            {
                "dimension_key": "communication_effectiveness",
                "weight": "0.30",
                "modalities": ["written", "spoken"],
            },
            {"dimension_key": "fluency", "weight": "0.25", "modalities": ["spoken_audio"]},
            {"dimension_key": "accuracy", "weight": "0.15", "modalities": ["written", "spoken"]},
            {"dimension_key": "vocabulary", "weight": "0.10", "modalities": ["written", "spoken"]},
            {
                "dimension_key": "pronunciation_intelligibility",
                "weight": "0.10",
                "modalities": ["spoken_audio"],
            },
            {"dimension_key": "listening", "weight": "0.10", "modalities": ["interactive_spoken"]},
        ],
    }
    return {
        "schema_version": 2,
        "roadmap_version": "phase-1-six-week-v1",
        "mapping_version": "seed-v1",
        "month": 1,
        "default_required": True,
        "program": {
            "program_key": "tam_phase_1",
            "display_name": "TAM Study Phase 1",
            "target_label": "Phase 1 target — six weeks",
            "nominal_weeks": 6,
        },
        "lineage": {
            "predecessor_roadmap_version": "month-1-v2",
            "legacy_task_map_sha256": EXPECTED_ROOT_SHA256["tam-roadmap-task-map.yaml"],
            "compatibility_month": 1,
        },
        "calendar": {
            "anchor_date": "2026-08-24",
            "nominal_end_date": "2026-10-03",
            "weekday_minutes": 180,
            "saturday_minutes": 120,
            "sunday_minutes": 0,
            "ordinary_interview_minutes": 60,
            "pipeline_minutes": 30,
            "roadmap_minutes": 75,
            "close_minutes": 15,
        },
        "week7": {
            "available": True,
            "starts_on": "2026-10-05",
            "ends_on": "2026-10-10",
            "completion_only": True,
            "variance_trigger_percent": 15,
            "provisional_trigger_codes": ["actual_variance_above_threshold"],
            "activation_trigger_codes": [
                "coverage_incomplete",
                "exit_not_assessed",
                "exit_assessed_not_demonstrated",
            ],
        },
        "interview_queue": queue,
        "english_dimensions": english_dimensions,
        "coverage": {
            "requirements": [
                {
                    "requirement_key": "task:m1-w1-d01-close",
                    "kind": "task",
                    "legacy_stable_id": "m1-w1-d01-close",
                    "source_path": "Week 1.md",
                    "source_heading": "Day 1",
                }
            ],
            "assignments": [
                {
                    "requirement_key": "task:m1-w1-d01-close",
                    "phase_task_ids": ["p1-w01-d01-close"],
                    "completion_owner_task_id": "p1-w01-d01-close",
                    "treatment": "transition_import",
                    "reconciliation_note": "Preserve verified evidence.",
                }
            ],
        },
        "contracts": {
            "interview_cycle": {
                "kind": "ordinary_interview",
                "total_minutes": 60,
                "steps": [
                    {"step_key": "frame", "minutes": 5, "assistance": "none"},
                    {"step_key": "independent_attempt_a", "minutes": 15, "assistance": "none"},
                    {"step_key": "self_review", "minutes": 5, "assistance": "none"},
                    {
                        "step_key": "codex_coaching",
                        "minutes": 20,
                        "assistance": "coach_after_attempt_a",
                        "fresh_codex_task": True,
                    },
                    {
                        "step_key": "separate_attempt_b",
                        "minutes": 5,
                        "assistance": "none",
                        "after_coach_handoff": True,
                    },
                    {"step_key": "save_handoff_and_notes", "minutes": 10, "assistance": "analyst"},
                ],
                "attempt_b": {
                    "separate_from_coach_task": True,
                    "same_question_as_attempt_a": True,
                    "qualifying_for_level": False,
                },
                "coach_handoff": {
                    "required_before_attempt_b": True,
                    "coach_must_not_claim_attempt_b": True,
                },
            },
            "sealed_final_mock": {
                "kind": "sealed_final_mock",
                "total_minutes": 60,
                "queue_ordinal": 30,
                "fixed_local_date": "2026-10-02",
                "coaching_allowed": False,
                "attempt_b_allowed": False,
                "steps": [
                    {"step_key": "setup", "minutes": 5, "assistance": "none"},
                    {"step_key": "sealed_mock", "minutes": 45, "assistance": "none"},
                    {"step_key": "save_and_self_review", "minutes": 10, "assistance": "none"},
                ],
            },
            "pipeline": {
                "kind": "multi_action_pipeline",
                "output_contract_version": 2,
                "weekly_quality_target": 10,
                "default_weekday_actions": 2,
                "daily_pass_fail": False,
                "action_types": ["application", "recruiter_reply"],
                "required_fields": [
                    "company",
                    "role",
                    "context_snapshot_ref",
                    "relevance",
                    "known_gap",
                    "resume_or_story_version",
                    "completed_action",
                    "completed_on",
                    "current_stage",
                    "next_action",
                ],
                "nonqualifying_reasons": [
                    "simple_acknowledgement",
                    "research_without_required_artifact",
                ],
                "conversion_stages": [
                    "applied",
                    "recruiter_contact",
                    "recruiter_screen",
                    "hiring_manager_interview",
                    "next_round",
                    "offer",
                    "rejected",
                    "no_response",
                    "withdrawn",
                ],
            },
        },
        "reconciliations": [],
        "days": [
            {
                "week": 1,
                "day": 1,
                "source_path": "Phase 1 - Week 1.md",
                "source_heading": "Day 1",
                "tasks": [
                    {
                        "stable_id": "p1-w01-d01-close",
                        "block": "daily_close",
                        "order": 1,
                        "exercise_type": "official_reading",
                        "timebox_minutes": 15,
                        "contract": "close",
                        "allowed_ai_role": "analyst",
                    }
                ],
            }
        ],
    }


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_v2_release(release_dir: Path) -> None:
    release_dir.mkdir(parents=True)
    for filename in SCORING_FILES:
        shutil.copyfile(CONFIG_DIR / filename, release_dir / filename)
    (release_dir / "tam-roadmap-task-map.yaml").write_text(
        yaml.safe_dump(_valid_v2_roadmap(), sort_keys=False),
        encoding="utf-8",
    )


def test_phase1_release_freezes_legacy_scoring_bytes() -> None:
    root_bytes: dict[str, bytes] = {}
    for filename, expected_hash in EXPECTED_ROOT_SHA256.items():
        content = (CONFIG_DIR / filename).read_bytes()
        root_bytes[filename] = content
        assert _sha256(content) == expected_hash

    for filename in SCORING_FILES:
        release_path = PHASE1_RELEASE_DIR / filename
        assert release_path.is_file(), f"missing Phase 1 scoring freeze: {release_path}"
        release_bytes = release_path.read_bytes()
        assert release_bytes == root_bytes[filename]
        assert _sha256(release_bytes) == EXPECTED_ROOT_SHA256[filename]


def test_legacy_root_bundle_remains_schema_v1() -> None:
    bundle = load_config_bundle(CONFIG_DIR)

    assert bundle.schema_version == 1
    assert bundle.roadmap_schema_version == 1
    assert len(bundle.roadmap_tasks) == 158
    assert len({task.day for task in bundle.roadmap_tasks}) == 24
    assert bundle.program.display_name == "Month 1"
    assert bundle.calendar.weekday_minutes == 240
    assert bundle.calendar.saturday_minutes == 120
    assert bundle.calendar.sunday_minutes == 0


def test_unknown_roadmap_schema_is_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    roadmap_path = fixture_dir / "tam-roadmap-task-map.yaml"
    roadmap_path.write_text(
        roadmap_path.read_text(encoding="utf-8").replace(
            "schema_version: 1", "schema_version: 3", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="unsupported roadmap schema version 3"):
        load_config_bundle(fixture_dir)


def test_phase1_program_calendar_and_week7_contracts_are_strict() -> None:
    program = RoadmapProgramConfig.model_validate(
        {
            "program_key": "tam_phase_1",
            "display_name": "TAM Study Phase 1",
            "target_label": "Phase 1 target — six weeks",
            "nominal_weeks": 6,
        }
    )
    calendar = RoadmapCalendarConfig.model_validate(
        {
            "anchor_date": "2026-08-24",
            "nominal_end_date": "2026-10-03",
            "weekday_minutes": 180,
            "saturday_minutes": 120,
            "sunday_minutes": 0,
            "ordinary_interview_minutes": 60,
            "pipeline_minutes": 30,
            "roadmap_minutes": 75,
            "close_minutes": 15,
        }
    )
    week7 = Week7PolicyConfig.model_validate(
        {
            "available": True,
            "starts_on": "2026-10-05",
            "ends_on": "2026-10-10",
            "completion_only": True,
            "variance_trigger_percent": 15,
            "provisional_trigger_codes": ["actual_variance_above_threshold"],
            "activation_trigger_codes": [
                "coverage_incomplete",
                "exit_not_assessed",
                "exit_assessed_not_demonstrated",
            ],
        }
    )

    assert program.nominal_weeks == 6
    assert calendar.weekday_minutes == 180
    assert week7.activation_trigger_codes == (
        "coverage_incomplete",
        "exit_not_assessed",
        "exit_assessed_not_demonstrated",
    )

    with pytest.raises(ValidationError):
        RoadmapProgramConfig.model_validate({**program.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError, match="weekday minutes"):
        RoadmapCalendarConfig.model_validate({**calendar.model_dump(), "weekday_minutes": 240})
    with pytest.raises(ValidationError, match="activation trigger codes"):
        Week7PolicyConfig.model_validate(
            {
                **week7.model_dump(),
                "activation_trigger_codes": ["actual_variance_above_threshold"],
            }
        )


def test_phase1_english_dimensions_are_exact_and_do_not_score_accent() -> None:
    payload = {
        "policy_version": "phase-1-english-v1",
        "aggregate_skill_slug": "tam_english",
        "scale_min": 0,
        "scale_max": 4,
        "unavailable_state": "not_assessed",
        "accent_scored": False,
        "dimensions": [
            {
                "dimension_key": "communication_effectiveness",
                "weight": "0.30",
                "modalities": ["written", "spoken"],
            },
            {"dimension_key": "fluency", "weight": "0.25", "modalities": ["spoken_audio"]},
            {"dimension_key": "accuracy", "weight": "0.15", "modalities": ["written", "spoken"]},
            {"dimension_key": "vocabulary", "weight": "0.10", "modalities": ["written", "spoken"]},
            {
                "dimension_key": "pronunciation_intelligibility",
                "weight": "0.10",
                "modalities": ["spoken_audio"],
            },
            {"dimension_key": "listening", "weight": "0.10", "modalities": ["interactive_spoken"]},
        ],
    }

    policy = EnglishDimensionPolicyConfig.model_validate(payload)
    assert sum((item.weight for item in policy.dimensions), Decimal()) == Decimal("1")

    with pytest.raises(ValidationError):
        EnglishDimensionPolicyConfig.model_validate({**payload, "accent_scored": True})
    with pytest.raises(ValidationError, match="six English dimensions"):
        EnglishDimensionPolicyConfig.model_validate(
            {**payload, "dimensions": payload["dimensions"][:-1]}
        )


def test_v2_release_loads_with_v1_scoring_and_phase1_contracts(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "phase-1-six-week-v1"
    _write_v2_release(release_dir)

    bundle = load_config_bundle(release_dir)

    assert bundle.schema_version == 1
    assert bundle.roadmap_schema_version == 2
    assert bundle.roadmap_version == "phase-1-six-week-v1"
    assert bundle.program.program_key == "tam_phase_1"
    assert bundle.lineage is not None
    assert len(bundle.interview_queue) == 30
    assert bundle.coverage is not None
    assert len(bundle.roadmap_tasks) == 1


def test_v2_release_cannot_seed_scoring_even_before_session_use(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "phase-1-six-week-v1"
    _write_v2_release(release_dir)
    bundle = load_config_bundle(release_dir)

    with pytest.raises(SeedConfigError, match="roadmap-only release cannot seed scoring"):
        asyncio.run(seed_config(bundle, owner_id=None, session=None, apply=True))
    with pytest.raises(SeedConfigError, match="roadmap-only release cannot seed scoring"):
        asyncio.run(_apply(release_dir, "not-a-database-url"))


def test_release_registry_requires_exact_key_and_hash_and_is_not_recursive(
    tmp_path: Path,
) -> None:
    legacy_dir = tmp_path / "config"
    legacy_dir.mkdir()
    for source in CONFIG_DIR.glob("*.yaml"):
        shutil.copyfile(source, legacy_dir / source.name)
    releases_dir = legacy_dir / "releases"
    release_dir = releases_dir / "phase-1-six-week-v1"
    _write_v2_release(release_dir)
    nested = releases_dir / "ignored" / "nested"
    _write_v2_release(nested)

    registry = RoadmapReleaseRegistry.load(
        legacy_config_dir=legacy_dir,
        releases_dir=releases_dir,
    )
    phase1 = load_config_bundle(release_dir)

    assert (
        registry.resolve(
            roadmap_version="phase-1-six-week-v1",
            content_hash=phase1.content_hash.hex(),
        ).content_hash
        == phase1.content_hash
    )
    with pytest.raises(ConfigError, match="exact roadmap release"):
        registry.resolve(
            roadmap_version="phase-1-six-week-v1",
            content_hash="0" * 64,
        )


def test_validate_roadmap_release_cli_reports_v2_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release_dir = tmp_path / "phase-1-six-week-v1"
    _write_v2_release(release_dir)

    result = cli_main(
        [
            "validate-roadmap-release",
            "--release-dir",
            str(release_dir),
            "--legacy-config-dir",
            str(CONFIG_DIR),
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "coverage_assignments": 1,
        "coverage_requirements": 1,
        "interview_questions": 30,
        "nominal_minutes": 15,
        "program_key": "tam_phase_1",
        "roadmap_schema_version": 2,
        "roadmap_version": "phase-1-six-week-v1",
        "saturdays": 0,
        "study_days": 1,
        "weekday_days": 1,
    }
