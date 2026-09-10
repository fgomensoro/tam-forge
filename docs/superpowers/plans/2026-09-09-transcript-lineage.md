# Transcript Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist an immutable transcript with words, uncertainty, corrections and model lineage, so accepting one releases the encrypted local spool.

**Architecture:** A new `speech` backend module reusing the provenance precedent from `agents`: canonical JSON v1 in a single `TEXT` column, its SHA-256 verified by a database constraint, relational columns generated from the JSON so row and body cannot diverge. Corrections are a second append-only table pointing at a transcript. The macOS client posts the transcript it already computes; the existing upload path releases the spool on its own once the server reports both gates true.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL, Pydantic v2, Swift 6 / SwiftUI, XCTest.

**Spec:** `docs/superpowers/specs/2026-09-09-transcript-lineage-design.md`

## Global Constraints

- Alembic revision ids must be 32 characters or fewer. This plan's revision is `20260909_0018_transcripts` (25).
- No Pydantic field may be typed `None`. A bare `{"type": "null"}` breaks the Swift OpenAPI generator and takes down `macos-native`, `native-ui` and `e2e`. Use `X | None` unions.
- Adding a migration moves the head asserted by `test_curriculum_schema.py::test_alembic_has_exactly_one_linear_head`. Adding an operation moves `FROZEN_OPENAPI_SHA256` in `scripts/ci/tests/test_check_openapi.py`. Update both.
- Run every `uv` command as `uv run --no-sync ...`. On a fresh worktree run `uv sync --all-packages --all-extras` once first, otherwise `--no-sync` creates an empty environment and dies with `Failed to spawn: pytest`.
- Transcript text is private. It never reaches a log line, an object key, an error message, or a response field outside the owner's own GET. Write endpoints set the `no-store` headers via the existing `_prevent_storage`.
- Canonical JSON v1 is `tamforge_backend.agents.hashing`: UTF-8, sorted keys, plain finite decimals, no whitespace.

---

### Task 1: Shared provenance base and the two tables

Move the provenance record base out of `agents` so `speech` can use it without importing a private name, then add both tables and the migration.

**Files:**
- Create: `apps/backend/src/tamforge_backend/models/provenance.py`
- Modify: `apps/backend/src/tamforge_backend/agents/models.py:29-63` (import the moved names instead of defining them)
- Create: `apps/backend/src/tamforge_backend/speech/__init__.py`
- Create: `apps/backend/src/tamforge_backend/speech/models.py`
- Create: `apps/backend/alembic/versions/20260909_0018_transcripts.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py:8-18` (register `tamforge_backend.speech.models`)
- Modify: `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` (new head constant)
- Test: `apps/backend/tests/speech/test_transcript_models.py`

**Interfaces:**
- Consumes: `tamforge_backend.models.base.Base`, `public.digest`, `public.tamforge_provenance_canonical` (both already created by `20260905_0015_model_provenance`).
- Produces: `Record` and `provenance_checks(table, *, prompt=False, limit=262144)` in `models/provenance.py`; `SpeechTranscript` and `SpeechTranscriptCorrection` in `speech/models.py`.

- [ ] **Step 1: Move the base without changing behaviour**

Cut `Record` and `_checks` out of `agents/models.py` into a new `models/provenance.py`, renaming `_checks` to `provenance_checks`. Keep the bodies byte-identical apart from the name.

```python
"""Shared append-only provenance base: canonical JSON is the hashed byte domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Record(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("owners.id"), nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    hash_format: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def provenance_checks(table: str, *, prompt: bool = False, limit: int = 262144) -> tuple[Any, ...]:
    checks: tuple[Any, ...] = (
        UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id_id"),
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("owner_id > 0", name="owner_positive"),
        CheckConstraint("hash_format = 1", name="hash_format_v1"),
        CheckConstraint(
            f"octet_length(canonical_json) BETWEEN 1 AND {limit}", name="content_bounded"
        ),
        CheckConstraint(
            "content_hash = public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')",
            name="hash_matches",
        ),
    )
    if not prompt:
        checks += (
            CheckConstraint(
                "canonical_json = public.tamforge_provenance_canonical(canonical_json::jsonb)",
                name="canonical_bytes",
            ),
        )
    return checks
```

