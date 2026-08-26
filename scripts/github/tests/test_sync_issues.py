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
    load_and_validate,
    main,
    origin_matches,
    sync_manifest,
)


class FakeGitHub:
    def __init__(self) -> None:
        self.labels: list[dict[str, Any]] = []
        self.milestones: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, int | None, dict[str, object] | None]] = []

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
        number = len(collection) + 1
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
                "privacy_impact": "No private learner data.",
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
                "privacy_impact": "No private learner data.",
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
                "privacy_impact": "No private learner data.",
                "verification": ["make check"],
                "plan": "docs/plan.md",
                "task": "Task 2",
            },
        ],
    }
    path = tmp_path / "manifest.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_catalog_transcribes_all_approved_records(catalog_path: Path) -> None:
    manifest = load_and_validate(catalog_path)
    assert manifest.repository == "fgomensoro/tam-forge"
    assert len(manifest.labels) == CATALOG_COUNTS.labels == 17
    assert len(manifest.milestones) == CATALOG_COUNTS.milestones == 5
    assert len(manifest.epics) == CATALOG_COUNTS.epics == 9
    assert len(manifest.children) == CATALOG_COUNTS.children == 105


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
    }
    assert {epic.key: epic.milestone for epic in manifest.epics} == expected_assignment


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
    first = sync_manifest(catalog_path, github, apply=True)
    writes_after_first = len(github.writes)
    second = sync_manifest(catalog_path, github, apply=True)
    assert len(first.created) == 136
    assert len(github.labels) == 17
    assert len(github.milestones) == 5
    assert len(github.issues) == 114
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


def test_catalog_count_invariants_fail_before_client_call(
    catalog_path: Path, tmp_path: Path
) -> None:
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    data["issues"].pop()
    path = tmp_path / "wrong-count.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    github = FakeGitHub()
    with pytest.raises(ManifestError, match="exactly 105 child issues"):
        sync_manifest(path, github, apply=False)
    assert github.calls == []


def test_cli_defaults_to_dry_run_and_apply_is_explicit(
    catalog_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
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
    with pytest.raises(ManifestError, match="exactly 105 child issues"):
        main(arguments)
    assert github.calls == []


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
    assert "114 issue" in result.stdout
    assert "DRY RUN" in result.stdout
