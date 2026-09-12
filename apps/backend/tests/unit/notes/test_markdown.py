"""The exported Markdown carries Frank's front matter and every section, nothing invented."""

from __future__ import annotations

from datetime import date

from tamforge_backend.notes.markdown import NoteDocument, note_filename, render_note_markdown


def _document(**overrides: object) -> NoteDocument:
    data: dict[str, object] = {
        "title": "Webhooks: delivery and retries",
        "stable_id": "p1-w01-d01-roadmap",
        "local_date": date(2026, 9, 12),
        "status": "approved",
        "assistance": "coached",
        "assessment_status": "self_review_complete",
        "drafted_by": "coach",
        "rule": "A 200 confirms durable acceptance, not processing.",
        "explanation": "The provider retries until it sees a 2xx.",
        "example": "Stripe retries for up to three days with backoff.",
        "misconceptions": ["A 200 means the event was processed."],
        "validated_queries": [
            {"query": "SELECT count(*) FROM events;", "result": "42"},
        ],
        "sources": ["docs/webhooks.md"],
        "flashcards": [
            {"question": "What does a 200 confirm?", "answer": "Durable acceptance."},
        ],
    }
    data.update(overrides)
    return NoteDocument(**data)  # type: ignore[arg-type]


def test_front_matter_uses_the_vault_keys_and_records_assistance_and_assessment() -> None:
    text = render_note_markdown(_document())
    head, body = text.split("\n---\n", 1)
    assert head.splitlines()[0] == "---"
    assert "type: polished-study-note" in head
    assert "status: validated" in head
    assert 'topic: "Webhooks: delivery and retries"' in head
    assert "date: 2026-09-12" in head
    assert "assistance: coached" in head
    assert "assessment: self_review_complete" in head
    assert "future-app-source: true" in head
    assert "flashcard-source: true" in head
    assert body.startswith("\n# Webhooks: delivery and retries")


def test_flashcard_source_is_true_only_for_an_approved_note_with_cards() -> None:
    draft = render_note_markdown(_document(status="draft"))
    assert "status: draft" in draft and "flashcard-source: false" in draft
    no_cards = render_note_markdown(_document(flashcards=[]))
    assert "flashcard-source: false" in no_cards


def test_every_section_is_rendered_and_empty_ones_show_a_dash() -> None:
    text = render_note_markdown(_document())
    for heading in (
        "## Rule",
        "## Explanation",
        "## Example",
        "## Corrected misconceptions",
        "## Validated queries",
        "## Sources",
        "## Card-ready Q/A",
        "## Assistance and assessment",
    ):
        assert heading in text
    assert "```sql\nSELECT count(*) FROM events;\n```" in text
    assert "Result: 42" in text
    assert "**Q:** What does a 200 confirm?" in text
    sparse = render_note_markdown(
        _document(misconceptions=[], validated_queries=[], sources=[], flashcards=[])
    )
    assert sparse.count("\n- —") == 2
    assert sparse.count("\n—\n") == 2


def test_the_filename_is_the_date_and_a_safe_title() -> None:
    assert note_filename(_document()) == "2026-09-12 - Webhooks delivery and retries.md"
    assert note_filename(_document(title="///")) == "2026-09-12 - p1-w01-d01-roadmap.md"
