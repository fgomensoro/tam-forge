"""Break things on purpose across recording, jobs and storage, and prove nothing is lost.

Each scenario injects one fault into a real production path (the recording service over
the shared doubles, the job service over the in-memory queue with the queue's real rules,
the object store contract fake) and then checks the invariant that fault must not break:
no source evidence lost, no duplicate session, no acknowledgement before durability, no
corrupted final artifact, and processing that resumes once the fault clears. The outcome of
every scenario is recorded with what was observed, so the report reads as evidence rather
than as a green dot.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID, uuid4

from ..jobs.schemas import ClaimJobCommand, CompleteJobCommand
from ..jobs.service import JobConflict, JobService
from ..recordings.schemas import RecordingPartUploadMetadata
from ..recordings.service import RecordingConflict, RecordingService, RecordingUnavailable
from ..speech.jobs import SPEECH_LEASE_SECONDS, enqueue_speech_analysis
from ..storage.fake import InMemoryObjectStore
from ..storage.models import ObjectConflict, ObjectStoreError, StoredObject
from ..testing.jobs import FakeJobStore
from ..testing.recordings import (
    OWNER_ID,
    SYSTEM_ID,
    CountingObjectStore,
    InMemoryRecordingRepository,
    create_command,
    encrypted_part,
    seal_command,
    upload,
)

FAILURE_INJECTION_VERSION: Final = "failure-injection-v1"

Layer = Literal["recording", "jobs", "storage"]


class InjectedOutage(ObjectStoreError):
    """The object store is down, on purpose."""


class FaultyObjectStore(CountingObjectStore):
    """The contract fake with a switch that makes the next write fail after nothing was stored."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_put = False

    async def put_immutable(self, **kwargs: object) -> object:  # type: ignore[override]
        if self.fail_next_put:
            self.fail_next_put = False
            raise InjectedOutage("injected object store outage")
        return await super().put_immutable(**kwargs)


@dataclass(frozen=True, slots=True)
class SealedFixture:
    service: RecordingService
    repository: InMemoryRecordingRepository
    store: FaultyObjectStore
    recording_id: UUID
    mic: tuple[RecordingPartUploadMetadata, bytes, bytes, bytes]
    system: tuple[RecordingPartUploadMetadata, bytes, bytes, bytes]


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    name: str
    layer: Layer
    invariant: str
    held: bool
    observed: str


async def _sealed_service() -> SealedFixture:
    repository = InMemoryRecordingRepository()
    store = FaultyObjectStore()
    service = RecordingService(repository, store)  # type: ignore[arg-type]
    recording_id = uuid4()
    await service.create(
        owner_id=OWNER_ID, command=create_command(recording_id), idempotency_key="create-1"
    )
    mic = encrypted_part(recording_id=recording_id)
    system = encrypted_part(
        recording_id=recording_id, track_id=SYSTEM_ID, track_kind="system_audio", channel_count=2
    )
    await upload(service, mic, "mic-0")
    await upload(service, system, "sys-0")
    return SealedFixture(service, repository, store, recording_id, mic, system)


async def scenario_no_ack_before_manifest_is_durable() -> ScenarioOutcome:
    fx = await _sealed_service()
    service, repository, store, recording_id = fx.service, fx.repository, fx.store, fx.recording_id
    command = seal_command(recording_id, [(fx.mic[0], fx.mic[3])], [(fx.system[0], fx.system[3])])
    store.fail_next_put = True
    puts_before = store.put_calls
    refused = False
    try:
        await service.seal(owner_id=OWNER_ID, command=command, idempotency_key="seal-1")
    except RecordingUnavailable:
        refused = True
    status = await service.status(owner_id=OWNER_ID, recording_id=recording_id)
    parts_intact = len(repository.parts) == 2
    # The fault has cleared: the same seal resumes and succeeds without re-uploading parts.
    sealed = await service.seal(owner_id=OWNER_ID, command=command, idempotency_key="seal-1")
    held = refused and status.state != "stored" and parts_intact and sealed.replayed is False
    return ScenarioOutcome(
        "seal-during-object-store-outage",
        "recording",
        "no acknowledgement before the manifest is durable; parts survive; the seal resumes",
        held,
        f"refused={refused} state_after_fault={status.state} parts={len(repository.parts)}"
        f" puts_before={puts_before} puts_after={store.put_calls}",
    )


