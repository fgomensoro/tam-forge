#!/usr/bin/env python3
"""Synchronize the approved TAM Forge issue catalog through ``gh api``.

The manifest is fully validated and a complete change plan is built before an
apply can perform its first write. Dry-run is the default. When this checkout
does not yet have the target repository configured as ``origin``, dry-run uses
an empty remote snapshot so the private repository can be planned before it
exists without invoking GitHub.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote

import yaml  # type: ignore[import-untyped]

EXPECTED_REPOSITORY = "fgomensoro/tam-forge"
EXPECTED_GITHUB_HOST = "github.com"
EXPECTED_OWNER_LOGIN = "fgomensoro"
EXPECTED_OWNER_ID = 102269369
MARKER_TOKEN = "tam-forge-key"
MARKER_PATTERN = re.compile(r"^<!-- tam-forge-key: ([A-Z][A-Z0-9-]*) -->$")
EPIC_KEY_PATTERN = re.compile(r"E[1-9][0-9]*")
CHILD_KEY_PATTERN = re.compile(r"E[1-9][0-9]*-I[0-9]{2}")
HEX_COLOR_PATTERN = re.compile(r"[0-9A-Fa-f]{6}")
PRIVACY_LEVELS = {"none", "low", "medium", "high"}


class ManifestError(ValueError):
    """Raised when the manifest is unsafe or internally inconsistent."""


class TargetNotFoundError(RuntimeError):
    """Raised when GitHub reports that the target repository does not exist."""


@dataclass(frozen=True)
class CatalogCounts:
    labels: int = 17
    milestones: int = 5
    epics: int = 9
    children: int = 105


CATALOG_COUNTS = CatalogCounts()


@dataclass(frozen=True)
class LabelSpec:
    name: str
    color: str
    description: str


@dataclass(frozen=True)
class MilestoneSpec:
    key: str
    title: str
    description: str


@dataclass(frozen=True)
class IssueSpec:
    key: str
    title: str
    milestone: str
    labels: tuple[str, ...]
    acceptance: tuple[str, ...]
    privacy_impact: str
    verification: tuple[str, ...]
    plan: str
    task: str
    children: tuple[str, ...] = ()
    epic: str | None = None
    depends_on: tuple[str, ...] = ()

    @property
    def is_epic(self) -> bool:
        return bool(self.children)


@dataclass(frozen=True)
class Manifest:
    version: int
    repository: str
    labels: tuple[LabelSpec, ...]
    milestones: tuple[MilestoneSpec, ...]
    issues: tuple[IssueSpec, ...]

    @property
    def epics(self) -> tuple[IssueSpec, ...]:
        return tuple(issue for issue in self.issues if issue.is_epic)

    @property
    def children(self) -> tuple[IssueSpec, ...]:
        return tuple(issue for issue in self.issues if not issue.is_epic)


@dataclass(frozen=True)
class Change:
    action: str
    resource: str
    key: str
    identifier: str | int | None
    payload: dict[str, object]


@dataclass
class SyncPlan:
    manifest: Manifest
    changes: list[Change] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    applied_writes: int = 0

    @property
    def created(self) -> list[Change]:
        return [change for change in self.changes if change.action == "create"]

    @property
    def updated(self) -> list[Change]:
        return [change for change in self.changes if change.action == "update"]


class GhClient(Protocol):
    def preflight_apply(self) -> None: ...

    def list_labels(self) -> list[dict[str, object]]: ...

    def list_milestones(self) -> list[dict[str, object]]: ...

    def list_issues(self) -> list[dict[str, object]]: ...

    def create(self, resource: str, payload: dict[str, object]) -> dict[str, object]: ...

    def update(
        self, resource: str, identifier: str | int, payload: dict[str, object]
    ) -> dict[str, object]: ...


class EmptyGhClient:
    """Read-only empty state used for an offline pre-repository dry-run."""

    def preflight_apply(self) -> None:
        raise PermissionError("offline client cannot be authorized for apply")

    def list_labels(self) -> list[dict[str, object]]:
        return []

    def list_milestones(self) -> list[dict[str, object]]:
        return []

    def list_issues(self) -> list[dict[str, object]]:
        return []

    def create(self, resource: str, payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("offline dry-run client cannot write")

    def update(
        self, resource: str, identifier: str | int, payload: dict[str, object]
    ) -> dict[str, object]:
        raise RuntimeError("offline dry-run client cannot write")


class GhCliClient:
    """Minimal, injection-safe wrapper around ``gh api`` argument arrays."""

    def __init__(self, repository: str) -> None:
        if repository != EXPECTED_REPOSITORY:
            raise ValueError("unsupported repository")
        self.repository = repository

    def preflight_apply(self) -> None:
        """Bind apply to Frank's exact private personal github.com repository."""

        configured_host = os.environ.get("GH_HOST", "").strip()
        if configured_host and configured_host != EXPECTED_GITHUB_HOST:
            raise PermissionError("GitHub host must be github.com")
        if not origin_matches(self.repository):
            raise PermissionError("origin must be the exact private personal GitHub repository")

        user = self._preflight_mapping(self._get("user"), "authenticated user")
        if user.get("login") != EXPECTED_OWNER_LOGIN:
            raise PermissionError("authenticated login is not the approved personal owner")
        if user.get("id") != EXPECTED_OWNER_ID:
            raise PermissionError("authenticated user ID is not the approved immutable owner ID")

        repository = self._preflight_mapping(
            self._get(f"repos/{self.repository}"), "target repository"
        )
        if repository.get("full_name") != EXPECTED_REPOSITORY:
            raise PermissionError(
                "target repository identity does not match the approved repository"
            )
        owner = self._preflight_mapping(repository.get("owner"), "repository owner")
        if owner.get("login") != EXPECTED_OWNER_LOGIN:
            raise PermissionError("repository owner login is not the approved personal owner")
        if owner.get("id") != EXPECTED_OWNER_ID:
            raise PermissionError("repository owner ID is not the approved immutable owner ID")
        if repository.get("private") is not True:
            raise PermissionError("target repository must be private")

    def _get(self, endpoint: str) -> object:
        return self._run_json(
            [
                "gh",
                "api",
                "--hostname",
                EXPECTED_GITHUB_HOST,
                "--method",
                "GET",
                endpoint,
            ]
        )

    @staticmethod
    def _preflight_mapping(value: object, context: str) -> dict[str, object]:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise PermissionError(f"{context} response is invalid")
        return cast(dict[str, object], value)

    def list_labels(self) -> list[dict[str, object]]:
        return self._list("labels")

    def list_milestones(self) -> list[dict[str, object]]:
        return self._list("milestones", state="all")

    def list_issues(self) -> list[dict[str, object]]:
        records = self._list("issues", state="all")
        return [record for record in records if "pull_request" not in record]

    def _list(self, resource: str, **parameters: str) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        page = 1
        while True:
            command = [
                "gh",
                "api",
                "--hostname",
                EXPECTED_GITHUB_HOST,
                "--method",
                "GET",
                f"repos/{self.repository}/{resource}",
                "-f",
                "per_page=100",
                "-f",
                f"page={page}",
            ]
            for key, value in sorted(parameters.items()):
                command.extend(["-f", f"{key}={value}"])
            page_records = self._run_json(command)
            if not isinstance(page_records, list):
                raise RuntimeError(f"GitHub returned non-list data for {resource}")
            typed_records = [
                cast(dict[str, object], item) for item in page_records if isinstance(item, dict)
            ]
            records.extend(typed_records)
            if len(typed_records) < 100:
                break
            page += 1
        return records

    def create(self, resource: str, payload: dict[str, object]) -> dict[str, object]:
        self._validate_resource(resource)
        endpoint = f"repos/{self.repository}/{resource}"
        result = self._request("POST", endpoint, payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"GitHub returned invalid {resource} create response")
        return cast(dict[str, object], result)

    def update(
        self, resource: str, identifier: str | int, payload: dict[str, object]
    ) -> dict[str, object]:
        self._validate_resource(resource)
        safe_identifier = quote(str(identifier), safe="")
        endpoint = f"repos/{self.repository}/{resource}/{safe_identifier}"
        result = self._request("PATCH", endpoint, payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"GitHub returned invalid {resource} update response")
        return cast(dict[str, object], result)

    def _request(self, method: str, endpoint: str, payload: dict[str, object]) -> object:
        command = [
            "gh",
            "api",
            "--hostname",
            EXPECTED_GITHUB_HOST,
            "--method",
            method,
            endpoint,
            "--input",
            "-",
        ]
        return self._run_json(command, input_text=json.dumps(payload, separators=(",", ":")))

    @staticmethod
    def _validate_resource(resource: str) -> None:
        if resource not in {"labels", "milestones", "issues"}:
            raise ValueError("unsupported GitHub planning resource")

    @staticmethod
    def _run_json(command: list[str], *, input_text: str | None = None) -> object:
        completed = subprocess.run(
            command,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            error = completed.stderr.lower()
            if "http 404" in error or "not found" in error:
                raise TargetNotFoundError("target repository was not found")
            raise RuntimeError("gh api request failed; inspect gh authentication separately")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("gh api returned invalid JSON") from exc


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ManifestError(f"{context} must be a mapping")
    return cast(dict[str, object], value)


def _list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestError(f"{context} must be a list")
    return cast(list[object], value)


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context} must be a non-empty string")
    return value.strip()


