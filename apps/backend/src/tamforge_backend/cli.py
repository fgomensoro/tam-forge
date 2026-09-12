"""Small administrative CLI with safe dry-run defaults."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .database import validate_test_database_url
from .evidence.config_loader import ConfigError, load_config_bundle
from .evidence.seed import SeedConfigError, SeedResult, seed_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tamforge")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed-config")
    seed.add_argument("--config-dir", type=Path, required=True)
    mode = seed.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    validate_roadmap = commands.add_parser("validate-roadmap-map")
    validate_roadmap.add_argument("--config", type=Path, required=True)
    validate_release = commands.add_parser("validate-roadmap-release")
    validate_release.add_argument("--release-dir", type=Path, required=True)
    validate_release.add_argument("--legacy-config-dir", type=Path, required=True)
    probe = commands.add_parser("claude-probe")
    probe.add_argument("--database-url", required=True)
    probe.add_argument("--model", default=None)
    attest = commands.add_parser("record-attestation")
    attest.add_argument("--database-url", required=True)
    attest.add_argument("--policy-version", required=True)
    attest.add_argument("--model-improvement-disabled", action="store_true")
    attest.add_argument("--subscription-policy-acknowledged", action="store_true")
    return parser


def _async_url(raw_url: str) -> str:
    url = make_url(raw_url)
    if url.drivername not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise SeedConfigError("seed apply requires PostgreSQL")
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


async def _apply(config_dir: Path, raw_url: str) -> SeedResult:
    bundle = load_config_bundle(config_dir)
    if bundle.roadmap_schema_version == 2:
        raise SeedConfigError("roadmap-only release cannot seed scoring")
    engine = create_async_engine(_async_url(raw_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            return await seed_config(bundle, owner_id=None, session=session, apply=True)
    finally:
        await engine.dispose()


async def _first_owner_id(factory: async_sessionmaker[AsyncSession]) -> int:
    from sqlalchemy import select

    from .auth.models import Owner

    async with factory() as session:
        owner_id = await session.scalar(select(Owner.id).order_by(Owner.id).limit(1))
        await session.rollback()
    if owner_id is None:
        raise ClaudeCliError("no owner has signed in yet; the attestation belongs to the owner")
    return int(owner_id)


class ClaudeCliError(Exception):
    """A Claude command could not run; the message never carries a secret."""


async def _claude_probe(raw_url: str, requested_model: str | None) -> dict[str, object]:
    from datetime import UTC, datetime

    from .agents.compatibility import AttestationRepository, probe_claude_compatibility
    from .agents.sdk_runtime import AgentSdkRuntime
    from .config import Settings

    settings = Settings()
    engine = create_async_engine(_async_url(raw_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id = await _first_owner_id(factory)
        async with factory() as session:
            result = await probe_claude_compatibility(
                runtime=AgentSdkRuntime(),
                repository=AttestationRepository(session),
                owner_id=owner_id,
                enabled=settings.claude_enabled,
                requested_model=requested_model or settings.planner_model,
                now=datetime.now(UTC),
            )
            await session.rollback()
    finally:
        await engine.dispose()
    return {
        "status": result.status,
        "reason": result.reason,
        "remediation": result.remediation,
        "checked_at": result.checked_at.isoformat(),
        "resolved_model": result.resolved_model,
        "sdk_version": result.sdk_version,
        "cli_version": result.cli_version,
    }


async def _record_attestation(
    raw_url: str, *, policy_version: str, model_improvement_disabled: bool, acknowledged: bool
) -> dict[str, object]:
    from .agents.compatibility import AttestationRepository
    from .agents.settings import EXPECTED_POLICY_VERSION, AttestationRecord

    if policy_version != EXPECTED_POLICY_VERSION:
        raise ClaudeCliError(
            f"policy version must be {EXPECTED_POLICY_VERSION}; bump the constant first if "
            "the published policy changed"
        )
    try:
        record = AttestationRecord(
            policy_version=policy_version,
            model_improvement_disabled=model_improvement_disabled,
            subscription_policy_acknowledged=acknowledged,
        )
    except ValueError as exc:
        raise ClaudeCliError("both claims must be affirmed for an attestation") from exc
    engine = create_async_engine(_async_url(raw_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner_id = await _first_owner_id(factory)
        async with factory() as session:
            await AttestationRepository(session).record(owner_id=owner_id, record=record)
    finally:
        await engine.dispose()
    return {"owner_id": owner_id, "policy_version": policy_version, "recorded": True}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-roadmap-map":
            bundle = load_config_bundle(
                args.config.parent,
                roadmap_tasks_path=args.config,
            )
            study_days = {task.day for task in bundle.roadmap_tasks}
            payload = {
                "roadmap_version": bundle.roadmap_version,
                "mapping_version": bundle.exercise_types[0].mapping_version,
                "tasks": len(bundle.roadmap_tasks),
                "study_days": len(study_days),
                "weekday_days": sum(day % 6 != 0 for day in study_days),
                "saturdays": sum(day % 6 == 0 for day in study_days),
                "total_minutes": sum(task.timebox_minutes for task in bundle.roadmap_tasks),
            }
        elif args.command == "validate-roadmap-release":
            bundle = load_config_bundle(
                args.legacy_config_dir,
                roadmap_tasks_path=(args.release_dir / "tam-roadmap-task-map.yaml"),
            )
            if bundle.roadmap_schema_version != 2:
                raise ConfigError("roadmap release must use schema version 2")
            study_days = {task.day for task in bundle.roadmap_tasks}
            coverage = bundle.coverage
            if coverage is None:  # pragma: no cover - schema v2 requires coverage
                raise ConfigError("roadmap release coverage is required")
            payload = {
                "roadmap_schema_version": bundle.roadmap_schema_version,
                "roadmap_version": bundle.roadmap_version,
                "program_key": bundle.program.program_key,
                "study_days": len(study_days),
                "weekday_days": sum(day % 6 != 0 for day in study_days),
                "saturdays": sum(day % 6 == 0 for day in study_days),
                "nominal_minutes": sum(task.timebox_minutes for task in bundle.roadmap_tasks),
                "interview_questions": len(bundle.interview_queue),
                "coverage_requirements": len(coverage.requirements),
                "coverage_assignments": len(coverage.assignments),
            }
        elif args.command == "claude-probe":
            payload = asyncio.run(_claude_probe(args.database_url, args.model))
        elif args.command == "record-attestation":
            payload = asyncio.run(
                _record_attestation(
                    args.database_url,
                    policy_version=args.policy_version,
                    model_improvement_disabled=args.model_improvement_disabled,
                    acknowledged=args.subscription_policy_acknowledged,
                )
            )
        elif args.command == "seed-config" and not args.apply:
            bundle = load_config_bundle(args.config_dir)
            result = asyncio.run(seed_config(bundle, owner_id=None, session=None, apply=False))
            payload = asdict(result)
        elif args.command == "seed-config":
            test_url = os.getenv("TEST_DATABASE_URL")
            runtime_url = os.getenv("TAMFORGE_DATABASE_URL")
            if test_url:
                raw_url = validate_test_database_url(test_url)
            elif runtime_url:
                raw_url = runtime_url
            else:
                raise SeedConfigError(
                    "seed apply requires explicit TEST_DATABASE_URL or TAMFORGE_DATABASE_URL"
                )
            result = asyncio.run(_apply(args.config_dir, raw_url))
            payload = asdict(result)
        else:  # pragma: no cover - argparse rejects this path
            raise SeedConfigError("unsupported command")
    except (ConfigError, SeedConfigError, ClaudeCliError, ValueError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
