"""Releases: verified before current, current switched atomically, rolled back by pointer only."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from infra.host.contract import load_contract
from infra.host.deploy import DeployRefused, ReleaseArtifact, install, preflight, rollback, verify

REPO = Path(__file__).resolve().parents[2]
CONTRACT = load_contract(REPO / "infra" / "config" / "host-layout.env")


class Host:
    def __init__(self, *, heads: str = "abc123 (head)\n", pg: int = 0) -> None:
        self.heads = heads
        self.pg = pg
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        if args[:2] == ["alembic", "heads"]:
            return 0, self.heads
        if args[:1] == ["pg_isready"]:
            return self.pg, ""
        return 0, ""


def artifact(
    tmp_path: Path, release_id: str = "20260912T150000Z-abcdef1", content: bytes = b"release"
) -> ReleaseArtifact:
    path = tmp_path / f"{release_id}.tar.gz"
    path.write_bytes(content)
    return ReleaseArtifact(
        release_id=release_id, path=path, expected_sha256=sha256(content).hexdigest()
    )


def test_preflight_passes_a_matching_artifact_on_a_healthy_host(tmp_path: Path) -> None:
    preflight(
        artifact(tmp_path),
        CONTRACT,
        runner=Host(),
        free_disk_bytes=10 * 1024**3,
        expected_host="tamforge-prod",
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"expected_host": "lamas-prod"}, "different host"),
        ({"free_disk_bytes": 1024**3}, "2 GiB free"),
        ({"runner": Host(heads="a (head)\nb (head)\n")}, "exactly one head"),
        ({"runner": Host(pg=2)}, "not answering"),
    ],
)
def test_preflight_refuses_each_missing_precondition(
    tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    kwargs: dict[str, object] = {
        "runner": Host(),
        "free_disk_bytes": 10 * 1024**3,
        "expected_host": "tamforge-prod",
    }
    kwargs.update(change)
    with pytest.raises(DeployRefused, match=reason):
        preflight(artifact(tmp_path), CONTRACT, **kwargs)  # type: ignore[arg-type]


def test_a_checksum_mismatch_or_bad_release_id_is_refused(tmp_path: Path) -> None:
    bad = ReleaseArtifact("20260912T150000Z-abcdef1", artifact(tmp_path).path, "0" * 64)
    with pytest.raises(DeployRefused, match="checksum"):
        preflight(
            bad,
            CONTRACT,
            runner=Host(),
            free_disk_bytes=10 * 1024**3,
            expected_host="tamforge-prod",
        )
    with pytest.raises(DeployRefused, match="release id"):
        preflight(
            artifact(tmp_path, release_id="latest"),
            CONTRACT,
            runner=Host(),
            free_disk_bytes=10 * 1024**3,
            expected_host="tamforge-prod",
        )


def test_install_unpacks_migrates_under_a_lock_then_switches_current_atomically(
    tmp_path: Path,
) -> None:
    host = Host()
    current = install(artifact(tmp_path), CONTRACT, root=tmp_path / "root", runner=host)
    assert current.is_symlink() and current.resolve().name == "20260912T150000Z-abcdef1"
    commands = [" ".join(c) for c in host.calls]
    assert commands[0].startswith("tar -xzf")
    assert (
        commands[1].startswith("flock /run/tamforge/migrate.lock alembic")
        and "tamforge_migrator" in commands[1]
    )
    assert sum("systemctl restart" in c for c in commands) == 5
    with pytest.raises(DeployRefused, match="installed once"):
        install(artifact(tmp_path), CONTRACT, root=tmp_path / "root", runner=host)


def test_a_failed_migration_leaves_current_untouched(tmp_path: Path) -> None:
    first = install(artifact(tmp_path), CONTRACT, root=tmp_path / "root", runner=Host())
    before = first.resolve()

    class MigrationFails(Host):
        def __call__(self, args: list[str]) -> tuple[int, str]:
            if "upgrade" in args:
                return 1, ""
            return super().__call__(args)

    with pytest.raises(DeployRefused, match="migration failed"):
        install(
            artifact(tmp_path, "20260913T150000Z-bbbbbbb"),
            CONTRACT,
            root=tmp_path / "root",
            runner=MigrationFails(),
        )
    assert first.resolve() == before


def test_verify_needs_every_owner_auth_ingest_and_job_endpoint_to_answer() -> None:
    assert verify(lambda path: 200) == {p: 200 for p in verify.__globals__["HEALTH_PATHS"]}
    with pytest.raises(DeployRefused, match="/api/v1/jobs/status"):
        verify(lambda path: 503 if path.endswith("jobs/status") else 200)


def test_rollback_moves_current_back_one_release_and_never_downgrades_the_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    install(artifact(tmp_path, "20260912T150000Z-aaaaaaa"), CONTRACT, root=root, runner=Host())
    install(artifact(tmp_path, "20260913T150000Z-bbbbbbb"), CONTRACT, root=root, runner=Host())
    host = Host()
    target = rollback(CONTRACT, root=root, runner=host)
    assert target.name == "20260912T150000Z-aaaaaaa"
    assert (root / "opt/tamforge/current").resolve() == target.resolve()
    assert not any("alembic" in " ".join(c) for c in host.calls)
    with pytest.raises(DeployRefused, match="no previous release"):
        rollback(CONTRACT, root=root, runner=Host())
