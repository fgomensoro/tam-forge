from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tamforge_backend.observability.health import HealthRegistry
from tamforge_backend.observability.heartbeats import (
    WORKER_COMPONENTS,
    report_worker_heartbeats,
)


class FakeStore:
    def __init__(self, recent: dict[str, tuple[str, str]]) -> None:
        self._recent = recent
        self.calls = 0

    async def recent(self, *, now: datetime) -> dict[str, tuple[str, str]]:
        del now
        self.calls += 1
        return dict(self._recent)


@pytest.mark.anyio
async def test_fresh_worker_beats_become_component_reports_and_absent_ones_stay_unknown() -> None:
    clock = [1000.0]
    registry = HealthRegistry(clock=lambda: clock[0])
    store = FakeStore({"general": ("ok", "none"), "claude": ("needs_attention", "auth")})

    await report_worker_heartbeats(registry, store, now=datetime(2026, 9, 12, tzinfo=UTC))  # type: ignore[arg-type]

    snapshot = registry.snapshot(database_ready=True)
    assert snapshot["components"]["resources"] == {"status": "ok", "reason": "none"}
    assert snapshot["components"]["claude"] == {"status": "needs_attention", "reason": "auth"}
    assert snapshot["components"]["speech"] == {"status": "unknown", "reason": "not_observed"}
    assert store.calls == 1

    clock[0] += 61
    stale = registry.snapshot(database_ready=True)
    assert stale["components"]["resources"] == {"status": "unknown", "reason": "stale"}


def test_every_worker_maps_onto_a_known_component() -> None:
    from tamforge_backend.observability.health import COMPONENTS

    assert set(WORKER_COMPONENTS.values()) <= COMPONENTS
