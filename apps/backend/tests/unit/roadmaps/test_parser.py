# ruff: noqa: E501
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from tamforge_backend.cli import main as cli_main
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.roadmaps.package import inspect_zip_stream
from tamforge_backend.roadmaps.parser import RoadmapParseError, parse_roadmap

ROOT = Path(__file__).parents[5]
CONFIG_DIR = ROOT / "config"
FIXTURES = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps"


def _fixture_files(name: str) -> dict[str, bytes]:
    payload = (FIXTURES / name).read_bytes()
    with inspect_zip_stream((payload,)) as package:
        assert package.accepted
        return {item.manifest.path: item.staged_path.read_bytes() for item in package.files}


def test_phase1_package_is_deterministic_markdown_and_sql_only() -> None:
    fixture = FIXTURES / "phase-1-six-week-v1.zip"
    with zipfile.ZipFile(fixture) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(Path(name).suffix.lower() in {".md", ".sql"} for name in names)
        assert not any(name.endswith(".json") for name in names)
        assert not any("Roadmap.archive" in name or "Roadmap.backup" in name for name in names)
        assert archive.testzip() is None

    files = _fixture_files("phase-1-six-week-v1.zip")
    assert "README.md" in files
    assert len(files) == 34


def _summary(roadmap: object) -> dict[str, object]:
    first = roadmap.tasks[0]  # type: ignore[attr-defined]
    weekday_minutes = sum(
        task.timebox_minutes
        for task in roadmap.tasks  # type: ignore[attr-defined]
        if task.day == 1
    )
    saturday_minutes = sum(
        task.timebox_minutes
        for task in roadmap.tasks  # type: ignore[attr-defined]
        if task.day == 6
    )
    return {
        "schema_version": roadmap.schema_version,  # type: ignore[attr-defined]
        "roadmap_version": roadmap.roadmap_version,  # type: ignore[attr-defined]
        "task_count": len(roadmap.tasks),  # type: ignore[attr-defined]
        "first_task": {
            "stable_id": first.stable_id,
            "week": first.week,
            "day": first.day,
            "block": first.block,
            "order": first.order,
            "timebox_minutes": first.timebox_minutes,
            "exercise_type": first.exercise_type,
            "mapping_version": first.mapping_version,
            "allowed_ai_role": first.allowed_ai_role,
        },
        "resource_keys": [item.key for item in roadmap.resources],  # type: ignore[attr-defined]
        "exit_criteria": [item.text for item in roadmap.exit_criteria],  # type: ignore[attr-defined]
        "weekday_minutes": weekday_minutes,
        "saturday_minutes": saturday_minutes,
    }


def test_parser_emits_exact_stable_tasks_contracts_resources_and_exit_criteria() -> None:
    roadmap = parse_roadmap(
        files=_fixture_files("month-v1.zip"),
        config=load_config_bundle(CONFIG_DIR),
    )
    expected = json.loads((FIXTURES / "expected-month-v1.json").read_text())

    assert _summary(roadmap) == expected
    assert len(roadmap.contracts) == 158
    assert roadmap.tasks[0].required_output
    assert roadmap.tasks[0].pass_criteria
    assert roadmap.tasks[0].evidence_requirements
    assert roadmap.tasks[0].procedure
    assert roadmap.tasks[0].source_heading == "Day 1 — Baseline and HTTP"
    assert len(roadmap.normalized_hash) == 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_heading", "heading 'Day 1 — Baseline and HTTP' is missing"),
        (
            "missing_source",
            "file 'Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md' is missing",
        ),
        ("duplicate_heading", "appears 2 times"),
        ("no_scheme", "must carry roadmap.yaml"),
        ("invalid_utf8", "valid UTF-8"),
    ],
)
def test_parser_rejects_missing_or_ambiguous_sources(mutation: str, message: str) -> None:
    files = _fixture_files("month-v1.zip")
    week_one = "Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md"
    if mutation == "missing_heading":
        files[week_one] = files[week_one].replace(
            "## Day 1 — Baseline and HTTP".encode(),
            b"## Removed heading",
        )
    elif mutation == "missing_source":
        del files[week_one]
    elif mutation == "duplicate_heading":
        files[week_one] += b"\n## Day 1 \xe2\x80\x94 Baseline and HTTP\n"
    elif mutation == "no_scheme":
        del files["roadmap.yaml"]
    elif mutation == "invalid_utf8":
        files[week_one] += b"\n\xff"

    with pytest.raises(RoadmapParseError, match=message):
        parse_roadmap(files=files, config=load_config_bundle(CONFIG_DIR))


def test_links_that_leave_the_package_are_allowed_but_not_block_sources() -> None:
    files = _fixture_files("month-v1.zip")
    files["README.md"] += (
        b"\n- [[../private|Private]]\n- [[Docs/2026-09-08 - Active Study Reforecast]]\n"
    )

    roadmap = parse_roadmap(files=files, config=load_config_bundle(CONFIG_DIR))

    assert all(item.kind == "external" or item.key in files for item in roadmap.resources)


def test_parser_does_not_treat_a_heading_inside_a_code_fence_as_source() -> None:
    files = _fixture_files("month-v1.zip")
    week_one = "Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md"
    files[week_one] = files[week_one].replace(
        "## Day 1 — Baseline and HTTP".encode(),
        "```markdown\n## Day 1 — Baseline and HTTP\n```".encode(),
    )

    with pytest.raises(RoadmapParseError, match="is missing"):
        parse_roadmap(files=files, config=load_config_bundle(CONFIG_DIR))


def test_parser_allows_repeated_headings_that_are_not_task_sources() -> None:
    files = _fixture_files("month-v1.zip")
    files["README.md"] += b"\n## Repeated exercise\nOne.\n## Repeated exercise\nTwo.\n"

    roadmap = parse_roadmap(files=files, config=load_config_bundle(CONFIG_DIR))

    assert len(roadmap.tasks) == 158


def test_parser_allows_parent_resource_reference_that_stays_inside_package() -> None:
    files = _fixture_files("month-v1.zip")
    files["docs/guide.md"] = b"# Guide\n\n[[../templates/scorecard|Scorecard]]\n"

    roadmap = parse_roadmap(files=files, config=load_config_bundle(CONFIG_DIR))

    scorecard = next(item for item in roadmap.resources if item.key == "templates/scorecard.md")
    assert scorecard.source_paths == ("README.md", "docs/guide.md")


def test_parser_accepts_correction_tasks_only_with_inherited_mapping_lineage() -> None:
    roadmap = parse_roadmap(
        files=_fixture_files("month-v1.zip"),
        config=load_config_bundle(CONFIG_DIR),
    )

    corrections = [task for task in roadmap.tasks if task.block == "correction_warmup"]
    assert len(corrections) == 20
    assert all(task.exercise_type is None and task.mapping_version is None for task in corrections)
    assert all(task.correction_selection is not None for task in corrections)


def test_validate_roadmap_map_cli_reports_deterministic_timebox_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli_main(
        [
            "validate-roadmap-map",
            "--config",
            str(CONFIG_DIR / "tam-roadmap-task-map.yaml"),
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "roadmap_version": "month-1-v2",
        "mapping_version": "seed-v1",
        "tasks": 158,
        "study_days": 24,
        "weekday_days": 20,
        "saturdays": 4,
        "total_minutes": 5280,
    }
