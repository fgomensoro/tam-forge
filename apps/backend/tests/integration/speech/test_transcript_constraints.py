"""Real PostgreSQL constraint checks for transcript provenance.

Every insert here goes straight through a raw `Connection`, bypassing
`SqlAlchemyTranscriptRepository` entirely, so these assertions hold even if the
repository never ran: they are the database's own guarantees, not the Python
layer's. `tests/speech/test_transcript_repository.py` covers the repository
against a fake session and says so in its own docstring; this file is the
integration suite it points to for the generated `recording_id` / `track` /
`transcript_id` columns, the `content_hash` and `canonical_json` CHECK
constraints (verified with `public.digest` and
`public.tamforge_provenance_canonical`), the `speech_transcripts` uniqueness
on `(owner_id, recording_id, track)`, the `RESTRICT` foreign keys, and the
`BEFORE UPDATE OR DELETE` immutability triggers from
`20260909_0018_transcripts.py`.

`speech_transcript_corrections` shares the exact same `provenance_checks()`
constraint set as `speech_transcripts` -- hash match, canonical bytes, body
bound -- just at a different size limit. Proving that mechanism once, against
`speech_transcripts`, is proof of the shared function; this file does not
repeat those three checks against corrections. What corrections adds
structurally -- its own generated `transcript_id` column and its own
immutability trigger -- is covered directly, below.

One `ON DELETE RESTRICT` foreign key in this migration is not independently
observable from here: `fk_speech_transcript_corrections_transcript` protects a
`speech_transcripts` row referenced by a correction, but that row's own
`trg_speech_transcripts_immutable` trigger (`BEFORE ... FOR EACH STATEMENT`)
unconditionally rejects every `DELETE` against `speech_transcripts` before
Postgres gets far enough to evaluate any foreign key referencing it -- proven
empirically while writing this file: attempting to delete a transcript that a
correction points at raises the same "provenance is immutable" error as
deleting one with no correction at all. The delete is blocked either way;
`test_delete_is_rejected_by_the_immutability_trigger` below already proves
that. Only `fk_speech_transcripts_recording` (deleting the parent `recordings`
row) is reachable on its own, and is the one exercised here.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from tamforge_backend.agents.hashing import canonical_bytes
from tamforge_backend.database import database_url_to_sync
from tamforge_backend.speech.models import CORRECTION_BODY_LIMIT, TRANSCRIPT_BODY_LIMIT

pytestmark = pytest.mark.integration


@dataclass
class Seeded:
    engine: Engine
    owner_id: int
    recording_id: int


def _random_positive_bigint() -> int:
    return secrets.randbelow(2**48) + 1


def _insert_owner(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (:gid, :login) RETURNING id"
        ),
        {"gid": _random_positive_bigint(), "login": f"speech-constraints-{uuid4().hex[:12]}"},
    ).scalar_one()


def _insert_recording(connection: Connection, *, owner_id: int) -> int:
    return connection.execute(
        text(
            "INSERT INTO recordings ("
            "owner_id, client_recording_id, started_at, "
            "create_idempotency_key, create_request_hash, create_result_json"
            ") VALUES ("
            ":owner_id, :client_recording_id, :started_at, :key, :hash, CAST(:result AS jsonb)"
            ") RETURNING id"
        ),
        {
            "owner_id": owner_id,
            "client_recording_id": uuid4(),
            "started_at": datetime.now(UTC),
            "key": f"key-{uuid4().hex}",
            "hash": b"\x00" * 32,
            "result": "{}",
        },
    ).scalar_one()


def _transcript_canonical(
    *,
    recording_id: int,
    track: str,
    limit: int = TRANSCRIPT_BODY_LIMIT,
    **overrides: object,
) -> tuple[str, bytes]:
    body: dict[str, object] = {
        "schema_version": 1,
        "text": "hello there",
        "recording_id": recording_id,
        "track": track,
    }
    body.update(overrides)
    data = canonical_bytes(body, limit=limit)
    return data.decode("utf-8"), sha256(data).digest()


def _oversized_transcript_canonical(*, recording_id: int, track: str) -> tuple[str, bytes]:
    """A canonical, correctly-hashed body exactly one byte past the 4 MiB bound.

    `canonical_bytes` itself enforces `TRANSCRIPT_BODY_LIMIT`, so both calls
    below pass a much larger `limit` -- the point is to reach PostgreSQL with a
    body Python's own guard would otherwise have rejected first, and prove the
    database's `ck_speech_transcripts_content_bounded` check catches it too.
    """
    empty, _ = _transcript_canonical(
        recording_id=recording_id, track=track, text="", limit=10_000_000
    )
    filler = "x" * (TRANSCRIPT_BODY_LIMIT + 1 - len(empty.encode("utf-8")))
    return _transcript_canonical(
        recording_id=recording_id, track=track, text=filler, limit=10_000_000
    )


def _non_canonical_transcript_json(*, recording_id: int, track: str) -> tuple[str, bytes]:
    """Valid JSON, correctly hashed, deliberately not canonical: keys out of
    the ascending order `tamforge_provenance_canonical` requires."""
    raw = (
        f'{{"track":"{track}","recording_id":{recording_id},'
        '"schema_version":1,"text":"hello there"}'
    )
    return raw, sha256(raw.encode("utf-8")).digest()


def _insert_transcript(
    connection: Connection, *, owner_id: int, canonical_json: str, content_hash: bytes
) -> int:
    return connection.execute(
        text(
            "INSERT INTO speech_transcripts (owner_id, canonical_json, content_hash) "
            "VALUES (:owner_id, :canonical_json, :content_hash) RETURNING id"
        ),
        {"owner_id": owner_id, "canonical_json": canonical_json, "content_hash": content_hash},
    ).scalar_one()


def _insert_valid_transcript(
    connection: Connection, *, owner_id: int, recording_id: int, track: str = "microphone"
) -> int:
    canonical, content_hash = _transcript_canonical(recording_id=recording_id, track=track)
    return _insert_transcript(
        connection, owner_id=owner_id, canonical_json=canonical, content_hash=content_hash
    )


def _correction_canonical(*, transcript_id: int, **overrides: object) -> tuple[str, bytes]:
    body: dict[str, object] = {
        "schema_version": 1,
        "segment_index": 0,
        "word_start_index": 0,
        "word_end_index": 1,
        "original_text": "helo",
        "corrected_text": "hello",
        "reason": "misheard_term",
        "transcript_id": transcript_id,
    }
    body.update(overrides)
    data = canonical_bytes(body, limit=CORRECTION_BODY_LIMIT)
    return data.decode("utf-8"), sha256(data).digest()


def _insert_valid_correction(connection: Connection, *, owner_id: int, transcript_id: int) -> int:
    canonical, content_hash = _correction_canonical(transcript_id=transcript_id)
    return connection.execute(
        text(
            "INSERT INTO speech_transcript_corrections (owner_id, canonical_json, content_hash) "
            "VALUES (:owner_id, :canonical_json, :content_hash) RETURNING id"
        ),
        {"owner_id": owner_id, "canonical_json": canonical, "content_hash": content_hash},
    ).scalar_one()


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def seeded(engine: Engine) -> Seeded:
    with engine.begin() as connection:
        owner_id = _insert_owner(connection)
        recording_id = _insert_recording(connection, owner_id=owner_id)
    return Seeded(engine=engine, owner_id=owner_id, recording_id=recording_id)


# ---- speech_transcripts -----------------------------------------------------


def test_content_hash_must_equal_sha256_of_canonical_json(seeded: Seeded) -> None:
    canonical, _ = _transcript_canonical(recording_id=seeded.recording_id, track="microphone")
    with pytest.raises(IntegrityError, match="ck_speech_transcripts_hash_matches"):
        with seeded.engine.begin() as connection:
            _insert_transcript(
                connection,
                owner_id=seeded.owner_id,
                canonical_json=canonical,
                content_hash=b"\x00" * 32,
            )


def test_canonical_json_must_be_canonical_not_just_valid_json(seeded: Seeded) -> None:
    raw, content_hash = _non_canonical_transcript_json(
        recording_id=seeded.recording_id, track="microphone"
    )
    with pytest.raises(IntegrityError, match="ck_speech_transcripts_canonical_bytes"):
        with seeded.engine.begin() as connection:
            _insert_transcript(
                connection, owner_id=seeded.owner_id, canonical_json=raw, content_hash=content_hash
            )


def test_second_transcript_for_same_owner_recording_track_conflicts(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
    canonical, content_hash = _transcript_canonical(
        recording_id=seeded.recording_id, track="microphone", text="a different transcript"
    )
    with pytest.raises(IntegrityError, match="uq_speech_transcripts_recording_track"):
        with seeded.engine.begin() as connection:
            _insert_transcript(
                connection,
                owner_id=seeded.owner_id,
                canonical_json=canonical,
                content_hash=content_hash,
            )


def test_track_outside_allowed_pair_is_rejected(seeded: Seeded) -> None:
    canonical, content_hash = _transcript_canonical(
        recording_id=seeded.recording_id, track="webcam"
    )
    with pytest.raises(IntegrityError, match="ck_speech_transcripts_track_allowed"):
        with seeded.engine.begin() as connection:
            _insert_transcript(
                connection,
                owner_id=seeded.owner_id,
                canonical_json=canonical,
                content_hash=content_hash,
            )


def test_body_one_byte_over_four_mebibytes_is_rejected(seeded: Seeded) -> None:
    canonical, content_hash = _oversized_transcript_canonical(
        recording_id=seeded.recording_id, track="microphone"
    )
    assert len(canonical.encode("utf-8")) == TRANSCRIPT_BODY_LIMIT + 1
    with pytest.raises(IntegrityError, match="ck_speech_transcripts_content_bounded"):
        with seeded.engine.begin() as connection:
            _insert_transcript(
                connection,
                owner_id=seeded.owner_id,
                canonical_json=canonical,
                content_hash=content_hash,
            )


def test_generated_recording_id_and_track_match_the_json_body(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        transcript_id = _insert_valid_transcript(
            connection,
            owner_id=seeded.owner_id,
            recording_id=seeded.recording_id,
            track="system_audio",
        )
        row = connection.execute(
            text("SELECT recording_id, track FROM speech_transcripts WHERE id = :id"),
            {"id": transcript_id},
        ).one()
    assert row.recording_id == seeded.recording_id
    assert row.track == "system_audio"


def test_update_is_rejected_by_the_immutability_trigger(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        transcript_id = _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
    with pytest.raises(ProgrammingError, match="immutable"):
        with seeded.engine.begin() as connection:
            connection.execute(
                text("UPDATE speech_transcripts SET hash_format = hash_format WHERE id = :id"),
                {"id": transcript_id},
            )


def test_delete_is_rejected_by_the_immutability_trigger(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        transcript_id = _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
    with pytest.raises(ProgrammingError, match="immutable"):
        with seeded.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM speech_transcripts WHERE id = :id"), {"id": transcript_id}
            )


def test_deleting_a_referenced_recording_is_restricted_by_foreign_key(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
    with pytest.raises(IntegrityError, match="fk_speech_transcripts_recording"):
        with seeded.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM recordings WHERE id = :id"), {"id": seeded.recording_id}
            )


# ---- speech_transcript_corrections ------------------------------------------


def test_correction_generated_transcript_id_matches_the_json_body(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        transcript_id = _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
        correction_id = _insert_valid_correction(
            connection, owner_id=seeded.owner_id, transcript_id=transcript_id
        )
        row = connection.execute(
            text("SELECT transcript_id FROM speech_transcript_corrections WHERE id = :id"),
            {"id": correction_id},
        ).one()
    assert row.transcript_id == transcript_id


def test_correction_update_is_rejected_by_the_immutability_trigger(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        transcript_id = _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
        correction_id = _insert_valid_correction(
            connection, owner_id=seeded.owner_id, transcript_id=transcript_id
        )
    with pytest.raises(ProgrammingError, match="immutable"):
        with seeded.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE speech_transcript_corrections SET hash_format = hash_format "
                    "WHERE id = :id"
                ),
                {"id": correction_id},
            )


def test_correction_delete_is_rejected_by_the_immutability_trigger(seeded: Seeded) -> None:
    with seeded.engine.begin() as connection:
        transcript_id = _insert_valid_transcript(
            connection, owner_id=seeded.owner_id, recording_id=seeded.recording_id
        )
        correction_id = _insert_valid_correction(
            connection, owner_id=seeded.owner_id, transcript_id=transcript_id
        )
    with pytest.raises(ProgrammingError, match="immutable"):
        with seeded.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM speech_transcript_corrections WHERE id = :id"),
                {"id": correction_id},
            )
