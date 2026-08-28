from __future__ import annotations

import re
from pathlib import Path

PLAN = Path("docs/superpowers/plans/2026-08-25-tam-forge-01-foundation-learning.md")


def pytest_commands() -> list[str]:
    return [
        line.strip()
        for line in PLAN.read_text(encoding="utf-8").splitlines()
        if "uv run pytest" in line
    ]


def test_plan_has_every_task_in_exact_sequence() -> None:
    text = PLAN.read_text(encoding="utf-8")
    task_numbers = [int(value) for value in re.findall(r"^## Task (\d+):", text, re.MULTILINE)]

    assert task_numbers == list(range(1, 27))


def test_every_explicit_integration_path_command_selects_integration_marker() -> None:
    integration_commands = [
        command for command in pytest_commands() if "tests/integration" in command
    ]

    assert integration_commands
    assert all(" -m integration " in command for command in integration_commands)


def test_unit_commands_never_select_integration_marker() -> None:
    unit_commands = [command for command in pytest_commands() if "tests/unit" in command]

    assert unit_commands
    assert all(" -m integration " not in command for command in unit_commands)
