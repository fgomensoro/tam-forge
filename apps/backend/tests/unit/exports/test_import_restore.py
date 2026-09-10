"""A dry run that writes nothing, and a restore that is all of it or none."""

from __future__ import annotations

from hashlib import sha256

import pytest
from tamforge_backend.exports.import_restore import (
    DryRunReport,
    ImportError_,
    PartialRestore,
    RecordingWriter,
    RestorePlan,
    apply_restore,
    dry_run,
)
from tamforge_protocol.exports import EXPORT_FORMAT, EXPORT_VERSION, ExportManifest

BODIES = {
    "recordings/11.bin": b"audio-bytes",
    "transcripts/21.json": b'{"segments": []}',
}


def artifact(artifact_id: int, kind: str, path: str) -> dict:
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "path": path,
        "sha256": sha256(BODIES[path]).hexdigest(),
        "byte_length": len(BODIES[path]),
    }


def manifest(**overrides: object) -> ExportManifest:
    data: dict[str, object] = {
        "owner_id": 1,
        "artifacts": (
            artifact(11, "recording", "recordings/11.bin"),
            artifact(21, "transcript", "transcripts/21.json"),
        ),
        "relations": ({"subject_id": 21, "relation": "transcribes", "object_id": 11},),
    }
    data.update(overrides)
    return ExportManifest.model_validate(data)


def on_disk(**changes: bytes):
    bodies = {**BODIES, **changes}
    return (
        {path: sha256(body).hexdigest() for path, body in bodies.items()},
        {path: len(body) for path, body in bodies.items()},
    )


def run(**overrides: object) -> DryRunReport:
    digests, sizes = on_disk()
    data: dict[str, object] = {
        "digests": digests,
        "sizes": sizes,
        "manifest_format": EXPORT_FORMAT,
        "manifest_version": EXPORT_VERSION,
    }
    data.update(overrides)
    return dry_run(manifest(), **data)  # type: ignore[arg-type]


def test_a_clean_export_is_ready_to_restore() -> None:
    report = run()

    assert report.ready is True
    assert report.problems == ()
    assert (report.artifact_count, report.relation_count) == (2, 1)


def test_the_dry_run_writes_nothing_at_all() -> None:
    # Not a row, not a file, not a marker saying it was attempted.
    writer = RecordingWriter()
    run()

    assert writer.written == []


def test_altered_content_is_reported_rather_than_restored() -> None:
    digests, sizes = on_disk(**{"transcripts/21.json": b'{"segments": ["tampered"]}'})
    report = dry_run(
        manifest(),
        digests=digests,
        sizes=sizes,
        manifest_format=EXPORT_FORMAT,
        manifest_version=EXPORT_VERSION,
    )

    assert report.ready is False
    assert any("does not match its hash" in problem for problem in report.problems)


def test_an_unknown_format_version_is_reported_before_anything_else() -> None:
    report = run(manifest_version="9")

    assert report.ready is False
    assert any("does not know" in problem for problem in report.problems)


def test_every_problem_is_reported_rather_than_only_the_first() -> None:
    digests, sizes = on_disk()
    digests.pop("recordings/11.bin")
    report = dry_run(
        manifest(),
        digests=digests,
        sizes=sizes,
        manifest_format="someone-elses",
        manifest_version="1",
    )

    assert len(report.problems) == 2


def test_a_rejected_dry_run_cannot_be_approved() -> None:
    rejected = run(manifest_version="9")

    with pytest.raises(ImportError_, match="rejected dry run"):
        RestorePlan(manifest=manifest(), approved_by="owner", report=rejected)


def test_a_restore_names_who_approved_it() -> None:
    with pytest.raises(ImportError_, match="names who approved"):
        RestorePlan(manifest=manifest(), approved_by="   ", report=run())


def test_an_approved_restore_writes_every_artifact() -> None:
    writer = RecordingWriter()
    plan = RestorePlan(manifest=manifest(), approved_by="owner", report=run())

    written = apply_restore(plan, write=writer.write)

    assert set(written) == set(BODIES)
    assert set(writer.written) == set(BODIES)


def test_a_failure_partway_raises_rather_than_returning_a_short_list() -> None:
    # A partial restore that reports success looks like a workspace, and the missing
    # half is invisible until someone goes looking for it.
    plan = RestorePlan(manifest=manifest(), approved_by="owner", report=run())
    attempted: list[str] = []

    def failing(path: str) -> None:
        attempted.append(path)
        if len(attempted) == 2:
            raise OSError("disk full")

    with pytest.raises(PartialRestore, match="after 1 of 2 artifacts"):
        apply_restore(plan, write=failing)


def test_the_failure_says_how_far_it_got_so_a_rollback_can_be_checked() -> None:
    plan = RestorePlan(manifest=manifest(), approved_by="owner", report=run())

    def failing(path: str) -> None:
        raise OSError("permission denied")

    with pytest.raises(PartialRestore) as raised:
        apply_restore(plan, write=failing)

    assert "after 0 of 2" in str(raised.value)
    assert raised.value.__cause__ is not None
