"""The restore drill: isolated by construction, and evidence tied to the archive's bytes."""

from __future__ import annotations

import subprocess
import tarfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from infra.gastos.archive import EXPECTED_HOSTNAME, ArchiveError, create
from infra.gastos.restore_drill import (
    CONTAINER_PREFIX,
    DrillError,
    Evidence,
    Sandbox,
    assert_isolated,
    drill,
)

ARCHIVED = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)


def tar_bytes(members: dict[str, bytes]) -> bytes:
    import io

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def sqlite_bytes() -> bytes:
    import sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "noco.db"
        connection = sqlite3.connect(path)
        connection.execute("create table nc_bases (id integer primary key)")
        connection.execute("create table nc_tables (id integer primary key)")
        connection.commit()
        connection.close()
        return path.read_bytes()


class FakeHost:
    """A Gastos host whose payloads are small but structurally right."""

    def __call__(self, host: str, command: str) -> bytes:
        if command == "hostname":
            return f"{EXPECTED_HOSTNAME}\n".encode()
        if "nocodb" in command:
            return tar_bytes({"./noco.db": sqlite_bytes()})
        if "n8n_data" in command or "/home/node/.n8n" in command:
            return tar_bytes({"./config": b"{}", "./nodes/package.json": b"{}"})
        if "gapfiller" in command:
            return tar_bytes({"./docker-compose.yml": b"services: {}", "./bridge.py": b"print(1)"})
        if command.endswith("docker-compose.yml"):
            return (
                b"services:\n  n8n:\n    environment:\n"
                b"      N8N_HOST: ${N8N_HOST}\n      KEY: ${N8N_ENCRYPTION_KEY}\n"
            )
        if command.endswith(".env"):
            return b"N8N_HOST=example\nN8N_ENCRYPTION_KEY=s3cr3t-value\n"
        if "Caddyfile" in command:
            return b"example.test {\n  reverse_proxy n8n:5678\n}\n"
        return f"payload for {command}".encode()


class FakeDocker:
    """Answers the drill's Docker commands like a healthy PostgreSQL 16 would."""

    def __init__(self, *, caddy_ok: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.caddy_ok = caddy_ok

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        joined = " ".join(args)
        out = ""
        code = 0
        if args[0] == "run" and "caddy" in joined:
            code = 0 if self.caddy_ok else 1
        elif "show server_version" in joined:
            out = "16.4"
        elif "pg_roles" in joined:
            out = "3"
        elif "information_schema.tables" in joined:
            out = "51" if "-d n8n" in joined else "2"
        elif "where active" in joined:
            out = "4"
        elif "workflow_entity" in joined and "count" in joined:
            out = "12"
        elif "select count(*)" in joined:
            out = "7"
        return subprocess.CompletedProcess(args, code, out, "")


def make_archive(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / "archive"
    key = tmp_path / "keys" / "gastos.key"
    create(archive, key_path=key, runner=FakeHost(), now=lambda: ARCHIVED)
    return archive, key


# --- isolation is a gate, not a convention ------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        ["exec", "n8n-postgres-1", "psql"],
        ["rm", "-f", "n8n-n8n-1"],
        [
            "run",
            "--network",
            "none",
            "--name",
            "gastos-restore-x",
            "-v",
            "n8n_pgdata:/x",
            "postgres:16",
        ],
        ["run", "--name", "gastos-restore-x", "postgres:16"],
        ["run", "--network", "host", "--name", "gastos-restore-x", "postgres:16"],
        ["run", "--network", "none", "--name", "other-pg", "postgres:16"],
        [
            "run",
            "--network",
            "none",
            "--name",
            "gastos-restore-x",
            "-p",
            "5432:5432",
            "postgres:16",
        ],
        [
            "run",
            "--network",
            "none",
            "--name",
            "gastos-restore-x",
            "-v",
            "/var/run/docker.sock:/s",
            "x",
        ],
        ["run", "--network", "none", "--name", "gastos-restore-x", "--privileged", "postgres:16"],
        ["exec", "gastos-restore-x", "ssh", "hetzner-server-2"],
        ["exec", "gastos-restore-x", "echo", "lamas-prod"],
        ["volume", "rm", "gastos-restore-x"],
        ["compose", "down"],
    ],
)
def test_a_command_outside_the_sandbox_is_refused(command: list[str]) -> None:
    with pytest.raises(DrillError):
        assert_isolated(command)


def test_sandbox_commands_are_allowed() -> None:
    assert_isolated(
        ["run", "-d", "--network", "none", "--name", "gastos-restore-pg-1", "postgres:16"]
    )
    assert_isolated(["exec", "gastos-restore-pg-1", "pg_isready", "-U", "postgres"])
    assert_isolated(["rm", "-f", "gastos-restore-pg-1"])


def test_the_sandbox_refuses_before_the_runner_sees_the_command() -> None:
    docker = FakeDocker()
    sandbox = Sandbox(docker)
    with pytest.raises(DrillError):
        sandbox("exec", "n8n-postgres-1", "psql")
    assert docker.calls == []


# --- the drill proves a restore and records it --------------------------------------------


