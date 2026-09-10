"""Service-level coverage for what `test_transcript_routes.py` cannot reach.

The route tests inject a stub `TranscriptService`, so they never exercise the
service's own logic: resolving the path's client-facing recording UUID,
gating on recording state, deciding `replayed`, or -- the one piece of new
system behavior this task adds -- flipping `Recording.transcript_lineage_accepted`.
This file drives the real `TranscriptService` against two small fakes instead:
a `FakeTranscriptRepository` standing in for Task 3's repository (this file
only needs *a* transcript row back from `store`, not the real content-hash
race handling Task 3 already covers in `test_transcript_repository.py`), and
a `FakeSession` standing in for the `Recording` half of the request-scoped
`AsyncSession`, using the same statement-introspection technique
`test_transcript_repository.py`'s `FakeSession` already uses for
`SpeechTranscript`.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from tamforge_backend.recordings.models import Recording
from tamforge_backend.speech.contracts import TranscriptConflict, TranscriptNotFound
from tamforge_backend.speech.models import MAX_CORRECTIONS_PER_TRANSCRIPT
from tamforge_backend.speech.repository import Written
from tamforge_backend.speech.schemas import TranscriptCorrectionCommand, TranscriptSubmitCommand
from tamforge_backend.speech.service import TranscriptService

CREATED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def submit_command(**overrides: object) -> TranscriptSubmitCommand:
    body: dict[str, Any] = {
        "schema_version": 1,
        "track": "microphone",
        "segments": [
            {
                "text": "hello there",
                "start_ms": 0,
                "end_ms": 900,
                "words": [{"text": "hello", "start_ms": 0, "end_ms": 400, "probability": 0.98}],
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
    body.update(overrides)
    return TranscriptSubmitCommand.model_validate(body)


def correction_command(**overrides: object) -> TranscriptCorrectionCommand:
    body: dict[str, Any] = {
        "schema_version": 1,
        "segment_index": 0,
        "word_start_index": 0,
        "word_end_index": 1,
        "original_text": "helo",
        "corrected_text": "hello",
        "reason": "misheard_term",
    }
    body.update(overrides)
    return TranscriptCorrectionCommand.model_validate(body)


def fake_recording(
    *, pk: int = 42, owner_id: int = 1, client_recording_id: UUID, state: str = "stored",
    transcript_lineage_accepted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pk,
        owner_id=owner_id,
        client_recording_id=client_recording_id,
        state=state,
        transcript_lineage_accepted=transcript_lineage_accepted,
    )


class FakeSession:
    """Answers only the two `Recording` queries `TranscriptService` issues.

    `scalar` matches the same way `test_transcript_repository.py`'s
    `FakeSession` does: read the compiled statement's mapped class and bound
    parameters, filter by attribute equality. `begin` is a no-op transaction
    (nothing here ever fails or rolls back) and `flush` needs to do nothing
    because `_accept_lineage` mutates the fake `Recording` namespace in
    place -- the same object stays in `self.recordings`, so the mutation is
    already visible without a real flush.
    """

    def __init__(self, recordings: list[SimpleNamespace]) -> None:
        self.recordings = recordings

    async def scalar(self, statement: object) -> object | None:
        model = statement.column_descriptions[0]["type"]  # type: ignore[attr-defined]
        assert model is Recording
        params = statement.compile().params  # type: ignore[attr-defined]
        matches = [
            row
            for row in self.recordings
            if all(
                getattr(row, key.rsplit("_", 1)[0], object()) == value
                for key, value in params.items()
            )
        ]
        return matches[0] if matches else None

    async def flush(self) -> None:
        pass

    @asynccontextmanager
    async def begin(self):
        yield self


class FakeTranscriptRepository:
    """A `SqlAlchemyTranscriptRepository` stand-in with real replay semantics
    for exactly what `TranscriptService` needs: the second submission for the
    same (recording, track) returns the row already on file, a differing one
    raises `TranscriptConflict`, and an identical correction body replays the
    correction already appended -- matching Task 3's contract without its
    concurrency machinery, which is out of scope here (see the module
    docstring). The real repository decides a correction's identity by content
    hash; the fake compares canonical bodies directly, since every row it
    hands back carries the same placeholder hash.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[int, str], SimpleNamespace] = {}
        self._corrections: dict[int, list[SimpleNamespace]] = {}
        self._next_transcript_id = 1
        self._next_correction_id = 1
        self.store_calls: list[tuple[int, int, str]] = []
        self.by_recording_calls = 0
        self.by_recording_track_calls = 0
        self.corrections_calls = 0

    async def store(
        self, *, owner_id: int, recording: object, track: str, body: dict[str, object]
    ) -> Written[Any]:
        recording_pk = recording.id  # type: ignore[attr-defined]
        self.store_calls.append((owner_id, recording_pk, track))
        key = (recording_pk, track)
        merged = {**body, "recording_id": recording_pk, "track": track}
        existing = self._rows.get(key)
        if existing is not None:
            if json.loads(existing.canonical_json) != merged:
                raise TranscriptConflict()
            return Written(existing, replayed=True)
        row = SimpleNamespace(
            id=self._next_transcript_id,
            owner_id=owner_id,
            recording_id=recording_pk,
            track=track,
            canonical_json=json.dumps(merged),
            content_hash=b"\x11" * 32,
            created_at=CREATED_AT,
        )
        self._next_transcript_id += 1
        self._rows[key] = row
        return Written(row, replayed=False)

    async def by_recording(
        self, *, owner_id: int, recording_id: int
    ) -> tuple[SimpleNamespace, ...]:
        del owner_id
        self.by_recording_calls += 1
        return tuple(row for (pk, _track), row in self._rows.items() if pk == recording_id)

    async def by_recording_track(
        self, *, owner_id: int, recording_id: int, track: str
    ) -> SimpleNamespace | None:
        del owner_id
        self.by_recording_track_calls += 1
        return self._rows.get((recording_id, track))

    async def corrections(
        self, *, owner_id: int, transcript_id: int
    ) -> tuple[SimpleNamespace, ...]:
        del owner_id
        self.corrections_calls += 1
        return tuple(self._corrections.get(transcript_id, []))

    def seed_corrections(self, *, transcript_id: int, count: int) -> None:
        """Put `count` corrections on file behind the service's back.

        `add_correction` can no longer reach this state on its own: the real
        repository refuses the write once a transcript is at the cap. Two
        concurrent appends that both clear its check-then-insert guard still
        can overshoot it, though, which is the state the read path has to
        survive -- so this writes the rows directly rather than through
        `append_correction`.
        """
        stored = self._corrections.setdefault(transcript_id, [])
        stored.clear()
        for index in range(count):
            stored.append(
                SimpleNamespace(
                    id=index + 1,
                    owner_id=1,
                    transcript_id=transcript_id,
                    canonical_json=json.dumps(
                        {
                            "transcript_id": transcript_id,
                            "segment_index": 0,
                            "word_start_index": 0,
                            "word_end_index": 1,
                            "original_text": "helo",
                            "corrected_text": "hello",
                            "reason": "misheard_term",
                        }
                    ),
                    content_hash=b"\x22" * 32,
                    created_at=CREATED_AT,
                )
            )

    async def append_correction(
        self, *, owner_id: int, transcript: object, body: dict[str, object]
    ) -> Written[Any]:
        transcript_id = transcript.id  # type: ignore[attr-defined]
        canonical_json = json.dumps({**body, "transcript_id": transcript_id})
        stored = self._corrections.setdefault(transcript_id, [])
        existing = next((row for row in stored if row.canonical_json == canonical_json), None)
        if existing is not None:
            return Written(existing, replayed=True)
        row = SimpleNamespace(
            id=self._next_correction_id,
            owner_id=owner_id,
            transcript_id=transcript_id,
            canonical_json=canonical_json,
            content_hash=b"\x22" * 32,
            created_at=CREATED_AT,
        )
        self._next_correction_id += 1
        stored.append(row)
        return Written(row, replayed=False)