In `agents/models.py` replace the deleted definitions with `from ..models.provenance import Record, provenance_checks` and define `_checks = provenance_checks` immediately below it, so the existing call sites in that file keep working untouched.

- [ ] **Step 2: Run the existing agent suite to prove the move changed nothing**

Run: `uv run --no-sync pytest apps/backend/tests/unit/agents -q`
Expected: PASS, same count as before the move.

- [ ] **Step 3: Write the failing model test**

Create `apps/backend/tests/speech/__init__.py` (empty) and `apps/backend/tests/speech/test_transcript_models.py`:

```python
from __future__ import annotations

from tamforge_backend.speech.models import SpeechTranscript, SpeechTranscriptCorrection


def test_transcript_table_shape() -> None:
    table = SpeechTranscript.__table__
    assert table.name == "speech_transcripts"
    columns = set(table.columns.keys())
    assert columns == {
        "id",
        "owner_id",
        "recording_id",
        "track",
        "canonical_json",
        "content_hash",
        "hash_format",
        "created_at",
    }
    names = {constraint.name for constraint in table.constraints}
    assert "uq_speech_transcripts_recording_track" in names


def test_transcript_body_bound_is_four_mebibytes() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in SpeechTranscript.__table__.constraints
        if hasattr(constraint, "sqltext")
    }
    assert "4194304" in checks["ck_speech_transcripts_content_bounded"]


def test_correction_points_at_a_transcript() -> None:
    table = SpeechTranscriptCorrection.__table__
    assert table.name == "speech_transcript_corrections"
    assert "transcript_id" in table.columns
```

- [ ] **Step 4: Run it and watch it fail**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tamforge_backend.speech'`.

- [ ] **Step 5: Write the models**

`apps/backend/src/tamforge_backend/speech/models.py`:

```python
"""Immutable local-transcript provenance and its append-only corrections."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..models.provenance import Record, provenance_checks

TRANSCRIPT_BODY_LIMIT = 4194304
CORRECTION_BODY_LIMIT = 8192


class SpeechTranscript(Record):
    __tablename__ = "speech_transcripts"
    __table_args__ = provenance_checks(
        "speech_transcripts", limit=TRANSCRIPT_BODY_LIMIT
    ) + (
        UniqueConstraint(
            "owner_id", "recording_id", "track", name="uq_speech_transcripts_recording_track"
        ),
        ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_speech_transcripts_recording",
        ),
        CheckConstraint(
            "track IN ('microphone', 'system_audio')", name="track_allowed"
        ),
    )
    recording_id: Mapped[int] = mapped_column(
        BigInteger,
        Computed("(canonical_json::jsonb->>'recording_id')::bigint", persisted=True),
        nullable=False,
    )
    track: Mapped[str] = mapped_column(
        Text, Computed("canonical_json::jsonb->>'track'", persisted=True), nullable=False
    )


class SpeechTranscriptCorrection(Record):
    __tablename__ = "speech_transcript_corrections"
    __table_args__ = provenance_checks(
        "speech_transcript_corrections", limit=CORRECTION_BODY_LIMIT
    ) + (
        ForeignKeyConstraint(
            ["owner_id", "transcript_id"],
            ["speech_transcripts.owner_id", "speech_transcripts.id"],
            name="fk_speech_transcript_corrections_transcript",
        ),
    )
    transcript_id: Mapped[int] = mapped_column(
        BigInteger,
        Computed("(canonical_json::jsonb->>'transcript_id')::bigint", persisted=True),
        nullable=False,
    )


def reject_mutation(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise RuntimeError("speech provenance rows are append-only")


for _model in (SpeechTranscript, SpeechTranscriptCorrection):
    event.listen(_model, "before_update", reject_mutation)
    event.listen(_model, "before_delete", reject_mutation)
```

Register the module in `models/__init__.py` by appending `"tamforge_backend.speech.models",` to `_MODEL_MODULES`.

