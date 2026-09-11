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


# --- the encrypted daily backup (issue #12) ------------------------------------------------


from pathlib import Path  # noqa: E402

from infra.backup.encrypted import (  # noqa: E402
    BackupError,
    BackupManifest,
    assert_no_secret,
    backup,
    decrypt_dump,
    restore_drill,
    verify,
)

KEY = bytes(range(32))
CAPTURED = datetime(2026, 9, 15, 3, tzinfo=UTC)


def make_backup(tmp_path: Path, **overrides: object) -> Path:
    destination = tmp_path / "backup" / CAPTURED.strftime("%Y%m%dT%H%M%SZ")
    kwargs: dict[str, object] = {
        "key": KEY,
        "dump": lambda: b"PGDMP fake custom-format dump bytes",
        "config": {"DATABASE_URL": "postgresql://x", "OBJECT_STORE_SECRET_KEY": "hunter2"},
        "tool_versions": {"pg_dump": "16.15", "python-cryptography": "46.0.7"},
        "schema_head": "abc123def456",
        "now": lambda: CAPTURED,
    }
    kwargs.update(overrides)
    backup(destination, **kwargs)  # type: ignore[arg-type]
    return destination


def test_a_backup_is_encrypted_hash_covered_and_its_manifest_names_no_value(tmp_path: Path) -> None:
    destination = make_backup(tmp_path)
    manifest = verify(destination, key=KEY)
    assert isinstance(manifest, BackupManifest) and manifest.cipher == "AES-256-GCM"
    assert [p.name for p in manifest.payloads] == ["db/tamforge.dump", "config/inventory.json"]
    ciphertext = (destination / "payloads" / "db" / "tamforge.dump.enc").read_bytes()
    assert b"PGDMP" not in ciphertext
    text = (destination / "manifest.json").read_text()
    assert "hunter2" not in text and "postgresql://x" not in text and KEY.hex() not in text
    assert '"OBJECT_STORE_SECRET_KEY"' in text  # the key name is inventory; the value never is
    assert decrypt_dump(destination, key=KEY) == b"PGDMP fake custom-format dump bytes"


def test_the_manifest_is_published_last_and_a_directory_is_written_once(tmp_path: Path) -> None:
    destination = make_backup(tmp_path)
    assert not list(destination.glob("*.tmp")) and not list(destination.glob("payloads/**/*.tmp"))
    with pytest.raises(BackupError, match="written once"):
        make_backup(tmp_path)


def test_an_empty_dump_or_a_bad_key_never_produces_a_backup(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="empty dump"):
        make_backup(tmp_path, dump=lambda: b"")
    with pytest.raises(BackupError, match="32 bytes"):
        make_backup(tmp_path / "other", key=b"short")


def test_a_manifest_that_would_carry_a_credential_is_refused() -> None:
    for text in ("password=hunter2", "api_key: abc", "-----BEGIN RSA PRIVATE KEY-----"):
        with pytest.raises(BackupError, match="credential"):
            assert_no_secret(text)
    assert_no_secret('{"config_keys": ["POSTGRES_PASSWORD"]}')


def test_a_changed_byte_or_a_missing_payload_fails_verification(tmp_path: Path) -> None:
    destination = make_backup(tmp_path)
    path = destination / "payloads" / "db" / "tamforge.dump.enc"
    data = bytearray(path.read_bytes())
    data[3] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(BackupError, match="does not match"):
        verify(destination)
    path.unlink()
    with pytest.raises(BackupError, match="partial backup"):
        verify(destination, key=KEY)


def test_the_wrong_key_cannot_read_the_backup(tmp_path: Path) -> None:
    destination = make_backup(tmp_path)
    with pytest.raises(BackupError, match="decryption failed"):
        verify(destination, key=bytes(32))


def test_the_restore_drill_restores_through_the_injected_step_and_measures_both_numbers(
    tmp_path: Path,
) -> None:
    destination = make_backup(tmp_path)
    restored: list[bytes] = []
    ticks = iter([CAPTURED + timedelta(hours=20), CAPTURED + timedelta(hours=20, minutes=7)])
    result = restore_drill(
        destination,
        key=KEY,
        environment=Environment("restore-drill", is_production=False),
        restore=restored.append,
        thresholds=Thresholds(max_rpo_minutes=1500, max_rto_minutes=60),
        clock=lambda: next(ticks),
    )
    assert restored == [b"PGDMP fake custom-format dump bytes"]
    assert (result.verified, result.rpo_minutes, result.rto_minutes) == (2, 20 * 60 + 7, 7)
    assert result.met


def test_the_restore_drill_refuses_production_before_decrypting_anything(tmp_path: Path) -> None:
    destination = make_backup(tmp_path)
    restored: list[bytes] = []
    with pytest.raises(ProductionRefused):
        restore_drill(
            destination,
            key=KEY,
            environment=Environment("production", is_production=True),
            restore=restored.append,
            thresholds=Thresholds(max_rpo_minutes=1500, max_rto_minutes=60),
        )
    assert restored == []
