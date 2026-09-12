from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps"
CASES = {
    "month-1": (
        ROOT / "config" / "tam-roadmap-task-map.yaml",
        FIXTURES / "month-v1.zip",
        FIXTURES / "month-v1.zip",
        (24, 158),
    ),
    "six-week": (
        ROOT / "config" / "releases" / "phase-1-six-week-v1" / "tam-roadmap-task-map.yaml",
        FIXTURES / "phase-1-six-week-v1.zip",
        FIXTURES / "phase-1-six-week-scheme-v1.zip",
        (36, 148),
    ),
}


def _module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "convert_task_map", ROOT / "scripts" / "dev" / "convert_task_map.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case", sorted(CASES))
def test_checked_in_scheme_packages_match_their_sources(case: str) -> None:
    task_map, package, output, (days, blocks) = CASES[case]
    scheme = _module().convert_task_map(task_map, package, output, check=True)
    assert len(scheme.days) == days
    assert sum(len(day.blocks) for day in scheme.days) == blocks


@pytest.mark.parametrize("case", sorted(CASES))
def test_conversion_is_deterministic_and_check_detects_drift(case: str, tmp_path: Path) -> None:
    module = _module()
    task_map, package, _, _ = CASES[case]
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    module.convert_task_map(task_map, package, first)
    module.convert_task_map(task_map, package, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "roadmap.yaml" in names
    second.write_bytes(second.read_bytes() + b"\n")
    with pytest.raises(module.ConversionError, match="does not match"):
        module.convert_task_map(task_map, package, second, check=True)


def test_six_week_contracts_map_onto_the_server_vocabulary() -> None:
    module = _module()
    saturday = {"contract": "saturday", "stable_id": "p1-w01-d06-sat-no-ai-sql"}
    assert module._contract_type(saturday) == "saturday_sql"
    assert (
        module._contract_type({"contract": "saturday", "stable_id": "x-sat-fresh-mock"})
        == "saturday_case"
    )
    assert (
        module._contract_type(
            {"contract": "saturday", "stable_id": "x-sat-portfolio-to-depth-gauntlet"}
        )
        == "saturday_gauntlet"
    )
    assert (
        module._contract_type({"contract": "saturday", "stable_id": "x-sat-next-week-planning"})
        == "saturday_scoring"
    )
    assert module._contract_type({"contract": "interview", "stable_id": "x"}) == "communication"
    assert module._contract_type({"contract": "roadmap", "stable_id": "x"}) == "technical"
    assert module._contract_type({"contract": "sql", "stable_id": "x"}) == "sql"
