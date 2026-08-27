from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.roadmaps.package import inspect_zip_stream
from tamforge_backend.roadmaps.ports import (
    CreateImportResult,
    ImportApproval,
    ImportConflict,
    RoadmapImportRecord,
    RoadmapRepository,
    RoadmapVersionRecord,
)
from tamforge_backend.roadmaps.service import (
    ImportNotApprovable,
    RoadmapService,
)
from tamforge_backend.storage.fake import InMemoryObjectStore

ROOT = Path(__file__).parents[5]
CONFIG = load_config_bundle(ROOT / "config")
FIXTURES = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps"


class RecordingStore(InMemoryObjectStore):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.put_count = 0

    async def put_immutable(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.events.append("snapshot.put")
        self.put_count += 1
        return await super().put_immutable(**kwargs)  # type: ignore[arg-type]

    async def stat(self, key: str):  # type: ignore[no-untyped-def]
        self.events.append("snapshot.stat")
        return await super().stat(key)


class FakeRoadmapRepository(RoadmapRepository):
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.imports: dict[int, RoadmapImportRecord] = {}
        self.versions: dict[int, RoadmapVersionRecord] = {}
        self.exit_eligible = False
        self.activity_versions = [1]
        self._next_import = 1
        self._next_version = 1

    async def find_duplicate_import(
        self, *, owner_id: int, source_key: str, idempotency_key: str, package_hash: str
    ) -> RoadmapImportRecord | None:
        for item in self.imports.values():
            if item.owner_id != owner_id:
                continue
            if item.idempotency_key == idempotency_key:
                return item
        for item in self.imports.values():
            if item.owner_id != owner_id or item.source_key != source_key:
                continue
            if item.package_hash == package_hash:
                return item
        return None

    async def create_staged_import(
        self,
        *,
        owner_id: int,
        source_key: str,
        source_name: str,
        source_kind: str,
        package_hash: str,
        object_key: str,
        idempotency_key: str,
    ) -> CreateImportResult:
        del source_name, source_kind
        item = RoadmapImportRecord(
            id=self._next_import,
            owner_id=owner_id,
            source_id=1,
            source_key=source_key,
            package_hash=package_hash,
            object_key=object_key,
            status="staged",
            validation_report={},
            semantic_diff={},
            idempotency_key=idempotency_key,
            failure_code=None,
        )
        self.imports[item.id] = item
        self._next_import += 1
        return CreateImportResult(record=item, created=True)

    async def begin_validation(self, *, owner_id: int, import_id: int) -> RoadmapImportRecord:
        item = self.imports[import_id]
        assert item.owner_id == owner_id
        item = replace(item, status="validating")
        self.imports[import_id] = item
        return item

    async def finish_validation(
        self,
        *,
        owner_id: int,
        import_id: int,
        validation_report: dict[str, object],
        semantic_diff: dict[str, object],
    ) -> RoadmapImportRecord:
        item = self.imports[import_id]
        assert item.owner_id == owner_id
        item = replace(
            item,
            status="validated",
            validation_report=validation_report,
            semantic_diff=semantic_diff,
        )
        self.imports[import_id] = item
        return item

    async def reject_validation(
        self,
        *,
        owner_id: int,
        import_id: int,
        validation_report: dict[str, object],
        failure_code: str,
    ) -> RoadmapImportRecord:
        item = self.imports[import_id]
        assert item.owner_id == owner_id
        item = replace(
            item,
            status="rejected",
            validation_report=validation_report,
            failure_code=failure_code,
        )
        self.imports[import_id] = item
        return item

    async def get_import(self, *, owner_id: int, import_id: int) -> RoadmapImportRecord | None:
        item = self.imports.get(import_id)
        return item if item is not None and item.owner_id == owner_id else None

    async def latest_normalized_payload(
        self, *, owner_id: int, source_id: int
    ) -> dict[str, object] | None:
        candidates = [
            item
            for item in self.versions.values()
            if item.owner_id == owner_id and item.source_id == source_id
        ]
        return candidates[-1].normalized_payload if candidates else None

    async def approve_import(self, approval: ImportApproval) -> RoadmapVersionRecord:
        self.events.append("repository.approve")
        item = self.imports[approval.import_id]
        version = RoadmapVersionRecord(
            id=self._next_version,
            owner_id=approval.owner_id,
            source_id=item.source_id,
            version_key=approval.parsed.roadmap_version,
            version_number=self._next_version,
            month_number=approval.parsed.tasks[0].month,
            object_key=item.object_key,
            content_hash=approval.parsed.normalized_hash,
            manifest=approval.manifest,
            normalized_payload=approval.parsed.to_dict(),
            state="approved",
            mirror_status="pending" if approval.mirror_required else "not_required",
            mirror_ref=None,
            mirror_error_code=None,
        )
        self.versions[version.id] = version
        self.imports[item.id] = replace(item, status="imported")
        self._next_version += 1
        return version

    async def get_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord | None:
        item = self.versions.get(version_id)
        return item if item is not None and item.owner_id == owner_id else None

    async def list_versions(self, *, owner_id: int) -> tuple[RoadmapVersionRecord, ...]:
        return tuple(item for item in self.versions.values() if item.owner_id == owner_id)

    async def begin_mirror(self, *, owner_id: int, version_id: int) -> RoadmapVersionRecord:
        item = self.versions[version_id]
        assert item.owner_id == owner_id
        item = replace(item, mirror_status="syncing", mirror_error_code=None)
        self.versions[version_id] = item
        return item

    async def finish_mirror(
        self, *, owner_id: int, version_id: int, mirror_ref: str
    ) -> RoadmapVersionRecord:
        item = self.versions[version_id]
        assert item.owner_id == owner_id
        item = replace(item, mirror_status="synced", mirror_ref=mirror_ref)
        self.versions[version_id] = item
        return item

    async def fail_mirror(
        self, *, owner_id: int, version_id: int, error_code: str
    ) -> RoadmapVersionRecord:
        item = self.versions[version_id]
        assert item.owner_id == owner_id
        item = replace(item, mirror_status="failed", mirror_error_code=error_code)
        self.versions[version_id] = item
        return item

    async def activate_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord:
        target = self.versions[version_id]
        assert target.owner_id == owner_id
        if target.month_number > 1 and not self.exit_eligible:
            from tamforge_backend.roadmaps.ports import ActivationNotEligible

            raise ActivationNotEligible("previous month exit review is not eligible")
        for key, item in tuple(self.versions.items()):
            if item.owner_id == owner_id and item.state == "active":
                self.versions[key] = replace(item, state="superseded")
        target = replace(target, state="active")
        self.versions[version_id] = target
        return target


class RecordingMirror:
    enabled = True

    def __init__(self, outcomes: list[str | Exception], events: list[str]) -> None:
        self.outcomes = outcomes
        self.events = events
        self.calls = 0

    async def mirror(self, request: object) -> str:
        del request
        self.events.append("mirror.call")
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _package(name: str = "month-v1.zip"):
    return inspect_zip_stream(((FIXTURES / name).read_bytes(),))


@pytest.mark.anyio
async def test_duplicate_package_or_idempotency_returns_same_staged_import() -> None:
    events: list[str] = []
    repository = FakeRoadmapRepository(events)
    store = RecordingStore(events)
    service = RoadmapService(
        config=CONFIG,
        repository=repository,
        object_store=store,
        mirror=None,
    )

    with _package() as first_package:
        first = await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="import-1",
            package=first_package,
        )
    with _package() as repeated_package:
        repeated = await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="import-1",
            package=repeated_package,
        )
    with _package() as same_package_new_key:
        duplicate_content = await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="import-2",
            package=same_package_new_key,
        )

    assert first == repeated == duplicate_content
    assert first.status == "validated"
    assert store.put_count == 1


