"""The one command that could remove Gastos, built so that by default it cannot.

Retiring the stack is a single, irreversible act on a host that also carries a year of
lead data and every n8n credential. So the default here is a plan: the exact containers,
volumes, files and compose projects that would be touched, printed and then nothing. The
plan is not discovered on the host at run time; it is a fixed allowlist in this file, so
nothing can widen it by matching a glob or reading a directory listing.

Execution needs everything, not most things. The resolved hostname must be the Gastos
host. The archive must verify with its key, and its manifest hash must equal the hash the
restore drill recorded, so the archive that was proven to restore is the archive that
exists. The drill evidence must say the restore succeeded. A separately written approval
artifact must name that same manifest hash and the exact target list, must not have
expired, and must have been written after the drill. And the caller must still say
`--execute`. Any one of those missing, and the command prints why and exits without
having run anything on the host.

Nothing here is a convenience. Rebuilding the host for TAM Forge is a later, separately
gated step; this file only knows how to stop, and only when every record says it may.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Final

from infra.gastos.archive import EXPECTED_HOSTNAME, ArchiveError, require_gastos_host, verify
from infra.gastos.inventory import _CONTROL, HOST

# The complete list of what retirement touches. Fixed here; never read from the host.
TARGETS: Final[dict[str, tuple[str, ...]]] = {
    "compose_projects": (
        "/root/n8n/docker-compose.yml",
        "/root/gapfiller-bridge/docker-compose.yml",
    ),
    "containers": (
        "n8n-n8n-1",
        "n8n-nocodb-1",
        "n8n-caddy-1",
        "n8n-postgres-1",
        "gapfiller-bridge",
    ),
    "volumes": (
        "n8n_pgdata",
        "n8n_n8n_data",
        "n8n_nocodb_data",
        "n8n_caddy_data",
        "n8n_caddy_config",
    ),
    "files": ("/root/n8n", "/root/gapfiller-bridge"),
    "dns": ("homegastos.xyz",),
}

# Names that must never appear in a target list, whatever the approval says.
NEVER_TARGETS: Final[frozenset[str]] = frozenset(
    {"lamas-prod", "lamas", "/", "/root", "/home", "*"}
)

APPROVAL_MAX_AGE_HOURS: Final = 24


class DecommissionRefused(ValueError):
    """A gate that is not satisfied. The host has not been touched."""


def target_digest(targets: dict[str, tuple[str, ...]] = TARGETS) -> str:
    material = json.dumps({k: list(v) for k, v in targets.items()}, sort_keys=True)
    return sha256(material.encode("utf-8")).hexdigest()


def assert_targets_are_exact(targets: dict[str, tuple[str, ...]] = TARGETS) -> None:
    for group, names in targets.items():
        for name in names:
            if name in NEVER_TARGETS or any(ch in name for ch in "*?[") or name.strip() != name:
                raise DecommissionRefused(f"{group}: {name!r} is not an exact, permitted target")
            if not name:
                raise DecommissionRefused(f"{group}: empty target")


@dataclass(frozen=True, slots=True)
class Approval:
    """A separately written record that a person approved retiring this exact archive."""

    archive_manifest_sha256: str
    target_digest: str
    approved_at: datetime
    expires_at: datetime
    approved_by: str

    @classmethod
    def load(cls, path: Path) -> Approval:
        if not path.exists():
            raise DecommissionRefused("no approval artifact")
        body = json.loads(path.read_text(encoding="utf-8"))
        try:
            return cls(
                archive_manifest_sha256=body["archive_manifest_sha256"],
                target_digest=body["target_digest"],
                approved_at=datetime.fromisoformat(body["approved_at"]),
                expires_at=datetime.fromisoformat(body["expires_at"]),
                approved_by=body["approved_by"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DecommissionRefused(f"approval artifact is malformed: {error}") from error


@dataclass(frozen=True, slots=True)
class DrillRecord:
    archive_manifest_sha256: str
    drilled_at: datetime
    restored: bool

    @classmethod
    def load(cls, path: Path) -> DrillRecord:
        if not path.exists():
            raise DecommissionRefused("no restore drill evidence")
        body = json.loads(path.read_text(encoding="utf-8"))
        try:
            restored = (
                body["caddyfile_valid"]
                and body["nocodb"]["integrity"] == "ok"
                and not body["environment"]["keys_missing"]
                and all(d["table_count"] > 0 for d in body["databases"])
                and body["lamas_untouched"]
                and body["host_contacted"] is False
            )
            return cls(
                archive_manifest_sha256=body["archive_manifest_sha256"],
                drilled_at=datetime.strptime(body["drilled_at"], "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=UTC
                ),
                restored=bool(restored),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DecommissionRefused(f"drill evidence is malformed: {error}") from error


@dataclass(frozen=True, slots=True)
class Plan:
    hostname: str
    archive_manifest_sha256: str
    target_digest: str
    targets: dict[str, tuple[str, ...]]
    commands: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"host: {HOST} ({self.hostname})",
            f"archive manifest sha256: {self.archive_manifest_sha256}",
            f"target digest: {self.target_digest}",
            "would touch:",
        ]
        for group, names in self.targets.items():
            for name in names:
                lines.append(f"  {group}: {name}")
        lines.append("would run, in order:")
        lines.extend(f"  {command}" for command in self.commands)
        lines.append("no mutation performed (plan only)")
        return "\n".join(lines) + "\n"


def plan_commands(targets: dict[str, tuple[str, ...]] = TARGETS) -> tuple[str, ...]:
    """The exact host commands execution would run. Composed from the fixed targets only."""
    commands: list[str] = []
    for compose in targets["compose_projects"]:
        commands.append(f"docker compose -f {compose} down")
    for volume in targets["volumes"]:
        commands.append(f"docker volume rm {volume}")
    return tuple(commands)


def run_remote(host: str, command: str) -> str:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", *_CONTROL, host, command],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise DecommissionRefused(f"{command!r} failed: {completed.stderr.strip()[:300]}")
    return completed.stdout


def gate(
    *,
    archive: Path,
    key_path: Path,
    drill_evidence: Path,
    approval_path: Path | None,
    hostname: str,
    execute: bool,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Plan:
    """Every check, in order. Returns the plan; raises DecommissionRefused otherwise."""
    assert_targets_are_exact()
    try:
        require_gastos_host(hostname)
        verify(archive, key_path=key_path)
    except ArchiveError as error:
        raise DecommissionRefused(str(error)) from error
    manifest_sha = sha256((archive / "manifest.json").read_bytes()).hexdigest()
    digest = target_digest()
    plan = Plan(
        hostname=hostname.strip(),
        archive_manifest_sha256=manifest_sha,
        target_digest=digest,
        targets=TARGETS,
        commands=plan_commands(),
    )
    if not execute:
        return plan

    drill = DrillRecord.load(drill_evidence)
    if drill.archive_manifest_sha256 != manifest_sha:
        raise DecommissionRefused(
            "the restore drill proved a different archive than the one present"
        )
    if not drill.restored:
        raise DecommissionRefused("the restore drill did not prove a restore")
    if approval_path is None:
        raise DecommissionRefused("execution needs an approval artifact")
    approval = Approval.load(approval_path)
    if approval.archive_manifest_sha256 != manifest_sha:
        raise DecommissionRefused("the approval names a different archive")
    if approval.target_digest != digest:
        raise DecommissionRefused("the approval names a different target list")
    moment = now()
    if approval.approved_at < drill.drilled_at:
        raise DecommissionRefused("the approval predates the restore drill; approve again")
    if approval.expires_at <= moment:
        raise DecommissionRefused("the approval has expired; approve again")
    if approval.expires_at - approval.approved_at > timedelta(hours=APPROVAL_MAX_AGE_HOURS):
        raise DecommissionRefused(
            f"an approval may not last more than {APPROVAL_MAX_AGE_HOURS} hours"
        )
    return plan


def execute_plan(plan: Plan, *, runner: Callable[[str, str], str] = run_remote) -> tuple[str, ...]:
    """Run the plan's commands on the host, in order, stopping at the first failure."""
    outputs: list[str] = []
    for command in plan.commands:
        outputs.append(runner(HOST, command))
    return tuple(outputs)


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Plan, and only with every gate satisfied execute, the retirement of Gastos."
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--drill-evidence", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument(
        "--execute", action="store_true", help="actually run the plan; every gate must pass"
    )
    args = parser.parse_args(argv)

    hostname = run_remote(HOST, "hostname") if args.execute else EXPECTED_HOSTNAME
    try:
        plan = gate(
            archive=args.archive,
            key_path=args.key,
            drill_evidence=args.drill_evidence,
            approval_path=args.approval,
            hostname=hostname,
            execute=args.execute,
        )
    except DecommissionRefused as error:
        print(f"refused: {error}")
        return 2
    print(plan.render(), end="")
    if not args.execute:
        return 0
    execute_plan(plan)
    print("executed")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
