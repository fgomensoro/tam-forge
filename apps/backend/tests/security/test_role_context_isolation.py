"""Every role sees its slice and nothing else; the Interviewer sees no memory at all."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.memory.context import ContextRequest, ContextSource, build_context
from tamforge_protocol.memory import EvidenceLink, MemoryLedger, MemoryRevision, Provenance

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


def revision(rid: int, **overrides: object) -> MemoryRevision:
    data: dict[str, object] = {
        "memory_id": rid,
        "revision_id": rid,
        "revision_number": 1,
        "kind": "semantic",
        "scope": "global",
        "claim": f"claim {rid}",
        "confidence": 0.7,
        "sensitivity": "routine",
        "visible_to": frozenset({"tutor", "coach", "planner", "reviewer", "analyst"}),
        "evidence": (EvidenceLink(kind="activity", reference_id=1),),
        "provenance": Provenance(author="tutor", model_run_id=1),
        "valid_from": NOW - timedelta(days=1),
        "approval": "approved",
        "recorded_at": NOW - timedelta(days=1),
    }
    data.update(overrides)
    return MemoryRevision.model_validate(data)


@pytest.fixture
def seeded() -> tuple[tuple[ContextSource, ...], MemoryLedger]:
    """The plan's seed: hidden corrections, reviewer judgments, Coach notes, a second
    opportunity, a sensitive real interview, an expired hypothesis, a superseded fact."""
    book = MemoryLedger()
    for r in (
        revision(100),  # verified role memory, everyone
        revision(101, visible_to=frozenset({"reviewer"})),  # reviewer judgment
        revision(102, visible_to=frozenset({"coach"})),  # coach note
        revision(103, sensitivity="real_interview", visible_to=frozenset({"analyst", "coach"})),
        revision(104, kind="hypothesis", approval="proposed", expires_at=NOW - timedelta(hours=1)),
        revision(105, claim="old"),
        revision(106, revision_number=2, supersedes_revision_id=105, memory_id=105, claim="new"),
    ):
        book = book.append(r)
    sources = (
        ContextSource("assignment", "current_assignment", 1, "Week 3 SQL windows"),
        ContextSource(
            "attempt", "current_subject", 1, "the answer being written", is_current_answer=True
        ),
        ContextSource("rubric", "rubric_contract", 1, "rubric v3"),
        ContextSource("corr-1", "active_corrections", 1, "use CTEs"),
        ContextSource("corr-2", "active_corrections", 1, "name columns"),
        ContextSource(
            "corr-hidden", "active_corrections", 1, "hidden third", is_current_answer=True
        ),
        ContextSource("company-a", "active_company", 1, "Northwind brief", company_id=1),
        ContextSource("company-b", "active_company", 1, "Contoso brief", company_id=2),
        ContextSource("mem-100", "verified_role_memory", 1, "claim 100", revision_id=100),
        ContextSource("mem-101", "verified_role_memory", 1, "claim 101", revision_id=101),
        ContextSource("mem-102", "verified_role_memory", 1, "claim 102", revision_id=102),
        ContextSource(
            "mem-103",
            "verified_role_memory",
            1,
            "claim 103",
            revision_id=103,
            sensitivity="real_interview",
        ),
        ContextSource("mem-104", "verified_role_memory", 1, "claim 104", revision_id=104),
        ContextSource("mem-105", "verified_role_memory", 1, "old", revision_id=105),
        ContextSource("mem-106", "verified_role_memory", 1, "new", revision_id=106),
        ContextSource("history", "broader_history", 1, "two years of attempts"),
        ContextSource("other-owner", "related_evidence", 2, "someone else's evidence"),
    )
    return sources, book


def packet(seeded: tuple[tuple[ContextSource, ...], MemoryLedger], role: str, **overrides: object):
    sources, book = seeded
    data: dict[str, object] = {
        "owner_id": 1,
        "role": role,
        "ceiling": "routine",
        "at": NOW,
        "token_budget": 10_000,
        "company_id": 1,
    }
    data.update(overrides)
    return build_context(sources, ContextRequest(**data), ledger=book)  # type: ignore[arg-type]


def included(p) -> set[str]:
    return {i.source_id for i in p.included}


def reason(p, source_id: str) -> str:
    return next(e.reason for e in p.excluded if e.source_id == source_id)


def test_the_interviewer_receives_nothing_and_every_source_says_why(seeded) -> None:
    p = packet(seeded, "interviewer")
    assert p.included == ()
    assert {e.reason for e in p.excluded} == {"interviewer_excluded"}
    assert p.sources_seen == len(seeded[0])


def test_the_coach_never_sees_the_answer_it_is_coaching(seeded) -> None:
    p = packet(seeded, "coach")
    assert "attempt" not in included(p) and reason(p, "attempt") == "coach_current_answer_hidden"
    assert reason(p, "corr-hidden") == "coach_current_answer_hidden"
    assert {"corr-1", "corr-2", "mem-102"} <= included(p)


def test_the_reviewer_sees_its_judgments_but_no_company_brief_or_coach_notes(seeded) -> None:
    p = packet(seeded, "reviewer")
    assert "mem-101" in included(p)
    assert reason(p, "mem-102") == "not_current"
    assert (
        reason(p, "company-a") == "role_not_allowed" and reason(p, "history") == "role_not_allowed"
    )


def test_the_tutor_sees_the_working_set_but_not_reviewer_judgments_or_history(seeded) -> None:
    p = packet(seeded, "tutor")
    assert {
        "assignment",
        "attempt",
        "rubric",
        "corr-1",
        "corr-2",
        "mem-100",
        "mem-106",
    } <= included(p)
    assert reason(p, "mem-101") == "not_current"
    assert reason(p, "history") == "role_not_allowed"


def test_a_second_opportunity_never_leaks_into_this_company_context(seeded) -> None:
    for role in ("planner", "coach", "analyst"):
        p = packet(seeded, role)
        assert "company-a" in included(p) and reason(p, "company-b") == "other_company"


def test_a_real_interview_stays_out_below_its_ceiling_for_every_role(seeded) -> None:
    for role in ("planner", "tutor", "coach", "reviewer", "analyst"):
        p = packet(seeded, role)
        assert reason(p, "mem-103") == "sensitivity_above_ceiling"
    lifted = packet(seeded, "analyst", ceiling="real_interview")
    assert "mem-103" in included(lifted)
    still_hidden = packet(seeded, "tutor", ceiling="real_interview")
    assert reason(still_hidden, "mem-103") == "not_current"


def test_expired_hypotheses_and_superseded_facts_are_never_current(seeded) -> None:
    p = packet(seeded, "planner")
    assert reason(p, "mem-104") == "not_current"
    assert reason(p, "mem-105") == "not_current" and "mem-106" in included(p)


def test_another_owners_evidence_is_excluded_for_every_role(seeded) -> None:
    for role in ("planner", "tutor", "coach", "reviewer", "analyst"):
        assert reason(packet(seeded, role), "other-owner") == "other_owner"
