from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from scripts.github.sync_issues import (
    CATALOG_COUNTS,
    GhCliClient,
    ManifestError,
    TargetNotFoundError,
    load_and_validate,
    main,
    origin_matches,
    sync_manifest,
)


class FakeGitHub:
    def __init__(self, *, preflight_error: Exception | None = None) -> None:
        self.labels: list[dict[str, Any]] = []
        self.milestones: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, int | None, dict[str, object] | None]] = []
        self.preflight_error = preflight_error

    def preflight_apply(self) -> None:
        self.calls.append(("preflight", "authorization", None, None))
        if self.preflight_error is not None:
            raise self.preflight_error

    @property
    def writes(self) -> list[tuple[str, str, int | None, dict[str, object] | None]]:
        return [call for call in self.calls if call[0] in {"create", "update"}]

    def list_labels(self) -> list[dict[str, object]]:
        self.calls.append(("list", "labels", None, None))
        return deepcopy(self.labels)

    def list_milestones(self) -> list[dict[str, object]]:
        self.calls.append(("list", "milestones", None, None))
        return deepcopy(self.milestones)

    def list_issues(self) -> list[dict[str, object]]:
        self.calls.append(("list", "issues", None, None))
        return deepcopy(self.issues)

    def create(self, resource: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("create", resource, None, deepcopy(payload)))
        collection = self._collection(resource)
        number = max((int(item.get("number", 0)) for item in collection), default=0) + 1
        item = {**self._normalize(resource, payload), "number": number}
        collection.append(item)
        return deepcopy(item)

    def update(
        self, resource: str, number: str | int, payload: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append(
            ("update", resource, number if isinstance(number, int) else None, deepcopy(payload))
        )
        collection = self._collection(resource)
        if resource == "labels":
            item = next(record for record in collection if record["name"] == number)
        else:
            item = next(record for record in collection if record["number"] == number)
        item.update(self._normalize(resource, payload))
        return deepcopy(item)

    def _normalize(self, resource: str, payload: dict[str, object]) -> dict[str, Any]:
        normalized = deepcopy(payload)
        if resource == "milestones":
            normalized.setdefault("state", "open")
        if resource == "issues":
            milestone_number = normalized.get("milestone")
            normalized["milestone"] = deepcopy(
                next(record for record in self.milestones if record["number"] == milestone_number)
            )
            labels = normalized.get("labels", [])
            assert isinstance(labels, list)
            normalized["labels"] = [
                {"name": name} for name in labels if isinstance(name, str)
            ]
            normalized.setdefault("state", "open")
        return normalized

    def _collection(self, resource: str) -> list[dict[str, Any]]:
        return {
            "labels": self.labels,
            "milestones": self.milestones,
            "issues": self.issues,
        }[resource]


@pytest.fixture
def catalog_path() -> Path:
    return Path("docs/project/github-issues.yml")


def historical_issue_records() -> list[dict[str, Any]]:
    keys = [
        *(f"E1-I{number:02}" for number in range(1, 6)),
        *(f"E2-I{number:02}" for number in range(1, 13)),
    ]
    return [
        {
            "number": 100 + index,
            "title": key,
            "body": f"<!-- tam-forge-key: {key} -->\n",
            "state": "closed",
            "labels": [],
            "milestone": None,
        }
        for index, key in enumerate(keys)
    ]


@pytest.fixture
def small_manifest(tmp_path: Path) -> Path:
    data = {
        "version": 1,
        "repository": "fgomensoro/tam-forge",
        "labels": [
            {"name": "type:epic", "color": "5319E7", "description": "Epic"},
            {"name": "type:feature", "color": "1D76DB", "description": "Feature"},
        ],
        "milestones": [
            {"key": "M0", "title": "M0 — Safe Foundation", "description": "Foundation"}
        ],
        "issues": [
            {
                "key": "E1",
                "title": "Epic: Repository safety",
                "milestone": "M0",
                "labels": ["type:epic"],
                "children": ["E1-I01", "E1-I02"],
                "acceptance": ["Both children are complete."],
                "privacy_impact": "none",
                "verification": ["make check"],
                "plan": "docs/plan.md",
                "task": "Epic E1",
            },
            {
                "key": "E1-I01",
                "title": "Bootstrap",
                "epic": "E1",
                "milestone": "M0",
                "labels": ["type:feature"],
                "depends_on": [],
                "acceptance": ["Bootstrap passes."],
                "privacy_impact": "none",
                "verification": ["make check"],
                "plan": "docs/plan.md",
                "task": "Task 1",
            },
            {
                "key": "E1-I02",
                "title": "CI",
                "epic": "E1",
                "milestone": "M0",
                "labels": ["type:feature"],
                "depends_on": ["E1-I01"],
                "acceptance": ["CI passes."],
                "privacy_impact": "none",
                "verification": ["make check"],
                "plan": "docs/plan.md",
                "task": "Task 2",
            },
        ],
    }
    execution = {
        "owner": "subagent",
        "model": "gpt-5.6-terra",
        "effort": "high",
        "reason": "Narrow deterministic catalog work with focused tests.",
        "dispatch_gate": ["A gpt-5.6-sol / ultra catalog plan is locked."],
        "escalation_triggers": ["A dependency cycle or live drift appears."],
    }
    for issue in data["issues"]:
        if "epic" in issue:
            issue["execution"] = deepcopy(execution)
    path = tmp_path / "manifest.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_catalog_transcribes_all_approved_records(catalog_path: Path) -> None:
    manifest = load_and_validate(catalog_path)
    assert manifest.repository == "fgomensoro/tam-forge"
    assert len(manifest.labels) == CATALOG_COUNTS.labels == 18
    assert len(manifest.milestones) == CATALOG_COUNTS.milestones == 5
    assert len(manifest.epics) == CATALOG_COUNTS.epics == 10
    assert len(manifest.children) == CATALOG_COUNTS.children == 115


def test_native_catalog_has_e10_and_routes_every_executable_child(
    catalog_path: Path,
) -> None:
    manifest = load_and_validate(catalog_path)
    issues = {issue.key: issue for issue in manifest.issues}

    assert CATALOG_COUNTS.labels == 18
    assert CATALOG_COUNTS.epics == 10
    assert CATALOG_COUNTS.children == 115
    assert "area/macos" in {label.name for label in manifest.labels}
    assert issues["E10"].milestone == "M0"
    assert issues["E10"].children == tuple(f"E10-I{number:02}" for number in range(1, 11))
    assert all(issue.execution is not None for issue in manifest.children)
    historical_keys = {f"E1-I{number:02}" for number in range(1, 6)} | {
        f"E2-I{number:02}" for number in range(1, 13)
    }
    assert len(historical_keys) == 17
    assert all(
        issues[key].execution is not None and issues[key].execution.status == "historical"
        for key in historical_keys
    )
    assert all(
        issue.execution is not None and issue.execution.is_executable
        for issue in manifest.children
        if issue.key not in historical_keys
    )
    assert all(
        issues[key].execution is not None and issues[key].execution.is_executable
        for key in ("E10-I09", "E10-I10")
    )
    for key, model in (
        ("E10-I09", "gpt-5.6-terra"),
        ("E10-I10", "gpt-5.6-sol"),
    ):
        execution = issues[key].execution
        assert execution is not None
        assert (execution.model, execution.effort) == (model, "xhigh")
        assert issues[key].plan == (
            "docs/superpowers/plans/2026-08-31-tam-forge-native-macos-batch-02.md"
        )
        assert any("plan is locked" in gate for gate in execution.dispatch_gate)
    executable_routes = [
        (issue.execution.model, issue.execution.effort)
        for issue in manifest.children
        if issue.execution is not None and issue.execution.is_executable
    ]
    assert len(executable_routes) == 98
    assert executable_routes.count(("gpt-5.6-sol", "xhigh")) == 61
    assert executable_routes.count(("gpt-5.6-terra", "xhigh")) == 33
    assert executable_routes.count(("gpt-5.6-terra", "high")) == 4
    assert all(
        any("gpt-5.6-sol / ultra" in gate for gate in issue.execution.dispatch_gate)
        for issue in manifest.children
        if issue.execution is not None and issue.execution.is_executable
    )

    deletion_gate_keys = {"E3-I05", "E3-I06", "E3-I09", "E4-I04", "E4-I05", "E4-I12"}
    for key in deletion_gate_keys:
        acceptance = " ".join(issues[key].acceptance).casefold()
        assert "201 created" in acceptance, key
        assert "transcript plus lineage" in acceptance, key
        assert "transcription failure retains the spool" in acceptance, key


def test_open_native_catalog_records_do_not_publish_retired_client_or_recorder_work(
    catalog_path: Path,
) -> None:
    manifest = load_and_validate(catalog_path)
    open_children = [
        issue
        for issue in manifest.children
        if issue.execution is not None and issue.execution.status != "historical"
    ]
    retired_terms = (
        "blackhole",
        "tkinter",
        "wss",
        "silero",
        "faster-whisper",
        "apps/recorder",
        "pnpm",
    )
    for issue in open_children:
        if issue.epic not in {"E3", "E4"}:
            continue
        rendered = " ".join(
            (issue.title, *issue.acceptance, *issue.verification, issue.plan, issue.task)
        ).casefold()
        assert not any(term in rendered for term in retired_terms), issue.key
    for issue in open_children:
        labels = set(issue.labels)
        if issue.epic == "E3":
            assert "area/macos" in labels
            assert "area/recorder" not in labels
        if issue.epic == "E8":
            assert "area/macos" in labels
            assert "area/web" not in labels
        if issue.epic in {"E5", "E6", "E7", "E8", "E9"} and "area/macos" in labels:
            verification = " ".join(issue.verification).casefold()
            assert "pnpm" not in verification, issue.key
            assert "apps/web" not in verification, issue.key

    native_e7_ui = {"E7-I01", "E7-I05", "E7-I06", "E7-I07", "E7-I08"}
    issues = {issue.key: issue for issue in open_children}
    for key in native_e7_ui:
        issue = issues[key]
        assert "area/macos" in issue.labels
        assert any("xcodebuild" in command for command in issue.verification)
    assert "speaker-separated" not in " ".join(issues["E7-I07"].acceptance).casefold()
    e3 = next(issue for issue in manifest.epics if issue.key == "E3")
    assert "area/macos" in e3.labels
    assert "area/recorder" not in e3.labels


def test_execution_metadata_is_validated_and_rendered_for_executable_children(
    small_manifest: Path,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    execution = {
        "owner": "subagent",
        "model": "gpt-5.6-terra",
        "effort": "high",
        "reason": "Narrow deterministic catalog work with focused tests.",
        "dispatch_gate": ["A gpt-5.6-sol / ultra catalog plan is locked."],
        "escalation_triggers": ["A dependency cycle or live drift appears."],
    }
    for issue in data["issues"]:
        if "epic" in issue:
            issue["execution"] = execution
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    manifest = load_and_validate(small_manifest, _enforce_catalog_counts=False)
    child = next(issue for issue in manifest.children if issue.key == "E1-I01")
    assert child.execution is not None
    assert child.execution.model == "gpt-5.6-terra"

    github = FakeGitHub()
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    body = str(github.issues[1]["body"])
    assert "## Execution routing" in body
    assert "**Owner:** subagent" in body
    assert "**Model / effort:** gpt-5.6-terra / high" in body
    assert "- A gpt-5.6-sol / ultra catalog plan is locked." in body


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda execution: execution.__setitem__("effort", "medium"),
            "unsupported execution model/effort pair",
        ),
        (
            lambda execution: execution.__setitem__("owner", "coordinator"),
            "unsupported execution owner/model combination",
        ),
        (
            lambda execution: execution.__setitem__(
                "dispatch_gate", ["No Ultra plan is required."]
            ),
            "executable execution requires a gpt-5.6-sol / ultra plan",
        ),
        (
            lambda execution: execution.__setitem__("dispatch_gate", []),
            "execution dispatch_gate must not be empty",
        ),
        (
            lambda execution: execution.__setitem__("escalation_triggers", []),
            "execution escalation_triggers must not be empty",
        ),
    ],
)
def test_execution_metadata_fails_closed_when_not_dispatchable(
    small_manifest: Path,
    mutate: Any,
    message: str,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    execution = {
        "owner": "subagent",
        "model": "gpt-5.6-terra",
        "effort": "high",
        "reason": "Narrow deterministic catalog work with focused tests.",
        "dispatch_gate": ["A gpt-5.6-sol / ultra catalog plan is locked."],
        "escalation_triggers": ["A dependency cycle or live drift appears."],
    }
    mutate(execution)
    data["issues"][1]["execution"] = execution
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ManifestError, match=message):
        load_and_validate(small_manifest, _enforce_catalog_counts=False)


