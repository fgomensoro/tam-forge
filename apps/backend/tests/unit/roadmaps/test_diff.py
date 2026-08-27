from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.roadmaps.diff import diff_roadmaps
from tamforge_backend.roadmaps.package import inspect_zip_stream
from tamforge_backend.roadmaps.parser import parse_roadmap

ROOT = Path(__file__).parents[5]
CONFIG_DIR = ROOT / "config"
FIXTURES = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps"


def _fixture_files(name: str) -> dict[str, bytes]:
    with inspect_zip_stream(((FIXTURES / name).read_bytes(),)) as package:
        assert package.accepted
        return {item.manifest.path: item.staged_path.read_bytes() for item in package.files}


def test_semantic_diff_reports_field_changes_and_ignores_file_heading_order() -> None:
    before_bundle = load_config_bundle(CONFIG_DIR)
    tasks = list(before_bundle.roadmap_tasks)
    first = tasks[0]
    tasks[0] = first.model_copy(
        update={
            "objective": "Changed objective with the same stable identity.",
            "pass_criteria": first.pass_criteria + ("New reviewed pass condition.",),
        }
    )
    after_bundle = replace(before_bundle, roadmap_tasks=tuple(tasks))
    before = parse_roadmap(files=_fixture_files("month-v1.zip"), config=before_bundle)
    after = parse_roadmap(files=_fixture_files("month-v2.zip"), config=after_bundle)

    result = diff_roadmaps(before, after)

    changed_task = result.tasks.by_key("m1-w1-d01-sql")
    assert changed_task.status == "changed"
    assert changed_task.field("objective").before == first.objective
    assert (
        changed_task.field("objective").after == "Changed objective with the same stable identity."
    )
    assert all(
        result.tasks.by_key(task.stable_id).status == "unchanged" for task in before.tasks[1:]
    )

    changed_contract = result.pass_contracts.by_key("m1-w1-d01-sql")
    assert changed_contract.status == "changed"
    assert changed_contract.field("pass_criteria").before == list(first.pass_criteria)
    assert changed_contract.field("pass_criteria").after == [
        *first.pass_criteria,
        "New reviewed pass condition.",
    ]

    assert result.resources.by_key("https://example.com/http").status == "unchanged"
    assert result.resources.by_key("sql/tasks.md").status == "unchanged"
    assert result.resources.by_key("https://example.com/oauth").status == "added"
    assert result.exit_criteria.by_key("Explain one integration clearly.").status == "unchanged"
    assert result.exit_criteria.by_key("Score at least 3 independently.").status == "removed"
    assert result.exit_criteria.by_key("Score at least 4 independently.").status == "added"


def test_identical_normalized_roadmaps_have_only_unchanged_entries() -> None:
    roadmap = parse_roadmap(
        files=_fixture_files("month-v1.zip"),
        config=load_config_bundle(CONFIG_DIR),
    )

    result = diff_roadmaps(roadmap, roadmap)

    assert result.summary == {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "unchanged": 321,
    }
    assert result.is_semantically_identical
