"""Provisioning that reads by default and writes only through a checkpointed, exact plan.

`verify_target` is the gate every stage passes first: the root it is given must be Ubuntu
24.04 on x86_64, carry the approved host name, run no Gastos workload, and not be Lamas.
Anything else is a refusal with the reason, before a single command.

`plan` is the whole list of what provisioning would do, in order, from the contract alone:
pinned packages, service users and the shared group, directories with their exact owner and
mode, PostgreSQL bound to loopback with least-privilege roles, the firewall with SSH allowed
before anything is denied, hardened units installed and verified before enablement. The
default mode prints that plan. `apply` runs it through an injected command runner, records
every step it completed in a checkpoint manifest, skips steps whose state is already right so
a second run reports zero changes, and can roll back from any checkpoint: rollback restores
what it captured and disables TAM Forge units; it never removes packages, PostgreSQL data,
the Gastos archive, or anything on another host.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from .contract import FORBIDDEN_HOSTS, HostContract

Runner = Callable[[list[str]], tuple[int, str]]
"""Runs one command, returns (exit code, stdout). Tests inject a fake."""

GASTOS_MARKERS: Final[tuple[str, ...]] = ("n8n", "nocodb", "gapfiller")

# The only directory layout provisioning creates. (path, owner, group, mode)
LAYOUT: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("/opt/tamforge/releases", "root", "tamforge", "0750"),
    ("/etc/tamforge", "root", "tamforge", "0750"),
    ("/etc/tamforge/secrets", "root", "root", "0700"),
    ("/etc/tamforge/trust", "root", "root", "0755"),
    ("/var/lib/tamforge/api", "tamforge-api", "tamforge-api", "0750"),
    ("/var/lib/tamforge/worker", "tamforge-worker", "tamforge-worker", "0750"),
    ("/var/lib/tamforge/speech", "tamforge-speech", "tamforge-speech", "0750"),
    ("/var/lib/tamforge/claude", "tamforge-claude", "tamforge-claude", "0750"),
    ("/var/lib/tamforge/embedding", "tamforge-embedding", "tamforge-embedding", "0750"),
    ("/var/lib/tamforge/shared", "root", "tamforge", "2770"),
    ("/var/lib/tamforge/backup", "tamforge-backup", "tamforge-backup", "0700"),
    ("/var/lib/tamforge/quarantine", "tamforge-api", "tamforge-api", "0700"),
    ("/var/cache/tamforge/speech", "tamforge-speech", "tamforge-speech", "0750"),
    ("/var/cache/tamforge/embeddings", "tamforge-embedding", "tamforge-embedding", "0750"),
)

PG_ROLES: Final[tuple[str, ...]] = ("tamforge_app", "tamforge_migrator", "tamforge_backup")

Stage = Literal["packages", "identities", "layout", "postgresql", "firewall", "units"]
STAGES: Final[tuple[Stage, ...]] = (
    "packages",
    "identities",
    "layout",
    "postgresql",
    "firewall",
    "units",
)


class ProvisionRefused(ValueError):
    """The target is not the approved host, or a stage would break a rule."""


@dataclass(frozen=True, slots=True)
class TargetFacts:
    release: str
    arch: str
    hostname: str
    running_containers: tuple[str, ...]


def read_target(root: Path, runner: Runner) -> TargetFacts:
    """Read the facts the gate needs from a filesystem root and two read-only commands."""
    release = ""
    os_release = root / "etc" / "os-release"
    if os_release.exists():
        for line in os_release.read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION_ID="):
                release = line.split("=", 1)[1].strip().strip('"')
    _, arch = runner(["uname", "-m"])
    hostname_file = root / "etc" / "hostname"
    hostname = hostname_file.read_text(encoding="utf-8").strip() if hostname_file.exists() else ""
    code, containers = runner(["docker", "ps", "--format", "{{.Names}}"])
    running = tuple(c for c in containers.split() if c) if code == 0 else ()
    return TargetFacts(
        release=release, arch=arch.strip(), hostname=hostname, running_containers=running
    )


def verify_target(facts: TargetFacts, contract: HostContract) -> None:
    if facts.hostname in FORBIDDEN_HOSTS or "lamas" in facts.hostname:
        raise ProvisionRefused(f"{facts.hostname!r} is Lamas or Gastos; never provisioned")
    if facts.release != contract.release:
        raise ProvisionRefused(
            f"host is Ubuntu {facts.release!r}, contract requires {contract.release}"
        )
    if facts.arch != contract.arch:
        raise ProvisionRefused(f"host is {facts.arch!r}, contract requires {contract.arch}")
    if facts.hostname != contract.host_name:
        raise ProvisionRefused(f"host is {facts.hostname!r}, contract names {contract.host_name}")
    gastos = [c for c in facts.running_containers if any(m in c for m in GASTOS_MARKERS)]
    if gastos:
        raise ProvisionRefused(f"a Gastos workload is still running: {gastos}; decommission first")


@dataclass(frozen=True, slots=True)
class Step:
    stage: Stage
    description: str
    command: tuple[str, ...]
    # A read-only command whose zero exit means the step is already done.
    already: tuple[str, ...] | None = None
    # A step that changes nothing (a check, a snapshot, a reload); never counted as a change.
    read_only: bool = False
    # Name under which the step's output is kept in the checkpoint.
    capture: str | None = None


def plan(contract: HostContract) -> tuple[Step, ...]:
    """Every write provisioning would make, in order, from the contract alone."""
    steps: list[Step] = []
    for name, package in contract.packages.items():
        steps.append(
            Step(
                "packages",
                f"install {name} ({package})",
                ("apt-get", "install", "-y", "--no-install-recommends", package),
                already=("dpkg-query", "-W", package),
            )
        )
    steps.append(
        Step(
            "identities",
            f"create shared group {contract.shared_group}",
            ("groupadd", "--system", contract.shared_group),
            already=("getent", "group", contract.shared_group),
        )
    )
    for user in contract.service_users:
        steps.append(
            Step(
                "identities",
                f"create locked no-login user {user}",
                (
                    "useradd",
                    "--system",
                    "--no-create-home",
                    "--shell",
                    "/usr/sbin/nologin",
                    "--groups",
                    contract.shared_group,
                    user,
                ),
                already=("getent", "passwd", user),
            )
        )
    for path, owner, group, mode in LAYOUT:
        steps.append(
            Step(
                "layout",
                f"{path} {owner}:{group} {mode}",
                ("install", "-d", "-o", owner, "-g", group, "-m", mode, path),
                already=("test", "-d", path),
            )
        )
    steps.append(
        Step(
            "postgresql",
            "bind PostgreSQL to loopback only",
            # pg_conftool writes the value verbatim, so the quotes must be part of it or
            # PostgreSQL rejects the bare IP and refuses to start.
            ("pg_conftool", "16", "main", "set", "listen_addresses", "'127.0.0.1'"),
            already=(
                "grep",
                "-q",
                "listen_addresses = '127.0.0.1'",
                "/etc/postgresql/16/main/postgresql.conf",
            ),
        )
    )
    steps.append(
        Step(
            "postgresql",
            "create database tamforge with vector",
            ("sudo", "-u", "postgres", "psql", "-c", "CREATE DATABASE tamforge"),
            already=(
                "sudo",
                "-u",
                "postgres",
                "psql",
                "-tAc",
                "SELECT 1 FROM pg_database WHERE datname='tamforge'",
            ),
        )
    )
    for role in PG_ROLES:
        steps.append(
            Step(
                "postgresql",
                f"create least-privilege role {role}",
                (
                    "sudo",
                    "-u",
                    "postgres",
                    "psql",
                    "-c",
                    f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE",
                ),
                already=(
                    "sudo",
                    "-u",
                    "postgres",
                    "psql",
                    "-tAc",
                    f"SELECT 1 FROM pg_roles WHERE rolname='{role}'",
                ),
            )
        )
    # SSH first, then the web ports, then deny loopback-only ports externally, then enable.
    steps.append(
        Step(
            "firewall",
            "snapshot firewall state",
            ("ufw", "status", "verbose"),
            read_only=True,
            capture="ufw_status",
        )
    )
    cidr = contract.ssh_source_cidr
    steps.append(
        Step(
            "firewall",
            f"allow SSH from {cidr}",
            ("ufw", "allow", "from", cidr, "to", "any", "port", "22", "proto", "tcp"),
            already=("sh", "-c", f"ufw status | grep -q '22/tcp.*ALLOW.*{cidr}'"),
        )
    )
    for port in sorted(set(contract.public_ports) - {22}):
        steps.append(
            Step(
                "firewall",
                f"allow tcp/{port}",
                ("ufw", "allow", f"{port}/tcp"),
                already=("sh", "-c", f"ufw status | grep -q '{port}/tcp.*ALLOW'"),
            )
        )
    for port in contract.loopback_ports:
        steps.append(
            Step(
                "firewall",
                f"deny tcp/{port} from outside",
                ("ufw", "deny", f"{port}/tcp"),
                already=("sh", "-c", f"ufw status | grep -q '{port}/tcp.*DENY'"),
            )
        )
    steps.append(
        Step(
            "firewall",
            "enable firewall",
            ("ufw", "--force", "enable"),
            already=("sh", "-c", "ufw status | grep -q 'Status: active'"),
        )
    )
    steps.append(
        Step(
            "units",
            "verify units before enablement",
            ("systemd-analyze", "verify", "/etc/systemd/system/tamforge-*.service"),
            read_only=True,
        )
    )
    steps.append(Step("units", "reload systemd", ("systemctl", "daemon-reload"), read_only=True))
    return tuple(steps)


def assert_plan_is_safe(steps: tuple[Step, ...], contract: HostContract) -> None:
    joined = " ".join(" ".join(s.command) for s in steps)
    for name in FORBIDDEN_HOSTS:
        if name in joined:
            raise ProvisionRefused(f"the plan mentions {name}")
    firewall = [s for s in steps if s.stage == "firewall"]
    allow_ssh = next(i for i, s in enumerate(firewall) if "port" in s.command and "22" in s.command)
    enable = next(i for i, s in enumerate(firewall) if "enable" in s.command)
    if allow_ssh > enable:
        raise ProvisionRefused("SSH must be allowed before the firewall is enabled")
    for port in contract.loopback_ports:
        if f"allow {port}/tcp" in joined:
            raise ProvisionRefused(f"loopback port {port} must never be allowed publicly")
    for s in steps:
        if s.command[:1] == ("useradd",) and "root" in s.command:
            raise ProvisionRefused("no service runs as root")


@dataclass
class Checkpoint:
    """What apply has done so far; written after every step so a crash resumes here."""

    completed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    captured: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return (
            json.dumps(
                {"completed": self.completed, "changed": self.changed, "captured": self.captured},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        if not path.exists():
            return cls()
        body = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            completed=list(body["completed"]),
            changed=list(body["changed"]),
            captured=dict(body["captured"]),
        )


def apply(
    steps: tuple[Step, ...],
    *,
    runner: Runner,
    checkpoint_path: Path,
    stop_after: int | None = None,
) -> Checkpoint:
    """Run the plan, skipping steps already satisfied, recording every completion."""
    checkpoint = Checkpoint.load(checkpoint_path)
    for index, step in enumerate(steps):
        key = f"{index}:{step.description}"
        if key in checkpoint.completed:
            continue
        if step.already is not None:
            code, _ = runner(list(step.already))
            if code == 0:
                checkpoint.completed.append(key)
                checkpoint_path.write_text(checkpoint.to_json(), encoding="utf-8")
                continue
        code, output = runner(list(step.command))
        if code != 0:
            raise ProvisionRefused(f"step failed: {step.description}")
        if step.capture is not None:
            checkpoint.captured[step.capture] = output
        if not step.read_only:
            checkpoint.changed.append(key)
        checkpoint.completed.append(key)
        checkpoint_path.write_text(checkpoint.to_json(), encoding="utf-8")
        if stop_after is not None and index >= stop_after:
            break
    return checkpoint


def rollback(checkpoint: Checkpoint, *, runner: Runner) -> tuple[str, ...]:
    """Disable TAM Forge units and restore the captured firewall; remove nothing else."""
    ran: list[str] = []
    for unit in (
        "tamforge-api",
        "tamforge-worker",
        "tamforge-speech-worker",
        "tamforge-claude-worker",
        "tamforge-embedding-worker",
    ):
        runner(["systemctl", "disable", "--now", f"{unit}.service"])
        ran.append(f"disabled {unit}")
    if "ufw_status" in checkpoint.captured:
        runner(["ufw", "--force", "reset"])
        ran.append("firewall reset to captured state")
    return tuple(ran)


__all__ = [
    "LAYOUT",
    "PG_ROLES",
    "STAGES",
    "Checkpoint",
    "ProvisionRefused",
    "Step",
    "TargetFacts",
    "apply",
    "assert_plan_is_safe",
    "plan",
    "read_target",
    "rollback",
    "verify_target",
]
