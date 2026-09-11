"""The inventory reads and only reads, and can prove it about itself."""

from __future__ import annotations

import json

import pytest

from infra.gastos.inventory import (
    COMMANDS,
    READ_ONLY_EXECS,
    STATE_KEYS,
    assert_read_only,
    collect,
    render,
    state_digest,
)

FAKE = {
    "hostname": "n8n-prod-gastos",
    "containers": "n8n-n8n-1\tn8nio/n8n:1.60\tUp 3 days",
    "images": "n8nio/n8n:1.60\tsha256:abc",
    "volumes": "n8n_data\tlocal",
    "networks": "n8n_default\tbridge",
}


class FakeRunner:
    """A runner that records every script it was asked to execute."""

    def __init__(self, stable: bool = True) -> None:
        self.stable = stable
        self.calls: list[str] = []

    def __call__(self, host: str, script: str) -> str:
        self.calls.append(script)
        out = []
        for key in COMMANDS:
            if f"=== {key}" in script:
                value = FAKE.get(key, "")
                if not self.stable and key == "containers" and len(self.calls) == 3:
                    value = "n8n-n8n-1\tn8nio/n8n:1.60\tExited"
                out.append(f"=== {key}\n{value}")
        return "\n".join(out) + "\n"


def fake_runner(stable: bool = True) -> FakeRunner:
    return FakeRunner(stable)


def test_every_command_is_read_only_by_construction() -> None:
    assert_read_only(COMMANDS)


@pytest.mark.parametrize(
    "bad",
    [
        "docker compose down",
        "apt-get install curl",
        "systemctl restart docker",
        "echo hi > /etc/motd",
        "rm -rf /var/lib/docker",
        "docker restart n8n-n8n-1",
    ],
)
def test_a_command_that_could_write_is_refused_before_anything_runs(bad: str) -> None:
    with pytest.raises(ValueError, match="not read-only"):
        assert_read_only({**COMMANDS, "sneaky": bad})


def test_the_only_exec_into_a_container_is_the_allowlisted_catalogue_query() -> None:
    execs = {key for key, command in COMMANDS.items() if "docker exec" in command}
    assert execs == READ_ONLY_EXECS == {"postgres_databases"}
    assert "select" in COMMANDS["postgres_databases"].lower()

    with pytest.raises(ValueError, match="not allowlisted"):
        assert_read_only({**COMMANDS, "other": "docker exec n8n-n8n-1 ls"})


def test_the_inventory_runs_in_one_session_so_the_agent_prompts_once() -> None:
    runner = fake_runner()
    inventory = collect("fake-host", runner=runner)

    # before-state, full inventory, after-state: three calls, not fourteen.
    assert len(runner.calls) == 3
    assert inventory.host == "fake-host"
    assert inventory.results["hostname"] == "n8n-prod-gastos"


def test_an_unchanged_host_confirms_no_mutation() -> None:
    inventory = collect("fake-host", runner=fake_runner(stable=True))

    assert inventory.unchanged is True
    assert inventory.state_before_sha256 == inventory.state_after_sha256


def test_a_host_that_changed_under_the_inventory_says_so() -> None:
    inventory = collect("fake-host", runner=fake_runner(stable=False))

    assert inventory.unchanged is False


def test_the_state_digest_covers_what_a_mutation_would_touch() -> None:
    assert set(STATE_KEYS) == {"containers", "images", "volumes", "networks"}
    assert state_digest(FAKE) != state_digest({**FAKE, "volumes": ""})


def test_the_artifact_is_timestamped_and_carries_its_own_command_list() -> None:
    inventory = collect("fake-host", runner=fake_runner())
    document = json.loads(render(inventory))

    assert document["captured_at"].endswith("+00:00")
    assert document["read_only"] is True
    assert document["no_mutation_confirmed"] is True
    assert document["commands"] == COMMANDS
    assert "hostname" in document["results"]