def test_child_without_execution_metadata_fails_closed(small_manifest: Path) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    data["issues"][1].pop("execution")
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ManifestError, match="E1-I01 must define execution metadata"):
        load_and_validate(small_manifest, _enforce_catalog_counts=False)


def test_deferred_execution_requires_a_later_sol_ultra_plan_and_is_not_dispatchable(
    small_manifest: Path,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    data["issues"][1]["execution"] = {
        "status": "deferred",
        "reason": "Native parity work waits for the later batch.",
        "dispatch_gate": ["A later gpt-5.6-sol / ultra plan is locked."],
    }
    data["issues"][2]["execution"] = {
        "owner": "subagent",
        "model": "gpt-5.6-terra",
        "effort": "high",
        "reason": "Narrow deterministic catalog work with focused tests.",
        "dispatch_gate": ["A gpt-5.6-sol / ultra catalog plan is locked."],
        "escalation_triggers": ["A dependency cycle or live drift appears."],
    }
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    manifest = load_and_validate(small_manifest, _enforce_catalog_counts=False)
    child = next(issue for issue in manifest.children if issue.key == "E1-I01")
    assert child.execution is not None
    assert not child.execution.is_executable
    assert "gpt-5.6-sol / ultra" in child.execution.dispatch_gate[0]


def test_catalog_keys_and_titles_match_the_master_plan_exactly(catalog_path: Path) -> None:
    manifest = load_and_validate(catalog_path)
    master = Path(
        "docs/superpowers/plans/2026-08-25-tam-forge-master-implementation-plan.md"
    ).read_text(encoding="utf-8")
    expected_epics = {
        match.group(1): f"Epic: {match.group(2)}"
        for match in re.finditer(r"^### Epic (E\d+) — (.+)$", master, re.MULTILINE)
    }
    expected_children = {
        match.group(1): match.group(2)
        for match in re.finditer(r"^\d+\. `(E\d+-I\d{2})` (.+)\.$", master, re.MULTILINE)
    }
    assert {issue.key: issue.title for issue in manifest.epics} == expected_epics
    assert {issue.key: issue.title for issue in manifest.children} == expected_children
    assert {label.name for label in manifest.labels} == {
        "type/epic",
        "type/feature",
        "type/infrastructure",
        "type/security",
        "type/evaluation",
        "area/backend",
        "area/web",
        "area/macos",
        "area/recorder",
        "area/speech",
        "area/agents",
        "area/curriculum",
        "area/operations",
        "gate/destructive",
        "gate/privacy",
        "gate/spend",
        "gate/docker-local",
        "status/blocked",
    }
    expected_milestones = {
        "M0": "M0 — Safe Foundation",
        "M1": "M1 — Closed Spoken Loop",
        "M2": "M2 — Persistent Agents and Interviews",
        "M3": "M3 — Complete Month 1 Workspace",
        "M4": "M4 — Production and Portability",
    }
    assert {item.key: item.title for item in manifest.milestones} == expected_milestones
    expected_assignment = {
        "E1": "M0",
        "E2": "M0",
        "E3": "M1",
        "E4": "M1",
        "E5": "M1",
        "E6": "M2",
        "E7": "M2",
        "E8": "M3",
        "E9": "M4",
        "E10": "M0",
    }
    assert {epic.key: epic.milestone for epic in manifest.epics} == expected_assignment


def test_all_children_have_actionable_metadata_and_an_acyclic_dependency_dag(
    catalog_path: Path,
) -> None:
    manifest = load_and_validate(catalog_path)
    children = {issue.key: issue for issue in manifest.children}
    assert all(issue.acceptance and issue.verification for issue in children.values())
    assert not any(
        "satisfies the approved product and implementation-plan contract"
        in " ".join(issue.acceptance)
        for issue in children.values()
    )
    assert not any(
        "focused success and fail-closed tests demonstrate"
        in " ".join(issue.acceptance).lower()
        for issue in children.values()
    )
    assert len({command for issue in children.values() for command in issue.verification}) >= 20
    assert all(
        issue.privacy_impact in {"none", "low", "medium", "high"}
        for issue in children.values()
    )
    assert all("master-implementation-plan" not in issue.plan for issue in children.values())
    for issue in children.values():
        assert issue.execution is not None
        if not issue.execution.is_executable:
            continue
        plan_path = Path(issue.plan)
        assert plan_path.is_file(), issue.key
        headings = {
            line.lstrip("# ").strip()
            for line in plan_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")
        }
        assert issue.task in headings, issue.key

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise AssertionError(f"dependency cycle includes {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in children[key].depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for child_key in children:
        visit(child_key)


@pytest.mark.parametrize(
    ("key", "dependency", "verification_fragment", "privacy", "plan_fragment", "task"),
    [
        ("E1-I04", "E1-I03", "test_migrations", "low", "01-foundation", "Task 3:"),
        ("E2-I05", "E1-I04", "auth/test_service", "medium", "01-foundation", "Task 9:"),
        ("E3-I06", "E3-I05", "xcodebuild", "high", "native-macos-redesign", "6.4"),
        ("E4-I04", "E4-I03", "xcodebuild", "high", "native-macos-redesign", "7.2"),
        ("E5-I05", "E5-I04", "feedback_routes", "medium", "03-agents", "Task 8:"),
        ("E6-I08", "E6-I07", "retrieval", "high", "03-agents", "Task 10:"),
        ("E7-I06", "E7-I05", "interview", "high", "03-agents", "Task 17:"),
        ("E8-I08", "E8-I05", "portfolio", "medium", "03-agents", "Task 20:"),
        ("E9-I03", "E9-I02", "export", "high", "03-agents", "Task 23:"),
    ],
)
def test_representative_child_metadata_is_specific(
    catalog_path: Path,
    key: str,
    dependency: str,
    verification_fragment: str,
    privacy: str,
    plan_fragment: str,
    task: str,
) -> None:
    issue = next(item for item in load_and_validate(catalog_path).children if item.key == key)
    assert dependency in issue.depends_on
    assert verification_fragment in " ".join(issue.verification).lower()
    assert issue.privacy_impact == privacy
    assert plan_fragment in issue.plan
    assert issue.task.startswith(task)


def test_critical_approval_gate_labels_are_exact(catalog_path: Path) -> None:
    issues = {issue.key: set(issue.labels) for issue in load_and_validate(catalog_path).children}
    assert "gate/docker-local" in issues["E1-I04"]
    assert "gate/docker-local" in issues["E1-I05"]
    assert "gate/destructive" not in issues["E1-I06"]
    assert "gate/destructive" not in issues["E1-I07"]
    assert "gate/destructive" not in issues["E1-I08"]
    assert "gate/destructive" in issues["E1-I09"]
    assert "gate/privacy" in issues["E7-I06"]
    assert "gate/privacy" in issues["E9-I03"]


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda data: data["issues"][1].__setitem__(
                "acceptance",
                [
                    f"{data['issues'][1]['title']} satisfies the approved product "
                    "and implementation-plan contract."
                ],
            ),
            "title-restatement boilerplate",
        ),
        (
            lambda data: data["issues"][1].__setitem__(
                "acceptance",
                [
                    "Focused success and fail-closed tests demonstrate the issue title "
                    "under the invariants defined in Task 1."
                ],
            ),
            "title-restatement boilerplate",
        ),
        (
            lambda data: [
                issue.__setitem__("verification", ["make check"])
                for issue in data["issues"]
                if "epic" in issue
            ],
            "verification evidence is not sufficiently issue-specific",
        ),
        (lambda data: data["issues"][1].__setitem__("acceptance", []), "must not be empty"),
        (lambda data: data["issues"][1].__setitem__("verification", []), "must not be empty"),
        (
            lambda data: data["issues"][1].__setitem__("privacy_impact", "unbounded"),
            "privacy_impact must be one of",
        ),
        (
            lambda data: (
                data["issues"][1].__setitem__("depends_on", ["E1-I02"]),
                data["issues"][2].__setitem__("depends_on", ["E1-I01"]),
            ),
            "dependency cycle",
        ),
    ],
)
def test_catalog_content_quality_failures_precede_client_access(
    catalog_path: Path,
    tmp_path: Path,
    mutate: Any,
    error: str,
) -> None:
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "invalid-quality.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    with pytest.raises(ManifestError, match=error):
        sync_manifest(path, github, apply=True)
    assert github.calls == []