def test_submit_rejects_a_recording_that_is_not_yet_durable_on_the_server() -> None:
    recording_id = uuid4()
    session = FakeSession(
        [fake_recording(client_recording_id=recording_id, state="sealing")]
    )
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        with pytest.raises(TranscriptConflict):
            await service.submit(owner_id=1, recording_id=recording_id, command=submit_command())

    asyncio.run(exercise())


def test_submit_for_an_unknown_recording_raises_not_found() -> None:
    session = FakeSession([])
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        with pytest.raises(TranscriptNotFound):
            await service.submit(owner_id=1, recording_id=uuid4(), command=submit_command())

    asyncio.run(exercise())


def test_submit_for_another_owners_recording_is_indistinguishable_from_missing() -> None:
    """Owner isolation on `_resolve_recording`, this task's own named risk:
    submitting against a UUID that resolves to a recording owned by someone
    else must raise the exact same `TranscriptNotFound` a caller gets for a
    UUID that resolves to nothing at all. If `_resolve_recording` ever lost
    its `Recording.owner_id` filter, this submission would go through
    instead of raising -- a caller could then tell another owner's recording
    exists just by comparing responses.
    """
    someone_elses_recording = uuid4()
    session = FakeSession(
        [fake_recording(owner_id=2, client_recording_id=someone_elses_recording)]
    )
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        with pytest.raises(TranscriptNotFound):
            await service.submit(
                owner_id=1, recording_id=someone_elses_recording, command=submit_command()
            )
        # Same exception as a UUID nobody has ever used -- see
        # test_submit_for_an_unknown_recording_raises_not_found above.
        with pytest.raises(TranscriptNotFound):
            await service.submit(owner_id=1, recording_id=uuid4(), command=submit_command())

    asyncio.run(exercise())


