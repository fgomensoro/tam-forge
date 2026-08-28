"""Load, link, and content-address checked-in scoring YAML."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, DecimalException
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode

from .config_models import (
    CanonicalConfigPayload,
    ConfigBundle,
    ExerciseTypeConfig,
    ExerciseTypesFile,
    RoadmapTaskMapFile,
    RubricsFile,
    SkillConfig,
    SkillsFile,
    immutable_index,
)

_FILES = {
    "skills": "tam-skills.yaml",
    "exercise_types": "tam-exercise-types.yaml",
    "rubrics": "tam-rubrics.yaml",
    "roadmap_tasks": "tam-roadmap-task-map.yaml",
}
_MAX_CONFIG_BYTES = 2 * 1024 * 1024
_MAX_YAML_DEPTH = 64
_MAX_YAML_NODES = 20_000


class ConfigError(ValueError):
    """Configuration failed strict parsing or cross-file linking."""


class _LocatedDict(dict[str, Any]):
    __slots__ = ("line", "column")

    line: int
    column: int


class _StrictLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._config_depth = 0
        self._config_nodes = 0

    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        if self.check_event(AliasEvent):
            event = self.get_event()  # type: ignore[no-untyped-call]
            raise ComposerError(
                "while composing configuration",
                event.start_mark,
                "YAML aliases are not allowed",
                event.start_mark,
            )
        self._config_depth += 1
        self._config_nodes += 1
        event = self.peek_event()  # type: ignore[no-untyped-call]
        try:
            if self._config_depth > _MAX_YAML_DEPTH:
                raise ComposerError(
                    "while composing configuration",
                    event.start_mark,
                    f"YAML exceeds maximum depth {_MAX_YAML_DEPTH}",
                    event.start_mark,
                )
            if self._config_nodes > _MAX_YAML_NODES:
                raise ComposerError(
                    "while composing configuration",
                    event.start_mark,
                    f"YAML exceeds node limit {_MAX_YAML_NODES}",
                    event.start_mark,
                )
            return super().compose_node(parent, index)
        finally:
            self._config_depth -= 1


def _construct_mapping(loader: _StrictLoader, node: MappingNode, deep: bool = False) -> Any:
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "YAML merge keys are not allowed",
                key_node.start_mark,
            )
    loader.flatten_mapping(node)
    result = _LocatedDict()
    result.line = node.start_mark.line + 1
    result.column = node.start_mark.column + 1
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "configuration keys must be strings",
                key_node.start_mark,
            )
        if key in result:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


def _construct_decimal(loader: _StrictLoader, node: ScalarNode) -> Decimal:
    scalar = loader.construct_scalar(node)
    try:
        value = Decimal(scalar.replace("_", ""))
    except (DecimalException, ValueError) as exc:
        raise ConstructorError(
            "while constructing a decimal",
            node.start_mark,
            "configuration number must be a finite decimal",
            node.start_mark,
        ) from exc
    if not value.is_finite():
        raise ConstructorError(
            "while constructing a decimal",
            node.start_mark,
            "configuration number must be a finite decimal",
            node.start_mark,
        )
    return value


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)
_StrictLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)


def _location(value: object) -> tuple[int, int]:
    if isinstance(value, _LocatedDict):
        return value.line, value.column
    return 1, 1


def _at(path: Path, value: object, message: str) -> ConfigError:
    line, column = _location(value)
    return ConfigError(f"{path}:{line}:{column}: {message}")


def _descend(value: object, location: tuple[str | int, ...]) -> object:
    current = value
    located = value
    for part in location:
        if isinstance(part, str) and isinstance(current, dict):
            current = current.get(part, current)
        elif isinstance(part, int) and isinstance(current, list) and part < len(current):
            current = current[part]
        if isinstance(current, _LocatedDict):
            located = current
    return current if isinstance(current, _LocatedDict) else located


def _load_yaml[Model: BaseModel](path: Path, model: type[Model]) -> tuple[Model, object]:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"{path}:1:1: unable to read configuration") from exc
    if len(raw_bytes) > _MAX_CONFIG_BYTES:
        raise ConfigError(f"{path}:1:1: configuration exceeds size limit")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}:1:1: configuration must be UTF-8") from exc
    try:
        raw = yaml.load(text, Loader=_StrictLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        line = mark.line + 1 if mark else 1
        column = mark.column + 1 if mark else 1
        message = exc.problem or "invalid YAML"
        raise ConfigError(f"{path}:{line}:{column}: {message}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}:1:1: configuration root must be a mapping")
    try:
        return model.model_validate(raw), raw
    except ValidationError as exc:
        error = exc.errors(include_url=False)[0]
        target = _descend(raw, tuple(error["loc"]))
        line, column = _location(target)
        field = ".".join(str(part) for part in error["loc"])
        raise ConfigError(
            f"{path}:{line}:{column}: {field}: {error['msg']}"
        ) from exc


def _unique(
    values: tuple[Any, ...], attribute: str, *, path: Path, raw_items: object
) -> None:
    seen: set[str] = set()
    source_items = raw_items if isinstance(raw_items, list) else []
    for index, value in enumerate(values):
        key = str(getattr(value, attribute))
        if key in seen:
            source = source_items[index] if index < len(source_items) else raw_items
            raise _at(path, source, f"duplicate {attribute} {key!r}")
        seen.add(key)


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ConfigError("<config>:1:1: configuration number must be a finite decimal")
    if value == 0:
        return "0"
    try:
        rendered = format(value.normalize(), "f")
    except (DecimalException, OverflowError, ValueError) as exc:
        raise ConfigError("<config>:1:1: configuration decimal is out of bounds") from exc
    if len(rendered) > 128:
        raise ConfigError("<config>:1:1: configuration decimal is out of bounds")
    return rendered


def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python", by_alias=True))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_text(value)
    return value


def _canonical_payload(
    skills: SkillsFile,
    exercises: ExerciseTypesFile,
    rubrics: RubricsFile,
    roadmap: RoadmapTaskMapFile,
) -> dict[str, Any]:
    skill_payload = skills.model_dump(mode="python", by_alias=True)
    skill_payload["skills"] = sorted(skill_payload["skills"], key=lambda item: item["slug"])

    exercise_payload = exercises.model_dump(mode="python", by_alias=True)
    exercise_payload["supporting_tags"] = sorted(exercise_payload["supporting_tags"])
    for item in exercise_payload["exercise_types"]:
        item["skill_impacts"] = sorted(
            item["skill_impacts"], key=lambda impact: impact["skill_slug"]
        )
        item["tags"] = sorted(item["tags"])
        item["allowed_domain_competencies"] = sorted(
            item["allowed_domain_competencies"]
        )
        item["allowed_story_competencies"] = sorted(
            item["allowed_story_competencies"]
        )
        item["composite_metrics"] = sorted(
            item["composite_metrics"], key=lambda metric: metric["metric_slug"]
        )
    exercise_payload["exercise_types"] = sorted(
        exercise_payload["exercise_types"], key=lambda item: item["slug"]
    )

    rubric_payload = rubrics.model_dump(mode="python", by_alias=True)
    rubric_payload["rubrics"] = sorted(
        rubric_payload["rubrics"], key=lambda item: (item["slug"], item["version"])
    )

    roadmap_payload = roadmap.model_dump(mode="python", by_alias=True)
    roadmap_payload["reconciliations"] = sorted(
        roadmap_payload["reconciliations"], key=lambda item: item["slug"]
    )
    roadmap_payload["tasks"] = sorted(
        roadmap_payload["tasks"],
        key=lambda item: (item["week"], item["day"], item["order"], item["stable_id"]),
    )

    return _canonical(
        {
            "skills": skill_payload,
            "exercise_types": exercise_payload,
            "rubrics": rubric_payload,
            "roadmap_tasks": roadmap_payload,
        }
    )  # type: ignore[return-value]


def _payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _link_exercises(
    config: ExerciseTypesFile,
    raw: object,
    path: Path,
    skills: dict[str, SkillConfig],
) -> None:
    raw_items = raw.get("exercise_types", []) if isinstance(raw, dict) else []
    _unique(config.exercise_types, "slug", path=path, raw_items=raw_items)
    for index, exercise in enumerate(config.exercise_types):
        source = raw_items[index] if index < len(raw_items) else raw
        if exercise.mapping_version != config.mapping_version:
            raise _at(path, source, "exercise item mapping version must match release")
        impact_slugs = [impact.skill_slug for impact in exercise.impacts]
        if len(impact_slugs) != len(set(impact_slugs)):
            raise _at(path, source, f"duplicate skill impact in {exercise.slug!r}")
        unknown = set(impact_slugs) - skills.keys()
        if unknown:
            raise _at(path, source, f"unknown skill {sorted(unknown)[0]!r}")
        unknown_tags = set(exercise.tags) - config.supporting_tags
        if unknown_tags:
            raise _at(path, source, f"unknown tag {sorted(unknown_tags)[0]!r}")
        if exercise.slug in {
            "official_reading",
            "company_product_research",
            "application_or_outreach",
        } and exercise.impacts:
            raise _at(path, source, f"{exercise.slug} must not impact skills")
        english = exercise.skill_impacts.get("tam_english")
        if english is not None and english.condition not in {
            "spoken_or_written_english",
            "explained_aloud_in_english",
        }:
            raise _at(path, source, "TAM English impact must require produced English")
        if exercise.allowed_selected_competencies:
            if len(exercise.allowed_selected_competencies) != len(
                set(exercise.allowed_selected_competencies)
            ):
                raise _at(path, source, "duplicate selected skill")
            unknown_selected = set(exercise.allowed_selected_competencies) - skills.keys()
            if unknown_selected:
                raise _at(
                    path,
                    source,
                    f"unknown selected skill {sorted(unknown_selected)[0]!r}",
                )
            if set(impact_slugs) & set(exercise.allowed_selected_competencies):
                raise _at(path, source, "selected skill duplicates a fixed impact")
        metric_slugs = [metric.metric_slug for metric in exercise.composite_metrics]
        if len(metric_slugs) != len(set(metric_slugs)):
            raise _at(path, source, f"duplicate composite metric in {exercise.slug!r}")
        if set(metric_slugs) - {"portfolio_judgment"}:
            raise _at(path, source, "unknown composite metric")
        if exercise.slug == "portfolio_triage":
            if exercise.composite_metric_weights != {"portfolio_judgment": Decimal("1")}:
                raise _at(path, source, "portfolio_triage composite metric is required")
        elif exercise.composite_metrics:
            raise _at(path, source, "composite metric is not allowed for this exercise")

    exercises = {item.slug: item for item in config.exercise_types}
    for index, exercise in enumerate(config.exercise_types):
        source = raw_items[index] if index < len(raw_items) else raw
        for child in exercise.child_exercise_type_refs:
            linked = exercises.get(child.exercise_type)
            if linked is None:
                raise _at(path, source, f"unknown child exercise {child.exercise_type!r}")
            if linked.mapping_version != child.mapping_version:
                raise _at(path, source, f"unknown mapping version for {child.exercise_type!r}")


def _link_rubrics(config: RubricsFile, raw: object, path: Path) -> None:
    raw_items = raw.get("rubrics", []) if isinstance(raw, dict) else []
    _unique(config.rubrics, "slug", path=path, raw_items=raw_items)
    for index, rubric in enumerate(config.rubrics):
        source = raw_items[index] if index < len(raw_items) else raw
        source_mapping = source if isinstance(source, dict) else {}
        _unique(
            rubric.dimensions,
            "slug",
            path=path,
            raw_items=source_mapping.get("dimensions", []),
        )
    portfolio = next((item for item in config.rubrics if item.slug == "portfolio_judgment"), None)
    if portfolio is None:
        raise _at(path, raw, "portfolio_judgment rubric is required")
    if sum(item.maximum for item in portfolio.dimensions) != Decimal("20"):
        raise _at(path, raw, "Portfolio Judgment dimensions must total exactly 20")
    if sum(item.weight for item in portfolio.dimensions) != Decimal("1"):
        raise _at(path, raw, "Portfolio Judgment dimension weights must total exactly 1")


def _link_tasks(
    config: RoadmapTaskMapFile,
    raw: object,
    path: Path,
    exercises: dict[str, ExerciseTypeConfig],
) -> None:
    raw_items = raw.get("tasks", []) if isinstance(raw, dict) else []
    _unique(config.tasks, "stable_id", path=path, raw_items=raw_items)
    seen_orders: set[tuple[int, int, int]] = set()
    totals: dict[tuple[int, int], int] = {}
    for index, task in enumerate(config.tasks):
        source = raw_items[index] if index < len(raw_items) else raw
        expected_week = ((task.day - 1) // 6) + 1
        if task.week != expected_week:
            raise _at(path, source, "task week does not match Month 1 day")
        if task.block != "correction_warmup":
            if task.exercise_type is None or task.mapping_version is None:
                raise _at(path, source, "non-correction task requires exercise and mapping")
            linked = exercises.get(task.exercise_type)
            if linked is None:
                raise _at(path, source, f"unknown exercise type {task.exercise_type!r}")
            if linked.mapping_version != task.mapping_version:
                raise _at(path, source, f"unknown mapping version for {task.exercise_type!r}")
        pure_path = PurePosixPath(task.source_path)
        if pure_path.is_absolute() or ".." in pure_path.parts or "\\" in task.source_path:
            raise _at(path, source, "source path must be a safe relative POSIX path")
        order_key = (task.week, task.day, task.order)
        if order_key in seen_orders:
            raise _at(path, source, "duplicate task order within day")
        seen_orders.add(order_key)
        totals[(task.week, task.day)] = totals.get((task.week, task.day), 0) + task.timebox_minutes

    expected_days = {
        (week, day)
        for week in range(1, 5)
        for day in range((week - 1) * 6 + 1, week * 6 + 1)
    }
    if totals.keys() != expected_days:
        raise _at(path, raw, "task map must define all 24 Month 1 study days")
    for key, total in totals.items():
        expected = 120 if key[1] % 6 == 0 else 240
        if total != expected:
            raise _at(path, raw, f"day {key[1]} must total exactly {expected} minutes")

    weekday_shape = (
        ("sql", 45),
        ("technical_learning", 45),
        ("career_pipeline", 30),
        ("correction_warmup", 10),
        ("tam_case", 60),
        ("communication_spoken", 35),
        ("daily_close", 15),
    )
    for week, day in sorted(key for key in expected_days if key[1] % 6):
        tasks = sorted(
            (task for task in config.tasks if (task.week, task.day) == (week, day)),
            key=lambda task: task.order,
        )
        actual_shape = tuple((task.block, task.timebox_minutes) for task in tasks)
        if actual_shape != weekday_shape:
            raise _at(path, raw, f"weekday {day} must use the exact block shape")

    task_by_id = {task.stable_id: task for task in config.tasks}
    reconciliation_items = (
        raw.get("reconciliations", []) if isinstance(raw, dict) else []
    )
    _unique(
        config.reconciliations,
        "slug",
        path=path,
        raw_items=reconciliation_items,
    )
    for index, reconciliation in enumerate(config.reconciliations):
        source = (
            reconciliation_items[index]
            if index < len(reconciliation_items)
            else raw
        )
        target_task = task_by_id.get(reconciliation.target_task_id)
        if target_task is None:
            raise _at(path, source, "reconciliation target task does not exist")
        if reconciliation.executable_text != target_task.objective:
            raise _at(path, source, "reconciliation executable text must match task objective")
        if (reconciliation.source_path, reconciliation.source_heading) != (
            target_task.source_path,
            target_task.source_heading,
        ):
            raise _at(path, source, "reconciliation source must match task provenance")


def load_config_bundle(
    config_dir: Path,
    *,
    skills_path: Path | None = None,
    exercise_types_path: Path | None = None,
    rubrics_path: Path | None = None,
    roadmap_tasks_path: Path | None = None,
) -> ConfigBundle:
    """Load all four files, reject ambiguity, and return linked immutable data."""
    paths = {
        "skills": skills_path or config_dir / _FILES["skills"],
        "exercise_types": exercise_types_path or config_dir / _FILES["exercise_types"],
        "rubrics": rubrics_path or config_dir / _FILES["rubrics"],
        "roadmap_tasks": roadmap_tasks_path or config_dir / _FILES["roadmap_tasks"],
    }
    skills_file, skills_raw = _load_yaml(paths["skills"], SkillsFile)
    exercise_file, exercise_raw = _load_yaml(paths["exercise_types"], ExerciseTypesFile)
    rubrics_file, rubrics_raw = _load_yaml(paths["rubrics"], RubricsFile)
    roadmap_file, roadmap_raw = _load_yaml(paths["roadmap_tasks"], RoadmapTaskMapFile)

    return _build_bundle(
        skills_file,
        exercise_file,
        rubrics_file,
        roadmap_file,
        raws={
            "skills": skills_raw,
            "exercise_types": exercise_raw,
            "rubrics": rubrics_raw,
            "roadmap_tasks": roadmap_raw,
        },
        paths=paths,
    )


def load_config_payload(payload: object) -> ConfigBundle:
    """Validate and reconstruct a bundle from its persisted canonical payload."""
    try:
        detached = json.loads(json.dumps(payload))
        parsed = CanonicalConfigPayload.model_validate(detached)
    except (TypeError, ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            error = exc.errors(include_url=False)[0]
            message = error["msg"]
        else:
            message = str(exc)
        raise ConfigError(f"canonical-payload:1:1: {message}") from exc

    raws = {
        "skills": detached["skills"],
        "exercise_types": detached["exercise_types"],
        "rubrics": detached["rubrics"],
        "roadmap_tasks": detached["roadmap_tasks"],
    }
    paths = {key: Path(f"canonical-payload/{key}") for key in raws}
    return _build_bundle(
        parsed.skills,
        parsed.exercise_types,
        parsed.rubrics,
        parsed.roadmap_tasks,
        raws=raws,
        paths=paths,
    )


def _build_bundle(
    skills_file: SkillsFile,
    exercise_file: ExerciseTypesFile,
    rubrics_file: RubricsFile,
    roadmap_file: RoadmapTaskMapFile,
    *,
    raws: dict[str, object],
    paths: dict[str, Path],
) -> ConfigBundle:
    skills_raw = raws["skills"]
    exercise_raw = raws["exercise_types"]
    rubrics_raw = raws["rubrics"]
    roadmap_raw = raws["roadmap_tasks"]

    versions = {
        skills_file.schema_version,
        exercise_file.schema_version,
        rubrics_file.schema_version,
        roadmap_file.schema_version,
    }
    if len(versions) != 1:
        raise _at(paths["skills"], skills_raw, "schema versions must match")
    if skills_file.config_version != rubrics_file.config_version:
        raise _at(paths["rubrics"], rubrics_raw, "config versions must match")
    release_versions = {
        skills_file.config_version,
        exercise_file.mapping_version,
        rubrics_file.formula.version,
        roadmap_file.mapping_version,
        *(rubric.version for rubric in rubrics_file.rubrics),
    }
    if len(release_versions) != 1:
        raise _at(
            paths["exercise_types"],
            exercise_raw,
            "mapping, formula, rubric, roadmap, and config versions must match",
        )
    if len(skills_file.skills) != 14:
        raise _at(paths["skills"], skills_raw, "exactly fourteen skills are required")

    skills_items = skills_raw.get("skills", []) if isinstance(skills_raw, dict) else []
    _unique(skills_file.skills, "slug", path=paths["skills"], raw_items=skills_items)
    skills = {item.slug: item for item in skills_file.skills}
    _link_exercises(exercise_file, exercise_raw, paths["exercise_types"], skills)
    _link_rubrics(rubrics_file, rubrics_raw, paths["rubrics"])
    exercises = {item.slug: item for item in exercise_file.exercise_types}
    _link_tasks(roadmap_file, roadmap_raw, paths["roadmap_tasks"], exercises)

    canonical_payload = _canonical_payload(
        skills_file, exercise_file, rubrics_file, roadmap_file
    )
    canonical_payload_json = _payload_json(canonical_payload)
    content_hash = hashlib.sha256(canonical_payload_json.encode("utf-8")).digest()
    version_key = f"{skills_file.config_version}-{content_hash.hex()[:12]}"
    sorted_tasks = tuple(
        sorted(
            roadmap_file.tasks,
            key=lambda task: (task.week, task.day, task.order, task.stable_id),
        )
    )
    return ConfigBundle(
        schema_version=versions.pop(),
        config_version=skills_file.config_version,
        skills=skills_file.skills,
        exercise_types=exercise_file.exercise_types,
        formula=rubrics_file.formula,
        rubrics=rubrics_file.rubrics,
        roadmap_version=roadmap_file.roadmap_version,
        roadmap_contracts=MappingProxyType(dict(roadmap_file.contracts)),
        reconciliations=roadmap_file.reconciliations,
        roadmap_tasks=sorted_tasks,
        content_hash=content_hash,
        version_key=version_key,
        _skills_by_slug=immutable_index(skills_file.skills, "slug"),
        _exercises_by_slug=immutable_index(exercise_file.exercise_types, "slug"),
        _rubrics_by_slug=immutable_index(rubrics_file.rubrics, "slug"),
        _canonical_payload_json=canonical_payload_json,
    )
