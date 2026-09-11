"""Every unit runs a named service user with a budget, hardening, and its own credentials only."""

from __future__ import annotations

from pathlib import Path

import pytest

from infra.host.contract import load_contract

REPO = Path(__file__).resolve().parents[2]
UNITS = sorted((REPO / "infra" / "systemd").glob("tamforge-*.service"))
CONTRACT = load_contract(REPO / "infra" / "config" / "host-layout.env")


def parse(path: Path) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith(("#", "[")):
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), []).append(value.strip())
    return values


def test_there_are_exactly_five_application_units() -> None:
    assert [u.name for u in UNITS] == [
        "tamforge-api.service",
        "tamforge-claude-worker.service",
        "tamforge-embedding-worker.service",
        "tamforge-speech-worker.service",
        "tamforge-worker.service",
    ]


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.stem)
def test_no_unit_runs_as_root_and_every_unit_is_hardened(unit: Path) -> None:
    values = parse(unit)
    assert values["User"][0] in CONTRACT.service_users and values["User"][0] != "root"
    assert values["Group"] == ["tamforge"]
    for directive, expected in {
        "NoNewPrivileges": "yes",
        "PrivateTmp": "yes",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "RestrictSUIDSGID": "yes",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }.items():
        assert values[directive] == [expected], directive
    assert values["ReadWritePaths"] == ["/var/lib/tamforge/shared"]
    assert values["RuntimeDirectoryMode"] == ["0750"]


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.stem)
def test_every_unit_has_a_memory_budget_from_the_contract_and_bounded_restarts(unit: Path) -> None:
    values = parse(unit)
    service = unit.stem.replace("tamforge-", "").replace("-worker", "") or "worker"
    service = {
        "api": "api",
        "worker": "worker",
        "speech": "speech",
        "claude": "claude",
        "embedding": "embedding",
    }[service]
    assert values["MemoryMax"] == [f"{CONTRACT.budgets_mb[service]}M"]
    assert int(values["MemoryHigh"][0].rstrip("M")) < CONTRACT.budgets_mb[service]
    assert values["TasksMax"] == ["256"] and values["LimitNOFILE"] == ["4096"]
    assert values["Restart"] == ["on-failure"] and int(values["StartLimitBurst"][0]) <= 5
    assert values["LogRateLimitIntervalSec"] and values["SyslogIdentifier"] == [unit.stem]


def test_the_total_of_unit_budgets_leaves_the_contract_reserve() -> None:
    total = sum(int(parse(u)["MemoryMax"][0].rstrip("M")) for u in UNITS)
    assert total == CONTRACT.budget_total_mb
    assert total + CONTRACT.safety_reserve_mb <= CONTRACT.ram_mb


def test_units_wait_for_postgresql_but_never_require_claude_or_speech() -> None:
    for unit in UNITS:
        values = parse(unit)
        assert "postgresql.service" in values["After"][0]
        assert "Requires" not in values


def test_credentials_are_per_service_and_never_shared() -> None:
    creds = {u.stem: set(parse(u).get("LoadCredential", [])) for u in UNITS}
    private_export = "export-signing-private.json:/etc/tamforge/secrets/export-signing-private.json"
    keyring = (
        "recording-manifest-keyring.json:/etc/tamforge/secrets/recording-manifest-keyring.json"
    )
    token = "claude-token:/etc/tamforge/secrets/claude-token"
    assert [u for u, c in creds.items() if private_export in c] == ["tamforge-worker"]
    assert [u for u, c in creds.items() if keyring in c] == ["tamforge-speech-worker"]
    assert [u for u, c in creds.items() if token in c] == ["tamforge-claude-worker"]
    public = "export-signing-public.json:/etc/tamforge/trust/export-signing-public.json"
    assert {u for u, c in creds.items() if public in c} == {"tamforge-api", "tamforge-worker"}


def test_the_general_worker_runs_the_general_entrypoint_from_the_immutable_release() -> None:
    values = parse(REPO / "infra" / "systemd" / "tamforge-worker.service")
    assert values["ExecStart"] == [
        "/opt/tamforge/current/.venv/bin/python -m tamforge_backend.workers.general"
    ]
    assert values["WorkingDirectory"] == ["/opt/tamforge/current"]


def test_the_api_binds_to_loopback_only() -> None:
    values = parse(REPO / "infra" / "systemd" / "tamforge-api.service")
    assert "--host 127.0.0.1" in values["ExecStart"][0]


def test_the_caddyfile_terminates_tls_proxies_loopback_and_hides_operational_routes() -> None:
    text = (REPO / "infra" / "caddy" / "Caddyfile").read_text()
    assert f"\n{CONTRACT.app_hostname} {{" in text
    assert text.count("reverse_proxy") >= 2 and "127.0.0.1:8000" in text
    assert "0.0.0.0" not in text and "admin off" in text
    assert "respond @operational 404" in text
    assert "Strict-Transport-Security" in text and "header_up -Cookie" in text
    assert "Authorization delete" in text and "X-Amz-Signature" in text
