"""The drill runs somewhere clean, verifies hashes, and reports two measured numbers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from infra.backup.drill import (
    BackupArtifact,
    DrillError,
    Environment,
    ProductionRefused,
    Thresholds,
    require_clean_environment,
    run_drill,
    verify_backup,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
BODIES = {"db/tamforge.dump": b"pg-dump-bytes", "objects/manifest.json": b'{"objects": []}'}


def artifact(path: str, minutes_old: int = 20) -> BackupArtifact:
    return BackupArtifact(
        path=path,
        sha256=sha256(BODIES[path]).hexdigest(),
        captured_at=NOW - timedelta(minutes=minutes_old),
    )


def digests(**changes: bytes) -> dict[str, str]:
    bodies = {**BODIES, **changes}
    return {path: sha256(body).hexdigest() for path, body in bodies.items()}


def drill(**overrides: object):
    data: dict[str, object] = {
        "artifacts": (artifact("db/tamforge.dump"), artifact("objects/manifest.json", 25)),
        "environment": Environment("restore-drill", is_production=False),
        "digests": digests(),
        "thresholds": Thresholds(max_rpo_minutes=60, max_rto_minutes=30),
        "started_at": NOW - timedelta(minutes=12),
        "finished_at": NOW,
        "now": NOW,
    }
    data.update(overrides)
    return run_drill(data.pop("artifacts"), **data)  # type: ignore[arg-type]


def test_the_drill_never_runs_against_production() -> None:
    # A drill that borrows the live system proves the opposite of what it claims to.
    live = Environment("prod-1", is_production=True)

    with pytest.raises(ProductionRefused, match="never runs against production"):
        require_clean_environment(live)
    with pytest.raises(ProductionRefused):
        drill(environment=live)


def test_it_refuses_before_it_touches_anything() -> None:
    live = Environment("prod-1", is_production=True)

    # Even with a backup that would fail verification, the refusal comes first.
    with pytest.raises(ProductionRefused):
        drill(environment=live, digests={})


def test_a_clean_run_reports_both_measured_numbers() -> None:
    result = drill()

    assert result.environment == "restore-drill"
    assert result.verified == 2
    assert result.rpo_minutes == 20
    assert result.rto_minutes == 12
    assert result.met is True
    assert result.missed == ()


def test_the_recovery_point_is_the_age_of_the_newest_thing_in_the_backup() -> None:
    # The oldest artifact does not decide it; what would be lost is everything after
    # the most recent capture.
    result = drill(
        artifacts=(artifact("db/tamforge.dump", 5), artifact("objects/manifest.json", 90))
    )

    assert result.rpo_minutes == 5


def test_a_missed_threshold_fails_rather_than_being_noted() -> None:
    late = drill(thresholds=Thresholds(max_rpo_minutes=10, max_rto_minutes=30))
    slow = drill(thresholds=Thresholds(max_rpo_minutes=60, max_rto_minutes=5))

    assert late.met is False and late.missed == ("rpo",)
    assert slow.met is False and slow.missed == ("rto",)


def test_both_thresholds_can_miss_at_once() -> None:
    result = drill(thresholds=Thresholds(max_rpo_minutes=1, max_rto_minutes=1))

    assert result.missed == ("rpo", "rto")


def test_altered_backup_content_fails_verification() -> None:
    with pytest.raises(DrillError, match="does not match its hash"):
        drill(digests=digests(**{"db/tamforge.dump": b"something-else"}))


def test_a_missing_backup_file_fails_verification() -> None:
    incomplete = digests()
    incomplete.pop("objects/manifest.json")

    with pytest.raises(DrillError, match="missing from the backup"):
        drill(digests=incomplete)


def test_an_empty_backup_proves_nothing() -> None:
    with pytest.raises(DrillError, match="proves nothing"):
        verify_backup((), digests=digests())


def test_a_restore_cannot_finish_before_it_starts() -> None:
    with pytest.raises(DrillError, match="finish before it starts"):
        drill(finished_at=NOW - timedelta(minutes=30))


def test_a_backup_from_the_future_is_refused_rather_than_measured() -> None:
    with pytest.raises(DrillError, match="from the future"):
        drill(artifacts=(artifact("db/tamforge.dump", -10),))


def test_an_artifact_without_a_hash_is_not_a_backup_artifact() -> None:
    with pytest.raises(DrillError, match="carries its hash"):
        BackupArtifact(path="db/tamforge.dump", sha256="short", captured_at=NOW)


def test_a_naive_capture_time_is_refused() -> None:
    with pytest.raises(DrillError, match="timezone-aware"):
        BackupArtifact(path="x", sha256="a" * 64, captured_at=datetime(2026, 9, 15, 12))


@pytest.mark.parametrize("changes", [{"max_rpo_minutes": 0}, {"max_rto_minutes": 0}])
def test_thresholds_are_positive(changes) -> None:
    base = {"max_rpo_minutes": 60, "max_rto_minutes": 30, **changes}
    with pytest.raises(DrillError, match="positive numbers"):
        Thresholds(**base)


def test_an_environment_has_a_name() -> None:
    with pytest.raises(DrillError, match="has a name"):
        Environment("   ", is_production=False)