def _strings(value: object, context: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    records = _list(value, context)
    parsed = tuple(_string(record, f"{context} item") for record in records)
    if not parsed and not allow_empty:
        raise ManifestError(f"{context} must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ManifestError(f"{context} contains duplicates")
    return parsed


def _require_exact_fields(
    record: dict[str, object], required: set[str], optional: set[str], context: str
) -> None:
    missing = required - record.keys()
    unknown = record.keys() - required - optional
    if missing:
        raise ManifestError(f"{context} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ManifestError(f"{context} has unknown fields: {', '.join(sorted(unknown))}")


def load_and_validate(path: Path, *, _enforce_catalog_counts: bool = True) -> Manifest:
    """Parse and validate every manifest invariant before client access."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"cannot load manifest: {exc}") from exc
    root = _mapping(raw, "manifest")
    _require_exact_fields(
        root,
        {"version", "repository", "labels", "milestones", "issues"},
        set(),
        "manifest",
    )
    if root["version"] != 1:
        raise ManifestError("manifest version must be 1")
    repository = _string(root["repository"], "repository")
    if repository != EXPECTED_REPOSITORY:
        raise ManifestError(f"repository must be {EXPECTED_REPOSITORY}")

    labels: list[LabelSpec] = []
    for index, item in enumerate(_list(root["labels"], "labels")):
        record = _mapping(item, f"label {index}")
        _require_exact_fields(record, {"name", "color", "description"}, set(), f"label {index}")
        color = _string(record["color"], f"label {index} color")
        if not HEX_COLOR_PATTERN.fullmatch(color):
            raise ManifestError(f"label {index} color must be six hexadecimal characters")
        labels.append(
            LabelSpec(
                name=_string(record["name"], f"label {index} name"),
                color=color.upper(),
                description=_string(record["description"], f"label {index} description"),
            )
        )

    milestones: list[MilestoneSpec] = []
    for index, item in enumerate(_list(root["milestones"], "milestones")):
        record = _mapping(item, f"milestone {index}")
        _require_exact_fields(
            record, {"key", "title", "description"}, set(), f"milestone {index}"
        )
        milestones.append(
            MilestoneSpec(
                key=_string(record["key"], f"milestone {index} key"),
                title=_string(record["title"], f"milestone {index} title"),
                description=_string(record["description"], f"milestone {index} description"),
            )
        )

    issues: list[IssueSpec] = []
    common_required = {
        "key",
        "title",
        "milestone",
        "labels",
        "acceptance",
        "privacy_impact",
        "verification",
        "plan",
        "task",
    }
    for index, item in enumerate(_list(root["issues"], "issues")):
        record = _mapping(item, f"issue {index}")
        _require_exact_fields(
            record,
            common_required,
            {"children", "epic", "depends_on"},
            f"issue {index}",
        )
        key = _string(record["key"], f"issue {index} key")
        is_epic_key = EPIC_KEY_PATTERN.fullmatch(key) is not None
        is_child_key = CHILD_KEY_PATTERN.fullmatch(key) is not None
        if not (is_epic_key or is_child_key):
            raise ManifestError(f"invalid key {key!r}")
        children = _strings(record.get("children", []), f"issue {key} children", allow_empty=True)
        epic_raw = record.get("epic")
        epic = _string(epic_raw, f"issue {key} epic") if epic_raw is not None else None
        depends = _strings(
            record.get("depends_on", []), f"issue {key} depends_on", allow_empty=True
        )
        if is_epic_key:
            if not children:
                raise ManifestError(f"epic {key} must define children")
            if epic is not None or depends:
                raise ManifestError(f"epic {key} cannot define epic or dependencies")
        else:
            if children:
                raise ManifestError(f"child {key} cannot define children")
            if epic is None:
                raise ManifestError(f"child {key} must define epic")
        privacy_impact = _string(record["privacy_impact"], f"issue {key} privacy_impact")
        if privacy_impact not in PRIVACY_LEVELS:
            raise ManifestError(
                f"issue {key} privacy_impact must be one of {sorted(PRIVACY_LEVELS)}"
            )
        issues.append(
            IssueSpec(
                key=key,
                title=_string(record["title"], f"issue {key} title"),
                milestone=_string(record["milestone"], f"issue {key} milestone"),
                labels=_strings(record["labels"], f"issue {key} labels"),
                acceptance=_strings(record["acceptance"], f"issue {key} acceptance"),
                privacy_impact=privacy_impact,
                verification=_strings(record["verification"], f"issue {key} verification"),
                plan=_string(record["plan"], f"issue {key} plan"),
                task=_string(record["task"], f"issue {key} task"),
                children=children,
                epic=epic,
                depends_on=depends,
            )
        )

    _reject_duplicates([label.name for label in labels], "label name")
    _reject_duplicates([milestone.key for milestone in milestones], "milestone key")
    _reject_duplicates([milestone.title for milestone in milestones], "milestone title")
    _reject_duplicates([issue.key for issue in issues], "issue key")
    label_names = {label.name for label in labels}
    milestone_keys = {milestone.key for milestone in milestones}
    issue_by_key = {issue.key: issue for issue in issues}
    epic_keys = {issue.key for issue in issues if issue.is_epic}
    child_keys = set(issue_by_key) - epic_keys

    manifest = Manifest(
        version=1,
        repository=repository,
        labels=tuple(labels),
        milestones=tuple(milestones),
        issues=tuple(issues),
    )
    if _enforce_catalog_counts:
        _validate_catalog_counts(manifest)

    for issue in manifest.children:
        if issue.epic not in epic_keys:
            raise ManifestError(f"issue {issue.key} has unknown epic {issue.epic}")

    for issue in issues:
        unknown_labels = set(issue.labels) - label_names
        if unknown_labels:
            raise ManifestError(f"issue {issue.key} uses unknown labels: {sorted(unknown_labels)}")
        if issue.milestone not in milestone_keys:
            raise ManifestError(f"issue {issue.key} uses unknown milestone {issue.milestone}")

    for issue in issues:
        if issue.is_epic:
            for child_key in issue.children:
                if child_key not in child_keys:
                    raise ManifestError(f"epic {issue.key} has unknown child {child_key}")
                child = issue_by_key[child_key]
                if child.epic != issue.key:
                    raise ManifestError(
                        f"invalid relationship direction: {child_key} does not point to {issue.key}"
                    )
                if child.milestone != issue.milestone:
                    raise ManifestError(f"child {child_key} must share milestone with {issue.key}")
        else:
            parent = issue_by_key[cast(str, issue.epic)]
            if issue.key not in parent.children:
                raise ManifestError(
                    "invalid relationship direction: "
                    f"{issue.key} missing from {parent.key} children"
                )
            for dependency in issue.depends_on:
                if dependency not in child_keys:
                    raise ManifestError(f"issue {issue.key} has unknown dependency {dependency}")
                if dependency == issue.key:
                    raise ManifestError(f"issue {issue.key} cannot depend on itself")

    _validate_dependency_dag(manifest.children)
    if _enforce_catalog_counts:
        _validate_catalog_content_quality(manifest)

    return manifest


def _reject_duplicates(values: list[str], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ManifestError(f"duplicate {field_name}: {value}")
        seen.add(value)


def _validate_catalog_counts(manifest: Manifest) -> None:
    if len(manifest.labels) != CATALOG_COUNTS.labels:
        raise ManifestError(f"catalog must contain exactly {CATALOG_COUNTS.labels} labels")
    if len(manifest.milestones) != CATALOG_COUNTS.milestones:
        raise ManifestError(f"catalog must contain exactly {CATALOG_COUNTS.milestones} milestones")
    if len(manifest.epics) != CATALOG_COUNTS.epics:
        raise ManifestError(f"catalog must contain exactly {CATALOG_COUNTS.epics} epics")
    if len(manifest.children) != CATALOG_COUNTS.children:
        raise ManifestError(f"catalog must contain exactly {CATALOG_COUNTS.children} child issues")
    expected_epics = {f"E{number}" for number in range(1, 10)}
    if {issue.key for issue in manifest.epics} != expected_epics:
        raise ManifestError("catalog epic keys must be exactly E1 through E9")


def _validate_dependency_dag(children: tuple[IssueSpec, ...]) -> None:
    by_key = {issue.key: issue for issue in children}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ManifestError(f"dependency cycle includes {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in by_key[key].depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)


def _validate_catalog_content_quality(manifest: Manifest) -> None:
    placeholder = "satisfies the approved product and implementation-plan contract"
    generated_prefix = "focused success and fail-closed tests demonstrate"
    if any(
        placeholder in " ".join(issue.acceptance).lower()
        or generated_prefix in " ".join(issue.acceptance).lower()
        for issue in manifest.children
    ):
        raise ManifestError("catalog acceptance criteria contain title-restatement boilerplate")
    commands = {command for issue in manifest.children for command in issue.verification}
    if len(commands) < 20:
        raise ManifestError("catalog verification evidence is not sufficiently issue-specific")
    for issue in manifest.children:
        if "master-implementation-plan" in issue.plan:
            raise ManifestError(f"issue {issue.key} must point to an executable child plan")
        if re.fullmatch(r"Task [0-9]+: .+", issue.task) is None:
            raise ManifestError(f"issue {issue.key} must name its executable plan task")


def marker(key: str) -> str:
    return f"<!-- tam-forge-key: {key} -->"


def managed_key_from_issue(issue: dict[str, object]) -> str | None:
    """Return one unambiguous first-line marker or fail closed on marker-like content."""

    body = issue.get("body")
    if not isinstance(body, str) or MARKER_TOKEN not in body.lower():
        return None
    number = issue.get("number")
    context = f"issue #{number}" if isinstance(number, int) else "issue with unknown number"
    lines = body.splitlines()
    first_line = lines[0] if lines else ""
    match = MARKER_PATTERN.fullmatch(first_line)
    if match is None or body.lower().count(MARKER_TOKEN) != 1:
        raise ManifestError(
            f"{context} has invalid managed marker; require one exact marker on the first line"
        )
    return match.group(1)


def render_issue_body(issue: IssueSpec, manifest: Manifest, numbers: dict[str, int]) -> str:
    lines = [
        marker(issue.key),
        "",
        f"**Plan:** `{issue.plan}`",
        f"**Task:** {issue.task}",
        f"**Privacy impact:** {issue.privacy_impact}",
    ]
    issue_by_key = {record.key: record for record in manifest.issues}
    if issue.is_epic:
        lines.extend(["", "## Child issues"])
        for child_key in issue.children:
            child = issue_by_key[child_key]
            prefix = f"#{numbers[child_key]} — " if child_key in numbers else ""
            lines.append(f"- [ ] {prefix}{child_key} {child.title}")
    else:
        assert issue.epic is not None
        parent_prefix = f"#{numbers[issue.epic]} — " if issue.epic in numbers else ""
        lines.extend(["", f"**Parent epic:** {parent_prefix}{issue.epic}"])
        if issue.depends_on:
            dependencies = []
            for dependency in issue.depends_on:
                prefix = f"#{numbers[dependency]} — " if dependency in numbers else ""
                dependencies.append(f"{prefix}{dependency}")
            lines.append(f"**Depends on:** {', '.join(dependencies)}")
        else:
            lines.append("**Depends on:** None")
    lines.extend(["", "## Acceptance criteria"])
    lines.extend(f"- [ ] {item}" for item in issue.acceptance)
    lines.extend(["", "## Verification"])
    lines.extend(f"- `{command}`" for command in issue.verification)
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CurrentState:
    labels: tuple[dict[str, object], ...]
    milestones: tuple[dict[str, object], ...]
    issues: tuple[dict[str, object], ...]


def load_current_state(client: GhClient) -> CurrentState:
    return CurrentState(
        labels=tuple(client.list_labels()),
        milestones=tuple(client.list_milestones()),
        issues=tuple(client.list_issues()),
    )


def build_sync_plan(manifest: Manifest, current: CurrentState) -> SyncPlan:
    """Build a deterministic write plan without mutating the client."""

    plan = SyncPlan(manifest=manifest)
    labels_by_name = {
        _required_current_string(item, "name", "label"): item for item in current.labels
    }
    milestones_by_title = {
        _required_current_string(item, "title", "milestone"): item for item in current.milestones
    }
    issue_by_key: dict[str, dict[str, object]] = {}
    numbers: dict[str, int] = {}
    for item in current.issues:
        key = managed_key_from_issue(item)
        if key is None:
            continue
        if key in issue_by_key:
            first_number = issue_by_key[key].get("number")
            second_number = item.get("number")
            raise ManifestError(
                f"duplicate managed issue marker: {key} on issues "
                f"#{first_number} and #{second_number}"
            )
        issue_by_key[key] = item
        number = item.get("number")
        if isinstance(number, int):
            numbers[key] = number

    for label in manifest.labels:
        desired: dict[str, object] = {
            "name": label.name,
            "color": label.color,
            "description": label.description,
        }
        existing = labels_by_name.get(label.name)
        if existing is None:
            plan.changes.append(Change("create", "labels", label.name, None, desired))
        elif _label_changed(existing, label):
            plan.changes.append(Change("update", "labels", label.name, label.name, desired))

    for milestone in manifest.milestones:
        desired = {"title": milestone.title, "description": milestone.description, "state": "open"}
        existing = milestones_by_title.get(milestone.title)
        if existing is None:
            plan.changes.append(Change("create", "milestones", milestone.key, None, desired))
        elif _milestone_changed(existing, milestone):
            number = _required_current_int(existing, "number", "milestone")
            plan.changes.append(Change("update", "milestones", milestone.key, number, desired))

    milestone_title_by_key = {item.key: item.title for item in manifest.milestones}
    for issue in manifest.issues:
        existing = issue_by_key.get(issue.key)
        desired_labels = list(issue.labels)
        if existing is not None:
            desired_labels = sorted(set(desired_labels) | _current_label_names(existing))
        desired = {
            "title": issue.title,
            "body": render_issue_body(issue, manifest, numbers),
            "labels": desired_labels,
            "milestone_title": milestone_title_by_key[issue.milestone],
        }
        if existing is None:
            plan.changes.append(Change("create", "issues", issue.key, None, desired))
            continue
        if existing.get("state", "open") == "closed":
            continue
        if _issue_changed(existing, desired):
            number = _required_current_int(existing, "number", "issue")
            plan.changes.append(Change("update", "issues", issue.key, number, desired))

    managed_keys = set(issue_by_key)
    manifest_keys = {issue.key for issue in manifest.issues}
    plan.stale = sorted(managed_keys - manifest_keys)
    return plan


def _required_current_string(item: dict[str, object], key: str, resource: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"GitHub {resource} response is missing string {key}")
    return value


def _required_current_int(item: dict[str, object], key: str, resource: str) -> int:
    value = item.get(key)
    if not isinstance(value, int):
        raise RuntimeError(f"GitHub {resource} response is missing integer {key}")
    return value


def _label_changed(existing: dict[str, object], desired: LabelSpec) -> bool:
    return (
        str(existing.get("color", "")).upper() != desired.color
        or existing.get("description", "") != desired.description
    )


def _milestone_changed(existing: dict[str, object], desired: MilestoneSpec) -> bool:
    return (
        existing.get("description", "") != desired.description
        or existing.get("state", "open") != "open"
    )


def _current_label_names(issue: dict[str, object]) -> set[str]:
    result: set[str] = set()
    labels = issue.get("labels", [])
    if not isinstance(labels, list):
        return result
    for item in labels:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            result.add(cast(str, item["name"]))
    return result


def _current_milestone_title(issue: dict[str, object]) -> str | None:
    milestone = issue.get("milestone")
    if milestone is None:
        return None
    if isinstance(milestone, str):
        return milestone
    if isinstance(milestone, dict) and isinstance(milestone.get("title"), str):
        return cast(str, milestone["title"])
    return None


def _issue_changed(existing: dict[str, object], desired: dict[str, object]) -> bool:
    return (
        existing.get("title") != desired["title"]
        or existing.get("body", "") != desired["body"]
        or _current_label_names(existing) != set(cast(list[str], desired["labels"]))
        or _current_milestone_title(existing) != desired["milestone_title"]
    )


def apply_sync_plan(plan: SyncPlan, client: GhClient) -> None:
    """Apply a validated plan in dependency-safe phases, without deletions."""

    for resource in ("labels", "milestones"):
        for change in [item for item in plan.changes if item.resource == resource]:
            _apply_change(change, client)
            plan.applied_writes += 1

    milestone_numbers = {
        _required_current_string(item, "title", "milestone"): _required_current_int(
            item, "number", "milestone"
        )
        for item in client.list_milestones()
    }
    current_issues = list(client.list_issues())
    issues_by_key = {
        key: item
        for item in current_issues
        if (key := managed_key_from_issue(item)) is not None
    }
    issue_changes = [item for item in plan.changes if item.resource == "issues"]
    issue_order = {issue.key: index for index, issue in enumerate(plan.manifest.issues)}
    issue_changes.sort(key=lambda item: issue_order[item.key])
    for change in issue_changes:
        payload = _materialize_issue_payload(change.payload, milestone_numbers)
        if change.action == "create":
            result = client.create("issues", payload)
            issues_by_key[change.key] = result
        else:
            assert change.identifier is not None
            result = client.update("issues", change.identifier, payload)
            issues_by_key[change.key] = result
        plan.applied_writes += 1

    # New issue numbers are only known after creation. Re-render all open managed
    # bodies once, then patch only records whose relationship links changed.
    numbers = {
        key: _required_current_int(item, "number", "issue") for key, item in issues_by_key.items()
    }
    milestone_title_by_key = {item.key: item.title for item in plan.manifest.milestones}
    for issue in plan.manifest.issues:
        existing = issues_by_key[issue.key]
        if existing.get("state", "open") == "closed":
            continue
        desired: dict[str, object] = {
            "title": issue.title,
            "body": render_issue_body(issue, plan.manifest, numbers),
            "labels": sorted(set(issue.labels) | _current_label_names(existing)),
            "milestone_title": milestone_title_by_key[issue.milestone],
        }
        if _issue_changed(existing, desired):
            number = _required_current_int(existing, "number", "issue")
            payload = _materialize_issue_payload(desired, milestone_numbers)
            issues_by_key[issue.key] = client.update("issues", number, payload)
            plan.applied_writes += 1


def _apply_change(change: Change, client: GhClient) -> dict[str, object]:
    if change.action == "create":
        return client.create(change.resource, change.payload)
    if change.action == "update" and change.identifier is not None:
        return client.update(change.resource, change.identifier, change.payload)
    raise RuntimeError(f"unsupported planned change: {change}")


def _materialize_issue_payload(
    desired: dict[str, object], milestone_numbers: dict[str, int]
) -> dict[str, object]:
    title = cast(str, desired["milestone_title"])
    if title not in milestone_numbers:
        raise RuntimeError(f"GitHub milestone was not available after upsert: {title}")
    return {
        "title": desired["title"],
        "body": desired["body"],
        "labels": desired["labels"],
        "milestone": milestone_numbers[title],
    }


def sync_manifest(
    path: Path,
    client: GhClient,
    *,
    apply: bool,
    _enforce_catalog_counts: bool = True,
) -> SyncPlan:
    manifest = load_and_validate(path, _enforce_catalog_counts=_enforce_catalog_counts)
    if apply:
        client.preflight_apply()
    current = load_current_state(client)
    plan = build_sync_plan(manifest, current)
    if apply:
        apply_sync_plan(plan, client)
    return plan


def origin_matches(repository: str) -> bool:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    remote = completed.stdout.strip().removesuffix(".git")
    allowed = {
        f"https://github.com/{repository}",
        f"ssh://git@github.com/{repository}",
        f"git@github.com:{repository}",
    }
    return remote in allowed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Expected owner/repository")
    parser.add_argument("--manifest", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="Plan changes without writes (default)"
    )
    mode.add_argument("--apply", action="store_true", help="Explicitly apply planned changes")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use an empty remote snapshot; valid only for dry-run",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    repository = cast(str, args.repo)
    if repository != EXPECTED_REPOSITORY:
        parser.error(f"--repo must equal {EXPECTED_REPOSITORY}")
    if args.offline and args.apply:
        parser.error("--offline cannot be combined with --apply")
    apply = bool(args.apply)
    offline = bool(args.offline) or (not apply and not origin_matches(repository))
    if apply and not origin_matches(repository):
        parser.error("--apply requires origin to be the private target repository")
    client: GhClient = EmptyGhClient() if offline else GhCliClient(repository)
    try:
        plan = sync_manifest(
            cast(Path, args.manifest),
            client,
            apply=apply,
        )
    except TargetNotFoundError:
        if apply:
            raise
        plan = sync_manifest(
            cast(Path, args.manifest),
            EmptyGhClient(),
            apply=False,
        )
        offline = True
    mode = "APPLY" if apply else "DRY RUN"
    suffix = " (offline empty state)" if offline else ""
    print(f"{mode}{suffix}: {len(plan.manifest.issues)} issue records")
    print(
        f"planned create={len(plan.created)} update={len(plan.updated)} "
        f"stale={len(plan.stale)} applied_writes={plan.applied_writes}"
    )
    for change in plan.changes:
        print(f"{change.action:6} {change.resource:10} {change.key}")
    for key in plan.stale:
        print(f"stale  issues     {key} (reported only; never auto-closed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