def test_second_apply_is_a_true_no_op(small_manifest: Path) -> None:
    github = FakeGitHub()
    first = sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    writes_after_first = len(github.writes)
    second = sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    assert first.created
    assert len(github.writes) == writes_after_first
    assert second.created == []
    assert second.updated == []


def test_full_catalog_second_apply_is_a_true_no_op(catalog_path: Path) -> None:
    github = FakeGitHub()
    github.issues = historical_issue_records()
    first = sync_manifest(catalog_path, github, apply=True)
    writes_after_first = len(github.writes)
    second = sync_manifest(catalog_path, github, apply=True)
    assert len(first.created) == 131
    assert len(github.labels) == 18
    assert len(github.milestones) == 5
    assert len(github.issues) == 125
    assert len(github.writes) == writes_after_first
    assert second.created == []
    assert second.updated == []


def test_dry_run_performs_zero_writes(small_manifest: Path) -> None:
    github = FakeGitHub()
    plan = sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)
    assert plan.created
    assert github.writes == []


def test_hidden_marker_identifies_issue_after_title_edit(small_manifest: Path) -> None:
    github = FakeGitHub()
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    github.issues[1]["title"] = "A title edited directly on GitHub"
    plan = sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)
    assert all(change.key != "E1-I01" or change.action == "update" for change in plan.changes)
    assert not any(change.key == "E1-I01" and change.action == "create" for change in plan.changes)


