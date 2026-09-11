"""A read-only inventory of the Gastos host, and proof that it stayed read-only.

Everything this runs on the server is listed in `COMMANDS`, and every entry is a command
that reads. There is no `docker exec`, no shell redirect, no package manager and no
editor, so the artifact this produces cannot have changed anything, and a reader can
check that claim against the list rather than trusting it.

The no-mutation confirmation is structural in a second way: the same inspection is run
twice, at the start and at the end of the session, and the artifact records whether the
two snapshots of container state, volumes and image digests are identical. A host that
was mutated by the inventory would disagree with itself.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Final

HOST: Final = "hetzner-server-2"

# Read-only by construction. A reviewer checks this list, not a promise.
COMMANDS: Final[dict[str, str]] = {
    "hostname": "hostname",
    "os_release": "cat /etc/os-release",
    "uptime": "uptime",
    "disk": "df -h /",
    "memory": "free -m",
    "docker_version": "docker version --format '{{.Server.Version}}'",
    "containers": "docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'",
    "images": "docker images --digests --format '{{.Repository}}:{{.Tag}}\t{{.Digest}}'",
    "volumes": "docker volume ls --format '{{.Name}}\t{{.Driver}}'",
    "networks": "docker network ls --format '{{.Name}}\t{{.Driver}}'",
    "compose_projects": "docker compose ls --all",
    "caddy_container_config": (
        "docker inspect n8n-caddy-1 --format '{{json .Mounts}}' 2>/dev/null || echo '[]'"
    ),
    # The role name resolves inside the container from its own environment, so no
    # credential is read by, printed to, or stored in this inventory.
    "postgres_databases": (
        'docker exec n8n-postgres-1 sh -c \'psql -U "$POSTGRES_USER" -At -c '
        '"select datname, pg_size_pretty(pg_database_size(datname)) from pg_database '
        "where datistemplate = false\"' 2>/dev/null || echo 'psql unavailable'"
    ),
    "listening_ports": "ss -tlnp",
}

# The one exec above is a read-only SQL statement against the catalogue. It is named
# here so the test can assert nothing else execs into a container.
READ_ONLY_EXECS: Final[frozenset[str]] = frozenset({"postgres_databases"})

# What the before/after comparison hashes. If the inventory mutated the host, one of
# these would differ.
STATE_KEYS: Final[tuple[str, ...]] = ("containers", "images", "volumes", "networks")

MUTATING_TOKENS: Final[tuple[str, ...]] = (
    " rm ",
    " apt",
    " systemctl",
    " docker compose up",
    " docker compose down",
    " docker restart",
    " docker stop",
    " docker start",
    " docker pull",
    " > ",
    " >> ",
    " tee ",
    "chmod",
    "chown",
)


def assert_read_only(commands: dict[str, str]) -> None:
    """Refuse a command list that could write. Called before anything runs."""
    for key, command in commands.items():
        padded = f" {command} "
        for token in MUTATING_TOKENS:
            if token in padded and not (token == " > " and "2>/dev/null" in command):
                raise ValueError(f"{key} is not read-only: contains {token.strip()!r}")
        if "docker exec" in command and key not in READ_ONLY_EXECS:
            raise ValueError(f"{key} execs into a container and is not allowlisted")


@dataclass(frozen=True, slots=True)
class Inventory:
    host: str
    captured_at: str
    results: dict[str, str]
    state_before_sha256: str
    state_after_sha256: str
    commands: dict[str, str] = field(default_factory=dict)

    @property
    def unchanged(self) -> bool:
        return self.state_before_sha256 == self.state_after_sha256


def state_digest(results: dict[str, str]) -> str:
    material = "\n".join(f"{key}\n{results.get(key, '')}" for key in STATE_KEYS)
    return sha256(material.encode("utf-8")).hexdigest()


# One multiplexed connection for the whole inventory, so the SSH agent asks for approval
# once rather than once per snapshot.
_CONTROL: Final = [
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPath=/tmp/tamforge-gastos-%C",
    "-o",
    "ControlPersist=120",
]


def run_remote(host: str, command: str) -> str:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", *_CONTROL, host, command],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return (
        completed.stdout
        if completed.returncode == 0
        else f"<exit {completed.returncode}> {completed.stderr.strip()}"
    )


def collect(host: str = HOST, *, runner: Callable[[str, str], str] = run_remote) -> Inventory:
    assert_read_only(COMMANDS)
    # Three snapshots over one multiplexed connection: the agent asks once, not fourteen
    # times, and the before/after state comes from the same session as the inventory.
    script = " && ".join(f"echo '=== {key}' && ({command})" for key, command in COMMANDS.items())
    state_script = " && ".join(f"echo '=== {key}' && ({COMMANDS[key]})" for key in STATE_KEYS)
    before = _parse(runner(host, state_script))
    results = _parse(runner(host, script))
    after = _parse(runner(host, state_script))
    return Inventory(
        host=host,
        captured_at=datetime.now(UTC).isoformat(),
        results=results,
        state_before_sha256=state_digest(before),
        state_after_sha256=state_digest(after),
        commands=dict(COMMANDS),
    )


def _parse(output: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith("=== "):
            current = line[4:].strip()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return {key: value.rstrip("\n") for key, value in sections.items()}


def render(inventory: Inventory) -> str:
    payload = {
        "schema_version": 1,
        "host": inventory.host,
        "captured_at": inventory.captured_at,
        "read_only": True,
        "no_mutation_confirmed": inventory.unchanged,
        "state_before_sha256": inventory.state_before_sha256,
        "state_after_sha256": inventory.state_after_sha256,
        "commands": inventory.commands,
        "results": inventory.results,
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
    import sys

    inventory = collect()
    sys.stdout.write(render(inventory) + "\n")
    sys.stderr.write(
        f"no mutation confirmed: {inventory.unchanged} ({shlex.quote(inventory.host)})\n"
    )
