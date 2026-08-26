from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import ConfigError, load_config_bundle

CONFIG_DIR = Path(__file__).parents[5] / "config"

EXPECTED_SKILLS = {
    "api_integration_architecture": ("3.0", "3.0", "3.25"),
    "structured_troubleshooting": ("2.0", "2.5", "3.0"),
    "sql_reconciliation": ("1.0", "2.0", "2.75"),
    "distributed_systems_reliability": ("2.0", "2.5", "3.0"),
    "payments_fintech_systems": ("2.0", "2.5", "3.0"),
    "technical_discovery": ("2.0", "2.5", "3.0"),
    "incident_escalation_management": ("2.0", "2.5", "3.0"),
    "implementation_project_management": ("2.0", "2.5", "2.75"),
    "proactive_account_strategy": ("2.0", "2.5", "2.75"),
    "executive_communication": ("1.0", "2.0", "3.0"),
    "cross_functional_influence": ("2.0", "2.5", "2.75"),
    "business_value_framing": ("1.0", "2.0", "3.0"),
    "technical_writing": ("1.0", "2.0", "2.75"),
    "tam_english": ("1.0", "2.0", "2.75"),
}

EXPECTED_EXERCISES = {
    "official_reading",
    "sql_guided_lesson",
    "sql_production_lab",
    "sql_no_ai_timed_assessment",
    "integration_diagram_and_explanation",
    "architecture_design_case",
    "api_failure_mode_analysis",
    "webhook_reliability_design",
    "troubleshooting_case",
    "oauth_security_troubleshooting",
    "technical_discovery_roleplay",
    "payment_lifecycle_case",
    "payment_reconciliation_case",
    "incident_simulation",
    "customer_incident_update",
    "internal_engineering_escalation",
    "postmortem_rca",
    "observability_health_dashboard",
    "implementation_plan",
    "project_kickoff_followup",
    "launch_readiness_decision",
    "account_plan_90_day",
    "technical_health_review_qbr",
    "audience_switching_explanation",
    "architecture_presentation",
    "customer_pushback_or_bad_news",
    "cross_functional_conflict_case",
    "behavioral_story_practice",
    "tell_me_about_yourself",
    "portfolio_triage",
    "technical_writing_timed",
    "full_tam_gauntlet",
    "company_product_research",
    "application_or_outreach",
}
EXPECTED_IMPACTS = {
    "official_reading": {},
    "sql_guided_lesson": {"sql_reconciliation": "0.35"},
    "sql_production_lab": {
        "sql_reconciliation": "1.00",
        "structured_troubleshooting": "0.25",
        "business_value_framing": "0.10",
    },
    "sql_no_ai_timed_assessment": {"sql_reconciliation": "1.00", "tam_english": "0.15"},
    "integration_diagram_and_explanation": {
        "api_integration_architecture": "1.00",
        "distributed_systems_reliability": "0.50",
        "technical_discovery": "0.40",
        "business_value_framing": "0.40",
        "tam_english": "0.40",
    },
    "architecture_design_case": {
        "api_integration_architecture": "1.00",
        "distributed_systems_reliability": "0.80",
        "technical_discovery": "0.60",
        "business_value_framing": "0.40",
        "implementation_project_management": "0.30",
        "executive_communication": "0.30",
        "tam_english": "0.40",
    },
    "api_failure_mode_analysis": {
        "distributed_systems_reliability": "1.00",
        "api_integration_architecture": "0.80",
        "structured_troubleshooting": "0.60",
        "technical_writing": "0.20",
        "sql_reconciliation": "0.20",
    },
    "webhook_reliability_design": {
        "api_integration_architecture": "1.00",
        "distributed_systems_reliability": "1.00",
        "structured_troubleshooting": "0.40",
        "incident_escalation_management": "0.30",
        "sql_reconciliation": "0.20",
    },
    "troubleshooting_case": {
        "structured_troubleshooting": "1.00",
        "distributed_systems_reliability": "0.50",
        "api_integration_architecture": "0.50",
        "incident_escalation_management": "0.40",
        "business_value_framing": "0.30",
        "tam_english": "0.40",
    },
    "oauth_security_troubleshooting": {
        "structured_troubleshooting": "1.00",
        "api_integration_architecture": "0.80",
        "distributed_systems_reliability": "0.30",
        "incident_escalation_management": "0.30",
        "executive_communication": "0.30",
        "tam_english": "0.30",
    },
    "technical_discovery_roleplay": {
        "technical_discovery": "1.00",
        "business_value_framing": "0.70",
        "api_integration_architecture": "0.50",
        "executive_communication": "0.40",
        "tam_english": "0.70",
    },
    "payment_lifecycle_case": {
        "payments_fintech_systems": "1.00",
        "distributed_systems_reliability": "0.50",
        "business_value_framing": "0.50",
        "sql_reconciliation": "0.30",
        "tam_english": "0.40",
    },
    "payment_reconciliation_case": {
        "payments_fintech_systems": "1.00",
        "sql_reconciliation": "1.00",
        "structured_troubleshooting": "0.50",
        "business_value_framing": "0.60",
        "technical_writing": "0.30",
    },
    "incident_simulation": {
        "incident_escalation_management": "1.00",
        "structured_troubleshooting": "0.80",
        "executive_communication": "0.70",
        "cross_functional_influence": "0.60",
        "business_value_framing": "0.60",
        "tam_english": "0.70",
    },
    "customer_incident_update": {
        "technical_writing": "1.00",
        "incident_escalation_management": "0.80",
        "executive_communication": "0.60",
        "business_value_framing": "0.50",
        "tam_english": "0.60",
    },
    "internal_engineering_escalation": {
        "technical_writing": "1.00",
        "incident_escalation_management": "0.80",
        "cross_functional_influence": "0.80",
        "business_value_framing": "0.50",
        "structured_troubleshooting": "0.40",
    },
    "postmortem_rca": {
        "incident_escalation_management": "1.00",
        "technical_writing": "1.00",
        "structured_troubleshooting": "0.60",
        "distributed_systems_reliability": "0.60",
        "business_value_framing": "0.50",
        "implementation_project_management": "0.30",
    },
    "observability_health_dashboard": {
        "proactive_account_strategy": "0.80",
        "structured_troubleshooting": "0.70",
        "business_value_framing": "0.70",
        "distributed_systems_reliability": "0.60",
        "incident_escalation_management": "0.60",
        "executive_communication": "0.50",
    },
    "implementation_plan": {
        "implementation_project_management": "1.00",
        "technical_writing": "0.70",
        "technical_discovery": "0.60",
        "cross_functional_influence": "0.50",
        "business_value_framing": "0.40",
        "proactive_account_strategy": "0.30",
    },
    "project_kickoff_followup": {
        "technical_writing": "1.00",
        "implementation_project_management": "0.80",
        "cross_functional_influence": "0.40",
        "technical_discovery": "0.30",
        "tam_english": "0.50",
    },
    "launch_readiness_decision": {
        "implementation_project_management": "1.00",
        "incident_escalation_management": "0.80",
        "cross_functional_influence": "0.80",
        "executive_communication": "0.80",
        "business_value_framing": "0.80",
        "tam_english": "0.60",
        "proactive_account_strategy": "0.40",
    },
    "account_plan_90_day": {
        "proactive_account_strategy": "1.00",
        "business_value_framing": "0.90",
        "technical_writing": "0.70",
        "executive_communication": "0.60",
        "cross_functional_influence": "0.50",
        "implementation_project_management": "0.40",
    },
    "technical_health_review_qbr": {
        "proactive_account_strategy": "1.00",
        "executive_communication": "1.00",
        "business_value_framing": "1.00",
        "tam_english": "0.80",
        "technical_writing": "0.60",
        "incident_escalation_management": "0.30",
    },
    "audience_switching_explanation": {
        "executive_communication": "1.00",
        "tam_english": "0.90",
        "business_value_framing": "0.80",
    },
    "architecture_presentation": {
        "executive_communication": "0.70",
        "tam_english": "0.80",
        "api_integration_architecture": "0.60",
        "business_value_framing": "0.50",
    },
    "customer_pushback_or_bad_news": {
        "cross_functional_influence": "0.80",
        "tam_english": "0.80",
        "executive_communication": "0.70",
        "incident_escalation_management": "0.50",
        "business_value_framing": "0.40",
    },
    "cross_functional_conflict_case": {
        "cross_functional_influence": "1.00",
        "business_value_framing": "0.80",
        "tam_english": "0.70",
        "executive_communication": "0.60",
        "proactive_account_strategy": "0.50",
        "incident_escalation_management": "0.30",
    },
    "behavioral_story_practice": {
        "tam_english": "0.70",
        "executive_communication": "0.40",
        "business_value_framing": "0.30",
    },
    "tell_me_about_yourself": {
        "tam_english": "1.00",
        "executive_communication": "0.50",
        "business_value_framing": "0.50",
    },
    "portfolio_triage": {
        "proactive_account_strategy": "0.90",
        "cross_functional_influence": "0.90",
        "incident_escalation_management": "0.80",
        "business_value_framing": "0.80",
        "executive_communication": "0.60",
        "tam_english": "0.60",
        "structured_troubleshooting": "0.40",
    },
    "technical_writing_timed": {
        "technical_writing": "1.00",
        "executive_communication": "0.50",
        "business_value_framing": "0.50",
        "tam_english": "0.50",
    },
    "full_tam_gauntlet": {},
    "company_product_research": {},
    "application_or_outreach": {},
}


