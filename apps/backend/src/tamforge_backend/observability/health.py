"""Component health observations expire; absent evidence is never success."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from threading import Lock
from typing import TypedDict

from .logging import REASONS

COMPONENTS = frozenset({"ingest", "claude", "speech", "backup", "resources", "export", "retention"})


class ComponentStatus(TypedDict):
    status: str
    reason: str


class HealthSnapshot(TypedDict):
    status: str
    ready: bool
    components: dict[str, ComponentStatus]


class HealthRegistry:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_age_seconds: float = 60,
    ) -> None:
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("invalid health observation lifetime")
        self._clock = clock
        self._max_age = max_age_seconds
        self._observations: dict[str, tuple[str, str, float]] = {}
        self._lock = Lock()

    def report(self, component: str, status: str, reason: str) -> None:
        if (
            component not in COMPONENTS
            or status not in {"ok", "needs_attention", "unknown"}
            or reason not in REASONS
            or (status == "ok") != (reason == "none")
        ):
            raise ValueError("invalid health observation")
        with self._lock:
            self._observations[component] = (status, reason, self._clock())

    def snapshot(self, *, database_ready: bool) -> HealthSnapshot:
        components: dict[str, ComponentStatus] = {
            "database": {
                "status": "ok" if database_ready else "needs_attention",
                "reason": "none" if database_ready else "transient_dependency",
            },
        }
        with self._lock:
            observations = self._observations.copy()
        now = self._clock()
        for component in sorted(COMPONENTS):
            observation = observations.get(component)
            if observation is None:
                state, reason = "unknown", "not_observed"
            else:
                state, reason, observed_at = observation
                if not 0 <= now - observed_at <= self._max_age:
                    state, reason = "unknown", "stale"
            components[component] = {"status": state, "reason": reason}
        ready = database_ready and components["ingest"]["status"] == "ok"
        return {
            "ready": ready,
            "status": "unready"
            if not ready
            else ("ok" if all(c["status"] == "ok" for c in components.values()) else "degraded"),
            "components": components,
        }


async def probe_database(
    probe: Callable[[], Awaitable[None]],
    *,
    timeout_seconds: float = 1,
) -> bool:
    try:
        async with asyncio.timeout(timeout_seconds):
            await probe()
        return True
    except Exception:
        # Cancellation from the caller is a BaseException and still propagates.
        return False
