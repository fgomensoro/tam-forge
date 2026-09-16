"""The answer bank splits into entries whose readiness labels stay unverified."""

from __future__ import annotations

from tamforge_backend.interviews.reference import (
    parse_reference_entries,
    rank_entries,
    render_citation,
)

ANSWER_BANK = """# Answer bank

Intro paragraph that belongs to no entry.

## Tell me about yourself
Readiness: ready
I am a TAM with eight years in payments integrations.

## Handling an escalation
- Status: draft
Duplicate webhooks at a payments customer; traced retries to the idempotency key.

## Empty heading

## Why this company
**Confidence:** 3/5
Their platform sits where my integration work matters.
"""


def test_entries_follow_headings_and_keep_their_readiness_labels() -> None:
    entries = parse_reference_entries(ANSWER_BANK)
    assert [e.heading for e in entries] == [
        "Tell me about yourself",
        "Handling an escalation",
        "Why this company",
    ]
    assert [e.readiness_label for e in entries] == ["ready", "draft", "3/5"]
    assert entries[1].body.startswith("Duplicate webhooks")
    assert entries[0].content_hash != entries[1].content_hash
    assert parse_reference_entries("# Title only\n\nprose\n") == ()


def test_ranking_prefers_heading_matches_and_citations_say_unverified() -> None:
    entries = tuple(
        (e.heading, e.body, e.readiness_label) for e in parse_reference_entries(ANSWER_BANK)
    )
    ranked = rank_entries(entries, "Describe an escalation with duplicate webhooks", limit=2)
    assert [r[0] for r in ranked] == ["Handling an escalation"]
    assert rank_entries(entries, "the a of", limit=2) == ()
    citation = render_citation(*ranked[0], "answer_bank")
    assert citation.startswith(
        "[answer_bank] Handling an escalation; readiness 'draft' (unverified): "
    )
    assert "unverified" in render_citation("h", "b", "", "story_catalog")