@pytest.mark.anyio
async def test_idempotency_conflict_wins_when_package_hash_matches_another_import() -> None:
    events: list[str] = []
    repository = FakeRoadmapRepository(events)
    service = RoadmapService(
        config=CONFIG,
        repository=repository,
        object_store=RecordingStore(events),
        mirror=None,
    )
    with _package("month-v2.zip") as package_two:
        await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="package-two",
            package=package_two,
        )
    with _package() as package_one:
        await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="package-one",
            package=package_one,
        )

    with _package("month-v2.zip") as conflicting:
        with pytest.raises(ImportConflict):
            await service.stage_package(
                owner_id=1,
                source_key="obsidian-main",
                source_name="TAM Roadmap",
                source_kind="obsidian",
                package_kind="zip",
                idempotency_key="package-one",
                package=conflicting,
            )


@pytest.mark.anyio
async def test_approval_checks_immutable_snapshot_before_persistence_and_never_activates() -> None:
    events: list[str] = []
    repository = FakeRoadmapRepository(events)
    store = RecordingStore(events)
    service = RoadmapService(
        config=CONFIG,
        repository=repository,
        object_store=store,
        mirror=None,
    )
    with _package() as package:
        staged = await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="approval-order",
            package=package,
        )
    events.clear()

    version = await service.approve_import(owner_id=1, import_id=staged.id)

    assert events[:2] == ["snapshot.stat", "repository.approve"]
    assert version.state == "approved"
    assert version.mirror_status == "not_required"
    assert repository.activity_versions == [1]


