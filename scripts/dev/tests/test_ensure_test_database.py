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
    bin_dir.mkdir(mode=0o700)
    bin_dir.chmod(0o700)
    log_path = tmp_path / "commands.log"
    env_log_path = tmp_path / "command-env.log"
    state_path = tmp_path / "database-created"
    ready_state_path = tmp_path / "readiness-attempts"
    shared_log = (
        'printf "%s\\n" "$0" "$@" "--END--" >> "$FAKE_COMMAND_LOG"\n'
        'printf "%s\\n" "${PGPASSWORD-}" "${PGCONNECT_TIMEOUT-}" "${PGOPTIONS-}" '
        '"--END--" >> "$FAKE_ENV_LOG"\n'
    )
    write_fake_command(
        bin_dir / "psql",
        shared_log
        + 'previous=""\n'
        + 'is_readiness=0\n'
        + 'for argument in "$@"; do\n'
        + '  if [ "$previous" = "--command" ] && [ "$argument" = "SELECT 1" ]; then\n'
        + '    is_readiness=1\n'
        + "  fi\n"
        + '  previous="$argument"\n'
        + "done\n"
        + 'if [ "$is_readiness" = "1" ]; then\n'
        + '  ready_count=0\n'
        + '  if [ -f "$FAKE_READY_STATE" ]; then read -r ready_count < "$FAKE_READY_STATE"; fi\n'
        + '  ready_count=$((ready_count + 1))\n'
        + '  printf "%s\\n" "$ready_count" > "$FAKE_READY_STATE"\n'
        + '  if [ "$ready_count" -le "${FAKE_READY_FAILURES:-0}" ]; then exit 16; fi\n'
        + '  printf "1\\n"\n'
        + "  exit 0\n"
        + "fi\n"
        + 'if [ "${FAKE_PSQL_FAIL:-0}" = "1" ]; then exit 17; fi\n'
        + 'if [ -f "$FAKE_DATABASE_STATE" ]; then printf "1\\n"; fi\n',
    )
    write_fake_command(
        bin_dir / "createdb",
        shared_log
        + 'if [ "${FAKE_CREATEDB_FAIL:-0}" = "1" ]; then exit 19; fi\n'
        + ': > "$FAKE_DATABASE_STATE"\n',
    )
    env = {**os.environ}
    for name in tuple(env):
        if name.startswith("TAMFORGE_TEST_DB_"):
            env.pop(name)
    env.update(
        {
            "PATH": str(bin_dir),
            "FAKE_COMMAND_LOG": str(log_path),
            "FAKE_ENV_LOG": str(env_log_path),
            "FAKE_DATABASE_STATE": str(state_path),
            "FAKE_READY_STATE": str(ready_state_path),
            "TAMFORGE_TEST_DB_TEST_MODE": "1",
            "TAMFORGE_TEST_DB_TOOL_ROOT": str(bin_dir),
        }
    )
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


def environment_blocks(env: dict[str, str]) -> list[list[str]]:
    return command_blocks(Path(env["FAKE_ENV_LOG"]))


def fake_platform_environment(
    tmp_path: Path,
    *,
    path_directory: Path,
) -> tuple[dict[str, str], Path, Path, Path]:
    platform_root = tmp_path / "platform-root"
    platform_root.mkdir(mode=0o700, exist_ok=True)
    platform_root.chmod(0o700)
    log_path = tmp_path / "platform-commands.log"
    env_log_path = tmp_path / "platform-command-env.log"
    state_path = tmp_path / "platform-database-created"
    env = {**os.environ}
    for name in tuple(env):
        if name.startswith("TAMFORGE_TEST_DB_"):
            env.pop(name)
    env.update(
        {
            "PATH": str(path_directory),
            "FAKE_COMMAND_LOG": str(log_path),
            "FAKE_ENV_LOG": str(env_log_path),
            "FAKE_DATABASE_STATE": str(state_path),
            "TAMFORGE_TEST_DB_TEST_MODE": "1",
            "TAMFORGE_TEST_DB_TOOL_ROOT": str(platform_root),
            "TAMFORGE_TEST_DB_PLATFORM_ROOT": str(platform_root),
        }
    )
    return env, log_path, state_path, platform_root