@pytest.mark.parametrize(
    "body",
    [
        "This prose mentions tam-forge-key: E1-I01.",
        "Intro first.\n<!-- tam-forge-key: E1-I01 -->\n",
        "<!-- tam-forge-key E1-I01 -->\n",
        "```\n<!-- tam-forge-key: E1-I01 -->\n```\n",
        "<!-- tam-forge-key: E1-I01 -->\n<!-- tam-forge-key: E1-I02 -->\n",
        "<!-- tam-forge-key: E1-I01 -->\nLater tam-forge-key token.\n",
    ],
)
def test_marker_like_content_must_be_one_exact_first_line_marker(
    small_manifest: Path, body: str
) -> None:
    github = FakeGitHub()
    github.issues = [
        {
            "number": 71,
            "title": "Adversarial marker",
            "body": body,
            "state": "open",
            "labels": [],
            "milestone": None,
        }
    ]
    with pytest.raises(ManifestError, match=r"issue #71.*marker"):
        sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)
    assert github.writes == []


def test_duplicate_valid_marker_claim_fails_closed_without_writes(small_manifest: Path) -> None:
    github = FakeGitHub()
    github.issues = [
        {
            "number": number,
            "title": f"Issue {number}",
            "body": "<!-- tam-forge-key: E1-I01 -->\n",
            "state": "open",
            "labels": [],
            "milestone": None,
        }
        for number in (81, 82)
    ]
    with pytest.raises(ManifestError, match="duplicate managed issue marker: E1-I01"):
        sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)
    assert github.writes == []


