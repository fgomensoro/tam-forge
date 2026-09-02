"""Idempotent append-only persistence for approved scoring configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.models import Owner
from .config_loader import ConfigError, load_config_payload
from .config_models import ConfigBundle
from .models import (
    Competency,
    ConfigSeedVersion,
    ExerciseSkillMapping,
    ExerciseTypeVersion,
    RubricDimension,
    RubricVersion,
)


class SeedConfigError(ValueError):
    """Scoring configuration cannot be safely persisted."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    status: Literal["validated", "inserted", "unchanged"]
    config_versions: int
    competencies: int
    exercise_types: int
    exercise_skill_mappings: int
    rubrics: int
    rubric_dimensions: int
    roadmap_tasks: int
    inserted_rows: int
    config_version_id: int | None


def _counts(bundle: ConfigBundle) -> dict[str, int]:
    mappings = sum(
        len(exercise.impacts) + len(exercise.allowed_selected_competencies)
        for exercise in bundle.exercise_types
    )
    return {
        "config_versions": 1,
        "competencies": len(bundle.skills),
        "exercise_types": len(bundle.exercise_types),
        "exercise_skill_mappings": mappings,
        "rubrics": len(bundle.rubrics),
        "rubric_dimensions": sum(len(rubric.dimensions) for rubric in bundle.rubrics),
        "roadmap_tasks": len(bundle.roadmap_tasks),
    }


async def _resolve_owner_id(session: AsyncSession, owner_id: int | None) -> int:
    if owner_id is not None:
        found = await session.scalar(select(Owner.id).where(Owner.id == owner_id))
        if found is None:
            raise SeedConfigError("owner does not exist")
        return owner_id
    owner_ids = tuple((await session.scalars(select(Owner.id).order_by(Owner.id))).all())
    if len(owner_ids) != 1:
        raise SeedConfigError("seed apply requires exactly one persisted owner")
    return owner_ids[0]


async def seed_config(
    bundle: ConfigBundle,
    *,
    owner_id: int | None,
    session: AsyncSession | None,
    apply: bool,
) -> SeedResult:
    """Validate only, or append one content-addressed config release atomically."""
    if bundle.roadmap_schema_version == 2:
        raise SeedConfigError("roadmap-only release cannot seed scoring")
    counts = _counts(bundle)
    if not apply:
        return SeedResult(
            status="validated",
            inserted_rows=0,
            config_version_id=None,
            **counts,
        )
    if session is None:
        raise SeedConfigError("seed apply requires a database session")

    resolved_owner_id = await _resolve_owner_id(session, owner_id)
    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended("
            "'tamforge:config-seed:' || CAST(CAST(:owner_id AS bigint) AS text), 0))"
        ),
        {"owner_id": resolved_owner_id},
    )
    existing = await session.scalar(
        select(ConfigSeedVersion).where(
            ConfigSeedVersion.owner_id == resolved_owner_id,
            ConfigSeedVersion.version_key == bundle.version_key,
        )
    )
    if existing is not None:
        if existing.content_hash != bundle.content_hash:
            raise SeedConfigError("existing config version has a different content hash")
        try:
            persisted = load_config_payload(existing.canonical_payload)
        except ConfigError as exc:
            raise SeedConfigError("existing config payload is invalid") from exc
        if (
            persisted.content_hash != bundle.content_hash
            or persisted.canonical_payload != bundle.canonical_payload
        ):
            raise SeedConfigError("existing config payload does not match its content hash")
        return SeedResult(
            status="unchanged",
            inserted_rows=0,
            config_version_id=existing.id,
            **counts,
        )

    config_version = ConfigSeedVersion(
        owner_id=resolved_owner_id,
        version_key=bundle.version_key,
        schema_version=bundle.schema_version,
        content_hash=bundle.content_hash,
        canonical_payload=bundle.canonical_payload,
    )
    session.add(config_version)
    await session.flush()

    competency_by_slug: dict[str, Competency] = {}
    for skill_item in bundle.skills:
        competency = Competency(
            owner_id=resolved_owner_id,
            config_seed_version_id=config_version.id,
            slug=skill_item.slug,
            name=skill_item.name,
            baseline_level=skill_item.baseline,
            month_one_target=skill_item.month_one_target,
            final_target=skill_item.final_target,
        )
        session.add(competency)
        competency_by_slug[skill_item.slug] = competency
    await session.flush()

    for exercise_item in bundle.exercise_types:
        exercise = ExerciseTypeVersion(
            owner_id=resolved_owner_id,
            config_seed_version_id=config_version.id,
            exercise_type=exercise_item.slug,
            mapping_version=exercise_item.mapping_version,
            evidence_mode=exercise_item.evidence_mode,
            condition_code="always",
            tags=list(exercise_item.tags),
        )
        session.add(exercise)
        await session.flush()
        for impact in exercise_item.impacts:
            session.add(
                ExerciseSkillMapping(
                    owner_id=resolved_owner_id,
                    config_seed_version_id=config_version.id,
                    exercise_type_version_id=exercise.id,
                    competency_id=competency_by_slug[impact.skill_slug].id,
                    impact=impact.weight,
                    condition_code=impact.condition,
                )
            )
        if exercise_item.selected_impact is not None:
            for slug in exercise_item.allowed_selected_competencies:
                session.add(
                    ExerciseSkillMapping(
                        owner_id=resolved_owner_id,
                        config_seed_version_id=config_version.id,
                        exercise_type_version_id=exercise.id,
                        competency_id=competency_by_slug[slug].id,
                        impact=exercise_item.selected_impact,
                        condition_code="reviewed_dynamic_impact",
                    )
                )

    for rubric_item in bundle.rubrics:
        rubric = RubricVersion(
            owner_id=resolved_owner_id,
            config_seed_version_id=config_version.id,
            rubric_key=rubric_item.slug,
            version_key=rubric_item.version,
            name=rubric_item.name,
            scope_code=rubric_item.scope,
            scale_min=rubric_item.scale_min,
            scale_max=rubric_item.scale_max,
        )
        session.add(rubric)
        await session.flush()
        for ordinal, dimension in enumerate(rubric_item.dimensions):
            session.add(
                RubricDimension(
                    owner_id=resolved_owner_id,
                    config_seed_version_id=config_version.id,
                    rubric_version_id=rubric.id,
                    dimension_key=dimension.slug,
                    name=dimension.name,
                    weight=dimension.weight,
                    max_score=dimension.maximum,
                    ordinal=ordinal,
                    availability_rule_code=dimension.availability_rule,
                )
            )

    inserted_rows = sum(
        counts[key]
        for key in (
            "config_versions",
            "competencies",
            "exercise_types",
            "exercise_skill_mappings",
            "rubrics",
            "rubric_dimensions",
        )
    )
    return SeedResult(
        status="inserted",
        inserted_rows=inserted_rows,
        config_version_id=config_version.id,
        **counts,
    )
