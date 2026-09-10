"""What the export has to be able to describe, given what this backend actually stores."""

from __future__ import annotations

from typing import get_args

from tamforge_protocol.exports import ArtifactKind, ExportManifest, RelationKind


def test_the_export_can_name_every_class_of_record_the_app_keeps() -> None:
    """An export that has no kind for a record cannot carry it without lying about it.

    These are the durable things the backend owns: the audio, the transcript derived from
    it, the attempt, the analysis that judged the attempt, the evidence event that came
    out of it, the report built over those, and the opportunity and interview a real
    conversation hangs from.
    """
    kinds = set(get_args(ArtifactKind))

    assert {
        "recording",
        "transcript",
        "attempt",
        "analysis",
        "evidence_event",
        "report",
        "opportunity",
        "interview",
    } <= kinds


def test_the_relation_vocabulary_covers_the_links_the_schema_really_has() -> None:
    # A transcript transcribes a recording, an analysis judges an attempt, an evidence
    # event evidences something, and an interview belongs to an opportunity. Without
    # these the manifest is a file listing rather than a map.
    relations = set(get_args(RelationKind))

    assert {"transcribes", "judges", "evidences", "belongs_to"} <= relations


def test_an_empty_export_is_still_a_valid_export() -> None:
    # A brand new workspace has nothing in it, and refusing to export that would make
    # the first backup the one nobody takes.
    empty = ExportManifest.model_validate({"owner_id": 1, "artifacts": ()})

    assert empty.artifacts == ()
    assert empty.relations == ()
    assert empty.format == "tamforge-export"