@pytest.fixture(scope="module")
def config_bundle():
    return load_config_bundle(CONFIG_DIR)


def test_normative_skill_contract(config_bundle) -> None:
    assert len(config_bundle.skills) == 14
    assert {
        skill.slug: (
            str(skill.baseline),
            str(skill.month_one_target),
            str(skill.final_target),
        )
        for skill in config_bundle.skills
    } == EXPECTED_SKILLS


def test_complete_normative_exercise_mapping(config_bundle) -> None:
    assert {exercise.slug for exercise in config_bundle.exercise_types} == EXPECTED_EXERCISES
    assert {
        exercise.slug: {
            slug: str(impact.weight) for slug, impact in exercise.skill_impacts.items()
        }
        for exercise in config_bundle.exercise_types
    } == EXPECTED_IMPACTS
    assert config_bundle.exercise("official_reading").skill_impacts == {}
    assert config_bundle.exercise("company_product_research").skill_impacts == {}
    assert config_bundle.exercise("application_or_outreach").skill_impacts == {}
    assert config_bundle.exercise("sql_production_lab").skill_impacts[
        "sql_reconciliation"
    ].weight == Decimal("1.00")


def test_english_and_dynamic_impacts_are_conditional(config_bundle) -> None:
    for exercise in config_bundle.exercise_types:
        english = exercise.skill_impacts.get("tam_english")
        if english is not None:
            assert english.condition in {
                "spoken_or_written_english",
                "explained_aloud_in_english",
            }

    audience = config_bundle.exercise("audience_switching_explanation")
    assert audience.required_precommit_field == "domain_competency_slug"
    assert audience.selected_impact == Decimal("0.30")
    assert audience.allowed_selected_competencies
    behavioral = config_bundle.exercise("behavioral_story_practice")
    assert behavioral.required_precommit_field == "story_competency_slug"
    assert behavioral.selected_impact == Decimal("0.40")


