"""Retiring Gastos: a plan by default, and execution only when every record agrees."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from infra.gastos.archive import EXPECTED_HOSTNAME, create
from infra.gastos.decommission import (
    NEVER_TARGETS,
    TARGETS,
    DecommissionRefused,
    Plan,
    assert_targets_are_exact,
    execute_plan,
    gate,
    plan_commands,
    target_digest,
)

ARCHIVED = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
DRILLED = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 11, 3, 0, tzinfo=UTC)


class FakeHost:
    def __call__(self, host: str, command: str) -> bytes:
        if command == "hostname":
            return f"{EXPECTED_HOSTNAME}\n".encode()
        return f"payload for {command}".encode()


@pytest.fixture
def records(tmp_path: Path) -> dict[str, Path]:
    archive = tmp_path / "archive"
    key = tmp_path / "gastos.key"
    create(archive, key_path=key, runner=FakeHost(), now=lambda: ARCHIVED)
    manifest_sha = sha256((archive / "manifest.json").read_bytes()).hexdigest()
    drill = tmp_path / "drill.json"
    drill.write_text(
        json.dumps(
            {
                "archive_manifest_sha256": manifest_sha,
                "drilled_at": DRILLED.strftime("%Y%m%dT%H%M%SZ"),
                "caddyfile_valid": True,
                "nocodb": {"integrity": "ok"},
                "environment": {"keys_missing": []},
                "databases": [{"table_count": 51}, {"table_count": 2}],
                "lamas_untouched": True,
                "host_contacted": False,
            }
        )
    )
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "archive_manifest_sha256": manifest_sha,
                "target_digest": target_digest(),
                "approved_at": (NOW - timedelta(minutes=10)).isoformat(),
                "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                "approved_by": "frank",
            }
        )
    )
    return {"archive": archive, "key": key, "drill": drill, "approval": approval, "root": tmp_path}


def run_gate(records: dict[str, Path], **overrides: object) -> Plan:
    kwargs: dict[str, object] = {
        "archive": records["archive"],
        "key_path": records["key"],
        "drill_evidence": records["drill"],
        "approval_path": records["approval"],
        "hostname": EXPECTED_HOSTNAME,
        "execute": True,
        "now": lambda: NOW,
    }
    kwargs.update(overrides)
    return gate(**kwargs)  # type: ignore[arg-type]


def rewrite(path: Path, **changes: object) -> None:
    body = json.loads(path.read_text())
    body.update(changes)
    path.write_text(json.dumps(body))


# --- the plan is fixed and exact ---------------------------------------------------------


def test_targets_are_exact_names_and_never_globs_or_roots() -> None:
    assert_targets_are_exact()
    for group, names in TARGETS.items():
        for name in names:
            assert "*" not in name and name not in NEVER_TARGETS
    with pytest.raises(DecommissionRefused):
        assert_targets_are_exact({"files": ("/root/n8n/*",)})
    with pytest.raises(DecommissionRefused):
        assert_targets_are_exact({"files": ("/",)})
    with pytest.raises(DecommissionRefused):
        assert_targets_are_exact({"containers": ("lamas-prod",)})


def test_the_plan_commands_come_only_from_the_fixed_targets() -> None:
    commands = plan_commands()
    assert all(
        c.startswith(("docker compose -f /root/", "docker volume rm n8n_")) for c in commands
    )
    assert "lamas" not in " ".join(commands)
    assert len(commands) == len(TARGETS["compose_projects"]) + len(TARGETS["volumes"])


def test_the_target_digest_changes_when_the_list_changes() -> None:
    assert target_digest() != target_digest({**TARGETS, "dns": ()})


# --- by default nothing happens ----------------------------------------------------------


def test_without_execute_the_gate_returns_a_plan_and_needs_no_evidence(
    records: dict[str, Path],
) -> None:
    plan = run_gate(
        records, execute=False, drill_evidence=records["root"] / "missing.json", approval_path=None
    )
    assert plan.hostname == EXPECTED_HOSTNAME
    assert "no mutation performed (plan only)" in plan.render()
    assert plan.commands == plan_commands()


def test_execution_runs_exactly_the_plan_in_order(records: dict[str, Path]) -> None:
    plan = run_gate(records)
    ran: list[str] = []

    def runner(host: str, command: str) -> str:
        ran.append(f"{host}: {command}")
        return "ok"

    execute_plan(plan, runner=runner)
    assert ran == [f"hetzner-server-2: {c}" for c in plan_commands()]


# --- every gate, and each one alone, refuses ---------------------------------------------


def test_the_wrong_host_is_refused(records: dict[str, Path]) -> None:
    with pytest.raises(DecommissionRefused, match="Lamas"):
        run_gate(records, hostname="lamas-prod")
    with pytest.raises(DecommissionRefused, match="expected host"):
        run_gate(records, hostname="some-new-box")


def test_an_archive_that_does_not_verify_is_refused(records: dict[str, Path]) -> None:
    (records["archive"] / "payloads" / "postgres" / "n8n.dump.enc").unlink()
    with pytest.raises(DecommissionRefused, match="partial"):
        run_gate(records)


def test_missing_drill_evidence_is_refused(records: dict[str, Path]) -> None:
    with pytest.raises(DecommissionRefused, match="no restore drill"):
        run_gate(records, drill_evidence=records["root"] / "nope.json")


def test_a_drill_of_a_different_archive_is_refused(records: dict[str, Path]) -> None:
    rewrite(records["drill"], archive_manifest_sha256="0" * 64)
    with pytest.raises(DecommissionRefused, match="different archive"):
        run_gate(records)


def test_a_drill_that_did_not_restore_is_refused(records: dict[str, Path]) -> None:
    rewrite(records["drill"], caddyfile_valid=False)
    with pytest.raises(DecommissionRefused, match="did not prove"):
        run_gate(records)


def test_a_drill_that_touched_the_host_is_refused(records: dict[str, Path]) -> None:
    rewrite(records["drill"], host_contacted=True)
    with pytest.raises(DecommissionRefused, match="did not prove"):
        run_gate(records)


def test_missing_approval_is_refused(records: dict[str, Path]) -> None:
    with pytest.raises(DecommissionRefused, match="needs an approval"):
        run_gate(records, approval_path=None)
    with pytest.raises(DecommissionRefused, match="no approval"):
        run_gate(records, approval_path=records["root"] / "nope.json")


def test_an_approval_for_another_archive_or_target_list_is_refused(
    records: dict[str, Path],
) -> None:
    rewrite(records["approval"], archive_manifest_sha256="1" * 64)
    with pytest.raises(DecommissionRefused, match="different archive"):
        run_gate(records)
    rewrite(
        records["approval"],
        archive_manifest_sha256=json.loads(records["drill"].read_text())["archive_manifest_sha256"],
        target_digest="2" * 64,
    )
    with pytest.raises(DecommissionRefused, match="different target list"):
        run_gate(records)


def test_an_expired_or_stale_approval_is_refused(records: dict[str, Path]) -> None:
    rewrite(records["approval"], expires_at=(NOW - timedelta(seconds=1)).isoformat())
    with pytest.raises(DecommissionRefused, match="expired"):
        run_gate(records)
    rewrite(
        records["approval"],
        approved_at=(DRILLED - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )
    with pytest.raises(DecommissionRefused, match="predates the restore drill"):
        run_gate(records)


def test_an_approval_cannot_be_open_ended(records: dict[str, Path]) -> None:
    rewrite(records["approval"], expires_at=(NOW + timedelta(days=30)).isoformat())
    with pytest.raises(DecommissionRefused, match="more than 24 hours"):
        run_gate(records)


def test_a_malformed_approval_is_refused_not_guessed(records: dict[str, Path]) -> None:
    records["approval"].write_text(json.dumps({"approved_by": "frank"}))
    with pytest.raises(DecommissionRefused, match="malformed"):
        run_gate(records)
