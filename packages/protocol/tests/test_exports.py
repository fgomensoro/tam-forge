"""An export that verifies from its own contents, and a manifest that reassembles."""

from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError
from tamforge_protocol.exports import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    ExportError,
    ExportManifest,
    related,
    require_readable,
    total_bytes,
    verify,
)

BODIES = {
    "recordings/11.bin": b"audio-bytes",
    "transcripts/21.json": b'{"segments": []}',
    "analyses/31.json": b'{"verdict": "clear"}',
}


def digest(body: bytes) -> str:
    return sha256(body).hexdigest()


def artifact(artifact_id: int, kind: str, path: str) -> dict:
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "path": path,
        "sha256": digest(BODIES[path]),
        "byte_length": len(BODIES[path]),
    }


def manifest(**overrides: object) -> ExportManifest:
    data: dict[str, object] = {
        "owner_id": 1,
        "artifacts": (
            artifact(11, "recording", "recordings/11.bin"),
            artifact(21, "transcript", "transcripts/21.json"),
            artifact(31, "analysis", "analyses/31.json"),
        ),
        "relations": (
            {"subject_id": 21, "relation": "transcribes", "object_id": 11},
            {"subject_id": 31, "relation": "judges", "object_id": 21},
        ),
    }
    data.update(overrides)
    return ExportManifest.model_validate(data)


def on_disk(**changes: bytes) -> tuple[dict[str, str], dict[str, int]]:
    bodies = {**BODIES, **changes}
    return (
        {path: digest(body) for path, body in bodies.items()},
        {path: len(body) for path, body in bodies.items()},
    )


def test_an_export_verifies_against_its_own_bytes() -> None:
    digests, sizes = on_disk()

    assert verify(manifest(), digests=digests, sizes=sizes) is None


def test_altered_content_fails_verification() -> None:
    digests, sizes = on_disk(**{"transcripts/21.json": b'{"segments": ["tampered"]}'})

    with pytest.raises(ExportError, match="does not match its hash"):
        verify(manifest(), digests=digests, sizes=sizes)


def test_a_missing_file_is_a_broken_export() -> None:
    digests, sizes = on_disk()
    digests.pop("analyses/31.json")

    with pytest.raises(ExportError, match="missing from the export"):
        verify(manifest(), digests=digests, sizes=sizes)


def test_a_file_nothing_accounts_for_is_a_broken_export_too() -> None:
    # An export you cannot fully account for is one you cannot trust to be complete.
    digests, sizes = on_disk()
    digests["stowaway.bin"] = digest(b"?")
    sizes["stowaway.bin"] = 1

    with pytest.raises(ExportError, match="unaccounted for"):
        verify(manifest(), digests=digests, sizes=sizes)


def test_a_length_that_disagrees_with_the_manifest_fails() -> None:
    digests, sizes = on_disk()
    sizes["recordings/11.bin"] = 999

    with pytest.raises(ExportError, match="length does not match"):
        verify(manifest(), digests=digests, sizes=sizes)


def test_the_manifest_says_how_the_pieces_fit_back_together() -> None:
    built = manifest()

    assert related(built, subject_id=21, relation="transcribes") == (11,)
    assert related(built, subject_id=31, relation="judges") == (21,)
    assert related(built, subject_id=11, relation="transcribes") == ()


def test_a_relation_naming_something_absent_is_refused() -> None:
    # It would turn the manifest into a map of a place that is not there.
    with pytest.raises(ValidationError, match="does not contain"):
        manifest(relations=({"subject_id": 21, "relation": "transcribes", "object_id": 99},))


def test_nothing_relates_to_itself() -> None:
    with pytest.raises(ValidationError, match="relate to itself"):
        manifest(relations=({"subject_id": 21, "relation": "transcribes", "object_id": 21},))


def test_an_artifact_appears_once_and_owns_its_path() -> None:
    doubled = (
        artifact(11, "recording", "recordings/11.bin"),
        artifact(11, "recording", "transcripts/21.json"),
    )
    with pytest.raises(ValidationError, match="appears once"):
        manifest(artifacts=doubled, relations=())

    shared = (
        artifact(11, "recording", "recordings/11.bin"),
        {**artifact(12, "transcript", "transcripts/21.json"), "path": "recordings/11.bin"},
    )
    with pytest.raises(ValidationError, match="share a path"):
        manifest(artifacts=shared, relations=())


def test_a_reader_refuses_a_version_it_does_not_know() -> None:
    assert require_readable(EXPORT_FORMAT, EXPORT_VERSION) is None

    for fmt, version in (("someone-elses-export", "1"), (EXPORT_FORMAT, "9")):
        with pytest.raises(ExportError, match="does not know"):
            require_readable(fmt, version)


def test_the_manifest_can_be_sized_without_opening_anything() -> None:
    assert total_bytes(manifest().artifacts) == sum(len(body) for body in BODIES.values())


def test_looking_up_something_absent_says_so() -> None:
    with pytest.raises(ExportError, match="does not contain that artifact"):
        manifest().artifact(99)