def test_valid_first_line_marker_is_managed(small_manifest: Path) -> None:
    github = FakeGitHub()
    github.issues = [
        {
            "number": 91,
            "title": "Edited title",
            "body": "<!-- tam-forge-key: E1-I01 -->\nExisting body\n",
            "state": "open",
            "labels": [],
            "milestone": None,
        }
    ]
    plan = sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)
    assert not any(change.key == "E1-I01" and change.action == "create" for change in plan.changes)
    assert github.writes == []


def test_bodies_have_deterministic_relationship_links(small_manifest: Path) -> None:
    github = FakeGitHub()
    first = sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    assert first.created
    epic = next(issue for issue in github.issues if "tam-forge-key: E1 " in str(issue["body"]))
    child = next(
        issue for issue in github.issues if "tam-forge-key: E1-I02 " in str(issue["body"])
    )
    assert "- [ ] #2 — E1-I01 Bootstrap" in str(epic["body"])
    assert "- [ ] #3 — E1-I02 CI" in str(epic["body"])
    assert "**Parent epic:** #1 — E1" in str(child["body"])
    assert "**Depends on:** #2 — E1-I01" in str(child["body"])


def test_labels_and_milestones_are_upserted_without_removing_unrelated(
    small_manifest: Path,
) -> None:
    github = FakeGitHub()
    github.labels = [
        {"name": "type:epic", "color": "000000", "description": "old", "number": 1},
        {"name": "external", "color": "FFFFFF", "description": "unrelated", "number": 2},
    ]
    github.milestones = [
        {"number": 1, "title": "M0 — Safe Foundation", "description": "old", "state": "open"}
    ]
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    epic_label = next(label for label in github.labels if label["name"] == "type:epic")
    external_label = next(label for label in github.labels if label["name"] == "external")
    assert epic_label["color"] == "5319E7"
    assert external_label["color"] == "FFFFFF"
    assert github.milestones[0]["description"] == "Foundation"


def test_open_managed_issues_replace_catalog_labels_but_keep_manual_labels(
    small_manifest: Path,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    data["labels"].extend(
        [
            {"name": "area/web", "color": "0E8A16", "description": "Web"},
            {"name": "area/macos", "color": "0052CC", "description": "macOS"},
            {"name": "status/blocked", "color": "B60205", "description": "Blocked"},
        ]
    )
    data["issues"][1]["labels"] = ["type:feature", "area/macos"]
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    github = FakeGitHub()
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    issue = next(item for item in github.issues if item["number"] == 2)
    issue["labels"] = [
        {"name": "type:feature"},
        {"name": "area/web"},
        {"name": "area/obsolete"},
        {"name": "gate/obsolete"},
        {"name": "type/obsolete"},
        {"name": "status/blocked"},
        {"name": "manual/triage"},
    ]

    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    assert issue["labels"] == [
        {"name": "type:feature"},
        {"name": "area/macos"},
        {"name": "manual/triage"},
        {"name": "status/blocked"},
    ]


def test_closed_managed_issues_keep_catalog_and_manual_labels_unchanged(
    small_manifest: Path,
) -> None:
    github = FakeGitHub()
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    issue = next(item for item in github.issues if item["number"] == 2)
    issue["state"] = "closed"
    issue["labels"] = [{"name": "type:feature"}, {"name": "manual/triage"}]
    writes_before = len(github.writes)

    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)

    assert issue["labels"] == [{"name": "type:feature"}, {"name": "manual/triage"}]
    assert len(github.writes) == writes_before


