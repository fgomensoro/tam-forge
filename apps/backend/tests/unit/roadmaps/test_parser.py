from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tamforge_backend.cli import main as cli_main
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.config_models import ConfigBundle
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


def _bundle_with_task(
    bundle: ConfigBundle,
    index: int,
    **updates: object,
) -> ConfigBundle:
    tasks = list(bundle.roadmap_tasks)
    tasks[index] = tasks[index].model_copy(update=updates)
    return replace(bundle, roadmap_tasks=tuple(tasks))


def _bundle_with_task_id(
    bundle: ConfigBundle,
    stable_id: str,
    **updates: object,
) -> ConfigBundle:
    index = next(
        index for index, task in enumerate(bundle.roadmap_tasks) if task.stable_id == stable_id
    )
    return _bundle_with_task(bundle, index, **updates)


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
        ("missing_heading", "source heading"),
        ("missing_source", "source file"),
        ("duplicate_heading", "duplicate Markdown heading"),
        ("missing_resource", "referenced local resource"),
        ("outside_resource", "outside the roadmap package"),
        ("invalid_utf8", "valid UTF-8"),
    ],
)
def test_parser_rejects_missing_or_ambiguous_sources_and_resources(
    mutation: str,
    message: str,
) -> None:
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
    elif mutation == "missing_resource":
        files["README.md"] = files["README.md"].replace(b"sql/tasks", b"sql/missing")
    elif mutation == "outside_resource":
        files["README.md"] += b"\n- [[../private|Private]]\n"
    elif mutation == "invalid_utf8":
        files[week_one] += b"\n\xff"

    with pytest.raises(RoadmapParseError, match=message):
        parse_roadmap(files=files, config=load_config_bundle(CONFIG_DIR))


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda bundle: replace(bundle, roadmap_schema_version=2),
            "requires schema version 1",
        ),
        (
            lambda bundle: replace(
                bundle,
                roadmap_tasks=bundle.roadmap_tasks + (bundle.roadmap_tasks[0],),
            ),
            "duplicate task ID",
        ),
        (
            lambda bundle: _bundle_with_task(bundle, 0, timebox_minutes=44),
            "weekday 1 must total exactly 240",
        ),
        (
            lambda bundle: _bundle_with_task_id(bundle, "m1-w3-d18-sql", timebox_minutes=31),
            "Saturday 18 exceeds 120",
        ),
        (
            lambda bundle: _bundle_with_task(bundle, 0, exercise_type="unknown_exercise"),
            "unknown exercise",
        ),
        (
            lambda bundle: _bundle_with_task(bundle, 0, mapping_version="unknown-v1"),
            "unknown mapping version",
        ),
    ],
)
def test_parser_rejects_invalid_task_map_contracts(
    mutator: object,
    message: str,
) -> None:
    bundle = mutator(load_config_bundle(CONFIG_DIR))  # type: ignore[operator]

    with pytest.raises(RoadmapParseError, match=message):
        parse_roadmap(files=_fixture_files("month-v1.zip"), config=bundle)


def test_parser_does_not_treat_a_heading_inside_a_code_fence_as_source() -> None:
    files = _fixture_files("month-v1.zip")
    week_one = "Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md"
    files[week_one] = files[week_one].replace(
        "## Day 1 — Baseline and HTTP".encode(),
        "```markdown\n## Day 1 — Baseline and HTTP\n```".encode(),
    )

    with pytest.raises(RoadmapParseError, match="source heading"):
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
