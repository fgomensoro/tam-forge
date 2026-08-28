from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.orm import make_transient_to_detached

MIGRATION_PATH = Path("apps/backend/alembic/versions/20260825_0004_evidence_scoring.py")
EXPECTED_TABLES = {
    "config_seed_versions",
    "competencies",
    "exercise_type_versions",
    "exercise_skill_mappings",
    "rubric_versions",
    "rubric_dimensions",
    "rubric_evaluations",
    "rubric_dimension_scores",
    "skill_evidence_events",
    "skill_snapshots",
    "portfolio_judgment_scores",
}
CANONICAL_COMPETENCY_SLUGS = {
    "api_integration_architecture",
    "structured_troubleshooting",
    "sql_reconciliation",
    "distributed_systems_reliability",
    "payments_fintech_systems",
    "technical_discovery",
    "incident_escalation_management",
    "implementation_project_management",
    "proactive_account_strategy",
    "executive_communication",
    "cross_functional_influence",
    "business_value_framing",
    "technical_writing",
    "tam_english",
}


def _load_migration() -> object:
    assert MIGRATION_PATH.exists(), "evidence scoring migration must exist"
    spec = importlib.util.spec_from_file_location("evidence_scoring_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_fresh_python(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )


def _offline_sql(direction: str, revision: str) -> str:
    output = StringIO()
    config = Config("apps/backend/alembic.ini", output_buffer=output)
    config.attributes["database_url"] = URL.create(
        "postgresql+psycopg",
        username="tamforge",
        password="offline-evidence-contract-password",
        host="127.0.0.1",
        port=54329,
        database="tamforge_test",
    ).render_as_string(hide_password=False)
    if direction == "upgrade":
        command.upgrade(config, revision, sql=True)
    else:
        command.downgrade(config, revision, sql=True)
    return output.getvalue()


def _constraint_names(table: sa.Table) -> set[str]:
    return {item.name for item in table.constraints if item.name is not None}


def _indexed_prefixes(table: sa.Table) -> set[tuple[str, ...]]:
    result = {tuple(column.name for column in index.columns) for index in table.indexes}
    result.update(
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
    )
    return result


class _StubResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def one_or_none(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalar_one(self) -> object:
        return self.value


class _StubConnection:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.statements: list[object] = []

    def execute(self, statement: object) -> _StubResult:
        self.statements.append(statement)
        assert self.values, "stub connection received an unexpected query"
        return _StubResult(self.values.pop(0))


def _skill_event(**overrides: object) -> object:
    from tamforge_backend.evidence.models import SkillEvidenceEvent

    now = datetime.now(UTC)
    values: dict[str, object] = {
        "owner_id": 1,
        "config_seed_version_id": 1,
        "activity_instance_id": 1,
        "attempt_id": 1,
        "rubric_evaluation_id": 1,
        "rubric_version_id": 1,
        "exercise_type_version_id": 1,
        "competency_id": 1,
        "formula_version": "skill-v1",
        "practice_mode": "independent_practice",
        "assistance_code": "no_ai",
        "evaluator_kind": "ai_rubric_reviewer",
        "difficulty_code": "standard",
        "raw_dimension_scores": {
            "schema_version": 1,
            "scores": [{"dimension_score_id": 1, "score": 3, "weight": 1}],
        },
        "raw_score_numerator": Decimal("3.000000"),
        "raw_score_denominator": Decimal("1.000000"),
        "performance_score": Decimal("3.000"),
        "exercise_skill_impact": Decimal("1.000000"),
        "practice_mode_factor": Decimal("0.650000"),
        "ai_independence_factor": Decimal("1.000000"),
        "evaluator_confidence_factor": Decimal("0.750000"),
        "difficulty_factor": Decimal("1.000000"),
        "effective_weight": Decimal("0.487500"),
        "qualifying_for_level": True,
        "qualification_reason_code": "qualifies",
        "explanation": {
            "schema_version": 1,
            "summary_code": "independent_scored_evidence",
            "dimension_score_ids": [1],
            "discount_codes": [],
        },
        "occurred_at": now,
        "created_at": now,
    }
    values.update(overrides)
    return SkillEvidenceEvent(**values)


def test_revision_contract_is_exact_and_linear() -> None:
    migration = _load_migration()

    assert migration.revision == "20260825_0004_evidence_scoring"
    assert migration.down_revision == "20260825_0003_study_activities"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_evidence_models_register_lazily_without_import_cycles() -> None:
    result = _run_fresh_python(
        "from tamforge_backend.models import Base, load_all_models; "
        "assert not Base.metadata.tables; "
        "load_all_models(); "
        f"assert {EXPECTED_TABLES!r} <= set(Base.metadata.tables)"
    )

    assert result.returncode == 0, result.stderr


def test_models_expose_required_tables_columns_and_types() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    expected_columns = {
        "config_seed_versions": {
            "id",
            "owner_id",
            "version_key",
            "schema_version",
            "content_hash",
            "canonical_payload",
            "created_at",
        },
        "competencies": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "slug",
            "name",
            "baseline_level",
            "month_one_target",
            "final_target",
            "created_at",
        },
        "exercise_type_versions": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "exercise_type",
            "mapping_version",
            "evidence_mode",
            "condition_code",
            "tags",
            "created_at",
        },
        "exercise_skill_mappings": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "exercise_type_version_id",
            "competency_id",
            "impact",
            "condition_code",
            "created_at",
        },
        "rubric_versions": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "rubric_key",
            "version_key",
            "name",
            "scope_code",
            "scale_min",
            "scale_max",
            "created_at",
        },
        "rubric_dimensions": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "dimension_key",
            "name",
            "weight",
            "max_score",
            "ordinal",
            "availability_rule_code",
            "created_at",
        },
        "rubric_evaluations": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "evaluator_kind",
            "evaluation_schema_version",
            "input_manifest",
            "evaluated_at",
            "created_at",
        },
        "rubric_dimension_scores": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "rubric_evaluation_id",
            "rubric_version_id",
            "rubric_dimension_id",
            "availability",
            "score",
            "weight_used",
            "evidence_manifest",
            "created_at",
        },
        "skill_evidence_events": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_evaluation_id",
            "rubric_version_id",
            "exercise_type_version_id",
            "competency_id",
            "formula_version",
            "practice_mode",
            "assistance_code",
            "evaluator_kind",
            "difficulty_code",
            "raw_dimension_scores",
            "raw_score_numerator",
            "raw_score_denominator",
            "performance_score",
            "exercise_skill_impact",
            "practice_mode_factor",
            "ai_independence_factor",
            "evaluator_confidence_factor",
            "difficulty_factor",
            "effective_weight",
            "qualifying_for_level",
            "qualification_reason_code",
            "explanation",
            "occurred_at",
            "created_at",
        },
        "skill_snapshots": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "competency_id",
            "formula_version",
            "snapshot_date",
            "snapshot_sequence",
            "estimated_level",
            "confidence_code",
            "trend_code",
            "recency_code",
            "baseline_target_gap",
            "month_one_target_gap",
            "final_target_gap",
            "total_effective_weight",
            "qualifying_event_count",
            "exercise_type_count",
            "last_strong_evidence_date",
            "contributing_event_manifest",
            "confidence_basis",
            "trend_basis",
            "created_at",
        },
        "portfolio_judgment_scores": {
            "id",
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_evaluation_id",
            "rubric_version_id",
            "formula_version",
            "impact_risk_assessment",
            "explicit_prioritization",
            "delegation_ownership",
            "communication_control",
            "proactive_work_protection",
            "evidence_based_reprioritization",
            "english_clarity",
            "total_score",
            "trend_basis",
            "scored_at",
            "created_at",
        },
    }

    nullable_columns = {
        ("rubric_evaluations", "attempt_id"),
        ("rubric_dimension_scores", "score"),
        ("rubric_dimension_scores", "weight_used"),
        ("skill_evidence_events", "attempt_id"),
        ("skill_snapshots", "last_strong_evidence_date"),
    }
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    for table_name, columns in expected_columns.items():
        table = Base.metadata.tables[table_name]
        assert set(table.c.keys()) == columns
        assert isinstance(table.c.id.type, sa.BigInteger)
        assert table.c.id.identity is not None and table.c.id.identity.always is True
        for column in table.c:
            assert column.nullable is ((table_name, column.name) in nullable_columns)

    numeric_columns = {
        "competencies": {"baseline_level", "month_one_target", "final_target"},
        "exercise_skill_mappings": {"impact"},
        "rubric_versions": {"scale_min", "scale_max"},
        "rubric_dimensions": {"weight", "max_score"},
        "rubric_dimension_scores": {"score", "weight_used"},
        "skill_evidence_events": {
            "raw_score_numerator",
            "raw_score_denominator",
            "performance_score",
            "exercise_skill_impact",
            "practice_mode_factor",
            "ai_independence_factor",
            "evaluator_confidence_factor",
            "difficulty_factor",
            "effective_weight",
        },
        "skill_snapshots": {
            "estimated_level",
            "baseline_target_gap",
            "month_one_target_gap",
            "final_target_gap",
            "total_effective_weight",
        },
        "portfolio_judgment_scores": {
            "impact_risk_assessment",
            "explicit_prioritization",
            "delegation_ownership",
            "communication_control",
            "proactive_work_protection",
            "evidence_based_reprioritization",
            "english_clarity",
            "total_score",
        },
    }
    for table_name, columns in numeric_columns.items():
        for column_name in columns:
            assert isinstance(Base.metadata.tables[table_name].c[column_name].type, sa.Numeric)

    json_columns = {
        "exercise_type_versions": {"tags"},
        "rubric_evaluations": {"input_manifest"},
        "rubric_dimension_scores": {"evidence_manifest"},
        "skill_evidence_events": {"raw_dimension_scores", "explanation"},
        "skill_snapshots": {
            "contributing_event_manifest",
            "confidence_basis",
            "trend_basis",
        },
        "portfolio_judgment_scores": {"trend_basis"},
    }
    for table_name, columns in json_columns.items():
        for column_name in columns:
            assert isinstance(
                Base.metadata.tables[table_name].c[column_name].type,
                postgresql.JSONB,
            )