def test_stale_managed_issue_is_reported_but_never_closed(small_manifest: Path) -> None:
    github = FakeGitHub()
    github.issues = [
        {
            "number": 99,
            "title": "Removed issue",
            "body": "<!-- tam-forge-key: OLD-I01 -->\n",
            "state": "open",
            "labels": [],
            "milestone": None,
        }
    ]
    plan = sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    assert plan.stale == ["OLD-I01"]
    assert github.issues[0]["state"] == "open"
    assert not any(call[0] == "update" and call[2] == 99 for call in github.writes)


def test_closed_managed_issue_is_not_recreated_or_reopened(small_manifest: Path) -> None:
    github = FakeGitHub()
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    target = github.issues[1]
    target["state"] = "closed"
    target["title"] = "Bootstrap"
    writes_before = len(github.writes)
    plan = sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    assert len(github.issues) == 3
    assert target["state"] == "closed"
    assert len(github.writes) == writes_before
    assert plan.created == []
    assert plan.updated == []


def test_missing_historical_child_fails_closed_without_recreation(
    small_manifest: Path,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    data["issues"][1]["execution"] = {
        "status": "historical",
        "reason": "Closed GitHub history; never dispatch or rewrite.",
    }
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    github.issues = historical_issue_records()[:1]
    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)
    github.issues = [
        issue
        for issue in github.issues
        if "tam-forge-key: E1-I01" not in str(issue["body"])
    ]
    writes_before = len(github.writes)

    with pytest.raises(ManifestError, match="historical issue E1-I01 is missing"):
        sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)

    assert len(github.writes) == writes_before


def test_historical_child_is_not_rewritten_if_reopened_during_apply(
    small_manifest: Path,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    data["issues"][1]["execution"] = {
        "status": "historical",
        "reason": "Closed GitHub history; never dispatch or rewrite.",
    }
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    class ReopeningGitHub(FakeGitHub):
        def __init__(self) -> None:
            super().__init__()
            self.issue_reads = 0

        def list_issues(self) -> list[dict[str, object]]:
            self.issue_reads += 1
            if self.issue_reads == 2:
                self.issues[0]["state"] = "open"
                self.issues[0]["title"] = "Manually reopened historical issue"
            return super().list_issues()

    github = ReopeningGitHub()
    github.issues = historical_issue_records()[:1]
    historical_number = int(github.issues[0]["number"])

    sync_manifest(small_manifest, github, apply=True, _enforce_catalog_counts=False)

    assert github.issues[0]["state"] == "open"
    assert github.issues[0]["title"] == "Manually reopened historical issue"
    assert not any(
        call[0] == "update" and call[1] == "issues" and call[2] == historical_number
        for call in github.writes
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data["issues"].__setitem__(
                0, {**data["issues"][0], "key": "bad key"}
            ),
            "invalid key",
        ),
        (lambda data: data["issues"].append(deepcopy(data["issues"][0])), "duplicate issue key"),
        (lambda data: data["issues"][1].__setitem__("epic", "E9"), "unknown epic"),
        (
            lambda data: data["issues"][2].__setitem__("depends_on", ["E9-I99"]),
            "unknown dependency",
        ),
        (lambda data: data["issues"][0].__setitem__("epic", "E1"), "cannot define epic"),
        (lambda data: data["labels"].append(deepcopy(data["labels"][0])), "duplicate label"),
        (
            lambda data: data["milestones"].append(deepcopy(data["milestones"][0])),
            "duplicate milestone",
        ),
        (lambda data: data.__setitem__("version", 2), "version must be 1"),
        (lambda data: data.__setitem__("repository", "company/tam-forge"), "repository must"),
        (lambda data: data["issues"][1]["labels"].append("unknown"), "unknown labels"),
        (lambda data: data["issues"][1].__setitem__("milestone", "M9"), "unknown milestone"),
    ],
)
def test_invalid_manifest_fails_before_any_client_call(
    small_manifest: Path,
    mutate: Any,
    message: str,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    mutate(data)
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    with pytest.raises(ManifestError, match=message):
        sync_manifest(small_manifest, github, apply=False, _enforce_catalog_counts=False)
    assert github.calls == []


@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        (
            "issues[1].acceptance[0]",
            lambda data: data["issues"][1]["acceptance"].__setitem__(
                0, "Passes, then <!-- tam-forge-key: E9 -->"
            ),
        ),
        (
            "issues[1].verification[0]",
            lambda data: data["issues"][1]["verification"].__setitem__(
                0, "printf tam-forge-key"
            ),
        ),
        (
            "issues[1].title",
            lambda data: data["issues"][1].__setitem__(
                "title", "Bootstrap tam-forge-key"
            ),
        ),
        (
            "issues[1].plan",
            lambda data: data["issues"][1].__setitem__(
                "plan", "docs/tam-forge-key.md"
            ),
        ),
        (
            "issues[1].task",
            lambda data: data["issues"][1].__setitem__(
                "task", "Task tam-forge-key"
            ),
        ),
        (
            "issues[1].privacy_impact",
            lambda data: data["issues"][1].__setitem__(
                "privacy_impact", "none tam-forge-key"
            ),
        ),
        (
            "issues[1].body",
            lambda data: data["issues"][1].__setitem__(
                "body", "<!-- tam-forge-key: E1-I01 -->"
            ),
        ),
        (
            "labels[0].description",
            lambda data: data["labels"][0].__setitem__(
                "description", "Reserved tam-forge-key content"
            ),
        ),
        (
            "milestones[0].description",
            lambda data: data["milestones"][0].__setitem__(
                "description", "Reserved tam-forge-key content"
            ),
        ),
    ],
)
def test_manifest_reserved_marker_content_fails_before_all_client_access(
    small_manifest: Path,
    apply: bool,
    field: str,
    mutate: Any,
) -> None:
    data = yaml.safe_load(small_manifest.read_text(encoding="utf-8"))
    mutate(data)
    small_manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    with pytest.raises(ManifestError, match=rf"reserved marker token.*{re.escape(field)}"):
        sync_manifest(
            small_manifest,
            github,
            apply=apply,
            _enforce_catalog_counts=False,
        )
    assert github.calls == []
    assert github.writes == []