def test_gauntlet_children_are_fully_linked(config_bundle) -> None:
    gauntlet = config_bundle.exercise("full_tam_gauntlet")
    assert gauntlet.component_scoring_required is True
    assert len(gauntlet.child_exercise_type_refs) == 9
    assert all(
        config_bundle.exercise(child.exercise_type).mapping_version == child.mapping_version
        for child in gauntlet.child_exercise_type_refs
    )


def test_portfolio_and_formula_match_approved_contract(config_bundle) -> None:
    assert sum(item.maximum for item in config_bundle.portfolio.dimensions) == Decimal("20")
    assert config_bundle.formula.prior_weight == Decimal("2.0")
    assert config_bundle.formula.latest_qualifying_events == 12
    assert config_bundle.formula.full_weight_same_day_limit == 2
    assert config_bundle.formula.practice_mode_factors.model_dump() == {
        "exposure_only": Decimal("0.00"),
        "guided_practice": Decimal("0.35"),
        "independent_practice": Decimal("0.65"),
        "timed_assessment": Decimal("0.90"),
        "mock_interview": Decimal("1.00"),
        "real_interview": Decimal("1.00"),
    }
    assert config_bundle.formula.assistance_factors.model_dump() == {
        "no_ai": Decimal("1.00"),
        "ai_after_committed_attempt": Decimal("1.00"),
        "ai_interviewer_only": Decimal("1.00"),
        "ai_hints_during_attempt": Decimal("0.75"),
        "ai_co_created": Decimal("0.40"),
        "ai_generated": Decimal("0.10"),
    }
    assert config_bundle.formula.evaluator_factors.model_dump() == {
        "self": Decimal("0.60"),
        "ai_rubric_reviewer": Decimal("0.75"),
        "peer": Decimal("0.85"),
        "human_coach": Decimal("0.95"),
        "explicit_interviewer_feedback": Decimal("1.00"),
    }
    assert config_bundle.formula.difficulty_factors.model_dump() == {
        "introductory": Decimal("0.80"),
        "standard": Decimal("1.00"),
        "advanced": Decimal("1.15"),
    }
    assert config_bundle.formula.qualifying_modes == {
        "independent_practice",
        "timed_assessment",
        "mock_interview",
        "real_interview",
    }
    assert config_bundle.formula.qualifying_assistance == {
        "no_ai",
        "ai_after_committed_attempt",
        "ai_interviewer_only",
    }
    assert config_bundle.formula.independent_practice_requires_attempt_a is True
    assert config_bundle.formula.attempt_b_qualifies is False