def test_competency_configuration_supports_all_fourteen_slugs_without_current_score() -> None:
    from tamforge_backend.evidence.models import Competency

    assert len(CANONICAL_COMPETENCY_SLUGS) == 14
    assert "current_score" not in Competency.__table__.c
    assert "estimated_level" not in Competency.__table__.c
    assert (
        "owner_id",
        "config_seed_version_id",
        "slug",
    ) in _indexed_prefixes(Competency.__table__)


def test_owner_version_activity_attempt_rubric_relations_are_composite_and_restrictive() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    required_targets = {
        "competencies": {("owner_id", "config_seed_version_id")},
        "exercise_type_versions": {("owner_id", "config_seed_version_id")},
        "exercise_skill_mappings": {
            ("owner_id", "config_seed_version_id", "exercise_type_version_id"),
            ("owner_id", "config_seed_version_id", "competency_id"),
        },
        "rubric_versions": {("owner_id", "config_seed_version_id")},
        "rubric_dimensions": {
            ("owner_id", "config_seed_version_id", "rubric_version_id")
        },
        "rubric_evaluations": {
            ("owner_id", "activity_instance_id"),
            ("owner_id", "activity_instance_id", "attempt_id"),
            ("owner_id", "config_seed_version_id", "rubric_version_id"),
        },
        "rubric_dimension_scores": {
            (
                "owner_id",
                "config_seed_version_id",
                "rubric_version_id",
                "rubric_evaluation_id",
            ),
            (
                "owner_id",
                "config_seed_version_id",
                "rubric_version_id",
                "rubric_dimension_id",
            ),
        },
        "skill_evidence_events": {
            ("owner_id", "activity_instance_id"),
            ("owner_id", "activity_instance_id", "attempt_id"),
            (
                "owner_id",
                "config_seed_version_id",
                "activity_instance_id",
                "attempt_id",
                "rubric_version_id",
                "rubric_evaluation_id",
            ),
            ("owner_id", "config_seed_version_id", "exercise_type_version_id"),
            ("owner_id", "config_seed_version_id", "competency_id"),
        },
        "skill_snapshots": {
            ("owner_id", "config_seed_version_id", "competency_id")
        },
        "portfolio_judgment_scores": {
            ("owner_id", "activity_instance_id", "attempt_id"),
            (
                "owner_id",
                "config_seed_version_id",
                "activity_instance_id",
                "attempt_id",
                "rubric_version_id",
                "rubric_evaluation_id",
            ),
        },
    }

    for table_name, expected_fk_columns in required_targets.items():
        table = Base.metadata.tables[table_name]
        actual = {
            tuple(element.parent.name for element in constraint.elements)
            for constraint in table.foreign_key_constraints
        }
        assert expected_fk_columns <= actual
        assert all(
            constraint.ondelete == "RESTRICT"
            for constraint in table.foreign_key_constraints
        )
        prefixes = _indexed_prefixes(table)
        assert all(columns in prefixes for columns in expected_fk_columns)


