"""Prove the Gastos archive restores somewhere that is not the host.

An archive that has never been restored is a hope. The drill decrypts a verified archive
into a private directory, brings up a throwaway PostgreSQL 16 container with no network at
all, loads the roles and every database from the dumps, and reads back what came out: the
tables each database has, how many rows the ones that matter hold, how many n8n workflows
exist and how many are active. The NocoDB metadata file is opened as SQLite and integrity
checked, the Caddyfile is validated as text by Caddy itself in another network-less
container, and every variable the compose file references is checked against the restored
environment file by name only.

Isolation is enforced, not assumed. Every Docker invocation goes through one gate that
refuses anything not addressed to a container the drill created (a `gastos-restore-`
name), anything that would attach a network, publish a port, or mount the host's Docker
socket, and any mention of the production or Lamas hosts. The host at Hetzner is never
contacted; the drill has no SSH runner to contact it with.

What comes out is a dated evidence record naming the archive by its manifest hash, so the
decommission gate can later ask "was this exact archive proven to restore" and get a yes
that is tied to bytes rather than to a date.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

from infra.gastos.archive import ArchiveError, Manifest, restore_plaintexts, verify

CONTAINER_PREFIX: Final = "gastos-restore-"
POSTGRES_IMAGE: Final = "postgres:16"
CADDY_IMAGE: Final = "caddy:2"

# Names that must never appear in a drill command: the live stack and Lamas.
FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "n8n-postgres-1",
        "n8n-n8n-1",
        "n8n-nocodb-1",
        "n8n-caddy-1",
        "gapfiller-bridge",
        "n8n_pgdata",
        "n8n_n8n_data",
        "n8n_nocodb_data",
        "n8n_caddy_data",
        "n8n_caddy_config",
        "hetzner-server-2",
        "n8n-prod-gastos",
        "lamas-prod",
        "lamas",
    }
)
FORBIDDEN_FLAGS: Final[tuple[str, ...]] = ("--network=host", "--privileged", "--pid=host")

DATABASES: Final[tuple[str, ...]] = ("n8n", "leadgen")
# Row counts worth recording. Names only; no content leaves the container.
SAMPLED_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "n8n": ("workflow_entity", "credentials_entity", "execution_entity", "user"),
    "leadgen": ("leads", "searches"),
}


class DrillError(ValueError):
    """A drill that could not prove the restore, or that tried to leave its sandbox."""


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=900, check=False
    )


def run_local(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)


def assert_isolated(args: list[str]) -> None:
    """Refuse any Docker command that reaches outside the drill's own sandbox."""
    joined = " ".join(args)
    for name in FORBIDDEN_NAMES:
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", joined):
            raise DrillError(f"command names {name!r}, which the drill must never touch")
    for flag in FORBIDDEN_FLAGS:
        if flag in args:
            raise DrillError(f"command uses {flag}")
    if "-p" in args or "--publish" in args or any(a.startswith("--publish") for a in args):
        raise DrillError("the drill publishes no ports")
    if any("docker.sock" in a for a in args):
        raise DrillError("the drill never mounts the Docker socket")
    verb = args[0] if args else ""
    if verb == "run":
        if "--network" not in args or args[args.index("--network") + 1] != "none":
            raise DrillError("every drill container runs with --network none")
        if "--name" in args and not args[args.index("--name") + 1].startswith(CONTAINER_PREFIX):
            raise DrillError(f"drill containers are named {CONTAINER_PREFIX}*")
    elif verb in {"exec", "rm", "cp", "logs", "inspect"}:
        targets = [a for a in args[1:] if not a.startswith("-")]
        if not targets or not any(t.startswith(CONTAINER_PREFIX) for t in targets):
            raise DrillError(f"{verb} must address a {CONTAINER_PREFIX}* container")
    elif verb not in {"image", "pull", "version"}:
        raise DrillError(f"docker {verb} is not part of the drill")


