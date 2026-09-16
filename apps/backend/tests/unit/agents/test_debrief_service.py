"""The debrief role: quotes must be in the transcript, skills in the catalog, no plan edits."""

from __future__ import annotations

from datetime import UTC, datetime

from tamforge_backend.agents.roles.debrief import (
    DebriefInterview,
    DebriefRequest,
    DebriefSkill,
    render_debrief_prompt,
    validate_debrief,
)

TRANSCRIPT = (
    "[0] Interviewer: Walk me through an escalation.\n"
    "[4200] Learner: A payments customer saw duplicate webhooks. I traced the retries to "
    "their idempotency key."
)
SKILLS = (
    DebriefSkill("structured_troubleshooting", "Structured troubleshooting"),
    DebriefSkill("business_value_framing", "Business value framing"),
)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "summary": "Clear root cause; no customer impact stated.",
        "dimensions": [
            {"slug": "answer_clarity", "score": "3.0", "rationale": "Ordered."},
            {"slug": "technical_examples", "score": "3.5", "rationale": "Concrete."},
            {"slug": "english_accuracy", "score": "3.0", "rationale": "Clean."},
            {"slug": "follow_up_handling", "score": "2.5", "rationale": "Short."},
        ],
        "strengths": [
            {
                "statement": "Names the root cause.",
                "evidence": "traced the retries to their idempotency key",
                "skill_slug": "structured_troubleshooting",
            },
            {
                "statement": "Concrete example.",
                "evidence": "duplicate webhooks",
                "skill_slug": "business_value_framing",
            },
        ],
        "gaps": [
            {
                "statement": "No impact in dollars or hours.",
                "evidence": "saw duplicate webhooks",
                "skill_slug": "business_value_framing",
            },
            {
                "statement": "No verification step named.",
                "evidence": "traced the retries",
                "skill_slug": "structured_troubleshooting",
            },
        ],
        "skills_affected": [
            {
                "skill_slug": "structured_troubleshooting",
                "direction": "up",
                "evidence": "traced the retries",
            }
        ],
        "next_week_practice": [
            {
                "description": "Retell with the customer's cost first.",
                "skill_slug": "business_value_framing",
                "minutes": 20,
            }
        ],
        "hiring_progression": "Advanced to the next round.",
    }
    base.update(overrides)
    return base


def test_a_quoted_catalog_bound_debrief_passes() -> None:
    assert validate_debrief(_payload(), transcript=TRANSCRIPT, skills=SKILLS) == ()


def test_quotes_are_matched_ignoring_case_and_spacing_but_must_exist() -> None:
    loose = _payload(
        skills_affected=[
            {
                "skill_slug": "structured_troubleshooting",
                "direction": "up",
                "evidence": "TRACED   the retries",
            }
        ]
    )
    assert validate_debrief(loose, transcript=TRANSCRIPT, skills=SKILLS) == ()
    invented = _payload(
        skills_affected=[
            {
                "skill_slug": "structured_troubleshooting",
                "direction": "up",
                "evidence": "we lost money",
            }
        ]
    )
    issues = validate_debrief(invented, transcript=TRANSCRIPT, skills=SKILLS)
    assert issues and "verbatim" in issues[0]


def test_skills_outside_the_catalog_duplicates_and_plan_changes_are_refused() -> None:
    outside = _payload(
        next_week_practice=[{"description": "x", "skill_slug": "charisma", "minutes": 10}]
    )
    assert "catalog" in validate_debrief(outside, transcript=TRANSCRIPT, skills=SKILLS)[0]
    doubled = _payload(
        skills_affected=[
            {"skill_slug": "structured_troubleshooting", "direction": "up", "evidence": "traced"},
            {"skill_slug": "structured_troubleshooting", "direction": "down", "evidence": "traced"},
        ]
    )
    assert "once" in validate_debrief(doubled, transcript=TRANSCRIPT, skills=SKILLS)[0]
    plan = _payload(hiring_progression="I rescheduled the Thursday block.")
    assert "plan" in validate_debrief(plan, transcript=TRANSCRIPT, skills=SKILLS)[0]
    shape = _payload(strengths=[])
    assert validate_debrief(shape, transcript=TRANSCRIPT, skills=SKILLS)[0].startswith("debrief ")


def test_the_prompt_carries_the_record_catalog_transcript_and_source_caveat() -> None:
    request = DebriefRequest(
        interview=DebriefInterview(
            "Coframe", "TAM", "screen", datetime(2026, 9, 10, tzinfo=UTC), "completed"
        ),
        transcript=TRANSCRIPT,
        skills=SKILLS,
        transcript_source="transcript_only",
        reference=("[answer_bank] Handling an escalation; readiness 'ready' (unverified): text",),
        repair_errors=("gaps evidence must be a verbatim quote from the transcript",),
    )
    prompt = render_debrief_prompt(request)
    assert "Interview: Coframe, TAM, stage screen, 2026-09-10, status completed." in prompt
    assert "- structured_troubleshooting: Structured troubleshooting" in prompt
    assert "pasted without audio" in prompt and "Never comment on pronunciation" in prompt
    assert "readiness labels are unverified" in prompt
    assert "Do not change the plan" in prompt
    assert "fix these:\n- gaps evidence" in prompt
    recorded = render_debrief_prompt(
        DebriefRequest(interview=request.interview, transcript=TRANSCRIPT, skills=SKILLS)
    )
    assert "comes from a recording" in recorded and "Reference material" not in recorded


def test_the_four_tracker_dimensions_are_scored_in_half_points() -> None:
    quarter = _payload(
        dimensions=[
            {"slug": "answer_clarity", "score": "2.75", "rationale": "x"},
            {"slug": "technical_examples", "score": "3", "rationale": "x"},
            {"slug": "english_accuracy", "score": "3", "rationale": "x"},
            {"slug": "follow_up_handling", "score": "3", "rationale": "x"},
        ]
    )
    assert "half points" in validate_debrief(quarter, transcript=TRANSCRIPT, skills=SKILLS)[0]
    wrong = _payload(
        dimensions=[
            {"slug": "charisma", "score": "3", "rationale": "x"},
            {"slug": "technical_examples", "score": "3", "rationale": "x"},
            {"slug": "english_accuracy", "score": "3", "rationale": "x"},
            {"slug": "follow_up_handling", "score": "3", "rationale": "x"},
        ]
    )
    assert "tracker dimensions" in validate_debrief(wrong, transcript=TRANSCRIPT, skills=SKILLS)[0]
    prompt = render_debrief_prompt(
        DebriefRequest(
            interview=DebriefInterview(
                "C", "R", "s", datetime(2026, 9, 10, tzinfo=UTC), "completed"
            ),
            transcript=TRANSCRIPT,
            skills=SKILLS,
        )
    )
    assert "- answer_clarity: Answer clarity and structure" in prompt
