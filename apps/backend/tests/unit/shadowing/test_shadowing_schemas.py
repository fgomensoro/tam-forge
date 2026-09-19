from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError


def _phrase(
    index: int, start_ms: int, end_ms: int, text: str = "Thanks for joining."
) -> dict[str, Any]:
    return {"index": index, "start_ms": start_ms, "end_ms": end_ms, "text": text, "enabled": True}


def _command(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "QBR opening",
        "format": "solo",
        "skill_slug": "english_fluency",
        "source_note": "Recorded talk, minute 3",
        "license_note": "CC BY 4.0",
        "duration_ms": 45_000,
        "phrases": [_phrase(0, 0, 2_000), _phrase(1, 2_000, 4_500)],
    }
    body.update(overrides)
    return body


def test_a_well_formed_clip_is_accepted_and_notes_default_to_empty() -> None:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand

    command = ShadowingClipCommand.model_validate(_command())
    assert [phrase.index for phrase in command.phrases] == [0, 1]
    assert command.phrases[1].start_ms == 2_000

    bare = _command()
    del bare["source_note"], bare["license_note"], bare["phrases"]
    minimal = ShadowingClipCommand.model_validate(bare)
    assert minimal.source_note == "" and minimal.license_note == "" and minimal.phrases == ()


@pytest.mark.parametrize(
    ("phrases", "reason"),
    [
        ([_phrase(1, 0, 2_000)], "count up from zero"),
        ([_phrase(0, 0, 2_000), _phrase(2, 2_000, 3_000)], "count up from zero"),
        ([_phrase(0, 2_000, 2_000)], "end after it starts"),
        ([_phrase(0, 3_000, 2_000)], "end after it starts"),
        ([_phrase(0, 0, 2_000), _phrase(1, 1_999, 3_000)], "must not overlap"),
        ([_phrase(0, 5_000, 6_000), _phrase(1, 0, 1_000)], "must not overlap"),
        ([_phrase(0, 44_000, 45_001)], "inside the clip"),
    ],
)
def test_phrases_are_ordered_non_overlapping_and_inside_the_clip(
    phrases: list[dict[str, Any]], reason: str
) -> None:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand

    with pytest.raises(ValidationError) as error:
        ShadowingClipCommand.model_validate(_command(phrases=phrases))
    assert reason in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"format": "trio"},
        {"skill_slug": "English Fluency"},
        {"skill_slug": ""},
        {"duration_ms": 999},
        {"duration_ms": 120_001},
        {"source_note": "x" * 501},
        {"license_note": "x" * 501},
        {"phrases": [_phrase(0, 0, 2_000, text="")]},
        {"unknown": 1},
    ],
)
def test_out_of_bounds_clip_fields_are_refused(overrides: dict[str, Any]) -> None:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand

    with pytest.raises(ValidationError):
        ShadowingClipCommand.model_validate(_command(**overrides))


def test_more_than_two_hundred_phrases_are_refused() -> None:
    from tamforge_backend.shadowing.schemas import MAX_PHRASES, ShadowingClipCommand

    phrases = [_phrase(i, i * 100, i * 100 + 100) for i in range(MAX_PHRASES + 1)]
    with pytest.raises(ValidationError):
        ShadowingClipCommand.model_validate(_command(duration_ms=120_000, phrases=phrases))


def test_excerpt_upload_bounds_type_size_and_hash() -> None:
    from tamforge_backend.shadowing.schemas import MAX_EXCERPT_BYTES, ExcerptUploadCommand

    digest = "a" * 64
    accepted = ExcerptUploadCommand(sha256=digest, byte_length=1_024, content_type="audio/mp4")
    assert accepted.content_type == "audio/mp4"
    for body in (
        {"sha256": digest, "byte_length": 0, "content_type": "audio/mp4"},
        {"sha256": digest, "byte_length": MAX_EXCERPT_BYTES + 1, "content_type": "audio/mp4"},
        {"sha256": digest, "byte_length": 1_024, "content_type": "audio/mpeg"},
        {"sha256": digest, "byte_length": 1_024, "content_type": "application/octet-stream"},
        {"sha256": "A" * 64, "byte_length": 1_024, "content_type": "video/mp4"},
        {"sha256": "a" * 63, "byte_length": 1_024, "content_type": "video/mp4"},
    ):
        with pytest.raises(ValidationError):
            ExcerptUploadCommand.model_validate(body)


def test_no_field_reaches_the_swift_generator_with_a_bare_none_default() -> None:
    from tamforge_backend.shadowing import schemas

    for name in schemas.__all__:
        model = getattr(schemas, name)
        if not hasattr(model, "model_fields"):
            continue
        for field_name, field in model.model_fields.items():
            assert field.default is not None, f"{name}.{field_name} defaults to None"
    assert schemas.ShadowingClipResponse.model_fields["excerpt"].is_required()
