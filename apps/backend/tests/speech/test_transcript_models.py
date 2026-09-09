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


def test_correction_identity_is_its_own_content_hash() -> None:
    # The constraint a retried correction POST collides with instead of
    # appending a duplicate annotation. Dropping it would leave
    # `append_correction`'s dedup SELECT racing the retry it exists to absorb.
    names = {constraint.name for constraint in SpeechTranscriptCorrection.__table__.constraints}
    assert "uq_speech_transcript_corrections_content" in names