def test_constraints_are_named_and_encode_ranges_shapes_and_reproducibility() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    expected = {
        "config_seed_versions": {
            "ck_config_seed_versions_version_key_safe",
            "ck_config_seed_versions_schema_version_positive",
            "ck_config_seed_versions_content_hash_length",
            "ck_config_seed_versions_canonical_payload_valid",
        },
        "competencies": {"ck_competencies_slug_safe", "ck_competencies_targets_bounded"},
        "exercise_type_versions": {
            "ck_exercise_type_versions_exercise_type_safe",
            "ck_exercise_type_versions_mapping_version_safe",
            "ck_exercise_type_versions_evidence_mode_allowed",
            "ck_exercise_type_versions_condition_code_allowed",
            "ck_exercise_type_versions_tags_valid",
        },
        "exercise_skill_mappings": {
            "ck_exercise_skill_mappings_impact_bounded",
            "ck_exercise_skill_mappings_condition_code_allowed",
        },
        "rubric_versions": {
            "ck_rubric_versions_keys_safe",
            "ck_rubric_versions_scope_code_allowed",
            "ck_rubric_versions_scale_coherent",
        },
        "rubric_dimensions": {
            "ck_rubric_dimensions_dimension_key_safe",
            "ck_rubric_dimensions_weight_positive",
            "ck_rubric_dimensions_max_score_bounded",
            "ck_rubric_dimensions_ordinal_nonnegative",
            "ck_rubric_dimensions_availability_rule_allowed",
        },
        "rubric_evaluations": {
            "ck_rubric_evaluations_evaluator_kind_allowed",
            "ck_rubric_evaluations_evaluation_schema_version_positive",
            "ck_rubric_evaluations_input_manifest_valid",
            "ck_rubric_evaluations_created_after_evaluation",
        },
        "rubric_dimension_scores": {
            "ck_rubric_dimension_scores_availability_allowed",
            "ck_rubric_dimension_scores_availability_score_coherent",
            "ck_rubric_dimension_scores_weight_used_bounded",
            "ck_rubric_dimension_scores_evidence_manifest_valid",
        },
        "skill_evidence_events": {
            "ck_skill_evidence_events_formula_version_safe",
            "ck_skill_evidence_events_practice_mode_allowed",
            "ck_skill_evidence_events_assistance_code_allowed",
            "ck_skill_evidence_events_evaluator_kind_allowed",
            "ck_skill_evidence_events_difficulty_code_allowed",
            "ck_skill_evidence_events_raw_dimension_scores_valid",
            "ck_skill_evidence_events_raw_score_terms_coherent",
            "ck_skill_evidence_events_factor_ranges",
            "ck_skill_evidence_events_effective_weight_reproducible",
            "ck_skill_evidence_events_qualification_reason_allowed",
            "ck_skill_evidence_events_qualification_coherent",
            "ck_skill_evidence_events_explanation_valid",
            "ck_skill_evidence_events_created_after_occurrence",
        },
        "skill_snapshots": {
            "ck_skill_snapshots_formula_version_safe",
            "ck_skill_snapshots_snapshot_sequence_positive",
            "ck_skill_snapshots_estimated_level_bounded",
            "ck_skill_snapshots_confidence_code_allowed",
            "ck_skill_snapshots_trend_code_allowed",
            "ck_skill_snapshots_recency_code_allowed",
            "ck_skill_snapshots_target_gaps_bounded",
            "ck_skill_snapshots_basis_counts_nonnegative",
            "ck_skill_snapshots_contributing_event_manifest_valid",
            "ck_skill_snapshots_confidence_basis_valid",
            "ck_skill_snapshots_trend_basis_valid",
        },
        "portfolio_judgment_scores": {
            "ck_portfolio_judgment_scores_formula_version_safe",
            "ck_portfolio_judgment_scores_components_bounded",
            "ck_portfolio_judgment_scores_total_bounded",
            "ck_portfolio_judgment_scores_total_reproducible",
            "ck_portfolio_judgment_scores_trend_basis_valid",
            "ck_portfolio_judgment_scores_created_after_score",
        },
    }

    for table_name, names in expected.items():
        assert names <= _constraint_names(Base.metadata.tables[table_name])