- [ ] **Step 6: Run the model test to green**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_models.py -q`
Expected: PASS.

- [ ] **Step 7: Write the migration**

`apps/backend/alembic/versions/20260909_0018_transcripts.py`, following the shape of `20260909_0017_attestations.py`: `revision = "20260909_0018_transcripts"`, `down_revision = "20260909_0017_attestations"`, raw `CREATE TABLE` statements matching the constraint names the models declare, and a `downgrade` that drops both tables in reverse order. Generated columns use `GENERATED ALWAYS AS (...) STORED`. Read the attestations migration first and mirror its formatting exactly.

- [ ] **Step 8: Verify the migration applies and the head is linear**

Run: `uv run --no-sync alembic -c apps/backend/alembic.ini upgrade head`
Expected: applies cleanly.

Then update the head constant in `apps/backend/tests/unit/roadmaps/test_curriculum_schema.py` to `20260909_0018_transcripts` and run:
`uv run --no-sync pytest apps/backend/tests/unit/roadmaps/test_curriculum_schema.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/backend/src/tamforge_backend/models/provenance.py apps/backend/src/tamforge_backend/agents/models.py apps/backend/src/tamforge_backend/speech apps/backend/alembic/versions/20260909_0018_transcripts.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/tests/speech apps/backend/tests/unit/roadmaps/test_curriculum_schema.py
git commit -m "feat(speech): store immutable transcripts and their corrections"
```

---

### Task 2: Wire request and response schemas

**Files:**
- Create: `apps/backend/src/tamforge_backend/speech/schemas.py`
- Test: `apps/backend/tests/speech/test_transcript_schemas.py`

**Interfaces:**
- Consumes: `StrictModel` conventions from `recordings/schemas.py` (`extra="forbid"`, `frozen=True`), `Sha256` pattern `^[0-9a-f]{64}$`.
- Produces: `TranscriptSubmitCommand`, `TranscriptResponse`, `TranscriptCorrectionCommand`, `TranscriptCorrectionResponse`, `TranscriptPage`, and the constant `SPEECH_SCHEMA_VERSION = 1`.

- [ ] **Step 1: Write the failing schema test**

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_backend.speech.schemas import TranscriptSubmitCommand

BODY = {
    "schema_version": 1,
    "track": "microphone",
    "segments": [
        {
            "text": "hello there",
            "start_ms": 0,
            "end_ms": 900,
            "words": [
                {"text": "hello", "start_ms": 0, "end_ms": 400, "probability": 0.98},
                {"text": "there", "start_ms": 400, "end_ms": 900, "probability": 0.91},
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
        "source_sample_rate": 48000,
        "source_channel_count": 1,
        "source_sample_count": 2880000,
        "output_sample_rate": 16000,
        "output_sample_count": 960000,
        "zero_filled_gaps": [],
        "source_pcm_sha256": "b" * 64,
        "derived_pcm_sha256": "c" * 64,
        "quality": {
            "version": "audio-quality-v1",
            "sample_rate": 48000,
            "channel_count": 1,
            "source_sample_count": 2880000,
            "duration_seconds": 60.0,
            "peak_absolute": 21000,
            "all_silence": False,
            "clipped_ratio": 0.0,
            "dc_offset": 0.0,
            "channel_imbalance_decibels": None,
            "discontinuity_count": 0,
            "unavailable_dimensions": [],
        },
    },
}


def test_accepts_a_complete_body() -> None:
    command = TranscriptSubmitCommand.model_validate(BODY)
    assert command.track == "microphone"
    assert command.segments[0].words[1].probability == pytest.approx(0.91)


def test_rejects_a_probability_outside_zero_to_one() -> None:
    body = {**BODY}
    body["segments"] = [
        {
            **BODY["segments"][0],
            "words": [{"text": "hi", "start_ms": 0, "end_ms": 10, "probability": 1.4}],
        }
    ]
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate(body)


def test_rejects_a_word_ending_before_it_starts() -> None:
    body = {**BODY}
    body["segments"] = [
        {
            **BODY["segments"][0],
            "words": [{"text": "hi", "start_ms": 90, "end_ms": 10, "probability": 0.5}],
        }
    ]
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate(body)


def test_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate({**BODY, "extra": 1})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_schemas.py -q`
Expected: FAIL with `ModuleNotFoundError` for `tamforge_backend.speech.schemas`.

- [ ] **Step 3: Write the schemas**

