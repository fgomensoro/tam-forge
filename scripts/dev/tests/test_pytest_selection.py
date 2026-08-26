from __future__ import annotations

import os
import subprocess
import sys

INTEGRATION_TEST = "apps/backend/tests/integration/test_migrations.py"


def run_integration_test(
    *extra_args: str,
    ambient_database_url: str | None = None,
    collect_only: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    env.pop("TEST_DATABASE_URL", None)
    if ambient_database_url is not None:
        env["TEST_DATABASE_URL"] = ambient_database_url
    args = [sys.executable, "-m", "pytest", INTEGRATION_TEST, "-q", *extra_args]
    if collect_only:
        args.append("--collect-only")
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_default_pytest_selection_excludes_integration_tests() -> None:
    result = run_integration_test(
        ambient_database_url=(
            "postgresql+asyncpg://tamforge:secret@remote.invalid:5432/tamforge_test"
        )
    )

    assert result.returncode == 5
    assert "1 deselected" in result.stdout
    assert "test_migrations_round_trip_and_keep_version_table" not in result.stdout


def test_explicit_integration_marker_collects_integration_tests() -> None:
    result = run_integration_test("-m", "integration")

    assert result.returncode == 0, result.stderr
    assert "test_migrations_round_trip_and_keep_version_table" in result.stdout
    assert "1 test collected" in result.stdout


def test_explicit_integration_rejects_remote_target_before_test_body_runs() -> None:
    secret = "remote-password-must-not-leak"
    result = run_integration_test(
        "-m",
        "integration",
        ambient_database_url=(
            f"postgresql+asyncpg://tamforge:{secret}@remote.invalid:5432/tamforge_test"
        ),
        collect_only=False,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert (
        "TEST_DATABASE_URL must be a complete PostgreSQL URL for tamforge_test"
        in combined_output
    )
    assert secret not in combined_output
    assert "connection refused" not in combined_output.lower()
