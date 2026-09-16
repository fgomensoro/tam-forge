"""Cards come from vault notes that opted in, from approved study notes, and from the Coach."""

from __future__ import annotations

from tamforge_backend.cards.importing import (
    coach_card_command,
    note_card_commands,
    package_card_commands,
    parse_flashcard_note,
    parse_front_matter,
)

VAULT_NOTE = """---
title: Idempotency
flashcard-source: true
skill: api_contracts
tags: [http, retries]
---

# Idempotency

Q: What does a 200 from the ingest endpoint mean?
A: The request was durably accepted.
It has not been processed yet.

**Q:** Why do retries need an idempotency key?
**A:** So a retried request does not create a second record.

Q: A question with no answer is skipped

Some prose that is not a card.

Question: Long form prefixes work too?
Answer: Yes.
"""


def test_front_matter_reads_flat_keys_and_ignores_nested_ones() -> None:
    front = parse_front_matter(VAULT_NOTE)
    assert front["flashcard-source"] == "true"
    assert front["skill"] == "api_contracts"
    assert parse_front_matter("# No front matter\n") == {}


def test_a_vault_note_yields_its_pairs_with_multiline_answers_and_its_skill() -> None:
    note = parse_flashcard_note(VAULT_NOTE)
    assert note is not None
    assert note.skill_slug == "api_contracts"
    assert note.pairs == (
        (
            "What does a 200 from the ingest endpoint mean?",
            "The request was durably accepted. It has not been processed yet.",
        ),
        (
            "Why do retries need an idempotency key?",
            "So a retried request does not create a second record.",
        ),
        ("Long form prefixes work too?", "Yes."),
    )


def test_notes_that_did_not_opt_in_or_name_a_bad_skill_are_handled() -> None:
    assert parse_flashcard_note("---\nflashcard-source: false\n---\nQ: x\nA: y\n") is None
    assert parse_flashcard_note("Q: x\nA: y\n") is None
    loose = parse_flashcard_note("---\nflashcard-source: yes\nskill: Not A Slug\n---\nQ: x\nA: y\n")
    assert loose is not None and loose.skill_slug == "general"
    assert loose.pairs == (("x", "y"),)


def test_package_commands_come_from_markdown_files_in_path_order_and_name_their_source() -> None:
    files = {
        "notes/b.md": VAULT_NOTE.encode(),
        "notes/a.md": b"---\nflashcard-source: true\n---\nQ: first?\nA: yes\n",
        "notes/skip.md": b"# nothing here\n",
        "assets/x.png": b"\x89PNG",
        "notes/bad.md": b"\xff\xfe",
    }
    commands = package_card_commands(files)
    assert [item.source_ref for item in commands] == [
        "package:notes/a.md",
        "package:notes/b.md",
        "package:notes/b.md",
        "package:notes/b.md",
    ]
    assert commands[0].skill_slug == "general" and commands[1].skill_slug == "api_contracts"
    assert all(item.source_kind == "package" for item in commands)
    assert all(item.assistance == "independent" for item in commands)


def test_note_and_coach_commands_record_their_source_and_assistance() -> None:
    from_note = note_card_commands(
        note_id=12,
        flashcards=[("What is TAM?", "Technical account management."), ("  ", "blank")],
        skill_slug="tam_general",
        assistance="coached",
    )
    assert len(from_note) == 1
    assert from_note[0].source_ref == "note:12" and from_note[0].source_kind == "study_note"
    assert from_note[0].assistance == "coached"
    from_coach = coach_card_command(
        message_id=5,
        index=2,
        question="Backoff?",
        answer="Exponential with jitter.",
        skill_slug="x",
    )
    assert from_coach.source_ref == "coach:5:2" and from_coach.assistance == "coached"
    assert from_coach.source_kind == "coach"