Mirror the `recordings/schemas.py` conventions: a local `StrictModel` with `ConfigDict(extra="forbid", frozen=True)`, `Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]`, `Track = Literal["microphone", "system_audio"]`. Bound every collection: at most 20,000 words per transcript, at most 4,000 segments, text fields at most 4,096 characters. Validate with `model_validator(mode="after")` that each word's `end_ms >= start_ms`, that words are ordered and contained within their segment's span, and that segments are ordered. `probability` is `Annotated[float, Field(ge=0.0, le=1.0)]`. `channel_imbalance_decibels` is `float | None`, never bare `None`.

- [ ] **Step 4: Run to green**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/tamforge_backend/speech/schemas.py apps/backend/tests/speech/test_transcript_schemas.py
git commit -m "feat(speech): validate submitted transcript bodies"
```

---

### Task 3: Repository

**Files:**
- Create: `apps/backend/src/tamforge_backend/speech/repository.py`
- Create: `apps/backend/src/tamforge_backend/speech/contracts.py`
- Test: `apps/backend/tests/speech/test_transcript_repository.py`

**Interfaces:**
- Consumes: `SpeechTranscript`, `SpeechTranscriptCorrection`, `canonical_bytes` and `digest` from `..agents.hashing`, `Recording` from `..recordings.models`.
- Produces: `SqlAlchemyTranscriptRepository` with `async def store(owner_id, recording, track, body) -> SpeechTranscript`, `async def by_recording(owner_id, recording_id) -> tuple[SpeechTranscript, ...]`, `async def append_correction(owner_id, transcript, body) -> SpeechTranscriptCorrection`, `async def corrections(owner_id, transcript_id) -> tuple[...]`. Errors `TranscriptConflict`, `TranscriptNotFound`, `TranscriptTooLarge` in `contracts.py`.

- [ ] **Step 1: Write the failing repository test**

Test against an async SQLAlchemy session over the real models with a stubbed recording row, covering: a stored transcript's `content_hash` equals `sha256(canonical_bytes(body))`; storing the identical body twice returns the first row rather than inserting a second; storing a different body for the same recording and track raises `TranscriptConflict`; a body over `TRANSCRIPT_BODY_LIMIT` raises `TranscriptTooLarge` before touching the session; `by_recording` returns nothing for another owner's id; `append_correction` on a transcript belonging to another owner raises `TranscriptNotFound`; corrections come back in insertion order.

Follow the session and fixture conventions already used by `apps/backend/tests/recordings/test_part_persistence.py`. Read that file first.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_repository.py -q`
Expected: FAIL with `ModuleNotFoundError` for `tamforge_backend.speech.repository`.

- [ ] **Step 3: Write the repository**

`store` builds the canonical body by adding the resolved `recording_id` and `track` to the validated command, calls `canonical_bytes(body, limit=TRANSCRIPT_BODY_LIMIT)`, hashes it, and inserts. Idempotency is decided by comparing `content_hash` against the existing row for `(owner_id, recording_id, track)`: equal means replay and returns the stored row, different means `TranscriptConflict`. No update path exists on either model.

- [ ] **Step 4: Run to green**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/tamforge_backend/speech/repository.py apps/backend/src/tamforge_backend/speech/contracts.py apps/backend/tests/speech/test_transcript_repository.py
git commit -m "feat(speech): store and read transcript provenance"
```

---

### Task 4: Service, routes, and the lineage flag

**Files:**
- Create: `apps/backend/src/tamforge_backend/speech/service.py`
- Create: `apps/backend/src/tamforge_backend/speech/routes.py`
- Modify: `apps/backend/src/tamforge_backend/api.py:40-48` (include the speech router)
- Modify: `.github/workflows/ci.yml:118` (add `apps/backend/tests/speech` to the `backend-unit` pytest paths)
- Modify: `scripts/ci/tests/test_check_openapi.py` (new `FROZEN_OPENAPI_SHA256`)
- Test: `apps/backend/tests/speech/test_transcript_routes.py`

**Interfaces:**
- Consumes: `SqlAlchemyTranscriptRepository`, `get_bearer_authenticated_owner`, `get_db_session`, `_prevent_storage` conventions from `recordings/routes.py`.
- Produces: `router = APIRouter(prefix="/api/v1/recordings", tags=["speech"])` with `POST /{recording_id}/transcripts`, `GET /{recording_id}/transcripts`, `POST /{recording_id}/transcripts/{track}/corrections`.

- [ ] **Step 1: Write the failing route test**

Use the `StubRecordingService` pattern from `apps/backend/tests/recordings/test_session_routes.py`: `create_app`, a stub service injected through `app.dependency_overrides`, and `TestClient`. Read that file first.

Cover: a POST returns 201 and the stub saw the authenticated owner id; a POST for a recording whose audio is not on the server returns 409; an identical POST with the same `Idempotency-Key` returns the stored result rather than a second row; a differing POST on the same track returns 409; a POST without a bearer token returns 401; a GET returns only the calling owner's transcripts; every response carries `Cache-Control: no-store`; and no response body or raised error message contains any word of the submitted transcript text.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_routes.py -q`
Expected: FAIL with `ModuleNotFoundError` for `tamforge_backend.speech.routes`.