def test_a_drill_restores_every_database_and_reads_back_the_counts(tmp_path: Path) -> None:
    archive, key = make_archive(tmp_path)
    docker = FakeDocker()
    evidence = drill(archive, key_path=key, runner=docker, now=lambda: NOW, sleep=lambda _: None)

    assert evidence.restored is True
    assert evidence.postgres_version == "16.4"
    assert [d.name for d in evidence.databases] == ["n8n", "leadgen"]
    assert evidence.databases[0].row_counts["workflow_entity"] == 12
    assert (evidence.workflows_total, evidence.workflows_active) == (12, 4)
    assert evidence.roles_restored == 3
    assert evidence.nocodb_integrity == "ok" and evidence.nocodb_table_count == 2
    assert evidence.caddyfile_valid is True
    assert evidence.caddyfile_validator == "docker caddy:2"
    assert evidence.env_keys_referenced == 2 and evidence.env_keys_missing == ()
    assert evidence.n8n_data_entries == 2 and evidence.gapfiller_source_entries == 2
    assert evidence.lamas_untouched is True


def test_the_evidence_names_the_archive_by_its_manifest_hash(tmp_path: Path) -> None:
    archive, key = make_archive(tmp_path)
    evidence = drill(
        archive, key_path=key, runner=FakeDocker(), now=lambda: NOW, sleep=lambda _: None
    )

    assert (
        evidence.archive_manifest_sha256
        == sha256((archive / "manifest.json").read_bytes()).hexdigest()
    )
    assert evidence.archive_captured_at == "20260911T010000Z"
    assert evidence.drilled_at == "20260911T020000Z"


def test_every_container_the_drill_started_is_removed_even_when_a_step_fails(
    tmp_path: Path,
) -> None:
    archive, key = make_archive(tmp_path)

    class BrokenRestore(FakeDocker):
        def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
            if args[0] == "exec" and "pg_restore" in args:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 1, "", "pg_restore: error: boom")
            return super().__call__(args)

    docker = BrokenRestore()
    with pytest.raises(DrillError, match="pg_restore"):
        drill(archive, key_path=key, runner=docker, now=lambda: NOW, sleep=lambda _: None)
    started = [c for c in docker.calls if c[0] == "run" and "--name" in c]
    removed = [c for c in docker.calls if c[0] == "rm"]
    assert len(started) == 1 and len(removed) == 1
    assert removed[0][-1] == started[0][started[0].index("--name") + 1]


def test_every_drill_container_has_no_network_and_a_drill_name(tmp_path: Path) -> None:
    archive, key = make_archive(tmp_path)
    docker = FakeDocker()
    drill(archive, key_path=key, runner=docker, now=lambda: NOW, sleep=lambda _: None)
    for call in docker.calls:
        if call[0] == "run":
            assert call[call.index("--network") + 1] == "none"
            if "--name" in call:
                assert call[call.index("--name") + 1].startswith(CONTAINER_PREFIX)


def test_an_invalid_caddyfile_or_a_missing_env_key_means_not_restored(tmp_path: Path) -> None:
    archive, key = make_archive(tmp_path)
    evidence = drill(
        archive,
        key_path=key,
        runner=FakeDocker(caddy_ok=False),
        now=lambda: NOW,
        sleep=lambda _: None,
    )
    assert evidence.caddyfile_valid is False
    assert evidence.restored is False


def test_without_the_caddy_image_a_local_caddy_binary_validates_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, key = make_archive(tmp_path)

    class NoCaddyImage(FakeDocker):
        def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
            if args[:2] == ["image", "inspect"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 1, "", "No such image")
            return super().__call__(args)

    local_calls: list[list[str]] = []

    def local(args: list[str]) -> subprocess.CompletedProcess[str]:
        local_calls.append(args)
        return subprocess.CompletedProcess(args, 0, "Valid configuration", "")

    monkeypatch.setattr("infra.gastos.restore_drill.shutil.which", lambda name: "/opt/bin/caddy")
    evidence = drill(
        archive,
        key_path=key,
        runner=NoCaddyImage(),
        local_runner=local,
        now=lambda: NOW,
        sleep=lambda _: None,
    )
    assert evidence.caddyfile_valid is True
    assert evidence.caddyfile_validator == "local caddy"
    assert local_calls and local_calls[0][1:4] == ["validate", "--adapter", "caddyfile"]


def test_without_any_caddy_the_file_is_recorded_as_not_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, key = make_archive(tmp_path)

    class NoCaddyImage(FakeDocker):
        def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
            if args[:2] == ["image", "inspect"]:
                return subprocess.CompletedProcess(args, 1, "", "No such image")
            return super().__call__(args)

    monkeypatch.setattr("infra.gastos.restore_drill.shutil.which", lambda name: None)
    evidence = drill(
        archive, key_path=key, runner=NoCaddyImage(), now=lambda: NOW, sleep=lambda _: None
    )
    assert evidence.caddyfile_valid is False
    assert evidence.caddyfile_validator == "unavailable"
    assert evidence.restored is False


def test_an_unverifiable_archive_never_starts_a_container(tmp_path: Path) -> None:
    archive, key = make_archive(tmp_path)
    (archive / "payloads" / "postgres" / "n8n.dump.enc").unlink()
    docker = FakeDocker()
    with pytest.raises(ArchiveError, match="partial"):
        drill(archive, key_path=key, runner=docker, now=lambda: NOW, sleep=lambda _: None)
    assert docker.calls == []


def test_the_evidence_json_carries_no_payload_content(tmp_path: Path) -> None:
    archive, key = make_archive(tmp_path)
    evidence = drill(
        archive, key_path=key, runner=FakeDocker(), now=lambda: NOW, sleep=lambda _: None
    )
    text = evidence.to_json()
    assert "s3cr3t-value" not in text and "POSTGRES_PASSWORD=<redacted>" in text
    assert "gastos-drill-" not in text and "<workdir>" in text
    assert '"host_contacted": false' in text and '"network": "none"' in text
    assert isinstance(evidence, Evidence)