class Sandbox:
    """Runs Docker commands through the isolation gate and remembers what ran.

    The record is what goes into the evidence, so the throwaway database password
    and the private working directory are redacted before they are remembered.
    """

    def __init__(self, runner: Runner, *, redact: dict[str, str] | None = None) -> None:
        self._runner = runner
        self._redact = redact or {}
        self.commands: list[str] = []

    def __call__(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        argv = list(args)
        assert_isolated(argv)
        rendered = "docker " + " ".join(argv)
        for secret, replacement in self._redact.items():
            rendered = rendered.replace(secret, replacement)
        self.commands.append(rendered)
        completed = self._runner(argv)
        if check and completed.returncode != 0:
            raise DrillError(
                f"docker {' '.join(argv[:3])} failed: {completed.stderr.strip()[:400]}"
            )
        return completed


@dataclass(frozen=True, slots=True)
class DatabaseEvidence:
    name: str
    table_count: int
    row_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class Evidence:
    drilled_at: str
    archive_captured_at: str
    archive_manifest_sha256: str
    postgres_version: str
    container: str
    databases: tuple[DatabaseEvidence, ...]
    roles_restored: int
    workflows_total: int
    workflows_active: int
    nocodb_integrity: str
    nocodb_table_count: int
    caddyfile_valid: bool
    caddyfile_validator: str
    n8n_data_entries: int
    gapfiller_source_entries: int
    env_keys_referenced: int
    env_keys_missing: tuple[str, ...]
    commands: tuple[str, ...]
    lamas_untouched: bool

    def to_json(self) -> str:
        body = {
            "schema_version": 1,
            "drilled_at": self.drilled_at,
            "archive_captured_at": self.archive_captured_at,
            "archive_manifest_sha256": self.archive_manifest_sha256,
            "isolated": True,
            "network": "none",
            "host_contacted": False,
            "lamas_untouched": self.lamas_untouched,
            "postgres_version": self.postgres_version,
            "container": self.container,
            "roles_restored": self.roles_restored,
            "databases": [
                {"name": d.name, "table_count": d.table_count, "row_counts": d.row_counts}
                for d in self.databases
            ],
            "n8n": {
                "workflows_total": self.workflows_total,
                "workflows_active": self.workflows_active,
            },
            "nocodb": {"integrity": self.nocodb_integrity, "table_count": self.nocodb_table_count},
            "caddyfile_valid": self.caddyfile_valid,
            "caddyfile_validator": self.caddyfile_validator,
            "files": {
                "n8n_data_entries": self.n8n_data_entries,
                "gapfiller_source_entries": self.gapfiller_source_entries,
            },
            "environment": {
                "keys_referenced": self.env_keys_referenced,
                "keys_missing": list(self.env_keys_missing),
            },
            "commands": list(self.commands),
        }
        return json.dumps(body, indent=2, sort_keys=True) + "\n"

    @property
    def restored(self) -> bool:
        return (
            self.caddyfile_valid
            and self.nocodb_integrity == "ok"
            and not self.env_keys_missing
            and all(d.table_count > 0 for d in self.databases)
            and self.lamas_untouched
        )


def _wait_ready(
    docker: Sandbox, container: str, *, sleep: Callable[[float], None], attempts: int = 60
) -> None:
    for _ in range(attempts):
        if docker("exec", container, "pg_isready", "-U", "postgres", check=False).returncode == 0:
            return
        sleep(1)
    raise DrillError("PostgreSQL never became ready inside the drill container")


def _psql(docker: Sandbox, container: str, database: str, sql: str) -> str:
    return docker(
        "exec", container, "psql", "-U", "postgres", "-d", database, "-At", "-c", sql
    ).stdout.strip()


def _sqlite_check(tar_path: Path, member: str, workdir: Path) -> tuple[str, int]:
    with tarfile.open(tar_path) as archive:
        extracted = archive.extractfile(member)
        if extracted is None:
            raise DrillError(f"{tar_path.name} has no {member}")
        target = workdir / "noco.db"
        target.write_bytes(extracted.read())
    connection = sqlite3.connect(target)
    try:
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        tables = connection.execute(
            "select count(*) from sqlite_master where type='table'"
        ).fetchone()[0]
    finally:
        connection.close()
    return str(integrity), int(tables)


def _validate_caddyfile(
    docker: Sandbox, caddyfile: Path, *, local_runner: Runner
) -> tuple[bool, str]:
    """Let Caddy itself judge the file, in a network-less container when the image is
    present locally, otherwise with a local `caddy` binary. Neither starts a server."""
    if docker("image", "inspect", CADDY_IMAGE, check=False).returncode == 0:
        result = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{caddyfile}:/etc/caddy/Caddyfile:ro",
            CADDY_IMAGE,
            "caddy",
            "validate",
            "--adapter",
            "caddyfile",
            "--config",
            "/etc/caddy/Caddyfile",
            check=False,
        )
        return result.returncode == 0, f"docker {CADDY_IMAGE}"
    binary = shutil.which("caddy")
    if binary is None:
        return False, "unavailable"
    result = local_runner(
        [binary, "validate", "--adapter", "caddyfile", "--config", str(caddyfile)]
    )
    return result.returncode == 0, f"local {Path(binary).name}"


def _tar_entries(path: Path) -> int:
    with tarfile.open(path) as archive:
        return sum(1 for _ in archive)


