"""End-to-end coverage of the real route, the real `TranscriptService`, the real
`SqlAlchemyTranscriptRepository`, and real PostgreSQL, all in the same process.

This is the seam the transcript-lineage final review's Important 1 found untested
anywhere on the branch: `tests/speech/test_transcript_routes.py` stubs the service,
`tests/speech/test_transcript_service.py` drives the real service against a fake
repository and a `FakeSession` whose `begin()` cannot raise, `tests/speech/
test_transcript_repository.py` drives the real repository against a hand-written
fake session that never rejects re-entry, and `test_transcript_constraints.py` in
this same directory goes straight through a raw `Connection`, bypassing
`SqlAlchemyTranscriptRepository` entirely (see its own docstring). Every layer was
tested against a fake of the layer below, so the one path that mattered -- a real
request through all of them at once -- was never run.

That gap is exactly what let Critical 1 ship: `TranscriptService._resolve_recording`
issued a plain entity `SELECT` on the request session, which autobegins a
transaction, and never closed it before `SqlAlchemyTranscriptRepository.store`
opened its own via `transaction_scope`. `AsyncSession.begin()` raises
`InvalidRequestError` -- a `SQLAlchemyError` -- when a transaction is already begun,
so the repository's own translation layer caught it and turned every submission into
a 503, and `Recording.transcript_lineage_accepted` was never set. No fake session in
the unit suites reproduces that: a fake's `begin()` just yields.

This test submits a transcript through the real HTTP route, asserts the lineage flag
actually flips in the database, resubmits the identical body and asserts the replay
path leaves the flag true too, and appends a correction -- the smallest scenario that
would have caught Critical 1, per the review. It also exercises a body with the kind
of fractional numbers real whisper output produces (`probability`, `clipped_ratio`,
`dc_offset`, `duration_seconds`), closing the review's Minor 6: nothing before this
file put a float through `SqlAlchemyTranscriptRepository`, the schema's
`validate_body_size`, and PostgreSQL's `ck_speech_transcripts_canonical_bytes`
together.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from tamforge_backend.auth.crypto import hash_secret
from tamforge_backend.config import Settings
from tamforge_backend.database import database_url_to_sync
from tamforge_backend.main import create_app
from tamforge_backend.storage.fake import InMemoryObjectStore

pytestmark = pytest.mark.integration

STARTED_AT = datetime(2026, 9, 9, 12, tzinfo=UTC)


@dataclass
class Seeded:
    owner_id: int
    token: str
    recording_id: UUID


def _migration(url: str) -> Config:
    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = url
    return config


def _reset(url: str) -> None:
    # Mirrors test_transcript_constraints.py's own `_reset` in this directory,
    # which in turn copies test_agent_runtime_migration.py: this file cannot
    # assume another file already left the schema at head, and several
    # integration files rebuild `public` themselves, so this one takes
    # responsibility for its own schema too.
    engine = create_engine(database_url_to_sync(url))
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    command.upgrade(_migration(url), "head")


def _settings(test_database_url: str) -> Settings:
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


def _insert_owner_with_native_session(connection: Connection, *, token: str) -> int:
    owner_id = connection.execute(
        text(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (:gid, :login) RETURNING id"
        ),
        {"gid": secrets.randbelow(2**48) + 1, "login": f"transcript-submit-{uuid4().hex[:12]}"},
    ).scalar_one()
    session_id = connection.execute(
        text(
            "INSERT INTO native_auth_sessions (owner_id, access_token_hash, access_expires_at) "
            "VALUES (:owner_id, :token_hash, CURRENT_TIMESTAMP + INTERVAL '15 minutes') "
            "RETURNING id"
        ),
        {"owner_id": owner_id, "token_hash": hash_secret(token)},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO native_refresh_tokens (session_id, token_hash, expires_at) "
            "VALUES (:session_id, :token_hash, CURRENT_TIMESTAMP + INTERVAL '30 days')"
        ),
        {"session_id": session_id, "token_hash": hash_secret(token[::-1])},
    )
    return owner_id


def _insert_stored_recording(connection: Connection, *, owner_id: int) -> UUID:
    # A hand-built row satisfying every coherence check a genuine `stored` recording
    # would (state_coverage_coherent, durable_audio_state_coherent,
    # seal_idempotency_tuple_coherent, seal_result_state_coherent) -- this test cares
    # about the transcript write path, not the recording ingest pipeline that
    # normally produces this state, and driving that whole pipeline just to seed one
    # row would only restate what test_recording_ingest.py already covers.
    client_recording_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO recordings ("
            "owner_id, client_recording_id, state, coverage_status, audio_created_on_server, "
            "started_at, ended_at, "
            "create_idempotency_key, create_request_hash, create_result_json, "
            "seal_idempotency_key, seal_request_hash, seal_result_json"
            ") VALUES ("
            ":owner_id, :client_recording_id, 'stored', 'complete', true, "
            ":started_at, :ended_at, "
            ":create_key, :create_hash, CAST(:create_result AS jsonb), "
            ":seal_key, :seal_hash, CAST(:seal_result AS jsonb)"
            ")"
        ),
        {
            "owner_id": owner_id,
            "client_recording_id": client_recording_id,
            "started_at": STARTED_AT,
            "ended_at": STARTED_AT + timedelta(seconds=1),
            "create_key": f"create-{uuid4().hex}",
            "create_hash": b"\x00" * 32,
            "create_result": "{}",
            "seal_key": f"seal-{uuid4().hex}",
            "seal_hash": b"\x00" * 32,
            "seal_result": "{}",
        },
    )
    # sealed_at is left NULL deliberately: ck_recordings_sealed_after_creation
    # requires it be >= created_at (a server-generated NOW()), and this row's
    # started_at/ended_at are fixed historical-looking timestamps chosen for
    # readability, not tied to wall-clock time. sealed_at is nullable and
    # TranscriptService never reads it, so leaving it out avoids a real-clock
    # dependency for no benefit to what this test verifies.
    return client_recording_id


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    _reset(test_database_url)
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        yield engine
    finally:
        engine.dispose()
        _reset(test_database_url)


@pytest.fixture
def seeded(engine: Engine) -> Seeded:
    # 43 characters, alnum: matches the bearer-token shape already proven against
    # get_bearer_authenticated_owner in test_recording_ingest.py.
    token = (uuid4().hex + uuid4().hex)[:43]
    with engine.begin() as connection:
        owner_id = _insert_owner_with_native_session(connection, token=token)
        recording_id = _insert_stored_recording(connection, owner_id=owner_id)
    return Seeded(owner_id=owner_id, token=token, recording_id=recording_id)


def _transcript_body(**overrides: object) -> dict[str, object]:
    # Deliberately carries the kind of fractional numbers whisper.cpp actually
    # emits (see the module docstring on Minor 6), not clean integers: this is the
    # first test on the branch to put a float through the real repository's
    # canonicalize-and-hash path against PostgreSQL's own canonicalization.
    body: dict[str, object] = {
        "schema_version": 1,
        "track": "microphone",
        "segments": [
            {
                "text": "hello there",
                "start_ms": 0,
                "end_ms": 900,
                "words": [
                    {
                        "text": "hello",
                        "start_ms": 0,
                        "end_ms": 400,
                        "probability": 0.9800000190734863,
                    },
                    {
                        "text": "there",
                        "start_ms": 400,
                        "end_ms": 900,
                        "probability": 0.30000000000000004,
                    },
                ],
            }
        ],
        "model_identity": {
            "runtime_version": "b4938",
            "model_filename": "ggml-base.en-q5_1.bin",
            "model_sha256": "a" * 64,
            "metal_requested": True,
            "used_builtin_vad": False,
            "language": "en",
        },
        "derivation": {
            "derivation_version": "tamforge-asr16k-v1",
            "source_sample_rate": 48_000,
            "source_channel_count": 1,
            "source_sample_count": 43_200,
            "output_sample_rate": 16_000,
            "output_sample_count": 14_400,
            "zero_filled_gaps": [],
            "source_pcm_sha256": "b" * 64,
            "derived_pcm_sha256": "c" * 64,
            "quality": {
                "version": "v1",
                "sample_rate": 48_000,
                "channel_count": 1,
                "source_sample_count": 43_200,
                "duration_seconds": 0.9000000000000001,
                "peak_absolute": 12_345,
                "all_silence": False,
                "clipped_ratio": 9.999999747378752e-05,
                "dc_offset": 1e-12,
                "channel_imbalance_decibels": None,
                "discontinuity_count": 0,
                "unavailable_dimensions": [],
            },
        },
    }
    body.update(overrides)
    return body


def test_submit_replay_and_correction_go_through_the_real_service_repository_and_database(
    seeded: Seeded, test_database_url: str
) -> None:
    app = create_app(_settings(test_database_url))
    app.state.object_store = InMemoryObjectStore()
    headers = {"Authorization": f"Bearer {seeded.token}"}
    body = _transcript_body()

    with TestClient(app) as client:
        # A fresh submission: this is the exact call Critical 1 made 503 on every
        # real database, because store()'s transaction_scope raised
        # InvalidRequestError against the transaction _resolve_recording's read
        # left open.
        first = client.post(
            f"/api/v1/recordings/{seeded.recording_id}/transcripts",
            json=body,
            headers={**headers, "Idempotency-Key": "transcript-submit-first"},
        )
        assert first.status_code == 201, first.text
        first_json = first.json()
        assert first_json["replayed"] is False
        transcript_id = first_json["transcript_id"]

        # An identical resubmission: exercises the content-hash replay path, which
        # calls add_correction's sibling read (by_recording_track, from inside
        # store's own transaction) and _accept_lineage's second commit again --
        # both places C1's fix has to hold for.
        second = client.post(
            f"/api/v1/recordings/{seeded.recording_id}/transcripts",
            json=body,
            headers={**headers, "Idempotency-Key": "transcript-submit-second"},
        )
        assert second.status_code == 201, second.text
        second_json = second.json()
        assert second_json["replayed"] is True
        assert second_json["transcript_id"] == transcript_id

        # A correction: add_correction's own read-then-write sequence
        # (_resolve_recording, then by_recording_track a second time) is the other
        # call C1 broke.
        correction_body = {
            "schema_version": 1,
            "segment_index": 0,
            "word_start_index": 0,
            "word_end_index": 1,
            "original_text": "helo",
            "corrected_text": "hello",
            "reason": "misheard_term",
        }
        correction = client.post(
            f"/api/v1/recordings/{seeded.recording_id}/transcripts/microphone/corrections",
            json=correction_body,
            headers={**headers, "Idempotency-Key": "transcript-correction-first"},
        )
        assert correction.status_code == 201, correction.text
        correction_json = correction.json()
        assert correction_json["transcript_id"] == transcript_id
        assert correction_json["replayed"] is False

        # Replaying the identical correction: append_correction's own
        # content-hash replay path, one more read-then-write sequence sharing the
        # same request session.
        replayed_correction = client.post(
            f"/api/v1/recordings/{seeded.recording_id}/transcripts/microphone/corrections",
            json=correction_body,
            headers={**headers, "Idempotency-Key": "transcript-correction-second"},
        )
        assert replayed_correction.status_code == 201, replayed_correction.text
        assert replayed_correction.json()["replayed"] is True
        assert replayed_correction.json()["correction_id"] == correction_json["correction_id"]

    # The whole point of this test: the lineage flag actually flipped in the
    # database, on the row this test seeded -- not just that the route returned
    # 201. A regression that reintroduces C1 would 503 above and never reach here;
    # a regression that returns 201 without setting the flag (e.g. a broken
    # _accept_lineage) would reach here and fail this assertion instead.
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with sync_engine.connect() as connection:
            flag = connection.execute(
                text(
                    "SELECT transcript_lineage_accepted FROM recordings "
                    "WHERE owner_id = :owner_id AND client_recording_id = :recording_id"
                ),
                {"owner_id": seeded.owner_id, "recording_id": seeded.recording_id},
            ).scalar_one()
    finally:
        sync_engine.dispose()
    assert flag is True