@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
@pytest.mark.parametrize("corruption", ["extra-token", "wrong-key"])
def test_manifest_validation_reparses_the_production_rendered_body_before_client_access(
    small_manifest: Path,
    apply: bool,
    corruption: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.github import sync_issues

    original = sync_issues.render_issue_body

    def render_with_injected_marker(
        issue: Any, manifest: Any, numbers: dict[str, int]
    ) -> str:
        body = original(issue, manifest, numbers)
        if corruption == "extra-token":
            return body + "tam-forge-key in rendered prose\n"
        return body.replace(
            f"<!-- tam-forge-key: {issue.key} -->",
            "<!-- tam-forge-key: E9 -->",
            1,
        )

    monkeypatch.setattr(sync_issues, "render_issue_body", render_with_injected_marker)
    github = FakeGitHub()
    with pytest.raises(ManifestError, match=r"rendered issue E1.*marker"):
        sync_manifest(
            small_manifest,
            github,
            apply=apply,
            _enforce_catalog_counts=False,
        )
    assert github.calls == []
    assert github.writes == []


def test_catalog_count_invariants_fail_before_client_call(
    catalog_path: Path, tmp_path: Path
) -> None:
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    data["issues"].pop()
    path = tmp_path / "wrong-count.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    with pytest.raises(ManifestError, match="exactly 115 child issues"):
        sync_manifest(path, github, apply=False)
    assert github.calls == []


def test_cli_defaults_to_dry_run_and_apply_is_explicit(
    catalog_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    github.issues = historical_issue_records()
    monkeypatch.setattr("scripts.github.sync_issues.GhCliClient", lambda _repo: github)
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: True)
    assert (
        main(
            [
                "--repo",
                "fgomensoro/tam-forge",
                "--manifest",
                str(catalog_path),
            ]
        )
        == 0
    )
    assert github.writes == []
    assert "DRY RUN" in capsys.readouterr().out

    assert main([
        "--repo", "fgomensoro/tam-forge", "--manifest", str(catalog_path), "--apply"
    ]) == 0
    assert github.writes


def test_cli_has_no_catalog_count_bypass(catalog_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--repo",
                "fgomensoro/tam-forge",
                "--manifest",
                str(catalog_path),
                "--allow-test-catalog",
            ]
        )


@pytest.mark.parametrize("apply", [False, True])
def test_cli_rejects_wrong_catalog_counts_before_any_api_call(
    catalog_path: Path,
    tmp_path: Path,
    apply: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    data["issues"].pop()
    invalid_path = tmp_path / "wrong-count.yml"
    invalid_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    monkeypatch.setattr("scripts.github.sync_issues.GhCliClient", lambda _repo: github)
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: True)
    arguments = [
        "--repo",
        "fgomensoro/tam-forge",
        "--manifest",
        str(invalid_path),
    ]
    if apply:
        arguments.append("--apply")
    with pytest.raises(ManifestError, match="exactly 115 child issues"):
        main(arguments)
    assert github.calls == []


def test_apply_preflight_failure_precedes_all_catalog_reads_and_writes(catalog_path: Path) -> None:
    github = FakeGitHub(preflight_error=PermissionError("authorization failed"))
    with pytest.raises(PermissionError, match="authorization failed"):
        sync_manifest(catalog_path, github, apply=True)
    assert github.calls == [("preflight", "authorization", None, None)]


@pytest.mark.parametrize(
    ("user", "repository", "error"),
    [
        ({"login": "company", "id": 102269369}, None, "authenticated login"),
        ({"login": "fgomensoro", "id": 7}, None, "authenticated user ID"),
        (
            {"login": "fgomensoro", "id": 102269369},
            {
                "full_name": "company/tam-forge",
                "private": True,
                "owner": {"login": "fgomensoro", "id": 102269369},
            },
            "repository identity",
        ),
        (
            {"login": "fgomensoro", "id": 102269369},
            {
                "full_name": "fgomensoro/tam-forge",
                "private": True,
                "owner": {"login": "company", "id": 102269369},
            },
            "repository owner login",
        ),
        (
            {"login": "fgomensoro", "id": 102269369},
            {
                "full_name": "fgomensoro/tam-forge",
                "private": True,
                "owner": {"login": "fgomensoro", "id": 7},
            },
            "repository owner ID",
        ),
        (
            {"login": "fgomensoro", "id": 102269369},
            {
                "full_name": "fgomensoro/tam-forge",
                "private": False,
                "owner": {"login": "fgomensoro", "id": 102269369},
            },
            "private",
        ),
    ],
)
def test_apply_preflight_rejects_wrong_identity_or_privacy(
    user: dict[str, object],
    repository: dict[str, object] | None,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: True)

    def fake_json(command: list[str], *, input_text: str | None = None) -> object:
        if command[-1] == "user":
            return user
        assert repository is not None
        return repository

    monkeypatch.setattr(GhCliClient, "_run_json", staticmethod(fake_json))
    with pytest.raises(PermissionError, match=error):
        GhCliClient("fgomensoro/tam-forge").preflight_apply()