def test_list_for_recording_owned_by_another_is_indistinguishable_from_missing() -> None:
    """Owner isolation on the read path: listing transcripts against
    another owner's recording UUID must raise the same `TranscriptNotFound`
    as a UUID that was never used, never leaking whether the recording
    exists.
    """
    someone_elses_recording = uuid4()
    session = FakeSession(
        [fake_recording(owner_id=2, client_recording_id=someone_elses_recording)]
    )
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        with pytest.raises(TranscriptNotFound):
            await service.list_for_recording(owner_id=1, recording_id=someone_elses_recording)
        with pytest.raises(TranscriptNotFound):
            await service.list_for_recording(owner_id=1, recording_id=uuid4())

    asyncio.run(exercise())


def test_fresh_submission_accepts_lineage_and_reports_no_replay() -> None:
    recording_id = uuid4()
    recording = fake_recording(client_recording_id=recording_id, transcript_lineage_accepted=False)
    session = FakeSession([recording])
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        result = await service.submit(
            owner_id=1, recording_id=recording_id, command=submit_command()
        )
        assert result.replayed is False
        assert result.recording_id == recording_id  # the client-facing UUID, not the internal pk
        assert recording.transcript_lineage_accepted is True

    asyncio.run(exercise())


def test_replayed_submission_still_accepts_lineage() -> None:
    """The self-healing path: a prior store already landed the transcript but
    the process died before the flag write, so the flag is still false on a
    recording that already holds a matching transcript row. A resubmission
    with identical content replays that row -- and must still flip the flag,
    not leave it as it stands, or the recording would never release its
    spool no matter how many times the client retries.
    """
    recording_id = uuid4()
    recording = fake_recording(client_recording_id=recording_id, transcript_lineage_accepted=False)
    session = FakeSession([recording])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]
    command = submit_command()

    async def exercise() -> None:
        first = await service.submit(owner_id=1, recording_id=recording_id, command=command)
        assert first.replayed is False
        # Simulate the crash: a prior process's second commit never landed.
        recording.transcript_lineage_accepted = False

        second = await service.submit(owner_id=1, recording_id=recording_id, command=command)

        assert second.replayed is True
        assert second.transcript_id == first.transcript_id
        assert len(repository.store_calls) == 2
        assert recording.transcript_lineage_accepted is True

    asyncio.run(exercise())


