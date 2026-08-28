"""Persist reconstructable scoring configuration and normalize AI assistance.

Revision ID: 20260826_0006_score_payload
Revises: 20260825_0005_today_read_models
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0006_score_payload"
down_revision: str | None = "20260825_0005_today_read_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSISTANCE_WITHOUT_INTERVIEWER = (
    "assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
    "'ai_hints_during_attempt', 'ai_co_created', 'ai_generated')"
)
_ASSISTANCE_WITH_LEGACY_INTERVIEWER = (
    "assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
    "'ai_interviewer_only', 'ai_hints_during_attempt', 'ai_co_created', "
    "'ai_generated')"
)
_QUALIFICATION_WITHOUT_INTERVIEWER = (
    "(qualifying_for_level AND qualification_reason_code = 'qualifies' "
    "AND attempt_id IS NOT NULL "
    "AND practice_mode IN ('independent_practice', 'timed_assessment', "
    "'mock_interview', 'real_interview') "
    "AND assistance_code IN ('no_ai', 'ai_after_committed_attempt')) OR "
    "(NOT qualifying_for_level AND qualification_reason_code <> 'qualifies')"
)
_QUALIFICATION_WITH_LEGACY_INTERVIEWER = (
    "(qualifying_for_level AND qualification_reason_code = 'qualifies' "
    "AND attempt_id IS NOT NULL "
    "AND practice_mode IN ('independent_practice', 'timed_assessment', "
    "'mock_interview', 'real_interview') "
    "AND assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
    "'ai_interviewer_only')) OR "
    "(NOT qualifying_for_level AND qualification_reason_code <> 'qualifies')"
)
_CANONICAL_PAYLOAD_VALID = (
    "jsonb_typeof(canonical_payload) = 'object' "
    "AND canonical_payload ?& ARRAY["
    "'skills', 'exercise_types', 'rubrics', 'roadmap_tasks'] "
    "AND canonical_payload - ARRAY["
    "'skills', 'exercise_types', 'rubrics', 'roadmap_tasks'"
    "] = '{}'::jsonb "
    "AND octet_length(canonical_payload::text) <= 8388608"
)


def upgrade() -> None:
    # Task 11 is the first writer of config_seed_versions, so an existing row here
    # signals an unsupported partial rollout; NOT NULL fails closed instead of
    # fabricating a payload that cannot reconstruct its historical configuration.
    op.add_column(
        "config_seed_versions",
        sa.Column(
            "canonical_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "canonical_payload_valid",
        "config_seed_versions",
        _CANONICAL_PAYLOAD_VALID,
    )

    # The replacement constraints deliberately fail closed if an unsupported
    # partial rollout already wrote the removed assistance code. Historical
    # evidence is never rewritten during migration.
    op.drop_constraint(
        op.f("ck_skill_evidence_events_qualification_coherent"),
        "skill_evidence_events",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_skill_evidence_events_assistance_code_allowed"),
        "skill_evidence_events",
        type_="check",
    )
    op.create_check_constraint(
        "assistance_code_allowed",
        "skill_evidence_events",
        _ASSISTANCE_WITHOUT_INTERVIEWER,
    )
    op.create_check_constraint(
        "qualification_coherent",
        "skill_evidence_events",
        _QUALIFICATION_WITHOUT_INTERVIEWER,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_skill_evidence_events_qualification_coherent"),
        "skill_evidence_events",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_skill_evidence_events_assistance_code_allowed"),
        "skill_evidence_events",
        type_="check",
    )
    op.create_check_constraint(
        "assistance_code_allowed",
        "skill_evidence_events",
        _ASSISTANCE_WITH_LEGACY_INTERVIEWER,
    )
    op.create_check_constraint(
        "qualification_coherent",
        "skill_evidence_events",
        _QUALIFICATION_WITH_LEGACY_INTERVIEWER,
    )

    op.drop_constraint(
        op.f("ck_config_seed_versions_canonical_payload_valid"),
        "config_seed_versions",
        type_="check",
    )
    op.drop_column("config_seed_versions", "canonical_payload")