def test_apply_preflight_rejects_absent_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: True)

    def fake_json(command: list[str], *, input_text: str | None = None) -> object:
        if command[-1] == "user":
            return {"login": "fgomensoro", "id": 102269369}
        raise TargetNotFoundError("target repository was not found")

    monkeypatch.setattr(GhCliClient, "_run_json", staticmethod(fake_json))
    with pytest.raises(TargetNotFoundError):
        GhCliClient("fgomensoro/tam-forge").preflight_apply()


def test_apply_preflight_rejects_host_environment_or_origin_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GhCliClient("fgomensoro/tam-forge")
    monkeypatch.setenv("GH_HOST", "enterprise.example")
    with pytest.raises(PermissionError, match="GitHub host"):
        client.preflight_apply()
    monkeypatch.delenv("GH_HOST")
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: False)
    with pytest.raises(PermissionError, match="origin"):
        client.preflight_apply()


def test_apply_preflight_accepts_exact_private_personal_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: True)
    responses: list[object] = [
        {"login": "fgomensoro", "id": 102269369},
        {
            "full_name": "fgomensoro/tam-forge",
            "private": True,
            "owner": {"login": "fgomensoro", "id": 102269369},
        },
    ]
    monkeypatch.setattr(
        GhCliClient,
        "_run_json",
        staticmethod(lambda command, *, input_text=None: responses.pop(0)),
    )
    GhCliClient("fgomensoro/tam-forge").preflight_apply()
    assert responses == []


def test_apply_preflight_gh_calls_are_host_bound_argv_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.setattr("scripts.github.sync_issues.origin_matches", lambda _repo: True)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        payload: object
        if command[-1] == "user":
            payload = {"login": "fgomensoro", "id": 102269369}
        else:
            payload = {
                "full_name": "fgomensoro/tam-forge",
                "private": True,
                "owner": {"login": "fgomensoro", "id": 102269369},
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    GhCliClient("fgomensoro/tam-forge").preflight_apply()
    assert len(calls) == 2
    for command, kwargs in calls:
        assert command[:4] == ["gh", "api", "--hostname", "github.com"]
        assert command[4:6] == ["--method", "GET"]
        assert kwargs["input"] is None
        assert "shell" not in kwargs


def test_cli_rejects_repository_mismatch(small_manifest: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--repo", "someone/else", "--manifest", str(small_manifest)])


def test_gh_cli_uses_argument_arrays_and_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        page_argument = next(item for item in command if item.startswith("page="))
        page = int(page_argument.removeprefix("page="))
        payload = [{"name": f"label-{index}"} for index in range(100)] if page == 1 else []
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = GhCliClient("fgomensoro/tam-forge")
    assert len(client.list_labels()) == 100
    assert len(calls) == 2
    assert all(isinstance(command, list) for command, _kwargs in calls)
    assert all(command[:2] == ["gh", "api"] for command, _kwargs in calls)
    assert all("--hostname" in command for command, _kwargs in calls)
    assert all("github.com" in command for command, _kwargs in calls)
    assert all("--paginate" not in command for command, _kwargs in calls)
    assert all("shell" not in kwargs for _command, kwargs in calls)


def test_gh_cli_sends_write_payload_only_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, '{"number": 1}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    payload: dict[str, object] = {
        "name": "$(touch /tmp/never-run)",
        "color": "000000",
        "description": "`whoami`",
    }
    GhCliClient("fgomensoro/tam-forge").create("labels", payload)
    command, kwargs = calls[0]
    assert command == [
        "gh",
        "api",
        "--hostname",
        "github.com",
        "--method",
        "POST",
        "repos/fgomensoro/tam-forge/labels",
        "--input",
        "-",
    ]
    assert kwargs["input"] == json.dumps(payload, separators=(",", ":"))
    assert "shell" not in kwargs


def test_gh_cli_lists_open_and_closed_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    GhCliClient("fgomensoro/tam-forge").list_issues()
    assert "state=all" in calls[0]
    assert "per_page=100" in calls[0]


def test_gh_cli_rejects_unapproved_resource_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    with pytest.raises(ValueError, match="unsupported GitHub planning resource"):
        GhCliClient("fgomensoro/tam-forge").create("actions/secrets", {})


@pytest.mark.parametrize(
    ("remote", "matches"),
    [
        ("https://github.com/fgomensoro/tam-forge.git\n", True),
        ("git@github.com:fgomensoro/tam-forge.git\n", True),
        ("https://evilgithub.com/fgomensoro/tam-forge.git\n", False),
        ("https://github.com/company/tam-forge.git\n", False),
    ],
)
def test_origin_match_requires_exact_github_owner_and_host(
    remote: str, matches: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, remote, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert origin_matches("fgomensoro/tam-forge") is matches


def test_local_catalog_cli_dry_run_is_offline_safe(catalog_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/github/sync_issues.py",
            "--repo",
            "fgomensoro/tam-forge",
            "--manifest",
            str(catalog_path),
            "--dry-run",
            "--offline",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "125 issue" in result.stdout
    assert "DRY RUN" in result.stdout
