"""Spans, previews, and the approval that binds to exact bytes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.interviews.redaction import (
    REDACTION_PLACEHOLDER,
    RedactionError,
    RedactionSpan,
    build_preview,
    digest,
    redact,
)
from tamforge_protocol.interviews import Interview

NOW = datetime(2026, 9, 15, 17, tzinfo=UTC)
TEXT = "Dana at Northwind said the renewal is at risk."


def real_interview(**overrides: object) -> Interview:
    data: dict[str, object] = {
        "interview_id": 11,
        "owner_id": 1,
        "kind": "real",
        "scheduled_for": NOW - timedelta(hours=2),
        "opportunity_id": 4,
        "stage_label": "Panel",
    }
    data.update(overrides)
    return Interview.model_validate(data)


def test_a_span_is_replaced_by_a_placeholder() -> None:
    redacted = redact(TEXT, (RedactionSpan(0, 4, "person_name"),))

    assert redacted.startswith(REDACTION_PLACEHOLDER)
    assert "Dana" not in redacted
    assert "Northwind" in redacted


def test_several_spans_apply_without_shifting_each_other() -> None:
    # Applied right to left, so an earlier offset stays valid as the text shrinks.
    redacted = redact(
        TEXT, (RedactionSpan(0, 4, "person_name"), RedactionSpan(8, 17, "company_name"))
    )

    assert "Dana" not in redacted and "Northwind" not in redacted
    assert redacted.count(REDACTION_PLACEHOLDER) == 2


def test_overlapping_spans_are_refused_rather_than_merged() -> None:
    with pytest.raises(RedactionError, match="ambiguous"):
        redact(TEXT, (RedactionSpan(0, 10, "person_name"), RedactionSpan(5, 17, "company_name")))


def test_a_span_past_the_end_of_the_text_is_refused() -> None:
    with pytest.raises(RedactionError, match="past the end"):
        redact(TEXT, (RedactionSpan(0, len(TEXT) + 1, "person_name"),))


def test_an_empty_or_backwards_span_is_not_a_span() -> None:
    for start, end in ((5, 5), (9, 4), (-1, 4)):
        with pytest.raises(RedactionError, match="nonempty range"):
            RedactionSpan(start, end, "person_name")


def test_a_preview_pins_the_source_and_what_it_would_produce() -> None:
    spans = (RedactionSpan(0, 4, "person_name"),)
    preview = build_preview(real_interview(), owner_id=1, text=TEXT, spans=spans, at=NOW)

    assert preview.source_sha256 == digest(TEXT)
    assert preview.preview_sha256 == digest(redact(TEXT, spans))
    assert preview.source_sha256 != preview.preview_sha256


def test_editing_the_text_changes_the_preview_it_describes() -> None:
    spans = (RedactionSpan(0, 4, "person_name"),)
    first = build_preview(real_interview(), owner_id=1, text=TEXT, spans=spans, at=NOW)
    edited = build_preview(
        real_interview(), owner_id=1, text=TEXT + " Also the API is failing.", spans=spans, at=NOW
    )

    assert first.source_sha256 != edited.source_sha256
    assert first.preview_sha256 != edited.preview_sha256


def test_the_category_vocabulary_has_no_catch_all() -> None:
    # "other" as a catch-all is how a category nobody reviews accumulates everything
    # difficult.
    from typing import get_args

    from tamforge_backend.interviews.redaction import RedactionCategory

    assert "other" not in get_args(RedactionCategory)
    assert "person_name" in get_args(RedactionCategory)


def test_a_naive_preview_timestamp_is_refused() -> None:
    with pytest.raises(RedactionError, match="timezone-aware"):
        build_preview(
            real_interview(),
            owner_id=1,
            text=TEXT,
            spans=(RedactionSpan(0, 4, "person_name"),),
            at=datetime(2026, 9, 15, 17),
        )
