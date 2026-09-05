"""Real PostgreSQL aggregate checks. Never start a database or external provider."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from tamforge_backend.agents.contracts import (
    ContextInput,
    ImmutableVersionConflict,
    InvalidProvenance,
    Lifecycle,
    PinnedVersion,
    ProvenanceNotFound,
    RunRequest,
    StateConflict,
    ToolAudit,
)
from tamforge_backend.agents.hashing import canonical_bytes
from tamforge_backend.agents.model_runs import ModelRunRepository
from tamforge_backend.agents.models import (
    AgentToolCall,
    ModelRun,
    ModelRunContextItem,
    ModelRunEvent,
    OutputSchemaVersion,
    PromptVersion,
    RubricVersionHash,
)
from tamforge_backend.agents.prompt_registry import PromptRegistry
from tamforge_backend.database import database_url_to_sync
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.models import RubricVersion
from tamforge_backend.evidence.seed import seed_config
from tamforge_backend.learning.models import Attempt
from tamforge_backend.learning.service import ActivityService
from tamforge_protocol.agents import AttemptTextReference

from apps.backend.tests.integration.workspaces.test_sql_execution_api import _seed_activity

pytestmark = [pytest.mark.integration, pytest.mark.postgres_integration]
ROOT = Path(__file__).parents[5]


@dataclass
class Case:
    url: str
    owner: int
    other_owner: int
    request: RunRequest

    def factory(self):
        engine = create_async_engine(
            make_url(self.url).set(drivername="postgresql+asyncpg"), poolclass=NullPool
        )
        return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _migration(url):
    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = url
    return config


def _reset(url):
    engine = create_engine(database_url_to_sync(url))
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    command.upgrade(_migration(url), "head")


def test_upgrade_downgrade_only_provenance_revision(test_database_url):
    _reset(test_database_url)
    config = _migration(test_database_url)
    command.downgrade(config, "20260904_0014_sql_executions")
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('public.model_runs')")) is None
            assert (
                connection.scalar(text("SELECT to_regclass('public.sql_executions')")) is not None
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('public.model_runs')")) is not None
            # Independent byte vector, including key ordering, decimal trim, and Unicode.
            assert connection.scalar(
                text(
                    "SELECT public.tamforge_provenance_canonical("
                    '\'{"é":"é","z":[1.00,0.0100,-0.0]}\'::jsonb)'
                )
            ) == ('{"z":[1,0.01,0],"é":"é"}')
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def case(test_database_url):
    _reset(test_database_url)
    sync = create_engine(database_url_to_sync(test_database_url))
    try:
        with sync.begin() as connection:
            owner = connection.scalar(
                text(
                    "INSERT INTO owners (github_user_id,github_login) "
                    "VALUES (102269369,'provenance') RETURNING id"
                )
            )
            other = connection.scalar(
                text(
                    "INSERT INTO owners (github_user_id,github_login) "
                    "VALUES (102269370,'other') RETURNING id"
                )
            )
            activity = _seed_activity(
                connection,
                owner_id=owner,
                suffix="provenance",
                local_date=date(2026, 9, 4),
                stable_id="fixture.sql.provenance",
            )
        result = Case(test_database_url, owner, other, None)

        async def seed():
            engine, factory = result.factory()
            try:
                async with factory() as session:
                    now = datetime.now(UTC) + timedelta(seconds=1)
                    service = ActivityService(session, clock=lambda: now)
                    await service.start(
                        owner_id=owner,
                        activity_id=activity,
                        expected_version=1,
                        idempotency_key="provenance-start",
                    )
                    now += timedelta(seconds=2)
                    await service.commit_output(
                        owner_id=owner,
                        activity_id=activity,
                        expected_version=2,
                        client_sequence=1,
                        artifact_refs=(),
                        parent_attempt_id=None,
                        idempotency_key="provenance-commit",
                        output={
                            "contract_version": 1,
                            "kind": "sql",
                            "prompt": "Count the records",
                            "audience": "TAM",
                            "time_limit_minutes": 45,
                            "query": "SELECT 1",
                            "result": "é🙂x",
                            "validation": "one row",
                            "explanation": "Count once",
                            "business_meaning": "One account",
                            "solving_seconds": 2,
                            "assistance_used": "none",
                        },
                    )
                    async with session.begin():
                        await seed_config(
                            load_config_bundle(ROOT / "config"),
                            owner_id=owner,
                            session=session,
                            apply=True,
                        )
                        attempt = await session.scalar(
                            select(Attempt).where(
                                Attempt.owner_id == owner, Attempt.activity_instance_id == activity
                            )
                        )
                        rubric = await session.scalar(
                            select(RubricVersion)
                            .where(RubricVersion.owner_id == owner)
                            .order_by(RubricVersion.id)
                            .limit(1)
                        )
                    registry = PromptRegistry(session)
                    prompt = await registry.publish_prompt(
                        owner_id=owner, key="reviewer", version="v1", content="review é\r\n"
                    )
                    schemas = await registry.publish_analysis_schemas(owner_id=owner)
                    binding = await registry.bind_rubric(owner_id=owner, rubric_id=rubric.id)
                    return RunRequest(
                        owner_id=owner,
                        invocation_key="original",
                        activity_id=activity,
                        attempt=PinnedVersion(
                            id=attempt.id, content_hash=attempt.commitment_hash.hex()
                        ),
                        prompt=PinnedVersion(id=prompt.id, content_hash=prompt.content_hash.hex()),
                        schema_version=PinnedVersion(
                            id=schemas[0].id, content_hash=schemas[0].content_hash.hex()
                        ),
                        rubric_binding=PinnedVersion(
                            id=binding.id, content_hash=binding.content_hash.hex()
                        ),
                        requested_model="requested-model",
                        sdk_version="1.0",
                        context=(
                            ContextInput(
                                ordinal=0,
                                reason="primary_evidence",
                                reference=AttemptTextReference(
                                    kind="attempt_text",
                                    attempt_id=attempt.id,
                                    commitment_sha256=attempt.commitment_hash.hex(),
                                    json_pointer="/output/result",
                                    start_codepoint=0,
                                    end_codepoint=2,
                                ),
                                prepared_input_hash=sha256("é🙂".encode()).hexdigest(),
                            ),
                        ),
                    )
            finally:
                await engine.dispose()

        result.request = asyncio.run(seed())
        yield result
    finally:
        sync.dispose()
        # Evolved activity state cannot pass historical downgrade constraints.
        _reset(test_database_url)


def test_registry_invocation_replay_owner_scope_and_hash_pins(case):
    async def exercise():
        engine, factory = case.factory()
        try:
            async with factory() as session:
                registry = PromptRegistry(session)
                first = await registry.publish_prompt(
                    owner_id=case.owner, key="reviewer", version="v1", content="review é\r\n"
                )
                assert first.content_hash == sha256("review é\r\n".encode()).digest()
                with pytest.raises(ImmutableVersionConflict):
                    await registry.publish_prompt(
                        owner_id=case.owner, key="reviewer", version="v1", content="review é\n"
                    )
                assert (
                    await registry.lookup(
                        owner_id=case.owner, content_hash=first.content_hash, kind="prompt"
                    )
                )[0].id == first.id
                with pytest.raises(ProvenanceNotFound):
                    await registry.lookup(
                        owner_id=case.other_owner, content_hash=first.content_hash, kind="prompt"
                    )
                with pytest.raises(InvalidProvenance):
                    await registry.bind_rubric(
                        owner_id=case.other_owner, rubric_id=case.request.rubric_binding.id
                    )
                repo = ModelRunRepository(session)
                run = await repo.register(case.request)
                assert (await repo.register(case.request)).id == run.id
                with pytest.raises(ImmutableVersionConflict):
                    await repo.register(
                        case.request.model_copy(update={"requested_model": "changed"})
                    )
                complete = await repo.read(owner_id=case.owner, run_hash=run.content_hash)
                assert len(complete.context) == 1
                context = json.loads(complete.context[0].canonical_json)
                assert context["prepared_input_hash"] == sha256("é🙂".encode()).hexdigest()
                assert "é🙂" not in complete.context[0].canonical_json
                with pytest.raises(ProvenanceNotFound):
                    await repo.read(owner_id=case.other_owner, run_hash=run.content_hash)
                for field in ("attempt", "prompt", "schema_version", "rubric_binding"):
                    pin = getattr(case.request, field).model_copy(update={"content_hash": "0" * 64})
                    with pytest.raises(InvalidProvenance):
                        await repo.register(
                            case.request.model_copy(
                                update={field: pin, "invocation_key": "bad-" + field}
                            )
                        )
                ref = case.request.context[0].reference.model_copy(
                    update={"json_pointer": "/output/prompt", "end_codepoint": 2}
                )
                context_input = case.request.context[0].model_copy(update={"reference": ref})
                with pytest.raises(InvalidProvenance):
                    await repo.register(
                        case.request.model_copy(
                            update={"context": (context_input,), "invocation_key": "metadata"}
                        )
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_lifecycle_tool_pending_success_failure_cancellation_and_terminal_order(case):
    async def exercise():
        engine, factory = case.factory()
        try:
            async with factory() as session:
                repo = ModelRunRepository(session)
                run = await repo.register(
                    case.request.model_copy(update={"invocation_key": "events"})
                )
                with pytest.raises(StateConflict):
                    await repo.append_event(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=0,
                        expected_state="registered",
                        event=Lifecycle(state="succeeded", elapsed_ms=0),
                    )
                await repo.append_event(
                    owner_id=case.owner,
                    run_hash=run.content_hash,
                    expected_sequence=0,
                    expected_state="registered",
                    event=Lifecycle(
                        state="running",
                        elapsed_ms=0,
                        resolved_model="observed-model",
                        sdk_version="1.1",
                    ),
                )
                audit = ToolAudit(
                    call_key="one",
                    phase="request",
                    tool_name="lookup",
                    tool_version="1",
                    schema_hash=case.request.schema_version.content_hash,
                    elapsed_ms=0,
                    context_ordinals=(0,),
                )
                await repo.append_tool(
                    owner_id=case.owner, run_hash=run.content_hash, expected_sequence=0, audit=audit
                )
                with pytest.raises(InvalidProvenance):
                    await repo.append_event(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=1,
                        expected_state="running",
                        event=Lifecycle(state="succeeded", elapsed_ms=10),
                    )
                await repo.append_tool(
                    owner_id=case.owner,
                    run_hash=run.content_hash,
                    expected_sequence=1,
                    audit=audit.model_copy(
                        update={
                            "phase": "failed",
                            "error_category": "transient_dependency",
                            "elapsed_ms": 2,
                        }
                    ),
                )
                with pytest.raises(InvalidProvenance):
                    await repo.append_tool(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=2,
                        audit=audit.model_copy(update={"phase": "succeeded"}),
                    )
                for index, phase in enumerate(("succeeded", "cancelled")):
                    call = audit.model_copy(update={"call_key": f"call-{index}"})
                    await repo.append_tool(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=2 + index * 2,
                        audit=call,
                    )
                    await repo.append_tool(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=3 + index * 2,
                        audit=call.model_copy(
                            update={
                                "phase": phase,
                                "elapsed_ms": 3,
                                "error_category": "cancelled" if phase == "cancelled" else None,
                            }
                        ),
                    )
                await repo.append_event(
                    owner_id=case.owner,
                    run_hash=run.content_hash,
                    expected_sequence=1,
                    expected_state="running",
                    event=Lifecycle(state="succeeded", elapsed_ms=10, output_hash="c" * 64),
                )
                with pytest.raises(StateConflict):
                    await repo.append_event(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=2,
                        expected_state="succeeded",
                        event=Lifecycle(
                            state="failed", elapsed_ms=11, error_category="internal_error"
                        ),
                    )
                with pytest.raises(InvalidProvenance):
                    await repo.append_tool(
                        owner_id=case.owner,
                        run_hash=run.content_hash,
                        expected_sequence=6,
                        audit=audit.model_copy(update={"call_key": "late"}),
                    )
                complete = await repo.read(owner_id=case.owner, run_hash=run.content_hash)
                assert len(complete.events) == 2 and len(complete.tools) == 6
                assert json.loads(complete.events[0].canonical_json)["event"]["resolved_model"] == (
                    "observed-model"
                )
                for state in ("failed", "cancelled"):
                    separate = await repo.register(
                        case.request.model_copy(
                            update={
                                "invocation_key": state,
                                "predecessor": PinnedVersion(
                                    id=run.id, content_hash=run.content_hash.hex()
                                ),
                            }
                        )
                    )
                    event = await repo.append_event(
                        owner_id=case.owner,
                        run_hash=separate.content_hash,
                        expected_sequence=0,
                        expected_state="registered",
                        event=Lifecycle(
                            state=state, elapsed_ms=1, error_category="processing_failure"
                        ),
                    )
                    assert event.sequence == 1
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_direct_sql_cannot_forge_content_sources_manifests_or_mutate_history(case):
    async def exercise():
        engine, factory = case.factory()
        try:
            async with factory() as session:
                repo = ModelRunRepository(session)
                run = await repo.register(case.request.model_copy(update={"invocation_key": "sql"}))
                complete = await repo.read(owner_id=case.owner, run_hash=run.content_hash)
                context = json.loads(complete.context[0].canonical_json)
                header = json.loads(run.canonical_json)

                async def bad_insert(
                    model, payload, *, owner=case.owner, run_id=None, forged=False
                ):
                    data = canonical_bytes(payload)
                    values = {
                        "owner_id": owner,
                        "canonical_json": data.decode(),
                        "content_hash": b"x" * 32 if forged else sha256(data).digest(),
                    }
                    if run_id is not None:
                        values["run_id"] = run_id
                    with pytest.raises(SQLAlchemyError) as caught:
                        async with session.begin():
                            await session.execute(model.__table__.insert().values(**values))
                    if not forged:
                        assert caught.value.orig.sqlstate == "P0001"

                await bad_insert(ModelRun, {**header, "invocation_key": "forged"}, forged=True)
                await bad_insert(ModelRun, {**header, "invocation_key": "missing-context"})
                await bad_insert(
                    ModelRun, {**header, "invocation_key": "wrong-owner"}, owner=case.other_owner
                )
                for field in ("attempt", "prompt", "schema_version", "rubric_binding"):
                    await bad_insert(
                        ModelRun,
                        {
                            **header,
                            "invocation_key": "sql-" + field,
                            field: {**header[field], "content_hash": "0" * 64},
                        },
                    )
                for changes in (
                    {"source_hash": "0" * 64},
                    {"prepared_input_hash": "0" * 64},
                    {"ordinal": 1},
                    {"activity_id": 999999},
                    {"reason": None},
                    {"reference": {**context["reference"], "end_codepoint": 999999}},
                    {"reference": {**context["reference"], "json_pointer": "/output/prompt"}},
                    {"reference": {**context["reference"], "commitment_sha256": "0" * 64}},
                ):
                    await bad_insert(ModelRunContextItem, {**context, **changes}, run_id=run.id)
                binding_data = None
                async with session.begin():
                    binding = await session.get(RubricVersionHash, case.request.rubric_binding.id)
                    binding_data = json.loads(binding.canonical_json)
                await bad_insert(RubricVersionHash, {**binding_data, "config_hash": "0" * 64})
                # Both JSON schema identity and exact prompt digest are enforced for raw INSERTs.
                for model, payload, extra in [
                    (PromptVersion, "prompt", {"key": "bad", "version": "v1"}),
                    (OutputSchemaVersion, "{}", {"key": "urn:bad", "version": "v1"}),
                ]:
                    with pytest.raises(SQLAlchemyError):
                        async with session.begin():
                            await session.execute(
                                model.__table__.insert().values(
                                    owner_id=case.owner,
                                    canonical_json=payload,
                                    content_hash=b"x" * 32,
                                    **extra,
                                )
                            )
                for model in (
                    PromptVersion,
                    OutputSchemaVersion,
                    RubricVersionHash,
                    ModelRun,
                    ModelRunContextItem,
                    ModelRunEvent,
                    AgentToolCall,
                ):
                    for action in (
                        f"UPDATE {model.__tablename__} SET owner_id=owner_id",
                        f"DELETE FROM {model.__tablename__}",
                        f"TRUNCATE {model.__tablename__} CASCADE",
                    ):
                        with pytest.raises(SQLAlchemyError):
                            async with session.begin():
                                await session.execute(text(action))
                assert (
                    await repo.read(owner_id=case.owner, run_hash=run.content_hash)
                ).header.id == run.id
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_concurrent_invocation_replay_and_expected_state_are_atomic(case):
    async def exercise():
        engine, factory = case.factory()
        try:

            async def register():
                async with factory() as session:
                    return await ModelRunRepository(session).register(
                        case.request.model_copy(update={"invocation_key": "concurrent"})
                    )

            first, second = await asyncio.gather(register(), register())
            assert first.id == second.id

            async def start():
                async with factory() as session:
                    try:
                        return await ModelRunRepository(session).append_event(
                            owner_id=case.owner,
                            run_hash=first.content_hash,
                            expected_sequence=0,
                            expected_state="registered",
                            event=Lifecycle(
                                state="running",
                                elapsed_ms=0,
                                resolved_model="observed",
                                cli_version="1",
                            ),
                        )
                    except StateConflict:
                        return None

            events = await asyncio.gather(start(), start())
            assert sum(item is not None for item in events) == 1
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize("ordinal", [1, 63])
def test_fresh_aggregate_rejects_nonzero_first_context_ordinal(case, ordinal):
    async def exercise():
        engine, factory = case.factory()
        try:
            async with factory() as session:
                repo = ModelRunRepository(session)
                original = await repo.register(
                    case.request.model_copy(update={"invocation_key": "ordinal-regression-seed"})
                )
                complete = await repo.read(owner_id=case.owner, run_hash=original.content_hash)
                context = json.loads(complete.context[0].canonical_json)
                context["ordinal"] = ordinal
                context_bytes = canonical_bytes(context)
                context_hash = sha256(context_bytes).digest()
                header = json.loads(original.canonical_json)
                header["invocation_key"] = f"nonzero-first-ordinal-{ordinal}"
                header["manifest"] = [context_hash.hex()]
                header["manifest_hash"] = sha256(canonical_bytes(header["manifest"])).hexdigest()
                header_bytes = canonical_bytes(header)
                # Every digest is correct and the new run has no existing context rows.
                with pytest.raises(SQLAlchemyError) as caught:
                    async with session.begin():
                        run_id = await session.scalar(
                            ModelRun.__table__.insert()
                            .values(
                                owner_id=case.owner,
                                canonical_json=header_bytes.decode(),
                                content_hash=sha256(header_bytes).digest(),
                            )
                            .returning(ModelRun.id)
                        )
                        await session.execute(
                            ModelRunContextItem.__table__.insert().values(
                                owner_id=case.owner,
                                run_id=run_id,
                                canonical_json=context_bytes.decode(),
                                content_hash=context_hash,
                            )
                        )
                assert caught.value.orig.sqlstate == "P0001"
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_rubric_binding_checks_legacy_config_bytes_and_rejects_forged_stored_hash(case):
    async def exercise():
        engine, factory = case.factory()
        try:
            async with factory() as session:
                async with session.begin():
                    source = (
                        (
                            await session.execute(
                                text(
                                    "SELECT c.*, h.rubric_id FROM config_seed_versions c "
                                    "JOIN rubric_version_hashes h ON h.owner_id=c.owner_id AND h.co"
                                    "nfig_id=c.id "
                                    "WHERE h.owner_id=:owner AND h.id=:binding"
                                ),
                                {"owner": case.owner, "binding": case.request.rubric_binding.id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    legacy_bytes = json.dumps(
                        source["canonical_payload"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                    assert len(legacy_bytes) > 262144
                    assert sha256(legacy_bytes).digest() == source["content_hash"]
                    pg_bytes = await session.scalar(
                        text(
                            "SELECT public.tamforge_provenance_legacy_config_json(canonical"
                            "_payload) "
                            "FROM config_seed_versions WHERE owner_id=:owner AND id=:id"
                        ),
                        {"owner": case.owner, "id": source["id"]},
                    )
                    assert pg_bytes.encode() == legacy_bytes
                    # Copy lawful rows under another owner with a forged stored hash.
                    config_id = await session.scalar(
                        text(
                            "INSERT INTO config_seed_versions (owner_id,version_key,schema_version,"
                            "content_hash,canonical_payload) SELECT :owner,version_key,sche"
                            "ma_version,"
                            ":bad_hash,canonical_payload FROM config_seed_versions WHERE id"
                            "=:source "
                            "RETURNING id"
                        ),
                        {"owner": case.other_owner, "bad_hash": b"x" * 32, "source": source["id"]},
                    )
                    rubric_id = await session.scalar(
                        text(
                            "INSERT INTO rubric_versions (owner_id,config_seed_version_id,r"
                            "ubric_key,"
                            "version_key,name,scope_code,scale_min,scale_max) SELECT :owner"
                            ",:config,"
                            "rubric_key,version_key,name,scope_code,scale_min,scale_max "
                            "FROM rubric_versions WHERE id=:source RETURNING id"
                        ),
                        {
                            "owner": case.other_owner,
                            "config": config_id,
                            "source": source["rubric_id"],
                        },
                    )
                    await session.execute(
                        text(
                            "INSERT INTO rubric_dimensions (owner_id,config_seed_version_id,"
                            "rubric_version_id,dimension_key,name,weight,max_score,ordinal,"
                            "availability_rule_code) SELECT :owner,:config,:rubric,dimensio"
                            "n_key,name,"
                            "weight,max_score,ordinal,availability_rule_code FROM rubric_di"
                            "mensions "
                            "WHERE rubric_version_id=:source"
                        ),
                        {
                            "owner": case.other_owner,
                            "config": config_id,
                            "rubric": rubric_id,
                            "source": source["rubric_id"],
                        },
                    )
                    original_binding = await session.get(
                        RubricVersionHash, case.request.rubric_binding.id
                    )
                    false_binding = json.loads(original_binding.canonical_json)
                    false_binding.update(
                        owner_id=case.other_owner,
                        config_id=config_id,
                        config_hash=(b"x" * 32).hex(),
                        rubric_id=rubric_id,
                    )
                valid = await PromptRegistry(session).bind_rubric(
                    owner_id=case.owner, rubric_id=source["rubric_id"]
                )
                assert valid.id == case.request.rubric_binding.id
                with pytest.raises(InvalidProvenance):
                    await PromptRegistry(session).bind_rubric(
                        owner_id=case.other_owner, rubric_id=rubric_id
                    )
                false_bytes = canonical_bytes(false_binding)
                with pytest.raises(SQLAlchemyError) as caught:
                    async with session.begin():
                        await session.execute(
                            RubricVersionHash.__table__.insert().values(
                                owner_id=case.other_owner,
                                canonical_json=false_bytes.decode(),
                                content_hash=sha256(false_bytes).digest(),
                            )
                        )
                assert caught.value.orig.sqlstate == "P0001"
                # Legacy accepted numbers are integers; Decimal config values remain strings.
                sample = {"z": [3, "0.0100", True, None], "é": "é\n"}
                expected = json.dumps(
                    sample, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
                async with session.begin():
                    assert (
                        await session.scalar(
                            text(
                                "SELECT public.tamforge_provenance_legacy_config_json(CAST(:val"
                                "ue AS jsonb))"
                            ),
                            {"value": expected},
                        )
                        == expected
                    )
                for value in ('{"value":1.0}', '{"value":0.01}'):
                    with pytest.raises(SQLAlchemyError) as caught:
                        async with session.begin():
                            await session.execute(
                                text(
                                    "SELECT public.tamforge_provenance_legacy_config_json("
                                    "CAST(:value AS jsonb))"
                                ),
                                {"value": value},
                            )
                    assert caught.value.orig.sqlstate == "P0001"
        finally:
            await engine.dispose()

    asyncio.run(exercise())
