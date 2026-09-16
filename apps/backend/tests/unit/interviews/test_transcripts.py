"""A pasted transcript becomes turns and counts, and names what it cannot judge."""

from __future__ import annotations

from tamforge_backend.interviews.transcripts import (
    EXCLUDED_FINDINGS,
    parse_transcript_turns,
    transcript_metrics,
)

TRANSCRIPT = """
Interviewer: Tell me about a time you handled an escalation.
Frank: Sure. A payments customer saw duplicate webhooks.
I traced the retries to their idempotency key.
Frank: Then I wrote the runbook.
[00:04] Interviewer: What would you change?
Frank: Add the key check to onboarding.
"""


def test_speaker_lines_start_turns_and_bare_lines_continue_them() -> None:
    turns = parse_transcript_turns(TRANSCRIPT, ("Frank",))
    assert [(t.speaker, t.label) for t in turns] == [
        ("other", "Interviewer"),
        ("learner", "Frank"),
        ("other", "Interviewer"),
        ("learner", "Frank"),
    ]
    assert turns[1].text == (
        "Sure. A payments customer saw duplicate webhooks. I traced the retries to their "
        "idempotency key. Then I wrote the runbook."
    )
    assert turns[3].text == "Add the key check to onboarding."


def test_learner_labels_are_case_insensitive_and_defaults_cover_me() -> None:
    turns = parse_transcript_turns("ME: hi\nBob: hello\nme: bye\n")
    assert [t.speaker for t in turns] == ["learner", "other", "learner"]
    assert parse_transcript_turns("no speakers here\n\n") == ()


def test_metrics_count_words_and_turns_and_list_the_excluded_findings() -> None:
    metrics = transcript_metrics(parse_transcript_turns(TRANSCRIPT, ("Frank",)))
    assert metrics["learner_turns"] == 2 and metrics["other_turns"] == 2
    assert metrics["learner_words"] == 26 and metrics["other_words"] == 13
    assert metrics["learner_word_share"] == round(26 / 39, 3)
    assert metrics["longest_learner_turn_words"] == 20
    assert metrics["excluded_findings"] == list(EXCLUDED_FINDINGS)
    assert {"pronunciation", "fluency"} <= set(EXCLUDED_FINDINGS)
    assert transcript_metrics(())["learner_word_share"] == 0.0