def test_month_one_task_map_is_explicit_and_time_bounded(config_bundle) -> None:
    assert len(config_bundle.roadmap_tasks) == 138
    assert len({task.stable_id for task in config_bundle.roadmap_tasks}) == 138
    weekdays = {(task.week, task.day) for task in config_bundle.roadmap_tasks if task.day % 6}
    saturdays = {(task.week, task.day) for task in config_bundle.roadmap_tasks if task.day % 6 == 0}
    assert all(
        sum(
            task.timebox_minutes
            for task in config_bundle.roadmap_tasks
            if (task.week, task.day) == key
        )
        == 240
        for key in weekdays
    )
    assert all(
        sum(
            task.timebox_minutes
            for task in config_bundle.roadmap_tasks
            if (task.week, task.day) == key
        )
        == 120
        for key in saturdays
    )
    assert all(task.exercise_type in EXPECTED_EXERCISES for task in config_bundle.roadmap_tasks)
    assert all(task.mapping_version == "seed-v1" for task in config_bundle.roadmap_tasks)


def test_hash_is_canonical_and_stable(config_bundle) -> None:
    again = load_config_bundle(CONFIG_DIR)
    assert config_bundle.content_hash == again.content_hash
    assert len(config_bundle.content_hash) == 32
    assert config_bundle.version_key.startswith("seed-v1-")


def test_invalid_mapping_reports_source_location() -> None:
    fixture_dir = Path(__file__).parents[2] / "fixtures" / "config"
    with pytest.raises(ConfigError, match=r"invalid-mapping\.yaml:\d+:\d+.*unknown skill"):
        load_config_bundle(CONFIG_DIR, exercise_types_path=fixture_dir / "invalid-mapping.yaml")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("weight: 0.35", "weight: 1.01", "less than or equal to 1"),
        ("tags: [webhooks, idempotency, retries_backoff]", "tags: [not_allowed]", "unknown tag"),
        ("slug: sql_guided_lesson", "slug: official_reading", "duplicate slug"),
        (
            "exercise_type: portfolio_triage, mapping_version: seed-v1",
            "exercise_type: missing_child, mapping_version: seed-v1",
            "unknown child exercise",
        ),
    ],
)
def test_invalid_exercise_contracts_fail_with_location(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    mapping = fixture_dir / "tam-exercise-types.yaml"
    original = mapping.read_text(encoding="utf-8")
    assert old in original
    mapping.write_text(original.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=rf"tam-exercise-types\.yaml:\d+:\d+.*{message}"):
        load_config_bundle(fixture_dir)


def test_unknown_fields_and_duplicate_yaml_keys_fail_with_location(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    skills = fixture_dir / "tam-skills.yaml"
    text = skills.read_text(encoding="utf-8")
    skills.write_text(
        text.replace("    name:", "    unknown_field: true\n    name:", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"tam-skills\.yaml:\d+:\d+.*Extra inputs"):
        load_config_bundle(fixture_dir)

    skills.write_text(
        text.replace("schema_version: 1", "schema_version: 1\nschema_version: 1"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"tam-skills\.yaml:2:1.*duplicate key"):
        load_config_bundle(fixture_dir)


def test_unknown_roadmap_day_group_field_fails_with_location(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    roadmap = fixture_dir / "tam-roadmap-task-map.yaml"
    text = roadmap.read_text(encoding="utf-8")
    roadmap.write_text(
        text.replace("    day: 1", "    day: 1\n    unexpected: true", 1),
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigError,
        match=r"tam-roadmap-task-map\.yaml:\d+:\d+.*unexpected.*not permitted",
    ):
        load_config_bundle(fixture_dir)


def test_partial_release_version_bump_is_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    mapping = fixture_dir / "tam-exercise-types.yaml"
    text = mapping.read_text(encoding="utf-8")
    mapping.write_text(
        text.replace("mapping_version: seed-v1", "mapping_version: seed-v2"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"versions must match"):
        load_config_bundle(fixture_dir)