def test_formula_and_configuration_versions_are_mandatory_everywhere() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    config_scoped = EXPECTED_TABLES - {"config_seed_versions"}
    for table_name in config_scoped:
        assert not Base.metadata.tables[table_name].c.config_seed_version_id.nullable
    for table_name in {
        "skill_evidence_events",
        "skill_snapshots",
        "portfolio_judgment_scores",
    }:
        assert not Base.metadata.tables[table_name].c.formula_version.nullable


def test_historical_occurrence_times_may_precede_ledger_insertion() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    expected_expressions = {
        "rubric_evaluations": "created_at >= evaluated_at",
        "skill_evidence_events": "created_at >= occurred_at",
        "portfolio_judgment_scores": "created_at >= scored_at",
    }
    for table_name, expression in expected_expressions.items():
        checks = {
            str(constraint.sqltext)
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        assert expression in checks


def test_one_evaluation_can_have_independent_scores_and_one_skill_per_event() -> None:
    from tamforge_backend.evidence.models import RubricDimensionScore, SkillEvidenceEvent

    score_table = RubricDimensionScore.__table__
    assert (
        "owner_id",
        "rubric_evaluation_id",
        "rubric_dimension_id",
    ) in _indexed_prefixes(score_table)
    event_table = SkillEvidenceEvent.__table__
    assert "competency_id" in event_table.c
    assert "competency_ids" not in event_table.c
    assert (
        "owner_id",
        "rubric_evaluation_id",
        "competency_id",
        "formula_version",
    ) in _indexed_prefixes(event_table)


def test_application_boundary_rejects_unstructured_manifests_and_nonreproducible_weight() -> None:
    from tamforge_backend.evidence.models import (
        EvidenceContractError,
        RubricEvaluation,
        SkillEvidenceEvent,
        _validate_structured_payloads,
        validate_skill_evidence_event,
    )

    now = datetime.now(UTC)
    unsafe_evaluation = RubricEvaluation(
        owner_id=1,
        config_seed_version_id=1,
        activity_instance_id=1,
        attempt_id=1,
        rubric_version_id=1,
        evaluator_kind="ai_rubric_reviewer",
        evaluation_schema_version=1,
        input_manifest={"schema_version": 1, "notes": "password=hunter2"},
        evaluated_at=now,
        created_at=now,
    )
    with pytest.raises(EvidenceContractError, match="structured evidence"):
        _validate_structured_payloads(None, None, unsafe_evaluation)

    event_record = SkillEvidenceEvent(
        owner_id=1,
        config_seed_version_id=1,
        activity_instance_id=1,
        attempt_id=1,
        rubric_evaluation_id=1,
        rubric_version_id=1,
        exercise_type_version_id=1,
        competency_id=1,
        formula_version="skill-v1",
        practice_mode="independent_practice",
        assistance_code="no_ai",
        evaluator_kind="ai_rubric_reviewer",
        difficulty_code="standard",
        raw_dimension_scores={
            "schema_version": 1,
            "scores": [{"dimension_score_id": 1, "score": 3, "weight": "secret"}],
        },
        raw_score_numerator=Decimal("3.000000"),
        raw_score_denominator=Decimal("1.000000"),
        performance_score=Decimal("3.000"),
        exercise_skill_impact=Decimal("1.000000"),
        practice_mode_factor=Decimal("0.650000"),
        ai_independence_factor=Decimal("1.000000"),
        evaluator_confidence_factor=Decimal("0.750000"),
        difficulty_factor=Decimal("1.000000"),
        effective_weight=Decimal("1.000000"),
        qualifying_for_level=True,
        qualification_reason_code="qualifies",
        explanation={
            "schema_version": 1,
            "summary_code": "independent_scored_evidence",
            "dimension_score_ids": [1],
            "discount_codes": [],
        },
        occurred_at=now,
        created_at=now,
    )
    with pytest.raises(EvidenceContractError, match="structured evidence"):
        validate_skill_evidence_event(None, None, event_record)

    event_record.raw_dimension_scores = {
        "schema_version": 1,
        "scores": [{"dimension_score_id": 1, "score": 3, "weight": 1}],
    }
    with pytest.raises(EvidenceContractError, match="effective evidence weight"):
        validate_skill_evidence_event(None, None, event_record)

    event_record.effective_weight = Decimal("0.487500")
    event_record.raw_score_numerator = Decimal("2.344500")
    event_record.performance_score = Decimal("2.345")
    with pytest.raises(EvidenceContractError, match="score terms"):
        validate_skill_evidence_event(None, None, event_record)

    event_record.raw_dimension_scores = {
        "schema_version": 1,
        "scores": [{"dimension_score_id": 1, "score": 2.3445, "weight": 1}],
    }
    validate_skill_evidence_event(None, None, event_record)


def test_skill_event_uses_configured_mode_and_activity_task_mapping() -> None:
    from tamforge_backend.evidence.models import (
        EvidenceContractError,
        validate_skill_evidence_event,
    )

    for configured_mode in ("guided_practice", "exposure_only"):
        configured_nonqualifying = _StubConnection(
            (
                configured_mode,
                "troubleshooting_case",
                "seed-v1",
                "troubleshooting_case",
                "seed-v1",
                Decimal("1.000000"),
                "always",
            )
        )
        with pytest.raises(EvidenceContractError, match="configured exercise mode"):
            validate_skill_evidence_event(
                None,
                configured_nonqualifying,  # type: ignore[arg-type]
                _skill_event(),
            )

    wrong_task_mapping = _StubConnection(
        (
            "independent_practice",
            "troubleshooting_case",
            "seed-v1",
            "sql_production_lab",
            "seed-v1",
            Decimal("1.000000"),
            "always",
        )
    )
    with pytest.raises(EvidenceContractError, match="activity task mapping"):
        validate_skill_evidence_event(None, wrong_task_mapping, _skill_event())  # type: ignore[arg-type]

    valid_lineage = _StubConnection(
        (
            "independent_practice",
            "troubleshooting_case",
            "seed-v1",
            "troubleshooting_case",
            "seed-v1",
            Decimal("1.000000"),
            "always",
        ),
        "attempt_a",
        "ai_rubric_reviewer",
        (Decimal("3.000"), Decimal("1.000000")),
    )
    validate_skill_evidence_event(None, valid_lineage, _skill_event())  # type: ignore[arg-type]
    assert valid_lineage.values == []

    missing_dimension = _StubConnection(
        (
            "independent_practice",
            "troubleshooting_case",
            "seed-v1",
            "troubleshooting_case",
            "seed-v1",
            Decimal("1.000000"),
            "always",
        ),
        "attempt_a",
        "ai_rubric_reviewer",
        None,
    )
    with pytest.raises(EvidenceContractError, match="immutable dimensions"):
        validate_skill_evidence_event(None, missing_dimension, _skill_event())  # type: ignore[arg-type]

    mismatched_dimension = _StubConnection(
        (
            "independent_practice",
            "troubleshooting_case",
            "seed-v1",
            "troubleshooting_case",
            "seed-v1",
            Decimal("1.000000"),
            "always",
        ),
        "attempt_a",
        "ai_rubric_reviewer",
        (Decimal("2.000"), Decimal("1.000000")),
    )
    with pytest.raises(EvidenceContractError, match="immutable dimensions"):
        validate_skill_evidence_event(
            None,
            mismatched_dimension,  # type: ignore[arg-type]
            _skill_event(),
        )


def test_qualification_reasons_are_exact_and_unscored_is_unrepresentable() -> None:
    from tamforge_backend.evidence.models import (
        QUALIFICATION_REASON_CODES,
        EvidenceContractError,
        _validate_qualification_reason,
    )

    assert "unscored" not in QUALIFICATION_REASON_CODES
    invalid_cases = (
        (
            _skill_event(
                qualifying_for_level=False,
                qualification_reason_code="nonqualifying_mode",
            ),
            "attempt_a",
            "always",
        ),
        (
            _skill_event(
                qualifying_for_level=False,
                qualification_reason_code="assisted_during_attempt",
            ),
            "attempt_a",
            "always",
        ),
        (
            _skill_event(
                qualifying_for_level=False,
                qualification_reason_code="missing_committed_attempt",
            ),
            "attempt_a",
            "always",
        ),
        (
            _skill_event(qualifying_for_level=False, qualification_reason_code="attempt_b"),
            "attempt_a",
            "always",
        ),
        (
            _skill_event(
                qualifying_for_level=False,
                qualification_reason_code="mapping_condition_not_met",
            ),
            "attempt_a",
            "always",
        ),
    )
    for record, attempt_kind, condition_code in invalid_cases:
        with pytest.raises(EvidenceContractError, match="qualification reason"):
            _validate_qualification_reason(record, attempt_kind, condition_code)  # type: ignore[arg-type]

    _validate_qualification_reason(
        _skill_event(
            qualifying_for_level=False,
            qualification_reason_code="nonqualifying_mode",
            practice_mode="guided_practice",
            practice_mode_factor=Decimal("0.350000"),
            effective_weight=Decimal("0.262500"),
        ),
        "attempt_a",
        "always",
    )
    _validate_qualification_reason(
        _skill_event(
            qualifying_for_level=False,
            qualification_reason_code="assisted_during_attempt",
            assistance_code="ai_hints_during_attempt",
        ),
        "attempt_a",
        "always",
    )
    _validate_qualification_reason(
        _skill_event(
            qualifying_for_level=False,
            qualification_reason_code="attempt_b",
        ),
        "attempt_b",
        "always",
    )
    _validate_qualification_reason(
        _skill_event(
            attempt_id=None,
            qualifying_for_level=False,
            qualification_reason_code="missing_committed_attempt",
        ),
        None,
        "always",
    )
    _validate_qualification_reason(
        _skill_event(
            qualifying_for_level=False,
            qualification_reason_code="mapping_condition_not_met",
        ),
        "attempt_a",
        "spoken_or_written_english",
    )
    _validate_qualification_reason(
        _skill_event(
            qualifying_for_level=False,
            qualification_reason_code="excluded_by_formula",
        ),
        "attempt_a",
        "always",
    )


def test_dimension_score_application_guard_enforces_dimension_maximum() -> None:
    from tamforge_backend.evidence.models import (
        EvidenceContractError,
        RubricDimensionScore,
        validate_rubric_dimension_score,
    )

    score = RubricDimensionScore(
        owner_id=1,
        config_seed_version_id=1,
        rubric_evaluation_id=1,
        rubric_version_id=1,
        rubric_dimension_id=1,
        availability="scored",
        score=Decimal("4.000"),
        weight_used=Decimal("1.000000"),
        evidence_manifest={"schema_version": 1, "artifact_ids": []},
        created_at=datetime.now(UTC),
    )
    with pytest.raises(EvidenceContractError, match="dimension maximum"):
        validate_rubric_dimension_score(None, _StubConnection(Decimal("3.000")), score)  # type: ignore[arg-type]

    unavailable = RubricDimensionScore(
        owner_id=1,
        config_seed_version_id=1,
        rubric_evaluation_id=1,
        rubric_version_id=1,
        rubric_dimension_id=1,
        availability="not_applicable",
        score=None,
        weight_used=None,
        evidence_manifest={"schema_version": 1, "artifact_ids": []},
        created_at=datetime.now(UTC),
    )
    validate_rubric_dimension_score(
        None,
        _StubConnection(Decimal("3.000")),
        unavailable,  # type: ignore[arg-type]
    )
    unavailable.score = Decimal("1.000")
    with pytest.raises(EvidenceContractError, match="cannot carry a score"):
        validate_rubric_dimension_score(None, None, unavailable)


def test_basis_ids_are_unique_scoped_and_context_specific() -> None:
    from tamforge_backend.evidence.models import (
        EvidenceContractError,
        PortfolioJudgmentScore,
        SkillSnapshot,
        _validate_basis,
        validate_portfolio_judgment_score,
        validate_skill_snapshot,
    )

    assert not _validate_basis(
        {"schema_version": 1, "basis_code": "stable", "event_ids": [1, 1]}
    )
    snapshot = SkillSnapshot(
        owner_id=1,
        config_seed_version_id=1,
        competency_id=1,
        formula_version="skill-v1",
        snapshot_date=date.today(),
        snapshot_sequence=1,
        estimated_level=Decimal("2.000"),
        confidence_code="low",
        trend_code="insufficient_evidence",
        recency_code="fresh",
        baseline_target_gap=Decimal("0.000"),
        month_one_target_gap=Decimal("0.500"),
        final_target_gap=Decimal("1.000"),
        total_effective_weight=Decimal("0.100000"),
        qualifying_event_count=1,
        exercise_type_count=1,
        last_strong_evidence_date=date.today(),
        contributing_event_manifest={
            "schema_version": 1,
            "events": [
                {"event_id": 1, "effective_weight": 0.1, "inclusion_code": "included"}
            ],
        },
        confidence_basis={"schema_version": 1, "basis_code": "low_weight", "event_ids": [2]},
        trend_basis={"schema_version": 1, "basis_code": "too_few_events", "event_ids": [1]},
        created_at=datetime.now(UTC),
    )
    with pytest.raises(EvidenceContractError, match="basis event ids"):
        validate_skill_snapshot(None, None, snapshot)

    snapshot.confidence_basis = {
        "schema_version": 1,
        "basis_code": "stable",
        "event_ids": [1],
    }
    with pytest.raises(EvidenceContractError, match="confidence basis code"):
        validate_skill_snapshot(None, None, snapshot)

    snapshot.confidence_basis = {
        "schema_version": 1,
        "basis_code": "low_weight",
        "event_ids": [1],
    }
    snapshot.trend_basis = {
        "schema_version": 1,
        "basis_code": "stable",
        "event_ids": [1],
    }
    with pytest.raises(EvidenceContractError, match="trend basis code"):
        validate_skill_snapshot(None, None, snapshot)

    portfolio = PortfolioJudgmentScore(
        owner_id=1,
        config_seed_version_id=1,
        activity_instance_id=1,
        attempt_id=1,
        rubric_evaluation_id=1,
        rubric_version_id=1,
        formula_version="portfolio-v1",
        impact_risk_assessment=Decimal("3"),
        explicit_prioritization=Decimal("2"),
        delegation_ownership=Decimal("2"),
        communication_control=Decimal("2"),
        proactive_work_protection=Decimal("1"),
        evidence_based_reprioritization=Decimal("2"),
        english_clarity=Decimal("1"),
        total_score=Decimal("13"),
        trend_basis={"schema_version": 1, "basis_code": "first_score", "event_ids": [9]},
        scored_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    with pytest.raises(EvidenceContractError, match="first portfolio score"):
        validate_portfolio_judgment_score(None, None, portfolio)

    portfolio.trend_basis = {
        "schema_version": 1,
        "basis_code": "too_few_events",
        "event_ids": [],
    }
    with pytest.raises(EvidenceContractError, match="prior score history"):
        validate_portfolio_judgment_score(None, None, portfolio)

    portfolio.trend_basis = {
        "schema_version": 1,
        "basis_code": "too_few_events",
        "event_ids": [9],
    }
    validate_portfolio_judgment_score(
        None,
        _StubConnection(1),
        portfolio,  # type: ignore[arg-type]
    )

    portfolio.trend_basis = {
        "schema_version": 1,
        "basis_code": "stable",
        "event_ids": [9],
    }
    with pytest.raises(EvidenceContractError, match="portfolio trend history"):
        validate_portfolio_judgment_score(None, _StubConnection(0), portfolio)  # type: ignore[arg-type]

    validate_portfolio_judgment_score(
        None,
        _StubConnection(1),
        portfolio,  # type: ignore[arg-type]
    )


def test_snapshot_application_guard_reconstructs_scoped_stored_events() -> None:
    from tamforge_backend.evidence.models import (
        EvidenceContractError,
        SkillSnapshot,
        validate_skill_snapshot,
    )

    snapshot = SkillSnapshot(
        owner_id=1,
        config_seed_version_id=1,
        competency_id=1,
        formula_version="skill-v1",
        snapshot_date=date.today(),
        snapshot_sequence=1,
        estimated_level=Decimal("2.000"),
        confidence_code="low",
        trend_code="insufficient_evidence",
        recency_code="fresh",
        baseline_target_gap=Decimal("0.000"),
        month_one_target_gap=Decimal("0.500"),
        final_target_gap=Decimal("1.000"),
        total_effective_weight=Decimal("0.100000"),
        qualifying_event_count=1,
        exercise_type_count=1,
        last_strong_evidence_date=date.today(),
        contributing_event_manifest={
            "schema_version": 1,
            "events": [
                {"event_id": 1, "effective_weight": 0.1, "inclusion_code": "included"}
            ],
        },
        confidence_basis={
            "schema_version": 1,
            "basis_code": "low_weight",
            "event_ids": [1],
        },
        trend_basis={
            "schema_version": 1,
            "basis_code": "too_few_events",
            "event_ids": [1],
        },
        created_at=datetime.now(UTC),
    )
    coherent = _StubConnection(
        (Decimal("2.000"), Decimal("2.500"), Decimal("3.000")),
        (Decimal("0.100000"), Decimal("2.000"), 7, True),
    )
    validate_skill_snapshot(None, coherent, snapshot)  # type: ignore[arg-type]

    fabricated_event = _StubConnection(
        (Decimal("2.000"), Decimal("2.500"), Decimal("3.000")),
        None,
    )
    with pytest.raises(EvidenceContractError, match="event provenance"):
        validate_skill_snapshot(None, fabricated_event, snapshot)  # type: ignore[arg-type]

    wrong_weight = _StubConnection(
        (Decimal("2.000"), Decimal("2.500"), Decimal("3.000")),
        (Decimal("0.200000"), Decimal("2.000"), 7, True),
    )
    with pytest.raises(EvidenceContractError, match="included snapshot event weight"):
        validate_skill_snapshot(None, wrong_weight, snapshot)  # type: ignore[arg-type]

    snapshot.contributing_event_manifest = {
        "schema_version": 1,
        "events": [
            {"event_id": 1, "effective_weight": 0.1, "inclusion_code": "included"},
            {"event_id": 1, "effective_weight": 0.1, "inclusion_code": "included"},
        ],
    }
    snapshot.total_effective_weight = Decimal("0.200000")
    snapshot.qualifying_event_count = 2
    duplicate_totals = _StubConnection(
        (Decimal("2.000"), Decimal("2.500"), Decimal("3.000")),
        (Decimal("0.100000"), Decimal("2.000"), 7, True),
        (Decimal("0.100000"), Decimal("2.000"), 7, True),
    )
    with pytest.raises(EvidenceContractError, match="structured evidence"):
        validate_skill_snapshot(None, duplicate_totals, snapshot)  # type: ignore[arg-type]


def test_immutable_configuration_and_history_are_rejected_by_orm() -> None:
    from tamforge_backend.evidence.models import (
        AppendOnlyEvidenceError,
        Competency,
        ConfigSeedVersion,
        PortfolioJudgmentScore,
        SkillEvidenceEvent,
        SkillSnapshot,
        reject_evidence_delete,
    )

    now = datetime.now(UTC)
    config = ConfigSeedVersion(
        id=1,
        owner_id=1,
        version_key="seed-v1",
        schema_version=1,
        content_hash=b"c" * 32,
        created_at=now,
    )
    competency = Competency(
        id=1,
        owner_id=1,
        config_seed_version_id=1,
        slug="structured_troubleshooting",
        name="Structured troubleshooting",
        baseline_level=Decimal("2.000"),
        month_one_target=Decimal("2.500"),
        final_target=Decimal("3.000"),
        created_at=now,
    )
    competency_target = Competency(
        id=2,
        owner_id=1,
        config_seed_version_id=1,
        slug="tam_english",
        name="TAM English",
        baseline_level=Decimal("1.000"),
        month_one_target=Decimal("2.000"),
        final_target=Decimal("2.750"),
        created_at=now,
    )
    event = SkillEvidenceEvent(
        id=1,
        owner_id=1,
        config_seed_version_id=1,
        activity_instance_id=1,
        attempt_id=1,
        rubric_evaluation_id=1,
        rubric_version_id=1,
        exercise_type_version_id=1,
        competency_id=1,
        formula_version="skill-v1",
        practice_mode="independent_practice",
        assistance_code="no_ai",
        evaluator_kind="ai_rubric_reviewer",
        difficulty_code="standard",
        raw_dimension_scores={"schema_version": 1, "scores": []},
        raw_score_numerator=Decimal("3.000000"),
        raw_score_denominator=Decimal("1.000000"),
        performance_score=Decimal("3.000"),
        exercise_skill_impact=Decimal("1.000000"),
        practice_mode_factor=Decimal("0.650000"),
        ai_independence_factor=Decimal("1.000000"),
        evaluator_confidence_factor=Decimal("0.750000"),
        difficulty_factor=Decimal("1.000000"),
        effective_weight=Decimal("0.487500"),
        qualifying_for_level=True,
        qualification_reason_code="qualifies",
        explanation={
            "schema_version": 1,
            "summary_code": "independent_scored_evidence",
            "dimension_score_ids": [],
            "discount_codes": [],
        },
        occurred_at=now,
        created_at=now,
    )
    snapshot = SkillSnapshot(
        id=1,
        owner_id=1,
        config_seed_version_id=1,
        competency_id=1,
        formula_version="skill-v1",
        snapshot_date=date.today(),
        snapshot_sequence=1,
        estimated_level=Decimal("2.500"),
        confidence_code="low",
        trend_code="insufficient_evidence",
        recency_code="fresh",
        baseline_target_gap=Decimal("-0.500"),
        month_one_target_gap=Decimal("0.000"),
        final_target_gap=Decimal("0.500"),
        total_effective_weight=Decimal("0.487500"),
        qualifying_event_count=1,
        exercise_type_count=1,
        last_strong_evidence_date=date.today(),
        contributing_event_manifest={"schema_version": 1, "events": []},
        confidence_basis={"schema_version": 1, "basis_code": "low_weight"},
        trend_basis={"schema_version": 1, "basis_code": "too_few_events", "event_ids": []},
        created_at=now,
    )
    portfolio = PortfolioJudgmentScore(
        id=1,
        owner_id=1,
        config_seed_version_id=1,
        activity_instance_id=1,
        attempt_id=1,
        rubric_evaluation_id=1,
        rubric_version_id=1,
        formula_version="portfolio-v1",
        impact_risk_assessment=Decimal("3.000"),
        explicit_prioritization=Decimal("2.000"),
        delegation_ownership=Decimal("2.000"),
        communication_control=Decimal("2.000"),
        proactive_work_protection=Decimal("1.000"),
        evidence_based_reprioritization=Decimal("2.000"),
        english_clarity=Decimal("1.000"),
        total_score=Decimal("13.000"),
        trend_basis={"schema_version": 1, "basis_code": "first_score", "event_ids": []},
        scored_at=now,
        created_at=now,
    )

    for record, attribute, new_value in (
        (config, "version_key", "rewritten"),
        (competency, "slug", "rewritten"),
        (competency_target, "final_target", Decimal("4.000")),
        (event, "performance_score", Decimal("4.000")),
        (snapshot, "estimated_level", Decimal("4.000")),
        (portfolio, "total_score", Decimal("20.000")),
    ):
        make_transient_to_detached(record)
        with pytest.raises(AppendOnlyEvidenceError, match="immutable"):
            setattr(record, attribute, new_value)
        with pytest.raises(AppendOnlyEvidenceError, match="immutable"):
            reject_evidence_delete(None, None, record)


def test_offline_upgrade_and_downgrade_include_guards_and_full_reversal() -> None:
    upgrade_sql = _offline_sql("upgrade", "20260825_0004_evidence_scoring")
    downgrade_sql = _offline_sql(
        "downgrade",
        "20260825_0004_evidence_scoring:20260825_0003_study_activities",
    )

    for table_name in EXPECTED_TABLES:
        assert f"CREATE TABLE {table_name}" in upgrade_sql
        assert f"DROP TABLE {table_name}" in downgrade_sql
    for function_name in {
        "tamforge_validate_score_manifest_v1",
        "tamforge_validate_explanation_v1",
        "tamforge_validate_basis_v1",
        "tamforge_reject_evidence_mutation",
        "tamforge_guard_skill_evidence_insert",
        "tamforge_guard_dimension_score_insert",
        "tamforge_guard_portfolio_score_insert",
    }:
        assert function_name in upgrade_sql
        assert function_name in downgrade_sql
    assert "trg_skill_evidence_events_immutable" in upgrade_sql
    assert "trg_competencies_immutable" in upgrade_sql


def test_offline_guards_reconcile_dimension_rows_mappings_and_snapshot_inputs() -> None:
    upgrade_sql = _offline_sql("upgrade", "20260825_0004_evidence_scoring")
    downgrade_sql = _offline_sql(
        "downgrade",
        "20260825_0004_evidence_scoring:20260825_0003_study_activities",
    )

    assert "FROM public.rubric_dimension_scores" in upgrade_sql
    assert "stored_score_numerator" in upgrade_sql
    assert "tamforge_guard_skill_snapshot_insert" in upgrade_sql
    assert "seen_event_ids" in upgrade_sql
    assert "snapshot estimate is not reproducible" in upgrade_sql
    assert "practice mode must match configured exercise mode" in upgrade_sql
    assert "activity task mapping" in upgrade_sql
    assert "score exceeds rubric dimension maximum" in upgrade_sql
    assert "snapshot basis event ids must be contributing events" in upgrade_sql
    assert "portfolio trend history provenance is invalid" in upgrade_sql
    assert "tamforge_guard_dimension_score_insert" in downgrade_sql
    assert "tamforge_guard_skill_snapshot_insert" in downgrade_sql
    assert "tamforge_guard_portfolio_score_insert" in downgrade_sql
    assert "'unscored'" not in upgrade_sql


def test_evidence_ledger_migration_allows_early_portfolio_history() -> None:
    upgrade_sql = _offline_sql("upgrade", "20260828_0010_evidence_ledger")
    downgrade_sql = _offline_sql(
        "downgrade",
        "20260828_0010_evidence_ledger:20260828_0009_output_commit",
    )

    assert (
        "'too_few_events', 'improving', 'stable', 'declining'" in upgrade_sql
    )
    assert "'too_few_events', 'improving', 'stable', 'declining'" not in downgrade_sql
    assert "'improving', 'stable', 'declining'" in downgrade_sql
