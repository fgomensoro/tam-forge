"""Pure parser for reviewed roadmap mappings and staged source bytes."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from ..evidence.config_models import ConfigBundle, RoadmapTaskConfig
from .contracts import (
    NormalizedCorrectionSelection,
    NormalizedExitCriterion,
    NormalizedProcedureStep,
    NormalizedResource,
    NormalizedTask,
    NormalizedTaskContract,
    ParsedRoadmap,
)

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.+?)\s*$")


class RoadmapParseError(ValueError):
    """Raised when reviewed map or source package semantics are invalid."""


@dataclass(frozen=True, slots=True)
class _ResourceAccumulator:
    kind: str
    labels: set[str]
    source_paths: set[str]


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _visible_lines(markdown: str) -> tuple[str, ...]:
    visible: list[str] = []
    fence_marker: str | None = None
    for line in markdown.splitlines():
        match = _FENCE.match(line)
        if match is not None:
            marker = match.group(1)[0]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            continue
        if fence_marker is None:
            visible.append(line)
    return tuple(visible)


def _decode_markdown(files: Mapping[str, bytes]) -> dict[str, str]:
    markdown: dict[str, str] = {}
    for path, payload in files.items():
        if path.lower().endswith(".md"):
            try:
                markdown[path] = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise RoadmapParseError(f"{path} must contain valid UTF-8 Markdown") from exc
    return markdown


def _headings(markdown: Mapping[str, str]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for path, content in markdown.items():
        counts: dict[str, int] = {}
        for line in _visible_lines(content):
            match = _HEADING.match(line)
            if match is None:
                continue
            heading = _text(match.group(2))
            counts[heading] = counts.get(heading, 0) + 1
        result[path] = counts
    return result


def _safe_local_target(source_path: str, raw_target: str) -> str:
    target = unicodedata.normalize("NFC", raw_target.split("#", 1)[0].replace("\\", "/"))
    if not target:
        return source_path
    if target.startswith("/") or re.match(r"^[A-Za-z]:", target):
        raise RoadmapParseError(f"resource reference {raw_target!r} is outside the roadmap package")
    source_parent = PurePosixPath(source_path).parent.as_posix()
    joined = posixpath.normpath(posixpath.join(source_parent, target))
    if joined == ".." or joined.startswith("../"):
        raise RoadmapParseError(f"resource reference {raw_target!r} is outside the roadmap package")
    return joined


def _resolve_local_resource(
    *,
    source_path: str,
    target: str,
    files: Mapping[str, bytes],
    obsidian: bool,
) -> str:
    candidates: list[str] = []
    if obsidian:
        root_target = unicodedata.normalize("NFC", target.split("#", 1)[0])
        if root_target.startswith("/") or re.match(r"^[A-Za-z]:", root_target):
            raise RoadmapParseError(f"resource reference {target!r} is outside the roadmap package")
        if root_target != ".." and not root_target.startswith("../"):
            candidates.append(root_target)
        candidates.append(_safe_local_target(source_path, target))
    else:
        candidates.append(_safe_local_target(source_path, target))
    expanded: list[str] = []
    for candidate in candidates:
        if not candidate:
            candidate = source_path
        expanded.append(candidate)
        if not PurePosixPath(candidate).suffix:
            expanded.append(f"{candidate}.md")
    for candidate in expanded:
        if candidate in files:
            return candidate
    raise RoadmapParseError(f"referenced local resource {target!r} from {source_path!r} is missing")


def _resources(
    files: Mapping[str, bytes],
    markdown: Mapping[str, str],
) -> tuple[NormalizedResource, ...]:
    accumulated: dict[str, _ResourceAccumulator] = {}

    def add(key: str, kind: str, label: str, source_path: str) -> None:
        existing = accumulated.get(key)
        if existing is None:
            existing = _ResourceAccumulator(kind=kind, labels=set(), source_paths=set())
            accumulated[key] = existing
        if existing.kind != kind:
            raise RoadmapParseError(f"resource {key!r} has conflicting kinds")
        existing.labels.add(_text(label))
        existing.source_paths.add(source_path)

    for source_path, content in markdown.items():
        visible = "\n".join(_visible_lines(content))
        for match in _WIKI_LINK.finditer(visible):
            target = _text(match.group(1))
            label = match.group(2) or target
            resolved = _resolve_local_resource(
                source_path=source_path,
                target=target,
                files=files,
                obsidian=True,
            )
            add(resolved, "local", label, source_path)
        without_wiki = _WIKI_LINK.sub("", visible)
        for match in _MARKDOWN_LINK.finditer(without_wiki):
            label = match.group(1)
            target = match.group(2)
            split = urlsplit(target)
            if split.scheme:
                if split.scheme not in {"http", "https"} or not split.netloc:
                    raise RoadmapParseError(f"unsupported resource URL {target!r}")
                add(target, "external", label, source_path)
            else:
                resolved = _resolve_local_resource(
                    source_path=source_path,
                    target=target,
                    files=files,
                    obsidian=False,
                )
                add(resolved, "local", label, source_path)
    return tuple(
        NormalizedResource(
            key=key,
            kind="external" if item.kind == "external" else "local",
            labels=tuple(sorted(item.labels)),
            source_paths=tuple(sorted(item.source_paths)),
        )
        for key, item in sorted(accumulated.items())
    )


def _exit_criteria(markdown: Mapping[str, str]) -> tuple[NormalizedExitCriterion, ...]:
    sources: dict[str, set[str]] = {}
    for path, content in markdown.items():
        active_level: int | None = None
        for line in _visible_lines(content):
            heading = _HEADING.match(line)
            if heading is not None:
                level = len(heading.group(1))
                title = _text(heading.group(2)).casefold()
                if title == "month 1 exit criteria":
                    active_level = level
                elif active_level is not None and level <= active_level:
                    active_level = None
                continue
            if active_level is None:
                continue
            item = _LIST_ITEM.match(line)
            if item is not None:
                criterion = _text(item.group(1))
                sources.setdefault(criterion, set()).add(path)
    if not sources:
        raise RoadmapParseError("roadmap package must define Month 1 exit criteria")
    return tuple(
        NormalizedExitCriterion(text=text, source_paths=tuple(sorted(paths)))
        for text, paths in sorted(sources.items())
    )


def _correction(task: RoadmapTaskConfig) -> NormalizedCorrectionSelection | None:
    selection = task.correction_selection
    if selection is None:
        return None
    return NormalizedCorrectionSelection(
        source=selection.source,
        maximum_items=selection.maximum_items,
        allowed_kinds=tuple(sorted(selection.allowed_kinds)),
        inherits_core_prompt=selection.inherits_core_prompt,
        inherits_original_exercise=selection.inherits_original_exercise,
        inherits_original_mapping_version=selection.inherits_original_mapping_version,
        no_attempt_c=selection.no_attempt_c,
        skill_level_effect=selection.skill_level_effect,
    )


def _task(task: RoadmapTaskConfig) -> NormalizedTask:
    return NormalizedTask(
        stable_id=task.stable_id,
        month=task.month,
        week=task.week,
        day=task.day,
        block=task.block,
        order=task.order,
        source_path=task.source_path,
        source_heading=task.source_heading,
        exercise_type=task.exercise_type,
        mapping_version=task.mapping_version,
        required=task.required,
        timebox_minutes=task.timebox_minutes,
        objective=task.objective,
        required_output=task.required_output,
        pass_criteria=task.pass_criteria,
        evidence_requirements=task.evidence_requirements,
        procedure=tuple(
            NormalizedProcedureStep(
                phase=step.phase,
                minutes=step.minutes,
                requirement=step.requirement,
            )
            for step in task.procedure
        ),
        constraints=task.constraints,
        correction_selection=_correction(task),
        allowed_ai_role=task.allowed_ai_role,
    )


def _contract(task: NormalizedTask) -> NormalizedTaskContract:
    return NormalizedTaskContract(
        stable_id=task.stable_id,
        required_output=task.required_output,
        pass_criteria=task.pass_criteria,
        evidence_requirements=task.evidence_requirements,
        procedure=task.procedure,
        constraints=task.constraints,
        correction_selection=task.correction_selection,
    )


def _validate_tasks(
    tasks: tuple[RoadmapTaskConfig, ...],
    *,
    config: ConfigBundle,
    files: Mapping[str, bytes],
    headings: Mapping[str, Mapping[str, int]],
) -> None:
    seen_ids: set[str] = set()
    seen_orders: set[tuple[int, int, int]] = set()
    totals: dict[int, int] = {}
    days: set[int] = set()
    for task in tasks:
        if task.stable_id in seen_ids:
            raise RoadmapParseError(f"duplicate task ID {task.stable_id!r}")
        seen_ids.add(task.stable_id)
        order_key = (task.week, task.day, task.order)
        if order_key in seen_orders:
            raise RoadmapParseError(f"duplicate task order for day {task.day}")
        seen_orders.add(order_key)
        if task.source_path not in files:
            raise RoadmapParseError(f"source file {task.source_path!r} is missing")
        heading_count = headings.get(task.source_path, {}).get(task.source_heading, 0)
        if heading_count == 0:
            raise RoadmapParseError(
                f"source heading {task.source_heading!r} is missing from {task.source_path!r}"
            )
        if heading_count > 1:
            raise RoadmapParseError(
                f"{task.source_path} contains duplicate Markdown heading {task.source_heading!r}"
            )
        expected_week = ((task.day - 1) // 6) + 1
        if task.week != expected_week:
            raise RoadmapParseError(f"task {task.stable_id!r} has an invalid week/day pair")
        if task.block == "correction_warmup":
            if task.exercise_type is not None or task.mapping_version is not None:
                raise RoadmapParseError("correction task must inherit exercise and mapping")
        else:
            if task.exercise_type is None or task.mapping_version is None:
                raise RoadmapParseError("ordinary task requires exercise and mapping")
            try:
                exercise = config.exercise(task.exercise_type)
            except KeyError as exc:
                raise RoadmapParseError(f"unknown exercise {task.exercise_type!r}") from exc
            if exercise.mapping_version != task.mapping_version:
                raise RoadmapParseError(
                    f"unknown mapping version {task.mapping_version!r} for {task.exercise_type!r}"
                )
        totals[task.day] = totals.get(task.day, 0) + task.timebox_minutes
        days.add(task.day)
    if days != set(range(1, 25)):
        raise RoadmapParseError("task map must define all 24 Month 1 study days and no Sundays")
    for day, total in sorted(totals.items()):
        if day % 6 == 0:
            if total > 120:
                raise RoadmapParseError(f"Saturday {day} exceeds 120 minutes")
        elif total != 240:
            raise RoadmapParseError(f"weekday {day} must total exactly 240 minutes")


def parse_roadmap(*, files: Mapping[str, bytes], config: ConfigBundle) -> ParsedRoadmap:
    """Validate source links and return a canonical reviewed runtime projection."""
    markdown = _decode_markdown(files)
    headings = _headings(markdown)
    source_tasks = tuple(
        sorted(
            config.roadmap_tasks,
            key=lambda item: (item.week, item.day, item.order, item.stable_id),
        )
    )
    _validate_tasks(source_tasks, config=config, files=files, headings=headings)
    tasks = tuple(_task(item) for item in source_tasks)
    contracts = tuple(_contract(item) for item in tasks)
    resources = _resources(files, markdown)
    exit_criteria = _exit_criteria(markdown)
    payload = {
        "schema_version": 1,
        "roadmap_version": config.roadmap_version,
        "tasks": [item.to_dict() for item in tasks],
        "contracts": [item.to_dict() for item in contracts],
        "resources": [item.to_dict() for item in resources],
        "exit_criteria": [item.to_dict() for item in exit_criteria],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ParsedRoadmap(
        schema_version=1,
        roadmap_version=config.roadmap_version,
        tasks=tasks,
        contracts=contracts,
        resources=resources,
        exit_criteria=exit_criteria,
        normalized_hash=hashlib.sha256(canonical).hexdigest(),
    )