- [ ] **Step 3: Write the service and routes**

The service resolves the path UUID to the internal recording row for that owner, refuses when the recording state is not `stored` or `stored_with_gaps` (the `transcript_lineage_requires_audio` constraint would refuse anyway; failing in the service gives an honest 409 instead of an integrity error), delegates to the repository, and on a first successful store sets `Recording.transcript_lineage_accepted = True` in the same transaction. A replay leaves the flag as it stands.

- [ ] **Step 4: Run to green, then the whole backend-unit set**

Run: `uv run --no-sync pytest apps/backend/tests/speech/test_transcript_routes.py -q`
Expected: PASS.

Run: `uv run --no-sync pytest apps/backend/tests/unit apps/backend/tests/security apps/backend/tests/recordings apps/backend/tests/speech packages/protocol/tests scripts/ci/tests scripts/dev/tests scripts/github/tests -m "not integration" -q`
Expected: PASS.

- [ ] **Step 5: Regenerate the OpenAPI surface and compare constructs**

Run: `uv run --no-sync python scripts/ci/check_openapi.py`

Then compare the generated `apps/macos/TAMForge/openapi.yaml` against main and confirm the new schemas introduced no OpenAPI 3.1-only construct. A bare `{"type": "null"}` anywhere in the diff means a Pydantic field is typed `None`; fix the schema rather than the lowering. Update `FROZEN_OPENAPI_SHA256` in `scripts/ci/tests/test_check_openapi.py` to the new digest.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/tamforge_backend/speech/service.py apps/backend/src/tamforge_backend/speech/routes.py apps/backend/src/tamforge_backend/api.py apps/macos/TAMForge/openapi.yaml scripts/ci/tests/test_check_openapi.py .github/workflows/ci.yml apps/backend/tests/speech/test_transcript_routes.py
git commit -m "feat(speech): accept a local transcript and release the spool gate"
```

---

### Task 5: PostgreSQL constraint coverage

The unit tests above run without PostgreSQL, so nothing yet proves the database refuses a non-canonical body or a mismatched hash.

**Files:**
- Test: `apps/backend/tests/integration/speech/test_transcript_constraints.py`

**Interfaces:**
- Consumes: the integration session fixtures already used by `apps/backend/tests/integration/agents/test_agent_runtime_migration.py`. Read that file first and copy its markers and fixtures.

- [ ] **Step 1: Write the failing constraint test**

Insert directly through the session, bypassing the repository, and assert the database refuses: a `content_hash` that is not the SHA-256 of `canonical_json`; a `canonical_json` that is valid JSON but not canonical (keys out of order); a second transcript for the same owner, recording and track; a `track` value outside the allowed pair; a body one byte over 4 MiB. Also assert the generated `recording_id` and `track` columns equal the values inside the JSON.

- [ ] **Step 2: Run it against a database without the migration and watch it fail**

Run: `uv run --no-sync alembic -c apps/backend/alembic.ini downgrade 20260909_0017_attestations`
Run: `uv run --no-sync pytest -m integration apps/backend/tests/integration/speech -q`
Expected: FAIL with an undefined-table error for `speech_transcripts`. This is the RED that proves the test actually reaches PostgreSQL rather than passing on a stub.

- [ ] **Step 3: Apply the migration and run to green**

Run: `uv run --no-sync alembic -c apps/backend/alembic.ini upgrade head`
Run: `uv run --no-sync pytest -m integration apps/backend/tests/integration/speech -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/speech
git commit -m "test(speech): prove the transcript constraints against PostgreSQL"
```

---

### Task 6: The client submits its transcript

**Files:**
- Modify: `apps/macos/TAMForge/Features/Recording/RecordingUploader.swift:14-20` (protocol) and `:112-125` (live client)
- Modify: `apps/macos/TAMForge/Features/Recording/RecordingCoordinator.swift:341-387` (submit after `.ready`)
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj` if a new file is added
- Test: `apps/macos/TAMForgeTests/RecordingFeatureTests.swift`

