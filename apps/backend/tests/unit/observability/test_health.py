import asyncio

import pytest
from tamforge_backend.observability.health import HealthRegistry, probe_dependency


def test_missing_or_stale_evidence_never_becomes_healthy() -> None:
    now = [0.0]
    registry = HealthRegistry(clock=lambda: now[0], max_age_seconds=30)
    assert registry.snapshot(database_ready=True)["status"] == "unready"
    registry.report("ingest", "ok", "none")
    assert registry.snapshot(database_ready=True)["ready"] is True
    now[0] = 31
    status = registry.snapshot(database_ready=True)
    assert status["ready"] is False
    assert status["components"]["ingest"] == {"status": "unknown", "reason": "stale"}


@pytest.mark.parametrize(
    "component,reason",
    [
        ("claude", "quota"),
        ("claude", "auth"),
        ("speech", "processing_failure"),
        ("backup", "stale"),
        ("resources", "disk_pressure"),
    ],
)
def test_noncritical_capabilities_do_not_restart_loop_study(component: str, reason: str) -> None:
    registry = HealthRegistry()
    registry.report("ingest", "ok", "none")
    registry.report(component, "needs_attention", reason)
    snapshot = registry.snapshot(database_ready=True)
    assert snapshot["ready"] is True
    assert snapshot["status"] == "degraded"
    assert snapshot["components"][component] == {"status": "needs_attention", "reason": reason}


def test_database_and_ingest_failures_block_readiness() -> None:
    registry = HealthRegistry()
    registry.report("ingest", "ok", "none")
    assert registry.snapshot(database_ready=False)["ready"] is False
    registry.report("ingest", "needs_attention", "durability_failure")
    assert registry.snapshot(database_ready=True)["ready"] is False


def test_health_rejects_sensitive_arbitrary_values() -> None:
    for args in [
        ("company name", "ok", "none"),
        ("claude", "secret", "none"),
        ("claude", "needs_attention", "token-secret"),
    ]:
        with pytest.raises(ValueError, match="health"):
            HealthRegistry().report(*args)


def test_database_probe_is_bounded_and_does_not_expose_exception() -> None:
    async def broken() -> None:
        raise RuntimeError("postgresql://user:secret@private-host")

    async def hung() -> None:
        await asyncio.sleep(1)

    assert asyncio.run(probe_dependency(broken, timeout_seconds=0.01)) is False
    assert asyncio.run(probe_dependency(hung, timeout_seconds=0.01)) is False


class _Stop(Exception):
    """Ends the heartbeat loop from inside the fake sleep, without cancelling it."""


def _drive_heartbeat(registry, probe, *, iterations: int) -> list[float]:
    from tamforge_backend.observability.health import run_health_heartbeat

    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) > iterations:
            raise _Stop

    async def main() -> None:
        try:
            await run_health_heartbeat(
                registry,
                component="ingest",
                probe=probe,
                interval_seconds=20,
                timeout_seconds=0.01,
                sleep=sleep,
            )
        except _Stop:
            return

    asyncio.run(main())
    return slept


def test_the_heartbeat_sleeps_before_its_first_probe() -> None:
    probed = []

    async def probe() -> None:
        probed.append(1)

    registry = HealthRegistry()
    _drive_heartbeat(registry, probe, iterations=0)

    # A starting application has observed nothing yet, and says so.
    assert probed == []
    assert registry.snapshot(database_ready=True)["components"]["ingest"] == {
        "status": "unknown",
        "reason": "not_observed",
    }


def test_a_healthy_probe_makes_the_service_ready_with_no_user_request() -> None:
    async def probe() -> None:
        return None

    registry = HealthRegistry()
    slept = _drive_heartbeat(registry, probe, iterations=1)

    assert slept[0] == 20
    snapshot = registry.snapshot(database_ready=True)
    assert snapshot["ready"] is True
    assert snapshot["components"]["ingest"] == {"status": "ok", "reason": "none"}


def test_a_failing_probe_blocks_readiness() -> None:
    async def probe() -> None:
        raise RuntimeError("object store unreachable")

    registry = HealthRegistry()
    _drive_heartbeat(registry, probe, iterations=1)

    snapshot = registry.snapshot(database_ready=True)
    assert snapshot["ready"] is False
    assert snapshot["components"]["ingest"] == {
        "status": "needs_attention",
        "reason": "transient_dependency",
    }


def test_a_hung_probe_is_a_failure_not_a_stall() -> None:
    async def probe() -> None:
        await asyncio.sleep(5)

    registry = HealthRegistry()
    _drive_heartbeat(registry, probe, iterations=1)

    assert registry.snapshot(database_ready=True)["ready"] is False


def test_the_heartbeat_recovers_once_the_dependency_returns() -> None:
    failures = [True]

    async def probe() -> None:
        if failures[0]:
            failures[0] = False
            raise RuntimeError("object store unreachable")

    registry = HealthRegistry()
    _drive_heartbeat(registry, probe, iterations=2)

    assert registry.snapshot(database_ready=True)["ready"] is True


def test_cancelling_the_heartbeat_stops_it() -> None:
    from tamforge_backend.observability.health import run_health_heartbeat

    async def probe() -> None:
        return None

    async def main() -> bool:
        registry = HealthRegistry()
        task = asyncio.create_task(
            run_health_heartbeat(
                registry, component="ingest", probe=probe, interval_seconds=0.01
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return task.done()

    assert asyncio.run(main()) is True