def _env_coverage(compose: str, env: str) -> tuple[int, tuple[str, ...]]:
    referenced = set(re.findall(r"\$\{([A-Z0-9_]+)\}", compose))
    present = {
        line.split("=", 1)[0]
        for line in env.splitlines()
        if "=" in line and not line.startswith("#")
    }
    return len(referenced), tuple(sorted(referenced - present))


def drill(
    archive: Path,
    *,
    key_path: Path,
    runner: Runner = run_docker,
    local_runner: Runner = run_local,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> Evidence:
    """Restore into an isolated container, read back what came out, tear it all down."""
    manifest: Manifest = verify(archive, key_path=key_path)
    manifest_sha = sha256((archive / "manifest.json").read_bytes()).hexdigest()
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    container = f"{CONTAINER_PREFIX}pg-{stamp}"
    password = secrets.token_hex(16)

    with tempfile.TemporaryDirectory(prefix="gastos-drill-") as tmp:
        workdir = Path(tmp)
        os.chmod(workdir, 0o700)
        plain = workdir / "plain"
        docker = Sandbox(runner, redact={password: "<redacted>", str(workdir): "<workdir>"})
        restore_plaintexts(archive, key_path=key_path, into=plain)
        try:
            docker(
                "run",
                "-d",
                "--network",
                "none",
                "--name",
                container,
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-v",
                f"{plain / 'postgres'}:/restore:ro",
                POSTGRES_IMAGE,
            )
            _wait_ready(docker, container, sleep=sleep)
            version = _psql(docker, container, "postgres", "show server_version")
            docker("exec", container, "psql", "-U", "postgres", "-q", "-f", "/restore/globals.sql")
            roles = int(
                _psql(
                    docker,
                    container,
                    "postgres",
                    "select count(*) from pg_roles where rolname not like 'pg_%'",
                )
            )
            databases: list[DatabaseEvidence] = []
            for name in DATABASES:
                docker("exec", container, "createdb", "-U", "postgres", name)
                docker(
                    "exec",
                    container,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "-d",
                    name,
                    "--no-owner",
                    f"/restore/{name}.dump",
                )
                table_count = int(
                    _psql(
                        docker,
                        container,
                        name,
                        "select count(*) from information_schema.tables"
                        " where table_schema='public'",
                    )
                )
                counts: dict[str, int] = {}
                for table in SAMPLED_TABLES.get(name, ()):
                    counts[table] = int(
                        _psql(docker, container, name, f'select count(*) from "{table}"')
                    )
                databases.append(
                    DatabaseEvidence(name=name, table_count=table_count, row_counts=counts)
                )
            workflows_total = int(
                _psql(docker, container, "n8n", "select count(*) from workflow_entity")
            )
            workflows_active = int(
                _psql(docker, container, "n8n", "select count(*) from workflow_entity where active")
            )
        finally:
            docker("rm", "-f", container, check=False)

        caddyfile = plain / "config" / "n8n" / "Caddyfile"
        caddy_valid, caddy_validator = _validate_caddyfile(
            docker, caddyfile, local_runner=local_runner
        )
        integrity, nocodb_tables = _sqlite_check(
            plain / "volumes" / "n8n_nocodb_data.tar", "./noco.db", workdir
        )
        referenced, missing = _env_coverage(
            (plain / "config" / "n8n" / "docker-compose.yml").read_text(encoding="utf-8"),
            (plain / "config" / "n8n" / ".env").read_text(encoding="utf-8"),
        )
        evidence = Evidence(
            drilled_at=stamp,
            archive_captured_at=manifest.captured_at,
            archive_manifest_sha256=manifest_sha,
            postgres_version=version,
            container=container,
            databases=tuple(databases),
            roles_restored=roles,
            workflows_total=workflows_total,
            workflows_active=workflows_active,
            nocodb_integrity=integrity,
            nocodb_table_count=nocodb_tables,
            caddyfile_valid=caddy_valid,
            caddyfile_validator=caddy_validator,
            n8n_data_entries=_tar_entries(plain / "volumes" / "n8n_n8n_data.tar"),
            gapfiller_source_entries=_tar_entries(
                plain / "config" / "gapfiller-bridge" / "source.tar"
            ),
            env_keys_referenced=referenced,
            env_keys_missing=missing,
            commands=tuple(docker.commands),
            lamas_untouched=not any("lamas" in c for c in docker.commands),
        )
    return evidence


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Isolated restore drill for a Gastos archive.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = drill(args.archive, key_path=args.key)
    except ArchiveError as error:
        print(f"archive refused: {error}")
        return 2
    args.evidence_out.write_text(evidence.to_json(), encoding="utf-8")
    summary = f"{len(evidence.databases)} databases, {evidence.workflows_total} workflows"
    print(f"restored: {evidence.restored} ({summary})")
    return 0 if evidence.restored else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
