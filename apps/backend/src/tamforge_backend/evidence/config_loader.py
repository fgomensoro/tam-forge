"""Load, link, and content-address checked-in scoring YAML."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, ScalarNode

from .config_models import (
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


class ConfigError(ValueError):
    """Configuration failed strict parsing or cross-file linking."""


class _LocatedDict(dict[str, Any]):
    __slots__ = ("line", "column")

    line: int
    column: int


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _StrictLoader, node: MappingNode, deep: bool = False) -> Any:
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
    return Decimal(loader.construct_scalar(node).replace("_", ""))


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
        return format(value, "f")
    return value


def _content_hash(*documents: BaseModel) -> bytes:
    payload = _canonical(documents)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


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
            unknown_selected = set(exercise.allowed_selected_competencies) - skills.keys()
            if unknown_selected:
                raise _at(
                    path,
                    source,
                    f"unknown selected skill {sorted(unknown_selected)[0]!r}",
                )

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

    content_hash = _content_hash(skills_file, exercise_file, rubrics_file, roadmap_file)
    version_key = f"{skills_file.config_version}-{content_hash.hex()[:12]}"
    return ConfigBundle(
        schema_version=versions.pop(),
        config_version=skills_file.config_version,
        skills=skills_file.skills,
        exercise_types=exercise_file.exercise_types,
        formula=rubrics_file.formula,
        rubrics=rubrics_file.rubrics,
        roadmap_version=roadmap_file.roadmap_version,
        roadmap_tasks=roadmap_file.tasks,
        content_hash=content_hash,
        version_key=version_key,
        _skills_by_slug=immutable_index(skills_file.skills, "slug"),
        _exercises_by_slug=immutable_index(exercise_file.exercise_types, "slug"),
        _rubrics_by_slug=immutable_index(rubrics_file.rubrics, "slug"),
    )