async def scenario_no_duplicate_session() -> ScenarioOutcome:
    repository = InMemoryRecordingRepository()
    service = RecordingService(repository, FaultyObjectStore())  # type: ignore[arg-type]
    recording_id = uuid4()
    first = await service.create(
        owner_id=OWNER_ID, command=create_command(recording_id), idempotency_key="create-1"
    )
    replay = await service.create(
        owner_id=OWNER_ID, command=create_command(recording_id), idempotency_key="create-1"
    )
    conflict = False
    try:
        await service.create(
            owner_id=OWNER_ID, command=create_command(recording_id), idempotency_key="create-2"
        )
    except RecordingConflict:
        conflict = True
    rows = len(repository.recordings)
    held = replay.replayed and first.recording_id == replay.recording_id and conflict and rows == 1
    return ScenarioOutcome(
        "create-replayed-and-reused",
        "recording",
        "one recording identity is one session: replay returns it, reuse is refused",
        held,
        f"replayed={replay.replayed} reuse_conflict={conflict} rows={rows}",
    )


async def scenario_corrupt_final_artifact_never_sealed() -> ScenarioOutcome:
    fx = await _sealed_service()
    service, store, recording_id = fx.service, fx.store, fx.recording_id
    tampered = encrypted_part(recording_id=recording_id, marker=9)
    command = seal_command(
        recording_id, [(tampered[0], tampered[3])], [(fx.system[0], fx.system[3])]
    )
    puts_before = store.put_calls
    refused = False
    try:
        await service.seal(owner_id=OWNER_ID, command=command, idempotency_key="seal-x")
    except RecordingConflict:
        refused = True
    status = await service.status(owner_id=OWNER_ID, recording_id=recording_id)
    held = refused and status.state != "stored" and store.put_calls == puts_before
    return ScenarioOutcome(
        "seal-with-tampered-part-hash",
        "recording",
        "a manifest that does not match the stored bytes is refused and writes nothing",
        held,
        f"refused={refused} state={status.state} manifest_puts={store.put_calls - puts_before}",
    )


async def scenario_worker_crash_resumes_without_duplicate_completion() -> ScenarioOutcome:
    now = datetime(2026, 9, 12, 15, tzinfo=UTC)
    store = FakeJobStore(now=now)
    service = JobService(store)
    job, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=now
    )
    first = await service.claim(ClaimJobCommand(worker_id="dead", kinds=("speech_analysis",)))
    store.now = now + timedelta(seconds=SPEECH_LEASE_SECONDS + 1)
    reclaimed = await service.reclaim_expired()
    second = await service.claim(ClaimJobCommand(worker_id="alive", kinds=("speech_analysis",)))
    dead_refused = False
    try:
        await service.complete(job_id=job.id, command=CompleteJobCommand(worker_id="dead"))
    except JobConflict:
        dead_refused = True
    done = await service.complete(job_id=job.id, command=CompleteJobCommand(worker_id="alive"))
    held = (
        first is not None
        and reclaimed.retried_job_ids == (job.id,)
        and second is not None
        and second.attempt_count == 2
        and dead_refused
        and done.state == "succeeded"
    )
    return ScenarioOutcome(
        "worker-crash-mid-job",
        "jobs",
        "a lost lease is reclaimed once, the job resumes elsewhere, the dead worker cannot finish",
        held,
        f"reclaimed={reclaimed.retried_job_ids} dead_refused={dead_refused} final={done.state}",
    )


