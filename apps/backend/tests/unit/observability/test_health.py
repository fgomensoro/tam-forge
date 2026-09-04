import asyncio

import pytest
from tamforge_backend.observability.health import HealthRegistry, probe_database


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

    assert asyncio.run(probe_database(broken, timeout_seconds=0.01)) is False
    assert asyncio.run(probe_database(hung, timeout_seconds=0.01)) is False
