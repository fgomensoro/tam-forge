from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HELPER = Path("scripts/dev/ensure_test_database.sh")


def write_fake_command(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o700)


@pytest.fixture
def fake_database_tools(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "commands.log"
    state_path = tmp_path / "database-created"
    shared_log = 'printf "%s\\n" "$0" "$@" "--END--" >> "$FAKE_COMMAND_LOG"\n'
    write_fake_command(
        bin_dir / "psql",
        shared_log
        + 'if [ "${FAKE_PSQL_FAIL:-0}" = "1" ]; then exit 17; fi\n'
        + 'if [ -f "$FAKE_DATABASE_STATE" ]; then printf "1\\n"; fi\n',
    )
    write_fake_command(
        bin_dir / "createdb",
        shared_log
        + 'if [ "${FAKE_CREATEDB_FAIL:-0}" = "1" ]; then exit 19; fi\n'
        + ': > "$FAKE_DATABASE_STATE"\n',
    )
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "FAKE_COMMAND_LOG": str(log_path),
        "FAKE_DATABASE_STATE": str(state_path),
    }
    return env, log_path, state_path


def run_helper(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(HELPER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def command_blocks(log_path: Path) -> list[list[str]]:
    if not log_path.exists():
        return []
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line == "--END--":
            blocks.append(current)
            current = []
        else:
            current.append(line)
    assert current == []
    return blocks


def test_default_target_is_created_once_and_repeated_runs_are_idempotent(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, state_path = fake_database_tools

    first = run_helper(env)
    second = run_helper(env)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert state_path.exists()
    blocks = command_blocks(log_path)
    assert [Path(block[0]).name for block in blocks] == ["psql", "createdb", "psql", "psql"]
    assert blocks[0][1:] == [
        "--no-psqlrc",
        "--host",
        "127.0.0.1",
        "--port",
        "54329",
        "--username",
        "tamforge",
        "--dbname",
        "postgres",
        "--tuples-only",
        "--no-align",
        "--set",
        "ON_ERROR_STOP=1",
        "--command",
        "SELECT 1 FROM pg_database WHERE datname = 'tamforge_test'",
    ]
    assert blocks[1][1:] == [
        "--host",
        "127.0.0.1",
        "--port",
        "54329",
        "--username",
        "tamforge",
        "--maintenance-db",
        "postgres",
        "tamforge_test",
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TAMFORGE_TEST_DB_HOST", "10.0.0.2"),
        ("TAMFORGE_TEST_DB_HOST", "localhost"),
        ("TAMFORGE_TEST_DB_HOST", "::1"),
        ("TAMFORGE_TEST_DB_HOST", "127.0.0.1; touch /tmp/tamforge-pwned"),
        ("TAMFORGE_TEST_DB_PORT", "54329;id"),
        ("TAMFORGE_TEST_DB_PORT", "0"),
        ("TAMFORGE_TEST_DB_PORT", "65536"),
        ("TAMFORGE_TEST_DB_ADMIN_USER", "tamforge;id"),
        ("TAMFORGE_TEST_DB_ADMIN_DATABASE", "tamforge"),
        ("TAMFORGE_TEST_DB_NAME", "tamforge"),
        ("TAMFORGE_TEST_DB_NAME", "tamforge_test;id"),
    ],
)
def test_invalid_configuration_is_rejected_before_any_command_runs(
    fake_database_tools: tuple[dict[str, str], Path, Path],
    name: str,
    value: str,
) -> None:
    env, log_path, _ = fake_database_tools
    env[name] = value

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []


def test_missing_tool_is_rejected_without_running_the_other_tool(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    (Path(env["PATH"]) / "createdb").unlink()

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []


def test_symlinked_tool_is_rejected_without_execution(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    bin_dir = Path(env["PATH"])
    real_psql = bin_dir / "real-psql"
    (bin_dir / "psql").rename(real_psql)
    (bin_dir / "psql").symlink_to(real_psql)

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []


def test_psql_failure_stops_before_createdb(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    env["FAKE_PSQL_FAIL"] = "1"

    result = run_helper(env)

    assert result.returncode != 0
    assert [Path(block[0]).name for block in command_blocks(log_path)] == ["psql"]


def test_createdb_failure_is_rechecked_and_fails_when_database_is_still_absent(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    env["FAKE_CREATEDB_FAIL"] = "1"

    result = run_helper(env)

    assert result.returncode != 0
    assert [Path(block[0]).name for block in command_blocks(log_path)] == [
        "psql",
        "createdb",
        "psql",
    ]
