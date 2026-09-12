# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.roadmaps.parser import RoadmapParseError, parse_roadmap
from tamforge_backend.roadmaps.scheme import (
    SchemeValidationError,
    parse_scheme_text,
    scheme_summary_from_payload,
    validate_scheme,
)

ROOT = Path(__file__).parents[5]
CONFIG = load_config_bundle(ROOT / "config")

WEEK = "Week 1.md"
FILES: dict[str, bytes] = {
    WEEK: b"# Week 1\n\n## Day 1\n\nDo it.\n\n## Day 2\n\nAgain.\n",
    "docs/Queue.md": b"# Queue\n\n## P1-Q01\n\nTell me about yourself.\n",
}

SCHEME = """
schema_version: 1
program: {key: demo, title: Demo}
rest_weekdays: [sunday]
days:
  - id: d01
    kind: weekday
    budget_minutes: 120
    blocks:
      - {id: d01-interview, type: communication, minutes: 60, source: {file: docs/Queue.md, heading: P1-Q01}, objective: Answer P1-Q01.}
      - {id: d01-learning, type: technical, minutes: 45, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}
      - {id: d01-close, type: close, minutes: 15, source: {file: Week 1.md, heading: Day 1}, objective: Close the day.}
      - {id: d01-fix, type: correction, minutes: 10, required: false, source: {file: Week 1.md, heading: Day 1}, objective: One due correction.}
  - id: d02
    kind: assessment
    budget_minutes: 60
    blocks:
      - {id: d02-sql, type: saturday_sql, minutes: 60, source: {file: Week 1.md, heading: Day 2}, objective: Assess.}
"""


def _files_with_scheme(text: str = SCHEME) -> dict[str, bytes]:
    files = dict(FILES)
    files["roadmap.yaml"] = text.encode("utf-8")
    return files


def test_valid_scheme_has_no_issues() -> None:
    scheme = parse_scheme_text(SCHEME)
    assert validate_scheme(scheme, files=FILES, config=CONFIG) == ()
    assert [day.kind for day in scheme.days] == ["weekday", "assessment"]
    assert scheme.rest_weekday_indexes == frozenset({6})


@pytest.mark.parametrize(
    ("before", "after", "fragment"),
    [
        ("heading: P1-Q01", "heading: P1-Q99", "heading 'P1-Q99' is missing"),
        ("file: docs/Queue.md", "file: docs/Missing.md", "file 'docs/Missing.md' is missing"),
        ("minutes: 45", "minutes: 30", "day 'd01' required minutes 105 do not equal budget 120"),
        ("type: technical", "type: physics", "type 'physics' is not a contract"),
        ("id: d01-close", "id: d01-interview", "id 'd01-interview' is duplicated"),
        (
            "objective: Read the day.}",
            "objective: Read the day., exercise_type: nope}",
            "exercise 'nope' is unknown",
        ),
    ],
)
def test_invalid_schemes_report_named_issues(before: str, after: str, fragment: str) -> None:
    scheme = parse_scheme_text(SCHEME.replace(before, after, 1))
    issues = validate_scheme(scheme, files=FILES, config=CONFIG)
    assert any(fragment in issue for issue in issues), issues


def test_budgets_above_storage_caps_are_issues() -> None:
    weekday = SCHEME.replace("budget_minutes: 120", "budget_minutes: 300", 1).replace(
        "minutes: 60, source: {file: docs/Queue.md", "minutes: 240, source: {file: docs/Queue.md", 1
    )
    issues = validate_scheme(parse_scheme_text(weekday), files=FILES, config=CONFIG)
    assert any("exceeds the weekday maximum of 240" in issue for issue in issues), issues
    assessment = SCHEME.replace("budget_minutes: 60", "budget_minutes: 130", 1).replace(
        "minutes: 60, source: {file: Week 1.md, heading: Day 2}",
        "minutes: 130, source: {file: Week 1.md, heading: Day 2}",
        1,
    )
    issues = validate_scheme(parse_scheme_text(assessment), files=FILES, config=CONFIG)
    assert any("exceeds the assessment maximum of 120" in issue for issue in issues), issues