async def scenario_duplicate_enqueue_is_one_job() -> ScenarioOutcome:
    now = datetime(2026, 9, 12, 15, tzinfo=UTC)
    service = JobService(FakeJobStore(now=now))
    a, replayed_a = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=now
    )
    b, replayed_b = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=now
    )
    held = a.id == b.id and not replayed_a and replayed_b
    return ScenarioOutcome(
        "duplicate-enqueue",
        "jobs",
        "the same recording and transcript enqueue one job however often the request is replayed",
        held,
        f"ids={a.id},{b.id} replayed={replayed_a},{replayed_b}",
    )


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def scenario_partial_upload_is_never_visible() -> ScenarioOutcome:
    import hashlib

    store = InMemoryObjectStore()
    full = b"immutable audio bytes"
    key = f"recordings/1/parts/{hashlib.sha256(full).hexdigest()}"
    refused = False
    try:
        # Declared as the full object, delivered truncated: the integrity check refuses it.
        await store.put_immutable(
            key=key,
            body=_chunks(full[:8]),
            sha256=hashlib.sha256(full).hexdigest(),
            content_type="application/octet-stream",
            metadata={},
        )
    except ObjectStoreError:
        refused = True
    visible = await store.stat(key)
    held = refused and visible is None
    return ScenarioOutcome(
        "partial-upload",
        "storage",
        "a body that does not match its declared hash is refused and nothing partial is visible",
        held,
        f"refused={refused} visible={visible is not None}",
    )


async def scenario_conflicting_bytes_never_replace_an_object() -> ScenarioOutcome:
    import hashlib

    store = InMemoryObjectStore()
    original = b"original bytes"
    digest = hashlib.sha256(original).hexdigest()
    key = f"recordings/1/parts/{digest}"
    metadata: Mapping[str, str] = {}
    stored: StoredObject = await store.put_immutable(
        key=key,
        body=_chunks(original),
        sha256=digest,
        content_type="application/octet-stream",
        metadata=metadata,
    )
    conflict = False
    try:
        await store.put_immutable(
            key=key,
            body=_chunks(b"other bytes"),
            sha256=digest,
            content_type="application/octet-stream",
            metadata=metadata,
        )
    except ObjectConflict:
        conflict = True
    after = await store.stat(key)
    held = conflict and after == stored
    return ScenarioOutcome(
        "conflicting-bytes-same-key",
        "storage",
        "an immutable object is never replaced; conflicting bytes are refused, the original stays",
        held,
        f"conflict={conflict} unchanged={after == stored}",
    )


SCENARIOS: Final = (
    scenario_no_ack_before_manifest_is_durable,
    scenario_no_duplicate_session,
    scenario_corrupt_final_artifact_never_sealed,
    scenario_worker_crash_resumes_without_duplicate_completion,
    scenario_duplicate_enqueue_is_one_job,
    scenario_partial_upload_is_never_visible,
    scenario_conflicting_bytes_never_replace_an_object,
)


@dataclass(frozen=True, slots=True)
class FailureInjectionReport:
    version: str
    outcomes: tuple[ScenarioOutcome, ...]

    @property
    def layers(self) -> frozenset[str]:
        return frozenset(o.layer for o in self.outcomes)

    @property
    def broken(self) -> tuple[str, ...]:
        return tuple(o.name for o in self.outcomes if not o.held)

    @property
    def passed(self) -> bool:
        return not self.broken and self.layers == {"recording", "jobs", "storage"}

    def render(self) -> str:
        return (
            json.dumps(
                {
                    "version": self.version,
                    "passed": self.passed,
                    "broken": list(self.broken),
                    "scenarios": [
                        {
                            "name": o.name,
                            "layer": o.layer,
                            "invariant": o.invariant,
                            "held": o.held,
                            "observed": o.observed,
                        }
                        for o in self.outcomes
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


async def run_failure_injection() -> FailureInjectionReport:
    outcomes = [await scenario() for scenario in SCENARIOS]
    return FailureInjectionReport(version=FAILURE_INJECTION_VERSION, outcomes=tuple(outcomes))


__all__ = [
    "FAILURE_INJECTION_VERSION",
    "SCENARIOS",
    "FailureInjectionReport",
    "FaultyObjectStore",
    "InjectedOutage",
    "ScenarioOutcome",
    "run_failure_injection",
]
