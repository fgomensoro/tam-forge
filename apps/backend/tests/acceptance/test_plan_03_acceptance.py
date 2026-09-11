"""The integrated acceptance run: did feedback arrive in time, and if not, why not."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.analysis.slo import (
    ASSESSMENT_SLO,
    ROUTINE_SLO,
    WAITING_ON_A_PERSON,
    WAITING_ON_CLAUDE,
    ProcessingRun,
    SloError,
    Suspension,
    summarize,
)

SEALED = datetime(2026, 9, 15, 10, tzinfo=UTC)


def run(**overrides: object) -> ProcessingRun:
    data: dict[str, object] = {
        "kind": "practice",
        "ingest_sealed_at": SEALED,
        "self_review_complete_at": SEALED,
        "feedback_ready_at": SEALED + timedelta(minutes=10),
    }
    data.update(overrides)
    return ProcessingRun(**data)  # type: ignore[arg-type]


def test_the_two_budgets_are_fifteen_and_sixty_minutes() -> None:
    assert ROUTINE_SLO == timedelta(minutes=15)
    assert ASSESSMENT_SLO == timedelta(minutes=60)
    assert run().budget == ROUTINE_SLO
    assert run(kind="mock").budget == ASSESSMENT_SLO
    assert run(kind="real", self_review_complete_at=None).budget == ASSESSMENT_SLO


def test_routine_feedback_passes_at_the_boundary_and_misses_just_past_it() -> None:
    assert run(feedback_ready_at=SEALED + ROUTINE_SLO).on_time is True

    late = run(feedback_ready_at=SEALED + ROUTINE_SLO + timedelta(milliseconds=1))
    assert late.on_time is False
    assert late.miss_reason == "over_budget"


def test_assessment_feedback_passes_at_the_hour_and_misses_just_past_it() -> None:
    at = run(kind="mock", feedback_ready_at=SEALED + ASSESSMENT_SLO)
    past = run(kind="mock", feedback_ready_at=SEALED + ASSESSMENT_SLO + timedelta(milliseconds=1))

    assert at.on_time is True
    assert past.on_time is False


def test_the_clock_starts_when_the_learner_has_also_committed() -> None:
    # Feedback cannot honestly start before the learner has committed their own read.
    later_review = run(
        self_review_complete_at=SEALED + timedelta(minutes=30),
        feedback_ready_at=SEALED + timedelta(minutes=40),
    )

    assert later_review.eligible_at == SEALED + timedelta(minutes=30)
    assert later_review.active_elapsed == timedelta(minutes=10)
    assert later_review.on_time is True


def test_a_real_interview_becomes_eligible_at_seal() -> None:
    # Its debrief is a separate gate rather than part of this clock.
    real = run(kind="real", self_review_complete_at=None)

    assert real.eligible_at == SEALED


def test_practice_without_a_self_review_is_not_a_run_at_all() -> None:
    with pytest.raises(SloError, match="only after a self-review"):
        run(self_review_complete_at=None)


@pytest.mark.parametrize("reason", sorted(WAITING_ON_A_PERSON))
def test_waiting_on_a_person_does_not_spend_the_budget(reason: str) -> None:
    # Holding the system to a deadline it cannot influence teaches nobody anything.
    waited = run(
        feedback_ready_at=SEALED + timedelta(minutes=70),
        suspensions=(
            Suspension(
                reason=reason,  # type: ignore[arg-type]
                started_at=SEALED + timedelta(minutes=2),
                ended_at=SEALED + timedelta(minutes=62),
            ),
        ),
    )

    assert waited.suspended == timedelta(minutes=60)
    assert waited.active_elapsed == timedelta(minutes=10)
    assert waited.on_time is True


@pytest.mark.parametrize("reason", sorted(WAITING_ON_CLAUDE))
def test_a_claude_outage_can_never_be_recorded_as_on_time(reason: str) -> None:
    # Otherwise a system that was unavailable for an hour reports a perfect record.
    recovered = run(
        feedback_ready_at=SEALED + timedelta(minutes=70),
        suspensions=(
            Suspension(
                reason=reason,  # type: ignore[arg-type]
                started_at=SEALED + timedelta(minutes=2),
                ended_at=SEALED + timedelta(minutes=62),
            ),
        ),
    )

    assert recovered.active_elapsed == timedelta(minutes=10)
    assert recovered.on_time is False
    assert recovered.miss_reason == "claude_unavailable"


def test_missing_feedback_is_a_miss_rather_than_an_absence() -> None:
    missing = run(feedback_ready_at=None)

    assert missing.active_elapsed is None
    assert missing.on_time is False
    assert missing.miss_reason == "no_feedback"


def test_a_speech_stage_that_missed_its_own_gate_blocks_the_composite() -> None:
    blocked = run(speech_stage_met=False)

    assert blocked.on_time is False
    assert blocked.miss_reason == "speech_stage_missed"


def test_an_unfinished_suspension_runs_to_the_moment_feedback_arrived() -> None:
    open_ended = run(
        feedback_ready_at=SEALED + timedelta(minutes=40),
        suspensions=(
            Suspension(reason="awaiting_debrief", started_at=SEALED + timedelta(minutes=5)),
        ),
    )

    assert open_ended.suspended == timedelta(minutes=35)
    assert open_ended.active_elapsed == timedelta(minutes=5)


def test_feedback_before_eligibility_is_refused_rather_than_counted_as_fast() -> None:
    impossible = run(
        self_review_complete_at=SEALED + timedelta(minutes=30),
        feedback_ready_at=SEALED + timedelta(minutes=5),
    )

    with pytest.raises(SloError, match="before the run is eligible"):
        impossible.active_elapsed


def test_a_suspension_cannot_end_before_it_starts() -> None:
    with pytest.raises(SloError, match="end before it starts"):
        Suspension(
            reason="claude_quota",
            started_at=SEALED + timedelta(minutes=10),
            ended_at=SEALED,
        )


def test_naive_timestamps_are_refused_on_runs_and_suspensions() -> None:
    with pytest.raises(SloError, match="timezone-aware"):
        run(ingest_sealed_at=datetime(2026, 9, 15, 10))
    with pytest.raises(SloError, match="timezone-aware"):
        Suspension(reason="claude_quota", started_at=datetime(2026, 9, 15, 10))


def test_the_acceptance_run_reports_every_outcome_and_hides_none() -> None:
    counts = summarize(
        [
            run(),
            run(feedback_ready_at=SEALED + timedelta(minutes=30)),
            run(feedback_ready_at=None),
            run(speech_stage_met=False),
            run(
                suspensions=(
                    Suspension(reason="claude_quota", started_at=SEALED + timedelta(minutes=1)),
                ),
            ),
        ]
    )

    assert counts == {
        "on_time": 1,
        "over_budget": 1,
        "no_feedback": 1,
        "speech_stage_missed": 1,
        "claude_unavailable": 1,
    }


# --- the release checklist (issue #114) ------------------------------------------------------


import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from tamforge_backend.operations.release_checklist import (  # noqa: E402
    CHECKLIST,
    ReleaseRefused,
    evaluate,
    require_releasable,
)

REPO = Path(__file__).resolve().parents[4]


def test_the_checklist_links_every_required_area() -> None:
    areas = {item.area for item in CHECKLIST}
    assert areas == {
        "signing",
        "permissions",
        "recording",
        "learning",
        "privacy",
        "recovery",
        "version",
    }
    assert all(item.required for item in CHECKLIST)
    assert all((REPO / item.evidence).exists() or item.area in {"version"} for item in CHECKLIST), [
        item.evidence for item in CHECKLIST if not (REPO / item.evidence).exists()
    ]


def test_the_repository_today_is_refused_and_says_exactly_why() -> None:
    decision = evaluate(REPO)
    unresolved = {v.key: v.reason for v in decision.unresolved}
    # Two items are open by design: no 60-minute runtime window has been recorded on
    # this head, and no release is tagged. Everything else resolves from committed evidence.
    assert set(unresolved) == {"recording.runtime_window", "version.tagged_exact_commit"}, (
        unresolved
    )
    assert "blocked template" in unresolved["recording.runtime_window"]
    assert "no release tag" in unresolved["version.tagged_exact_commit"]
    with pytest.raises(ReleaseRefused, match="recording.runtime_window"):
        require_releasable(decision)


def test_a_fully_resolved_tree_is_releasable(tmp_path: Path) -> None:
    for item in CHECKLIST:
        target = tmp_path / item.evidence
        target.parent.mkdir(parents=True, exist_ok=True)
        source = REPO / item.evidence
        if source.exists():
            shutil.copy(source, target)
    # Resolve the three open items the way they would be resolved for real.
    verification = tmp_path / "docs/project/recording-verification-v1.json"
    body = json.loads(verification.read_text())
    body["commit_sha"] = "a" * 40
    for result in body["results"]:
        result["status"] = "pass"
    verification.write_text(json.dumps(body))
    perf = tmp_path / "docs/project/speech-performance-60m-apple-m5-24gb.json"
    perf_body = json.loads(perf.read_text())
    perf_body["verdicts"]["transcriptionPeakWithinGate"] = True
    perf.write_text(json.dumps(perf_body))
    (tmp_path / "apps/macos/.release-tag").write_text("v0.1.0+6a7ca76\n")

    decision = evaluate(tmp_path)
    assert decision.releasable, decision.render()
    require_releasable(decision)


def test_a_tag_that_does_not_match_the_marketing_version_is_unresolved(tmp_path: Path) -> None:
    pbx = tmp_path / "apps/macos/TAMForge.xcodeproj/project.pbxproj"
    pbx.parent.mkdir(parents=True)
    pbx.write_text("MARKETING_VERSION = 0.1.0;\n")
    (tmp_path / "apps/macos/.release-tag").write_text("v0.2.0+abcdef1\n")
    decision = evaluate(tmp_path, tuple(item for item in CHECKLIST if item.area == "version"))
    assert not decision.releasable and "tag 'v0.2.0+abcdef1'" in decision.unresolved[0].reason


def test_the_decision_has_no_override() -> None:
    import inspect

    from tamforge_backend.operations import release_checklist

    source = inspect.getsource(release_checklist)
    assert "override" not in source.lower().replace("no override flag", "")
    assert "force" not in source.lower()
