"""Releases are immutable, verified before they are current, and rolled back by pointer.

A release is a checksummed artifact unpacked into its own directory under the releases
root. Preflight checks the host manifest, the artifact's checksum against the one recorded
for the release, that Alembic has a single head, and that disk and the database answer,
all through injected probes so the same logic runs against fakes here and the host there.
Install unpacks, migrates once under a lock with the migration role, and then switches the
`current` link atomically. Verify asks the service for its owner, auth, ingest and job
endpoints. Rollback moves `current` back to the previous compatible release and restarts;
it never downgrades the database, because a schema that is behind the code is a bug and a
schema that is ahead of it is data, and data is never rolled back automatically.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final

from .contract import HostContract

Runner = Callable[[list[str]], tuple[int, str]]
Prober = Callable[[str], int]
"""HTTP GET of a path on the loopback service, returns the status code."""

RELEASE_ID_PATTERN: Final = r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$"
HEALTH_PATHS: Final[tuple[str, ...]] = (
    "/healthz",
    "/readyz",
    "/api/v1/auth/session",
    "/api/v1/recordings/status",
    "/api/v1/jobs/status",
)


class DeployRefused(ValueError):
    """A release that must not become current, or a rollback that has nowhere to go."""


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    release_id: str
    path: Path
    expected_sha256: str

    def verify_checksum(self) -> None:
        if not self.path.exists():
            raise DeployRefused("artifact is missing")
        actual = sha256(self.path.read_bytes()).hexdigest()
        if actual != self.expected_sha256:
            raise DeployRefused("artifact checksum does not match the recorded release")


def preflight(
    artifact: ReleaseArtifact,
    contract: HostContract,
    *,
    runner: Runner,
    free_disk_bytes: int,
    expected_host: str,
) -> None:
    import re

    if not re.fullmatch(RELEASE_ID_PATTERN, artifact.release_id):
        raise DeployRefused("release id is not <stamp>-<commit>")
    if expected_host != contract.host_name:
        raise DeployRefused("release is bound to a different host")
    artifact.verify_checksum()
    if free_disk_bytes < 2 * 1024**3:
        raise DeployRefused("less than 2 GiB free; refusing to install")
    code, heads = runner(["alembic", "heads"])
    if code != 0 or len([h for h in heads.splitlines() if h.strip()]) != 1:
        raise DeployRefused("Alembic must have exactly one head")
    code, _ = runner(["pg_isready", "-h", "127.0.0.1"])
    if code != 0:
        raise DeployRefused("PostgreSQL is not answering on loopback")


def install(
    artifact: ReleaseArtifact,
    contract: HostContract,
    *,
    root: Path,
    runner: Runner,
) -> Path:
    """Unpack into its own directory, migrate once, then switch `current` atomically."""
    releases = root / contract.releases_dir.lstrip("/")
    target = releases / artifact.release_id
    if target.exists():
        raise DeployRefused("a release is installed once; pick a new release id")
    target.mkdir(parents=True)
    code, _ = runner(["tar", "-xzf", str(artifact.path), "-C", str(target)])
    if code != 0:
        raise DeployRefused("artifact could not be unpacked")
    code, _ = runner(
        [
            "flock",
            "/run/tamforge/migrate.lock",
            "alembic",
            "-x",
            "role=tamforge_migrator",
            "upgrade",
            "head",
        ]
    )
    if code != 0:
        raise DeployRefused("migration failed; current release untouched")
    current = root / contract.current_link.lstrip("/")
    current.parent.mkdir(parents=True, exist_ok=True)
    temp = current.with_name(current.name + ".next")
    if temp.exists() or temp.is_symlink():
        temp.unlink()
    os.symlink(target, temp)
    os.replace(temp, current)
    for unit in (
        "tamforge-api",
        "tamforge-worker",
        "tamforge-speech-worker",
        "tamforge-claude-worker",
        "tamforge-embedding-worker",
    ):
        runner(["systemctl", "restart", f"{unit}.service"])
    return current


def verify(prober: Prober) -> dict[str, int]:
    """Every owner, auth, ingest and job endpoint must answer; a 5xx anywhere fails."""
    results = {path: prober(path) for path in HEALTH_PATHS}
    bad = {p: c for p, c in results.items() if c >= 500 or c == 0}
    if bad:
        raise DeployRefused(f"release failed verification: {sorted(bad)}")
    return results


def rollback(contract: HostContract, *, root: Path, runner: Runner) -> Path:
    """Point `current` at the previous release. The database is never downgraded."""
    releases = root / contract.releases_dir.lstrip("/")
    current = root / contract.current_link.lstrip("/")
    installed = sorted(p for p in releases.iterdir() if p.is_dir())
    if not current.is_symlink():
        raise DeployRefused("no current release to roll back from")
    current_target = current.resolve()
    previous = [p for p in installed if p.resolve() < current_target]
    if not previous:
        raise DeployRefused("no previous release to roll back to")
    target = previous[-1]
    temp = current.with_name(current.name + ".next")
    if temp.exists() or temp.is_symlink():
        temp.unlink()
    os.symlink(target, temp)
    os.replace(temp, current)
    for unit in (
        "tamforge-api",
        "tamforge-worker",
        "tamforge-speech-worker",
        "tamforge-claude-worker",
        "tamforge-embedding-worker",
    ):
        runner(["systemctl", "restart", f"{unit}.service"])
    return target


__all__ = [
    "HEALTH_PATHS",
    "DeployRefused",
    "ReleaseArtifact",
    "install",
    "preflight",
    "rollback",
    "verify",
]
