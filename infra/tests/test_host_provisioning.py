"""Provisioning: contract checked first, target verified second, writes only through the plan."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from infra.host.contract import ContractError, HostContract, load_contract
from infra.host.provision import (
    LAYOUT,
    Checkpoint,
    ProvisionRefused,
    TargetFacts,
    apply,
    assert_plan_is_safe,
    plan,
    read_target,
    rollback,
    verify_target,
)

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "infra" / "config" / "host-layout.env"
FIXTURE = REPO / "infra" / "tests" / "fixtures" / "ubuntu-24.04-host"


class FakeCommands:
    """Answers read-only probes from a table and records every write. Never runs anything."""

    def __init__(
        self, *, satisfied: set[str] | None = None, containers: str = "", arch: str = "x86_64"
    ) -> None:
        self.satisfied = satisfied or set()
        self.containers = containers
        self.arch = arch
        self.writes: list[list[str]] = []
        self.reads: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        joined = " ".join(args)
        if args[:2] == ["uname", "-m"]:
            return 0, self.arch
        if args[:2] == ["docker", "ps"]:
            return 0, self.containers
        is_probe = args[0] in {"dpkg-query", "getent", "test", "grep"} or args[:2] == ["sh", "-c"]
        if is_probe or (args[:3] == ["sudo", "-u", "postgres"] and "-tAc" in args):
            self.reads.append(args)
            return (0, "1") if joined in self.satisfied else (1, "")
        if args[:2] == ["ufw", "status"]:
            self.reads.append(args)
            return 0, "Status: inactive"
        if args[:1] == ["systemd-analyze"] or args[:2] == ["systemctl", "daemon-reload"]:
            self.reads.append(args)
            return 0, ""
        self.writes.append(args)
        return 0, ""


@pytest.fixture
def contract() -> HostContract:
    return load_contract(CONTRACT)


# --- the contract -------------------------------------------------------------------------


def test_the_committed_contract_is_valid_and_names_no_secret(contract: HostContract) -> None:
    text = CONTRACT.read_text()
    assert contract.host_name == "tamforge-prod" and contract.release == "24.04"
    assert "PASSWORD" not in text and "TOKEN" not in text and "KEY=" not in text.replace("_KEY", "")


def test_budgets_plus_the_reserve_fit_the_host(contract: HostContract) -> None:
    assert contract.budget_total_mb + contract.safety_reserve_mb <= contract.ram_mb
    with pytest.raises(ContractError, match="exceed host RAM"):
        replace(contract, safety_reserve_mb=contract.ram_mb).validate()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("release", "22.04", "only Ubuntu 24.04"),
        ("arch", "aarch64", "only x86_64"),
        ("host_name", "lamas-prod", "never be provisioned"),
        ("public_ports", (22, 80, 443, 5432), "exactly SSH"),
        ("service_users", ("root",), "never root"),
        ("safety_reserve_mb", 128, "at least 512"),
    ],
)
def test_a_contract_that_breaks_a_rule_is_refused(
    contract: HostContract, field: str, value: object, reason: str
) -> None:
    with pytest.raises(ContractError, match=reason):
        replace(contract, **{field: value}).validate()  # type: ignore[arg-type]


# --- the target gate ------------------------------------------------------------------------


def test_the_fixture_host_passes_the_gate_and_no_command_wrote_anything(
    contract: HostContract,
) -> None:
    commands = FakeCommands()
    facts = read_target(FIXTURE, commands)
    verify_target(facts, contract)
    assert commands.writes == []


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (TargetFacts("22.04", "x86_64", "tamforge-prod", ()), "Ubuntu '22.04'"),
        (TargetFacts("24.04", "aarch64", "tamforge-prod", ()), "aarch64"),
        (TargetFacts("24.04", "x86_64", "lamas-prod", ()), "Lamas or Gastos"),
        (TargetFacts("24.04", "x86_64", "n8n-prod-gastos", ()), "Lamas or Gastos"),
        (TargetFacts("24.04", "x86_64", "some-box", ()), "contract names"),
        (
            TargetFacts("24.04", "x86_64", "tamforge-prod", ("n8n-n8n-1",)),
            "Gastos workload is still running",
        ),
    ],
)
def test_the_wrong_target_is_refused_before_any_write(
    contract: HostContract, facts: TargetFacts, reason: str
) -> None:
    with pytest.raises(ProvisionRefused, match=reason):
        verify_target(facts, contract)


def test_a_gastos_container_on_the_fixture_root_is_caught(
    contract: HostContract, tmp_path: Path
) -> None:
    shutil.copytree(FIXTURE, tmp_path / "root")
    facts = read_target(tmp_path / "root", FakeCommands(containers="n8n-postgres-1\nn8n-caddy-1"))
    with pytest.raises(ProvisionRefused, match="decommission first"):
        verify_target(facts, contract)


# --- the plan ----------------------------------------------------------------------------


def test_the_plan_is_ordered_pinned_rootless_and_never_opens_a_loopback_port(
    contract: HostContract,
) -> None:
    steps = plan(contract)
    assert_plan_is_safe(steps, contract)
    stages = [s.stage for s in steps]
    assert stages == sorted(
        stages, key=["packages", "identities", "layout", "postgresql", "firewall", "units"].index
    )
    packages = [s for s in steps if s.stage == "packages"]
    assert {s.command[-1] for s in packages} == {
        "postgresql-16",
        "postgresql-16-pgvector",
        "caddy",
        "ufw",
    }
    users = [s.command[-1] for s in steps if s.command[:1] == ("useradd",)]
    assert users == list(contract.service_users) and "root" not in users
    assert all("/usr/sbin/nologin" in s.command for s in steps if s.command[:1] == ("useradd",))
    joined = " ".join(" ".join(s.command) for s in steps)
    assert "listen_addresses '127.0.0.1'" in joined
    assert "allow 5432/tcp" not in joined and "deny 5432/tcp" in joined
    assert "systemd-analyze verify" in joined


def test_ssh_is_allowed_before_the_firewall_is_enabled(contract: HostContract) -> None:
    firewall = [s for s in plan(contract) if s.stage == "firewall"]
    assert firewall[0].command[:2] == ("ufw", "status") and firewall[0].read_only
    assert "22" in firewall[1].command and "allow" in firewall[1].command
    assert firewall[-1].command[-1] == "enable"


def test_every_layout_directory_has_an_exact_owner_and_mode(contract: HostContract) -> None:
    for path, owner, group, mode in LAYOUT:
        assert path.startswith(
            ("/opt/tamforge", "/etc/tamforge", "/var/lib/tamforge", "/var/cache/tamforge")
        )
        assert owner in ("root", *contract.service_users)
        assert mode in {"0700", "0750", "0755", "2770"}
    secrets = next(entry for entry in LAYOUT if entry[0] == "/etc/tamforge/secrets")
    assert secrets[1:] == ("root", "root", "0700")


# --- apply: checkpointed, idempotent, resumable, reversible -----------------------------


def test_apply_writes_every_step_once_and_a_second_apply_changes_nothing(
    contract: HostContract, tmp_path: Path
) -> None:
    steps = plan(contract)
    commands = FakeCommands()
    first = apply(steps, runner=commands, checkpoint_path=tmp_path / "checkpoint.json")
    assert len(first.completed) == len(steps)
    assert len(first.changed) == len([s for s in steps if not s.read_only])
    assert "ufw_status" in first.captured

    satisfied = {" ".join(s.already) for s in steps if s.already}
    again = apply(
        steps, runner=FakeCommands(satisfied=satisfied), checkpoint_path=tmp_path / "second.json"
    )
    assert again.changed == []
    assert len(again.completed) == len(steps)


def test_an_interrupted_apply_resumes_from_its_checkpoint_without_repeating_work(
    contract: HostContract, tmp_path: Path
) -> None:
    steps = plan(contract)
    checkpoint = tmp_path / "checkpoint.json"
    first = FakeCommands()
    partial = apply(steps, runner=first, checkpoint_path=checkpoint, stop_after=5)
    assert len(partial.completed) == 6
    second = FakeCommands()
    resumed = apply(steps, runner=second, checkpoint_path=checkpoint)
    assert len(resumed.completed) == len(steps)
    assert len(first.writes) + len(second.writes) == len(resumed.changed)
    assert all(w not in first.writes for w in second.writes)


def test_a_failing_step_stops_apply_with_the_checkpoint_intact(
    contract: HostContract, tmp_path: Path
) -> None:
    steps = plan(contract)

    class Breaks(FakeCommands):
        def __call__(self, args: list[str]) -> tuple[int, str]:
            if args[:1] == ["groupadd"]:
                return 1, ""
            return super().__call__(args)

    with pytest.raises(ProvisionRefused, match="step failed"):
        apply(steps, runner=Breaks(), checkpoint_path=tmp_path / "checkpoint.json")
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")
    assert all(":install" in key for key in checkpoint.completed)


def test_rollback_disables_units_and_restores_the_firewall_and_removes_nothing(
    contract: HostContract, tmp_path: Path
) -> None:
    steps = plan(contract)
    commands = FakeCommands()
    checkpoint = apply(steps, runner=commands, checkpoint_path=tmp_path / "checkpoint.json")
    undo = FakeCommands()
    ran = rollback(checkpoint, runner=undo)
    joined = " ".join(" ".join(w) for w in undo.writes)
    assert "systemctl disable --now tamforge-api.service" in joined
    assert "ufw --force reset" in joined
    assert (
        "apt-get remove" not in joined
        and "purge" not in joined
        and "userdel" not in joined
        and "rm " not in joined
    )
    assert (
        "dropdb" not in joined and "gastos" not in joined.lower() and "lamas" not in joined.lower()
    )
    assert len(ran) == 6