**Interfaces:**
- Consumes: `SpeechTranscriptionResult`, `ASRDerivationLineage`, `SpeechRuntimeIdentity`, `AudioQualityObservations`, `Components.Schemas.TranscriptSubmitCommand` (generated by Task 4's OpenAPI change).
- Produces: `func submitTranscript(_ command: TranscriptSubmitPayload, idempotencyKey: String) async throws -> RecordingServerStatus` on `RecordingServerServicing`, implemented by `LiveRecordingServerClient` and by the test fakes.

- [ ] **Step 1: Write the failing coordinator tests**

In `RecordingFeatureTests.swift`, using the existing fake server and fake transcriber:

1. A recording that transcribes successfully submits exactly one transcript, and the submitted body's word count matches the fake result.
2. A recording whose transcription fails submits nothing and leaves the upload state at `waitingForTranscript`.
3. A submission that throws leaves the spool present, and the next upload worker pass retries it.
4. When the server reports both gates true after submission, the spool is released.

- [ ] **Step 2: Run them and watch them fail**

Run: `xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination platform=macOS test -only-testing:TAMForgeTests/RecordingFeatureTests`
Expected: FAIL at compile time, `submitTranscript` is not a member of `RecordingServerServicing`.

Note: do not run this locally without the owner's approval. The plan's RED observation for this task is the required CI `macos-native` job on the pushed branch.

- [ ] **Step 3: Add the protocol method and the live implementation**

Add `submitTranscript` to `RecordingServerServicing` and implement it on `LiveRecordingServerClient` exactly like `seal`: build the body with `generatedRequestBody(payload, as: Components.Schemas.TranscriptSubmitCommand.self)`, POST to `/api/v1/recordings/\(id)/transcripts` with `expectedStatus: 201`, validate the response with `decodeGenerated`, and return the parsed status. The idempotency key is `"recording.transcript.\(id).\(track)"`, which makes a retry a replay rather than a conflict.

- [ ] **Step 4: Submit from the coordinator**

In `beginTranscription`, after `transcriptState = .ready(recordingID, result)`, map the result into the payload and submit. On success let the existing upload worker pick up the changed gates. On failure leave `transcriptState` at `.ready` and the upload state at `waitingForTranscript`, so the next pass retries. Never surface the transcript text in an error string.

- [ ] **Step 5: Run the Swift suite to green**

Run: `xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination platform=macOS test -only-testing:TAMForgeTests/RecordingFeatureTests`
Expected: PASS. Same note as Step 2: the authoritative run is CI.

- [ ] **Step 6: Commit**

```bash
git add apps/macos
git commit -m "feat(recording): submit the local transcript so the spool can release"
```

---

## Self-Review

**Spec coverage.** Immutable transcript, words, uncertainty and model hashes: Tasks 1 to 3. Corrections: Tasks 1, 3 and 4. The lineage flag and spool retention: Task 4 for the server half, Task 6 for the client half. The 4 MiB bound: Task 1 Step 5 and Task 5. Privacy rules: Task 4 Step 1 asserts them. The issue's own verification command is Task 3 Step 4 and Task 4 Step 4.

**Type consistency.** `provenance_checks` is named identically in Tasks 1 and 3. `TRANSCRIPT_BODY_LIMIT` is defined in Task 1 and consumed in Tasks 3 and 5. `submitTranscript` has one signature across Task 6's steps.

**Known gap carried on purpose.** The correction body's `segment_index` and word range are validated for shape but not checked against the transcript they point at, because doing so means reading and parsing a 1.6 MB body on every correction write. The `original_text` field is what makes a stale correction detectable later. Revisit when a correction UI exists.