def test_differing_resubmission_conflicts_and_never_touches_the_flag() -> None:
    recording_id = uuid4()
    recording = fake_recording(client_recording_id=recording_id, transcript_lineage_accepted=False)
    session = FakeSession([recording])
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        await service.submit(owner_id=1, recording_id=recording_id, command=submit_command())
        recording.transcript_lineage_accepted = False  # isolate this assertion from the first call

        with pytest.raises(TranscriptConflict):
            await service.submit(
                owner_id=1,
                recording_id=recording_id,
                command=submit_command(model_identity={
                    "runtime_version": "b4938",
                    "model_filename": "ggml-base.en-q5_1.bin",
                    "model_sha256": "f" * 64,
                    "metal_requested": True,
                    "used_builtin_vad": False,
                    "language": "en",
                }),
            )

        assert recording.transcript_lineage_accepted is False

    asyncio.run(exercise())


def test_list_for_recording_includes_corrections() -> None:
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]

    async def exercise() -> None:
        submitted = await service.submit(
            owner_id=1, recording_id=recording_id, command=submit_command()
        )
        await service.add_correction(
            owner_id=1,
            recording_id=recording_id,
            track="microphone",
            command=TranscriptCorrectionCommand.model_validate(
                {
                    "schema_version": 1,
                    "segment_index": 0,
                    "word_start_index": 0,
                    "word_end_index": 1,
                    "original_text": "helo",
                    "corrected_text": "hello",
                    "reason": "misheard_term",
                }
            ),
        )

        page = await service.list_for_recording(owner_id=1, recording_id=recording_id)

        assert len(page.items) == 1
        assert page.items[0].transcript_id == submitted.transcript_id
        assert len(page.items[0].corrections) == 1
        assert page.items[0].corrections[0].corrected_text == "hello"

    asyncio.run(exercise())


def test_retried_correction_replays_the_stored_row_and_reports_it() -> None:
    """A correction POST retried after a timeout has to come back as the
    correction already on file, flagged `replayed`, not as a second
    annotation. The service decides that flag exactly as `submit` decides its
    own: it reports whichever branch the repository took, without reading the
    rows on file to work it out.
    """
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        await service.submit(owner_id=1, recording_id=recording_id, command=submit_command())

        first = await service.add_correction(
            owner_id=1,
            recording_id=recording_id,
            track="microphone",
            command=correction_command(),
        )
        second = await service.add_correction(
            owner_id=1,
            recording_id=recording_id,
            track="microphone",
            command=correction_command(),
        )

        assert first.replayed is False
        assert second.replayed is True
        assert second.correction_id == first.correction_id
        page = await service.list_for_recording(owner_id=1, recording_id=recording_id)
        assert len(page.items[0].corrections) == 1

    asyncio.run(exercise())


def test_add_correction_for_a_missing_track_raises_not_found() -> None:
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    service = TranscriptService(session, FakeTranscriptRepository())  # type: ignore[arg-type]

    async def exercise() -> None:
        with pytest.raises(TranscriptNotFound):
            await service.add_correction(
                owner_id=1,
                recording_id=recording_id,
                track="system_audio",
                command=TranscriptCorrectionCommand.model_validate(
                    {
                        "schema_version": 1,
                        "segment_index": 0,
                        "word_start_index": 0,
                        "word_end_index": 1,
                        "original_text": "helo",
                        "corrected_text": "hello",
                        "reason": "misheard_term",
                    }
                ),
            )

    asyncio.run(exercise())


def test_listing_a_transcript_past_the_correction_cap_still_returns_a_page() -> None:
    """A transcript holding more corrections than `TranscriptResponse` declares
    room for used to make `_to_response` raise a pydantic `ValidationError`,
    which reached the client as an unhandled 500 rather than a problem+json
    body -- and did so on every subsequent read, so one write permanently cost
    the owner the ability to see the transcript at all. `_to_response` now
    renders no more corrections than the response model accepts.
    """
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]

    async def exercise() -> None:
        transcript = await service.submit(
            owner_id=1, recording_id=recording_id, command=submit_command()
        )
        repository.seed_corrections(
            transcript_id=transcript.transcript_id,
            count=MAX_CORRECTIONS_PER_TRANSCRIPT + 1,
        )

        page = await service.list_for_recording(owner_id=1, recording_id=recording_id)

        assert len(page.items[0].corrections) == MAX_CORRECTIONS_PER_TRANSCRIPT

    asyncio.run(exercise())