@pytest.mark.anyio
async def test_invalid_source_stays_visible_and_cannot_be_approved() -> None:
    events: list[str] = []
    repository = FakeRoadmapRepository(events)
    store = RecordingStore(events)
    service = RoadmapService(
        config=CONFIG,
        repository=repository,
        object_store=store,
        mirror=None,
    )
    with _package() as package:
        week = package.files[1].staged_path
        week.write_bytes(week.read_bytes().replace(b"## Day 1", b"## Removed Day 1"))
        staged = await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="folder_entries",
            idempotency_key="invalid-source",
            package=package,
        )

    assert staged.status == "rejected"
    assert staged.failure_code == "validation_failed"
    assert staged.validation_report["issues"]
    assert await store.stat(staged.object_key) is not None
    with pytest.raises(ImportNotApprovable):
        await service.approve_import(owner_id=1, import_id=staged.id)


@pytest.mark.anyio
async def test_mirror_failure_is_persisted_and_retry_does_not_duplicate_version() -> None:
    from tamforge_backend.roadmaps.ports import MirrorFailure

    events: list[str] = []
    repository = FakeRoadmapRepository(events)
    store = RecordingStore(events)
    mirror = RecordingMirror([MirrorFailure("write_failed"), "commit-abc"], events)
    service = RoadmapService(
        config=CONFIG,
        repository=repository,
        object_store=store,
        mirror=mirror,
    )
    with _package() as package:
        staged = await service.stage_package(
            owner_id=1,
            source_key="obsidian-main",
            source_name="TAM Roadmap",
            source_kind="obsidian",
            package_kind="zip",
            idempotency_key="mirror-retry",
            package=package,
        )

    failed = await service.approve_import(owner_id=1, import_id=staged.id)
    retried = await service.retry_mirror(owner_id=1, version_id=failed.id)

    assert failed.mirror_status == "failed"
    assert failed.mirror_error_code == "write_failed"
    assert retried.mirror_status == "synced"
    assert retried.mirror_ref == "commit-abc"
    assert len(repository.versions) == 1
    assert mirror.calls == 2


@pytest.mark.anyio
async def test_month_two_activation_requires_exit_review_and_preserves_activity_version() -> None:
    from tamforge_backend.roadmaps.ports import ActivationNotEligible

    events: list[str] = []
    repository = FakeRoadmapRepository(events)
    store = RecordingStore(events)
    service = RoadmapService(
        config=CONFIG,
        repository=repository,
        object_store=store,
        mirror=None,
    )
    approved = RoadmapVersionRecord(
        id=2,
        owner_id=1,
        source_id=1,
        version_key="month-2-v1",
        version_number=2,
        month_number=2,
        object_key="roadmap-source/1/month-2/" + "a" * 64,
        content_hash="b" * 64,
        manifest={},
        normalized_payload={},
        state="approved",
        mirror_status="not_required",
        mirror_ref=None,
        mirror_error_code=None,
    )
    repository.versions[approved.id] = approved

    with pytest.raises(ActivationNotEligible):
        await service.activate_version(owner_id=1, version_id=approved.id)
    repository.exit_eligible = True
    activated = await service.activate_version(owner_id=1, version_id=approved.id)

    assert activated.state == "active"
    assert repository.activity_versions == [1]


async def _collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])
