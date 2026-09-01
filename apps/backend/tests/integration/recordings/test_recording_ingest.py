"""Durable PostgreSQL coverage for native recording ingest boundaries."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.integration

MICROPHONE_ID = UUID("22222222-2222-4222-8222-222222222222")
SYSTEM_ID = UUID("33333333-3333-4333-8333-333333333333")
STARTED_AT = datetime(2026, 9, 1, 16, tzinfo=UTC)
PRESENTATION_TIMESCALE = 1_000_000_000


def _presentation_tick(sample: int) -> int:
    return (sample * PRESENTATION_TIMESCALE + 24_000) // 48_000


def _migrate(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    command.downgrade(migration, "base")
    command.upgrade(migration, "head")


def _create_command(recording_id: UUID) -> object:
    from tamforge_backend.recordings.schemas import RecordingCreateCommand

    return RecordingCreateCommand.model_validate(
        {
            "recording_id": str(recording_id),
            "started_at": STARTED_AT,
            "tracks": [
                {
                    "track_id": str(MICROPHONE_ID),
                    "kind": "microphone",
                    "format": {"channel_count": 1},
                    "conversion_version": "tamforge-pcm16-v1",
                },
                {
                    "track_id": str(SYSTEM_ID),
                    "kind": "system_audio",
                    "format": {"channel_count": 2},
                    "conversion_version": "tamforge-pcm16-v1",
                },
            ],
        }
    )


def _encrypted_part(
    *,
    recording_id: UUID,
    track_id: UUID,
    track_kind: str,
    channel_count: int,
    sequence: int,
    sample_start: int,
) -> tuple[object, bytes, bytes, bytes]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from tamforge_backend.recordings.contracts import part_aad_bytes
    from tamforge_backend.recordings.schemas import RecordingPartUploadMetadata

    marker = sequence + (1 if track_kind == "microphone" else 101)
    plaintext = bytes([marker, 0]) * (8 * channel_count)
    key = b"k" * 32
    nonce = bytes([marker]) * 12
    payload = {
        "recording_id": str(recording_id),
        "track_id": str(track_id),
        "track_kind": track_kind,
        "format": {"channel_count": channel_count},
        "sequence": sequence,
        "sample_start": sample_start,
        "sample_count": 8,
        "byte_length": len(plaintext),
        "ciphertext_byte_length": len(plaintext) + 16,
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
        "ciphertext_sha256": "0" * 64,
        "nonce_base64url": base64.urlsafe_b64encode(nonce).rstrip(b"=").decode(),
        "encryption_version": "aes-256-gcm-hkdf-sha256-v1",
    }
    provisional = RecordingPartUploadMetadata.model_validate(payload)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, part_aad_bytes(provisional))
    return (
        RecordingPartUploadMetadata.model_validate(
            {**payload, "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest()}
        ),
        key,
        ciphertext,
        plaintext,
    )


def _track_manifest(
    *,
    track_id: UUID,
    track_kind: str,
    channel_count: int,
    parts: tuple[tuple[object, bytes], ...],
    gaps: tuple[dict[str, object], ...] = (),
) -> object:
    from tamforge_backend.recordings.contracts import timeline_sha256
    from tamforge_backend.recordings.schemas import RecordingTrackManifest

    ordered_parts = tuple(
        sorted(parts, key=lambda item: item[0].sequence)  # type: ignore[union-attr]
    )
    descriptors = tuple(
        {
            "sequence": metadata.sequence,  # type: ignore[union-attr]
            "sample_start": metadata.sample_start,  # type: ignore[union-attr]
            "sample_count": metadata.sample_count,  # type: ignore[union-attr]
            "byte_length": metadata.byte_length,  # type: ignore[union-attr]
            "plaintext_sha256": metadata.plaintext_sha256,  # type: ignore[union-attr]
        }
        for metadata, _ in ordered_parts
    )
    source_identity = {
        "microphone": ("fixture:mono-microphone", "fixture:default-input"),
        "system_audio": ("fixture:stereo-screen-capture", "fixture:main-display"),
    }[track_kind]
    source_lineage = tuple(
        {
            "sample_start": metadata.sample_start,  # type: ignore[union-attr]
            "sample_count": metadata.sample_count,  # type: ignore[union-attr]
            "source_sample_rate_hz": 48_000,
            "source_channel_count": channel_count,
            "device_id": source_identity[0],
            "route": source_identity[1],
            "presentation_time_start": _presentation_tick(
                metadata.sample_start  # type: ignore[union-attr]
            ),
            "presentation_time_end": _presentation_tick(
                metadata.sample_start  # type: ignore[union-attr]
                + metadata.sample_count  # type: ignore[union-attr]
            ),
            "presentation_time_timescale": PRESENTATION_TIMESCALE,
            "conversion_version": "tamforge-pcm16-v1",
        }
        for metadata, _ in ordered_parts
    )
    segment_ends = [
        metadata.sample_start + metadata.sample_count  # type: ignore[union-attr]
        for metadata, _ in ordered_parts
    ] + [int(gap["sample_start"]) + int(gap["sample_count"]) for gap in gaps]
    provisional = RecordingTrackManifest.model_validate(
        {
            "track_id": str(track_id),
            "kind": track_kind,
            "format": {"channel_count": channel_count},
            "total_sample_count": max(segment_ends),
            "parts": descriptors,
            "gaps": gaps,
            "source_lineage": source_lineage,
            "pcm_sha256": hashlib.sha256(
                b"".join(plaintext for _, plaintext in ordered_parts)
            ).hexdigest(),
            "timeline_sha256": "0" * 64,
            "conversion_version": "tamforge-pcm16-v1",
        }
    )
    return provisional.model_copy(update={"timeline_sha256": timeline_sha256(provisional)})


def _seal_command(
    *,
    recording_id: UUID,
    microphone_parts: tuple[tuple[object, bytes], ...],
    system_parts: tuple[tuple[object, bytes], ...],
) -> object:
    """Build one deterministic complete seal payload for durable integration coverage."""
    from tamforge_backend.recordings.schemas import RecordingSealCommand

    microphone = _track_manifest(
        track_id=MICROPHONE_ID,
        track_kind="microphone",
        channel_count=1,
        parts=microphone_parts,
    )
    system = _track_manifest(
        track_id=SYSTEM_ID,
        track_kind="system_audio",
        channel_count=2,
        parts=system_parts,
        gaps=({"sample_start": 8, "sample_count": 8, "reason": "missing_audio"},),
    )
    return RecordingSealCommand.model_validate(
        {
            "recording_id": str(recording_id),
            "started_at": STARTED_AT,
            "ended_at": STARTED_AT + timedelta(seconds=1),
            "coverage_status": "stored_with_gaps",
            "tracks": (microphone, system),
        }
    )


def _settings(test_database_url: str) -> object:
    from sqlalchemy.engine import make_url
    from tamforge_backend.config import Settings

    async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
    return Settings(
        environment="test",
        database_url=async_url.render_as_string(hide_password=False),
        github_user_id=102269369,
        github_client_id="client-id",
        github_client_secret="provider-secret-not-persisted",
        session_signing_secret="state-signing-secret-with-enough-entropy",
        secure_cookies=False,
        _env_file=None,
    )


def _cleanup(sync_engine: object) -> None:
    from sqlalchemy import text

    try:
        with sync_engine.begin() as connection:  # type: ignore[union-attr]
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        sync_engine.dispose()  # type: ignore[union-attr]


def test_recording_migration_enforces_postgresql_state_constraints(
    test_database_url: str,
) -> None:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError
    from tamforge_backend.database import database_url_to_sync

    _migrate(test_database_url)
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        check_names = {
            item["name"] for item in inspect(sync_engine).get_check_constraints("recordings")
        }
        track_check_names = {
            item["name"]
            for item in inspect(sync_engine).get_check_constraints("recording_tracks")
        }
        assert {
            "state_coverage_coherent",
            "durable_audio_state_coherent",
            "seal_result_state_coherent",
        } <= check_names
        assert "final_manifest_state_coherent" in track_check_names

        with pytest.raises(IntegrityError, match="state_coverage_coherent"):
            with sync_engine.begin() as connection:
                owner_id = connection.execute(
                    text(
                        "INSERT INTO owners (github_user_id, github_login) "
                        "VALUES (102269369, 'owner-a') RETURNING id"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO recordings ("
                        "owner_id, client_recording_id, schema_version, state, started_at, "
                        "create_idempotency_key, create_request_hash, create_result_json"
                        ") VALUES ("
                        ":owner_id, :recording_id, 1, 'stored', CURRENT_TIMESTAMP, "
                        "'invalid-final-state', decode(repeat('00', 32), 'hex'), '{}'::jsonb"
                        ")"
                    ),
                    {"owner_id": owner_id, "recording_id": str(uuid4())},
                )
    finally:
        _cleanup(sync_engine)


def test_native_bearer_routes_scope_records_to_the_authenticated_owner(
    test_database_url: str,
) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from tamforge_backend.auth.crypto import hash_secret
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.main import create_app
    from tamforge_backend.storage.fake import InMemoryObjectStore

    _migrate(test_database_url)
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    owner_a_token = "a" * 43
    owner_b_token = "b" * 43
    recording_id = uuid4()
    try:
        with sync_engine.begin() as connection:
            for github_user_id, login, token in (
                (102269369, "owner-a", owner_a_token),
                (102269370, "owner-b", owner_b_token),
            ):
                owner_id = connection.execute(
                    text(
                        "INSERT INTO owners (github_user_id, github_login) "
                        "VALUES (:github_user_id, :login) RETURNING id"
                    ),
                    {"github_user_id": github_user_id, "login": login},
                ).scalar_one()
                native_session_id = connection.execute(
                    text(
                        "INSERT INTO native_auth_sessions ("
                        "owner_id, access_token_hash, access_expires_at"
                        ") VALUES (:owner_id, :token_hash, "
                        "CURRENT_TIMESTAMP + INTERVAL '15 minutes') "
                        "RETURNING id"
                    ),
                    {"owner_id": owner_id, "token_hash": hash_secret(token)},
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO native_refresh_tokens (session_id, token_hash, expires_at) "
                        "VALUES (:session_id, :token_hash, CURRENT_TIMESTAMP + INTERVAL '30 days')"
                    ),
                    {"session_id": native_session_id, "token_hash": hash_secret(token[::-1])},
                )

        app = create_app(_settings(test_database_url))  # type: ignore[arg-type]
        app.state.object_store = InMemoryObjectStore()
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/recordings",
                json=_create_command(recording_id).model_dump(mode="json"),  # type: ignore[union-attr]
                headers={"Authorization": f"Bearer {owner_a_token}", "Idempotency-Key": "owner-a"},
            )
            forbidden = client.get(
                f"/api/v1/recordings/{recording_id}",
                headers={"Authorization": f"Bearer {owner_b_token}"},
            )
            cookie_only = client.get(
                f"/api/v1/recordings/{recording_id}",
                cookies={"tamforge_session": "c" * 43},
            )

        assert created.status_code == 201
        assert forbidden.status_code == 404
        assert forbidden.json()["code"] == "recording_not_found"
        assert cookie_only.status_code == 401
    finally:
        _cleanup(sync_engine)


def test_part_recovery_high_water_and_two_track_seal_are_durable(
    test_database_url: str,
) -> None:
    from sqlalchemy import create_engine, event, select, text, update
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.recordings.contracts import canonical_json_bytes, timeline_sha256
    from tamforge_backend.recordings.models import Recording, RecordingTrack
    from tamforge_backend.recordings.repository import SqlAlchemyRecordingRepository
    from tamforge_backend.recordings.service import (
        RecordingService,
        recording_manifest_object_key,
        recording_part_object_key,
    )
    from tamforge_backend.storage.fake import InMemoryObjectStore

    _migrate(test_database_url)
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    recording_id = uuid4()
    try:
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'owner-a') RETURNING id"
                )
            ).scalar_one()

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            store = InMemoryObjectStore()
            late_part, late_key, late_ciphertext, late_plaintext = _encrypted_part(
                recording_id=recording_id,
                track_id=MICROPHONE_ID,
                track_kind="microphone",
                channel_count=1,
                sequence=1,
                sample_start=8,
            )
            early_part, early_key, early_ciphertext, early_plaintext = _encrypted_part(
                recording_id=recording_id,
                track_id=MICROPHONE_ID,
                track_kind="microphone",
                channel_count=1,
                sequence=0,
                sample_start=0,
            )
            system_part, system_key, system_ciphertext, system_plaintext = _encrypted_part(
                recording_id=recording_id,
                track_id=SYSTEM_ID,
                track_kind="system_audio",
                channel_count=2,
                sequence=0,
                sample_start=0,
            )

            class FailingFinalizeRepository(SqlAlchemyRecordingRepository):
                async def finalize_part(self, **kwargs):  # type: ignore[no-untyped-def]
                    def fail_before_commit(sync_session: object) -> None:
                        del sync_session
                        raise RuntimeError("forced recording finalize failure")

                    event.listen(self._session.sync_session, "before_commit", fail_before_commit)
                    return await super().finalize_part(**kwargs)

            async def upload(
                metadata: object,
                part_key: bytes,
                ciphertext: bytes,
                idempotency_key: str,
                *,
                fail: bool = False,
            ) -> object:
                async with factory() as session:
                    repository = (
                        FailingFinalizeRepository(session)
                        if fail
                        else SqlAlchemyRecordingRepository(session)
                    )
                    return await RecordingService(repository, store).upload_part(
                        owner_id=owner_id,
                        metadata=metadata,  # type: ignore[arg-type]
                        part_key=part_key,
                        ciphertext=ciphertext,
                        idempotency_key=idempotency_key,
                    )

            try:
                async with factory() as session:
                    service = RecordingService(SqlAlchemyRecordingRepository(session), store)
                    await service.create(
                        owner_id=owner_id,
                        command=_create_command(recording_id),  # type: ignore[arg-type]
                        idempotency_key="recording-create",
                    )

                late = await upload(late_part, late_key, late_ciphertext, "part-one")
                assert late.high_water_sample == 0  # type: ignore[union-attr]

                with pytest.raises(RuntimeError, match="forced recording finalize failure"):
                    await upload(
                        early_part,
                        early_key,
                        early_ciphertext,
                        "part-zero",
                        fail=True,
                    )
                early_object_key = recording_part_object_key(
                    owner_id=owner_id,
                    metadata=early_part,  # type: ignore[arg-type]
                )
                early_object = await store.stat(early_object_key)
                assert early_object is not None
                assert (
                    early_object.sha256
                    == early_part.plaintext_sha256  # type: ignore[union-attr]
                )
                assert early_object.byte_length == len(early_plaintext)

                recovered, replayed = await asyncio.gather(
                    upload(early_part, early_key, early_ciphertext, "part-zero"),
                    upload(early_part, early_key, early_ciphertext, "part-zero"),
                )
                replay_states = [
                    recovered.replayed,  # type: ignore[union-attr]
                    replayed.replayed,  # type: ignore[union-attr]
                ]
                assert sorted(replay_states) == [False, True]
                assert (
                    recovered.high_water_sample  # type: ignore[union-attr]
                    == replayed.high_water_sample  # type: ignore[union-attr]
                    == 16
                )

                system = await upload(
                    system_part,
                    system_key,
                    system_ciphertext,
                    "system-part-zero",
                )
                assert system.high_water_sample == 8  # type: ignore[union-attr]

                seal_command = _seal_command(
                    recording_id=recording_id,
                    microphone_parts=(
                        (early_part, early_plaintext),
                        (late_part, late_plaintext),
                    ),
                    system_parts=((system_part, system_plaintext),),
                )
                for manifest in seal_command.tracks:  # type: ignore[union-attr]
                    part_ranges = tuple(
                        (part.sample_start, part.sample_count) for part in manifest.parts
                    )
                    lineage_ranges = tuple(
                        (segment.sample_start, segment.sample_count)
                        for segment in manifest.source_lineage
                    )
                    assert lineage_ranges == part_ranges
                    assert all(
                        segment.presentation_time_timescale == PRESENTATION_TIMESCALE
                        and segment.source_sample_rate_hz == 48_000
                        and segment.source_channel_count == manifest.format.channel_count
                        and segment.conversion_version == "tamforge-pcm16-v1"
                        and segment.presentation_time_start
                        == _presentation_tick(segment.sample_start)
                        and segment.presentation_time_end
                        == _presentation_tick(segment.sample_start + segment.sample_count)
                        for segment in manifest.source_lineage
                    )
                    assert timeline_sha256(manifest) == manifest.timeline_sha256
                    changed_lineage = (
                        manifest.source_lineage[0].model_copy(update={"route": "fixture:changed"}),
                        *manifest.source_lineage[1:],
                    )
                    assert timeline_sha256(
                        manifest.model_copy(update={"source_lineage": changed_lineage})
                    ) != manifest.timeline_sha256
                async with factory() as seal_session:
                    sealed = await RecordingService(
                        SqlAlchemyRecordingRepository(seal_session), store
                    ).seal(
                        owner_id=owner_id,
                        command=seal_command,  # type: ignore[arg-type]
                        idempotency_key="recording-seal",
                    )

                assert sealed.state == "stored_with_gaps"
                assert sealed.coverage_status == "stored_with_gaps"
                assert sealed.audio_created_on_server is True
                assert sealed.transcript_lineage_accepted is False
                assert sealed.replayed is False

                async with factory() as fresh_session:
                    status = await RecordingService(
                        SqlAlchemyRecordingRepository(fresh_session), store
                    ).status(owner_id=owner_id, recording_id=recording_id)
                    recording = await fresh_session.scalar(
                        select(Recording)
                        .where(Recording.owner_id == owner_id)
                        .where(Recording.client_recording_id == recording_id)
                    )
                    assert recording is not None
                    tracks = tuple(
                        (
                            await fresh_session.scalars(
                                select(RecordingTrack)
                                .where(RecordingTrack.owner_id == owner_id)
                                .where(RecordingTrack.recording_id == recording.id)
                            )
                        ).all()
                    )

                assert status.state == "stored_with_gaps"
                assert status.coverage_status == "stored_with_gaps"
                assert status.audio_created_on_server is True
                assert status.transcript_lineage_accepted is False
                status_tracks = {track.kind: track for track in status.tracks}
                assert status_tracks["microphone"].high_water_sample == 16
                assert status_tracks["microphone"].stored_part_count == 2
                assert status_tracks["microphone"].gap_count == 0
                assert status_tracks["system_audio"].high_water_sample == 16
                assert status_tracks["system_audio"].stored_part_count == 1
                assert status_tracks["system_audio"].gap_count == 1

                rows_by_kind = {track.kind: track for track in tracks}
                assert rows_by_kind["microphone"].state == "stored"
                assert rows_by_kind["system_audio"].state == "stored_with_gaps"
                expected_manifest_digests: list[str] = []
                for manifest in seal_command.tracks:  # type: ignore[union-attr]
                    body = canonical_json_bytes(manifest)
                    digest = hashlib.sha256(body).hexdigest()
                    expected_manifest_digests.append(digest)
                    row = rows_by_kind[manifest.kind]
                    expected_key = recording_manifest_object_key(
                        owner_id=owner_id,
                        recording_id=recording_id,
                        track_id=manifest.track_id,
                        sha256=digest,
                    )
                    assert row.total_sample_count == 16
                    assert row.manifest_object_key == expected_key
                    assert row.manifest_sha256 == bytes.fromhex(digest)
                    assert row.manifest_byte_length == len(body)
                    stored_manifest = await store.stat(expected_key)
                    assert stored_manifest is not None
                    assert stored_manifest.sha256 == digest
                    assert stored_manifest.byte_length == len(body)
                    async with store.open(expected_key) as chunks:
                        persisted_body = b"".join([chunk async for chunk in chunks])
                    assert persisted_body == body

                assert sealed.track_manifest_sha256 == tuple(expected_manifest_digests)

                with pytest.raises(IntegrityError, match="state_coverage_coherent"):
                    async with factory.begin() as violating_session:
                        await violating_session.execute(
                            update(Recording)
                            .where(Recording.id == recording.id)
                            .values(coverage_status="complete")
                        )
                with pytest.raises(IntegrityError, match="durable_audio_state_coherent"):
                    async with factory.begin() as violating_session:
                        await violating_session.execute(
                            update(Recording)
                            .where(Recording.id == recording.id)
                            .values(audio_created_on_server=False)
                        )
                with pytest.raises(IntegrityError, match="final_manifest_state_coherent"):
                    async with factory.begin() as violating_session:
                        await violating_session.execute(
                            update(RecordingTrack)
                            .where(RecordingTrack.id == rows_by_kind["microphone"].id)
                            .values(manifest_object_key=None)
                        )
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        _cleanup(sync_engine)