def test_resubmitting_a_transcript_past_the_correction_cap_still_returns_a_response() -> None:
    """The same overflow broke the write path too: `submit` renders its result
    through `_to_response` as well, so a transcript past the cap could not even
    be resubmitted -- the retry a client makes to recover a lost response was
    itself answered with a 500.
    """
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]

    async def exercise() -> None:
        transcript = await service.submit(
            owner_id=1, recording_id=recording_id, command=submit_command()
        )
        repository.seed_corrections(
            transcript_id=transcript.transcript_id,
            count=MAX_CORRECTIONS_PER_TRANSCRIPT + 1,
        )

        replayed = await service.submit(
            owner_id=1, recording_id=recording_id, command=submit_command()
        )

        assert replayed.replayed is True
        assert len(replayed.corrections) == MAX_CORRECTIONS_PER_TRANSCRIPT

    asyncio.run(exercise())


def test_add_correction_decides_replay_without_reading_the_corrections_on_file() -> None:
    """`replayed` used to be derived by reading every correction id already on
    file and checking whether the appended row was one of them. A transcript
    holds up to `MAX_CORRECTIONS_PER_TRANSCRIPT` corrections of up to
    `CORRECTION_BODY_LIMIT` bytes each, so that prefetch pulled megabytes out
    of the database to answer a single boolean. `append_correction` already
    knows which branch it took -- a content-hash hit or a lost-race recovery
    is a replay, a fresh insert is not -- so it reports the answer and the
    service reads nothing extra.
    """
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]

    async def exercise() -> None:
        await service.submit(owner_id=1, recording_id=recording_id, command=submit_command())
        # `submit` renders its own response, which reads the corrections it has
        # to render. Only reads beyond that one are the prefetch under test.
        reads_before = repository.corrections_calls

        first = await service.add_correction(
            owner_id=1,
            recording_id=recording_id,
            track="microphone",
            command=correction_command(),
        )
        second = await service.add_correction(
            owner_id=1,
            recording_id=recording_id,
            track="microphone",
            command=correction_command(),
        )

        assert first.replayed is False
        assert second.replayed is True
        assert repository.corrections_calls == reads_before

    asyncio.run(exercise())


def test_submit_decides_replay_without_rereading_the_recordings_transcripts() -> None:
    """The same prefetch on the transcript side: `submit` used to read every
    transcript already on file for the recording purely to learn whether the
    row `store` handed back was one of them. `store` knows -- an existing-row
    hit or a lost-race recovery is a replay, a fresh insert is not.
    """
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]
    command = submit_command()

    async def exercise() -> None:
        first = await service.submit(owner_id=1, recording_id=recording_id, command=command)
        second = await service.submit(owner_id=1, recording_id=recording_id, command=command)

        assert first.replayed is False
        assert second.replayed is True
        assert repository.by_recording_calls == 0

    asyncio.run(exercise())


def test_add_correction_resolves_the_track_without_reading_the_other_one() -> None:
    """Resolving which transcript a correction belongs to used to read every
    transcript on the recording and pick the matching track in Python. A
    recording holds one transcript per track and a transcript body is bounded
    at `TRANSCRIPT_BODY_LIMIT` bytes, so that pulled both bodies -- megabytes
    at the limit -- out of the database to end up using nothing but the row's
    id and owner. The track belongs in the SELECT.
    """
    recording_id = uuid4()
    session = FakeSession([fake_recording(client_recording_id=recording_id)])
    repository = FakeTranscriptRepository()
    service = TranscriptService(session, repository)  # type: ignore[arg-type]

    async def exercise() -> None:
        await service.submit(owner_id=1, recording_id=recording_id, command=submit_command())
        await service.submit(
            owner_id=1,
            recording_id=recording_id,
            command=submit_command(track="system_audio"),
        )

        appended = await service.add_correction(
            owner_id=1,
            recording_id=recording_id,
            track="microphone",
            command=correction_command(),
        )

        assert appended.transcript_id == 1
        assert repository.by_recording_track_calls == 1
        assert repository.by_recording_calls == 0

    asyncio.run(exercise())
