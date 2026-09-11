"""Context packets: fixed hierarchy, a budget that trims from the bottom, a complete manifest."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tamforge_backend.memory.context import (
    HIERARCHY,
    MAX_ACTIVE_CORRECTIONS,
    ContextError,
    ContextRequest,
    ContextSource,
    build_context,
)
from tamforge_protocol.memory import EvidenceLink, MemoryLedger, MemoryRevision, Provenance

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


def source(source_id: str, tier: str, text: str = "x" * 40, **overrides: object) -> ContextSource:
    data: dict[str, object] = {"source_id": source_id, "tier": tier, "owner_id": 1, "text": text}
    data.update(overrides)
    return ContextSource(**data)  # type: ignore[arg-type]


def request(**overrides: object) -> ContextRequest:
    data: dict[str, object] = {
        "owner_id": 1,
        "role": "tutor",
        "ceiling": "routine",
        "at": NOW,
        "token_budget": 1_000,
    }
    data.update(overrides)
    return ContextRequest(**data)  # type: ignore[arg-type]


def ledger_with(*revision_ids: int) -> MemoryLedger:
    out = MemoryLedger()
    for rid in revision_ids:
        out = out.append(
            MemoryRevision(
                memory_id=rid,
                revision_id=rid,
                revision_number=1,
                kind="semantic",
                scope="global",
                claim=f"claim {rid}",
                confidence=0.7,
                sensitivity="routine",
                visible_to=frozenset({"tutor", "coach", "planner", "reviewer", "analyst"}),
                evidence=(EvidenceLink(kind="activity", reference_id=1),),
                provenance=Provenance(author="tutor", model_run_id=1),
                valid_from=NOW,
                approval="approved",
                recorded_at=NOW,
            )
        )
    return out


def test_the_packet_follows_the_approved_hierarchy_whatever_order_sources_arrive_in() -> None:
    shuffled = tuple(
        source(f"s-{tier}", tier) for tier in reversed(HIERARCHY) if tier != "broader_history"
    )
    packet = build_context(shuffled, request(role="planner"), ledger=MemoryLedger())
    assert [i.tier for i in packet.included] == [t for t in HIERARCHY if t != "broader_history"]
    assert [i.position for i in packet.included] == list(range(len(packet.included)))


def test_the_budget_trims_from_the_bottom_and_names_what_it_dropped() -> None:
    sources = (
        source("assignment", "current_assignment", "a" * 400),
        source("subject", "current_subject", "b" * 400),
        source("history", "verified_role_memory", "c" * 400),
    )
    packet = build_context(sources, request(token_budget=250), ledger=MemoryLedger())
    assert [i.source_id for i in packet.included] == ["assignment", "subject"]
    assert packet.tokens_used == 200
    assert packet.excluded == (
        (packet.excluded[0].__class__("history", "verified_role_memory", "over_budget")),
    )


def test_only_two_active_corrections_are_ever_included() -> None:
    corrections = tuple(source(f"corr-{i}", "active_corrections") for i in range(4))
    packet = build_context(corrections, request(), ledger=MemoryLedger())
    assert len(packet.included) == MAX_ACTIVE_CORRECTIONS
    assert sorted(e.source_id for e in packet.excluded) == ["corr-2", "corr-3"]
    assert {e.reason for e in packet.excluded} == {"over_budget"}


def test_ordering_is_stable_within_a_tier() -> None:
    sources = (
        source("b", "related_evidence"),
        source("a", "related_evidence"),
        source("c", "related_evidence"),
    )
    first = build_context(sources, request(), ledger=MemoryLedger())
    second = build_context(tuple(reversed(sources)), request(), ledger=MemoryLedger())
    assert [i.source_id for i in first.included] == ["a", "b", "c"]
    assert first.included == second.included


def test_a_memory_source_must_point_at_a_current_visible_revision() -> None:
    book = ledger_with(100)
    sources = (
        source("mem-current", "verified_role_memory", revision_id=100),
        source("mem-superseded", "verified_role_memory", revision_id=99),
    )
    packet = build_context(sources, request(), ledger=book)
    assert [i.source_id for i in packet.included] == ["mem-current"]
    assert packet.excluded[0].reason == "not_current"


def test_the_manifest_lists_every_source_exactly_once_with_one_decision() -> None:
    sources = (
        source("assignment", "current_assignment"),
        source("other", "current_subject", owner_id=2),
        source("secret", "related_evidence", sensitivity="real_interview"),
    )
    packet = build_context(sources, request(), ledger=MemoryLedger())
    assert packet.sources_seen == 3
    assert packet.manifest == (
        ("assignment", "included"),
        ("other", "other_owner"),
        ("secret", "sensitivity_above_ceiling"),
    )


def test_a_request_without_an_owner_or_budget_is_refused() -> None:
    with pytest.raises(ContextError, match="one owner"):
        request(owner_id=0)
    with pytest.raises(ContextError, match="budget"):
        request(token_budget=0)