def test_duplicate_heading_in_the_source_file_is_an_issue() -> None:
    files = dict(FILES)
    files[WEEK] = FILES[WEEK] + b"\n## Day 1\n\nAgain.\n"
    issues = validate_scheme(parse_scheme_text(SCHEME), files=files, config=CONFIG)
    assert any("appears 2 times" in issue for issue in issues), issues


def test_malformed_scheme_is_a_validation_error() -> None:
    with pytest.raises(SchemeValidationError):
        parse_scheme_text("schema_version: 1\ndays: [")
    with pytest.raises(SchemeValidationError, match="schema_version"):
        parse_scheme_text("schema_version: 2\nprogram: {key: x, title: X}\ndays: []")
    with pytest.raises(SchemeValidationError, match="must be a mapping"):
        parse_scheme_text("- just\n- a list\n")


def test_scheme_package_projects_onto_parsed_roadmap() -> None:
    parsed = parse_roadmap(files=_files_with_scheme(), config=CONFIG)
    assert parsed.schema_version == 2
    assert parsed.roadmap_version == "demo"
    assert [task.stable_id for task in parsed.tasks] == [
        "d01-interview",
        "d01-learning",
        "d01-close",
        "d01-fix",
        "d02-sql",
    ]
    first = parsed.tasks[0]
    assert (first.day, first.week, first.order, first.block) == (1, 1, 1, "communication_spoken")
    assert first.allowed_ai_role == "interviewer"
    assert first.procedure and first.pass_criteria
    assert first.mapping_version is not None
    correction = parsed.tasks[3]
    assert correction.block == "correction_warmup"
    assert not correction.required and correction.exercise_type is None
    assert correction.correction_selection is not None
    assert parsed.tasks[4].block == "saturday_assessment"
    assert parsed.tasks[4].allowed_ai_role == "none"
    assert parsed.scheme == {
        "rest_weekdays": [6],
        "program": {"key": "demo", "title": "Demo"},
        "lineage": None,
        "days": {
            "1": {"id": "d01", "kind": "weekday", "budget_minutes": 120},
            "2": {"id": "d02", "kind": "assessment", "budget_minutes": 60},
        },
    }
    assert parsed.exit_criteria == ()
    assert parsed.to_dict()["scheme"] == parsed.scheme
    assert len(parsed.normalized_hash) == 64


def test_scheme_package_with_issues_raises_parse_error() -> None:
    files = _files_with_scheme(SCHEME.replace("heading: P1-Q01", "heading: P1-Q99", 1))
    with pytest.raises(RoadmapParseError, match="P1-Q99"):
        parse_roadmap(files=files, config=CONFIG)


def test_scheme_package_keeps_links_that_leave_the_package() -> None:
    files = _files_with_scheme()
    files[WEEK] = FILES[WEEK] + b"\nSee [[Docs/2026-09-08 - Active Study Reforecast]].\n"
    parsed = parse_roadmap(files=files, config=CONFIG)
    assert all(item.kind == "external" or item.key in files for item in parsed.resources)


def test_scheme_package_reads_generic_exit_criteria() -> None:
    files = _files_with_scheme()
    files["docs/Exit.md"] = b"# Plan\n\n## Phase 1 exit criteria\n\n- Ship it.\n- Defend it.\n"
    parsed = parse_roadmap(files=files, config=CONFIG)
    assert [item.text for item in parsed.exit_criteria] == ["Defend it.", "Ship it."]


def test_scheme_summary_is_empty_for_legacy_and_compact_for_schemes() -> None:
    assert scheme_summary_from_payload(None) == {}
    parsed = parse_roadmap(files=_files_with_scheme(), config=CONFIG)
    assert scheme_summary_from_payload(parsed.scheme) == {
        "program": "Demo",
        "study_days": 2,
        "budget_minutes": {"1": 120, "2": 60},
    }
