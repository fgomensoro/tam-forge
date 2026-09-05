"""Explicit PostgreSQL gate: no service startup, defaults, skipped or empty success."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from ..database import validate_test_database_url


class IntegrationGate:
    def __init__(self) -> None:
        self.collected = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        self.collected = len(items)
        if any(
            item.get_closest_marker("integration") is None
            or item.get_closest_marker("postgres_integration") is None
            for item in items
        ):
            raise pytest.UsageError("Plan03 requires both integration markers")

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        self.failed += int(report.failed)
        self.skipped += int(report.skipped)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.failed += int(report.failed)
        self.skipped += int(report.skipped)
        if report.when == "call" and report.passed:
            self.passed += 1

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if exitstatus == 0 and (
            self.collected == 0 or self.passed != self.collected or self.failed or self.skipped
        ):
            session.exitstatus = 1
        print(
            f"Plan03: collected={self.collected} passed={self.passed} "
            f"failed={self.failed} skipped={self.skipped}"
        )


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(IntegrationGate(), "plan03-counts")


def run(
    paths: Sequence[str],
    *,
    test_database_url: str | None,
    process: Callable[..., Any] = subprocess.run,
) -> int:
    try:
        if not test_database_url or not paths or any(not p or p.startswith("-") for p in paths):
            raise ValueError
        url = validate_test_database_url(test_database_url)
    except ValueError:
        raise ValueError("explicit safe test_database_url and test paths required") from None
    environment = os.environ.copy()
    environment["TEST_DATABASE_URL"] = url
    environment["DATABASE_URL"] = url
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "--strict-markers",
        "-m",
        "postgres_integration",
        "-p",
        __spec__.name if __spec__ else __name__,
        "-q",
        *paths,
    ]
    return int(process(command, env=environment, check=False).returncode)


def main() -> int:
    try:
        return run(sys.argv[1:], test_database_url=os.getenv("TEST_DATABASE_URL"))
    except ValueError:
        print("Plan03 requires explicit safe TEST_DATABASE_URL and test paths", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