def fake_postgres_client_body() -> str:
    return (
        'printf "%s\\n" "$0" "$@" "--END--" >> "$FAKE_COMMAND_LOG"\n'
        'printf "%s\\n" "${PGPASSWORD-}" "${PGCONNECT_TIMEOUT-}" "${PGOPTIONS-}" '
        '"--END--" >> "$FAKE_ENV_LOG"\n'
        'previous=""\n'
        'for argument in "$@"; do\n'
        '  if [ "$previous" = "--command" ] && [ "$argument" = "SELECT 1" ]; then\n'
        '    printf "1\\n"\n'
        '    exit 0\n'
        '  fi\n'
        '  previous="$argument"\n'
        'done\n'
        'case " $* " in\n'
        '  *" --maintenance-db "*) : > "$FAKE_DATABASE_STATE" ;;\n'
        '  *) if [ -f "$FAKE_DATABASE_STATE" ]; then printf "1\\n"; fi ;;\n'
        "esac\n"
    )


def test_default_target_is_created_once_and_repeated_runs_are_idempotent(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, state_path = fake_database_tools

    first = run_helper(env)
    second = run_helper(env)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "tamforge" not in first.stderr
    assert "tamforge" not in second.stderr
    assert state_path.exists()
    blocks = command_blocks(log_path)
    assert [Path(block[0]).name for block in blocks] == [
        "psql",
        "psql",
        "createdb",
        "psql",
        "psql",
        "psql",
    ]
    assert blocks[0][1:] == [
        "--no-psqlrc",
        "--no-password",
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
        "--set=ON_ERROR_STOP=1",
        "--command",
        "SELECT 1",
    ]
    assert blocks[1][1:] == [
        "--no-psqlrc",
        "--no-password",
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
        "--set=ON_ERROR_STOP=1",
        "--command",
        "SELECT 1 FROM pg_database WHERE datname = 'tamforge_test'",
    ]
    assert blocks[2][1:] == [
        "--no-password",
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
    assert environment_blocks(env) == [
        ["tamforge", "5", "-c statement_timeout=5000 -c lock_timeout=5000"],
        ["tamforge", "5", "-c statement_timeout=5000 -c lock_timeout=5000"],
        ["tamforge", "5", "-c statement_timeout=5000 -c lock_timeout=5000"],
        ["tamforge", "5", "-c statement_timeout=5000 -c lock_timeout=5000"],
        ["tamforge", "5", "-c statement_timeout=5000 -c lock_timeout=5000"],
        ["tamforge", "5", "-c statement_timeout=5000 -c lock_timeout=5000"],
    ]


@pytest.mark.parametrize("database_exists", [True, False])
def test_readiness_retries_fail_fail_success_before_existing_or_creation_flow(
    fake_database_tools: tuple[dict[str, str], Path, Path],
    database_exists: bool,
) -> None:
    env, log_path, state_path = fake_database_tools
    if database_exists:
        state_path.touch()
    env.update(
        {
            "FAKE_READY_FAILURES": "2",
            "TAMFORGE_TEST_DB_READY_ATTEMPTS": "3",
            "TAMFORGE_TEST_DB_READY_DELAY_SECONDS": "0",
        }
    )

    result = run_helper(env)

    assert result.returncode == 0, result.stderr
    names = [Path(block[0]).name for block in command_blocks(log_path)]
    assert names[:3] == ["psql", "psql", "psql"]
    assert names[3:] == (["psql"] if database_exists else ["psql", "createdb", "psql"])
    assert state_path.exists()


def test_readiness_permanent_failure_exhausts_exact_attempts_without_createdb(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, state_path = fake_database_tools
    password = "readiness-password-must-not-leak"
    env.update(
        {
            "FAKE_READY_FAILURES": "99",
            "TAMFORGE_TEST_DB_PASSWORD": password,
            "TAMFORGE_TEST_DB_READY_ATTEMPTS": "3",
            "TAMFORGE_TEST_DB_READY_DELAY_SECONDS": "0",
        }
    )

    result = run_helper(env)

    assert result.returncode != 0
    assert [Path(block[0]).name for block in command_blocks(log_path)] == [
        "psql",
        "psql",
        "psql",
    ]
    assert not state_path.exists()
    assert "PostgreSQL did not become ready within the bounded wait" in result.stderr
    assert password not in result.stdout
    assert password not in result.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TAMFORGE_TEST_DB_READY_ATTEMPTS", "0"),
        ("TAMFORGE_TEST_DB_READY_ATTEMPTS", "61"),
        ("TAMFORGE_TEST_DB_READY_ATTEMPTS", "not-a-number"),
        ("TAMFORGE_TEST_DB_READY_DELAY_SECONDS", "-1"),
        ("TAMFORGE_TEST_DB_READY_DELAY_SECONDS", "6"),
        ("TAMFORGE_TEST_DB_READY_DELAY_SECONDS", "0.1"),
    ],
)
def test_malformed_test_readiness_knobs_fail_before_tool_invocation(
    fake_database_tools: tuple[dict[str, str], Path, Path],
    name: str,
    value: str,
) -> None:
    env, log_path, _ = fake_database_tools
    env[name] = value

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []


@pytest.mark.parametrize(
    "name",
    ["TAMFORGE_TEST_DB_READY_ATTEMPTS", "TAMFORGE_TEST_DB_READY_DELAY_SECONDS"],
)
def test_readiness_knobs_are_rejected_outside_isolated_test_mode(
    fake_database_tools: tuple[dict[str, str], Path, Path],
    name: str,
) -> None:
    env, log_path, _ = fake_database_tools
    env.pop("TAMFORGE_TEST_DB_TEST_MODE")
    env.pop("TAMFORGE_TEST_DB_TOOL_ROOT")
    env[name] = "1"

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []
    assert "readiness overrides require isolated test mode" in result.stderr


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
        ("TAMFORGE_TEST_DB_PASSWORD", ""),
        ("TAMFORGE_TEST_DB_PASSWORD", "contains space"),
        ("TAMFORGE_TEST_DB_PASSWORD", "line1\nline2"),
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


def test_symlinked_tool_within_isolated_test_root_is_resolved_and_allowed(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, state_path = fake_database_tools
    bin_dir = Path(env["PATH"])
    real_psql = bin_dir / "real-psql"
    (bin_dir / "psql").rename(real_psql)
    (bin_dir / "psql").symlink_to(real_psql)

    result = run_helper(env)

    assert result.returncode == 0, result.stderr
    assert state_path.exists()
    assert [Path(block[0]).name for block in command_blocks(log_path)] == [
        "real-psql",
        "real-psql",
        "createdb",
        "real-psql",
    ]


def test_debian_pg_wrapper_symlinks_are_classified_and_invoked_by_client_name(
    tmp_path: Path,
) -> None:
    platform_root = tmp_path / "platform-root"
    bin_dir = platform_root / "usr" / "bin"
    wrapper_dir = platform_root / "usr" / "share" / "postgresql-common"
    bin_dir.mkdir(parents=True)
    wrapper_dir.mkdir(parents=True)
    wrapper = wrapper_dir / "pg_wrapper"
    write_fake_command(wrapper, fake_postgres_client_body())
    (bin_dir / "psql").symlink_to("../share/postgresql-common/pg_wrapper")
    (bin_dir / "createdb").symlink_to("../share/postgresql-common/pg_wrapper")
    env, log_path, state_path, _ = fake_platform_environment(
        tmp_path,
        path_directory=bin_dir,
    )

    result = run_helper(env)

    assert result.returncode == 0, result.stderr
    assert state_path.exists()
    assert [Path(block[0]).name for block in command_blocks(log_path)] == [
        "psql",
        "psql",
        "createdb",
        "psql",
    ]


def test_debian_versioned_postgresql_clients_are_allowed(
    tmp_path: Path,
) -> None:
    platform_root = tmp_path / "platform-root"
    bin_dir = platform_root / "usr" / "lib" / "postgresql" / "16" / "bin"
    bin_dir.mkdir(parents=True)
    write_fake_command(bin_dir / "psql", fake_postgres_client_body())
    write_fake_command(bin_dir / "createdb", fake_postgres_client_body())
    env, log_path, state_path, _ = fake_platform_environment(
        tmp_path,
        path_directory=bin_dir,
    )

    result = run_helper(env)

    assert result.returncode == 0, result.stderr
    assert state_path.exists()
    assert [Path(block[0]).name for block in command_blocks(log_path)] == [
        "psql",
        "psql",
        "createdb",
        "psql",
    ]


@pytest.mark.parametrize("near_miss", ["pg_wrapper_backup", "16.1", "sibling-binary"])
def test_debian_client_layout_near_misses_are_rejected_without_execution(
    tmp_path: Path,
    near_miss: str,
) -> None:
    platform_root = tmp_path / "platform-root"
    if near_miss == "pg_wrapper_backup":
        bin_dir = platform_root / "usr" / "bin"
        target_dir = platform_root / "usr" / "share" / "postgresql-common"
        bin_dir.mkdir(parents=True)
        target_dir.mkdir(parents=True)
        target = target_dir / near_miss
        write_fake_command(target, fake_postgres_client_body())
        (bin_dir / "psql").symlink_to(f"../share/postgresql-common/{near_miss}")
        (bin_dir / "createdb").symlink_to(f"../share/postgresql-common/{near_miss}")
    elif near_miss == "16.1":
        bin_dir = platform_root / "usr" / "lib" / "postgresql" / near_miss / "bin"
        bin_dir.mkdir(parents=True)
        write_fake_command(bin_dir / "psql", fake_postgres_client_body())
        write_fake_command(bin_dir / "createdb", fake_postgres_client_body())
    else:
        bin_dir = platform_root / "usr" / "lib" / "postgresql" / "16" / "bin"
        bin_dir.mkdir(parents=True)
        sibling = bin_dir / near_miss
        write_fake_command(sibling, fake_postgres_client_body())
        (bin_dir / "psql").symlink_to(sibling)
        write_fake_command(bin_dir / "createdb", fake_postgres_client_body())
    env, log_path, state_path, _ = fake_platform_environment(
        tmp_path,
        path_directory=bin_dir,
    )

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []
    assert not state_path.exists()


def test_symlink_target_outside_isolated_root_is_rejected_without_execution(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, state_path = fake_database_tools
    bin_dir = Path(env["PATH"])
    outside_dir = state_path.parent / "outside"
    outside_dir.mkdir(mode=0o700)
    outside_tool = outside_dir / "psql"
    write_fake_command(outside_tool, ': > "$FAKE_DATABASE_STATE"\n')
    (bin_dir / "psql").unlink()
    (bin_dir / "psql").symlink_to(outside_tool)

    result = run_helper(env)

    assert result.returncode != 0
    assert command_blocks(log_path) == []
    assert not state_path.exists()


def test_broken_or_looping_symlink_is_rejected_without_execution(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    bin_dir = Path(env["PATH"])
    (bin_dir / "psql").unlink()
    (bin_dir / "psql").symlink_to(bin_dir / "missing-psql")

    broken = run_helper(env)

    assert broken.returncode != 0
    assert command_blocks(log_path) == []

    (bin_dir / "psql").unlink()
    (bin_dir / "psql").symlink_to(bin_dir / "psql")
    loop = run_helper(env)

    assert loop.returncode != 0
    assert command_blocks(log_path) == []


def test_insecure_test_root_or_writable_target_is_rejected_before_execution(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    bin_dir = Path(env["PATH"])
    bin_dir.chmod(0o755)

    insecure_root = run_helper(env)

    assert insecure_root.returncode != 0
    assert command_blocks(log_path) == []

    bin_dir.chmod(0o700)
    (bin_dir / "psql").chmod(0o722)
    writable_target = run_helper(env)

    assert writable_target.returncode != 0
    assert command_blocks(log_path) == []


def test_password_override_is_child_only_and_never_appears_in_output(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, _, _ = fake_database_tools
    password = "local-test-password-123"
    env["TAMFORGE_TEST_DB_PASSWORD"] = password

    result = run_helper(env)

    assert result.returncode == 0, result.stderr
    assert password not in result.stdout
    assert password not in result.stderr
    assert all(block[0] == password for block in environment_blocks(env))


def test_psql_failure_stops_before_createdb(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    env["FAKE_PSQL_FAIL"] = "1"

    result = run_helper(env)

    assert result.returncode != 0
    assert [Path(block[0]).name for block in command_blocks(log_path)] == ["psql", "psql"]


def test_createdb_failure_is_rechecked_and_fails_when_database_is_still_absent(
    fake_database_tools: tuple[dict[str, str], Path, Path],
) -> None:
    env, log_path, _ = fake_database_tools
    env["FAKE_CREATEDB_FAIL"] = "1"

    result = run_helper(env)

    assert result.returncode != 0
    assert [Path(block[0]).name for block in command_blocks(log_path)] == [
        "psql",
        "psql",
        "createdb",
        "psql",
    ]
