"""Explicit catalog and secret DSN configuration; no application DB fallback."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator

from .sql_contracts import SqlExercise, SqlRunnerError

_MAX_CONFIG_BYTES = 2 * 1024 * 1024


class _CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    catalog_version: Literal[1]
    exercises: tuple[SqlExercise, ...]

    @field_validator("catalog_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("catalog version must be an integer")
        return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def _read_json(raw: str) -> object:
    if len(raw.encode("utf-8")) > _MAX_CONFIG_BYTES:
        raise ValueError("configuration too large")
    return json.loads(raw, object_pairs_hook=_unique_object)


def _validate_dsn(dsn: str, role_name: str) -> None:
    parts = urlsplit(dsn)
    if (
        parts.scheme not in {"postgres", "postgresql"}
        or not parts.hostname
        or unquote(parts.username or "") != role_name
        or not parts.path.startswith("/")
        or len(parts.path) <= 1
        or parts.fragment
        or any(c.isspace() for c in dsn)
    ):
        raise ValueError("invalid connection configuration")
    # Forbid options/user/service overrides, duplicate options and driver-specific
    # arbitrary server settings. TLS policy is explicit and cannot request disable.
    options = parse_qsl(parts.query, strict_parsing=True)
    if len(options) > 1 or any(
        key != "sslmode"
        or value
        not in {
            "require",
            "verify-ca",
            "verify-full",
        }
        for key, value in options
    ):
        raise ValueError("invalid connection options")
    _ = parts.port


class SqlExerciseCatalog:
    """Server-owned immutable mappings; secret values are absent from repr."""

    def __init__(
        self, *, exercises: tuple[SqlExercise, ...] = (), dsns: Mapping[str, str] | None = None
    ) -> None:
        by_task: dict[str, SqlExercise] = {}
        by_key: dict[str, SqlExercise] = {}
        secrets: dict[str, SecretStr] = {}
        schemas: set[str] = set()
        roles: set[str] = set()
        try:
            for exercise in exercises:
                # Revalidate even a model assembled with unchecked model_copy.
                exercise = SqlExercise.model_validate(exercise.model_dump())
                if (
                    exercise.key in by_key
                    or exercise.schema_name in schemas
                    or exercise.role_name in roles
                ):
                    raise ValueError("ambiguous exercise configuration")
                by_key[exercise.key] = exercise
                schemas.add(exercise.schema_name)
                roles.add(exercise.role_name)
                for task_id in exercise.task_stable_ids:
                    if task_id in by_task:
                        raise ValueError("ambiguous task configuration")
                    by_task[task_id] = exercise
            if set(dsns or {}) != set(by_key):
                raise ValueError("incomplete connection configuration")
            for key, dsn in (dsns or {}).items():
                _validate_dsn(dsn, by_key[key].role_name)
                secrets[key] = SecretStr(dsn)
        except (ValueError, TypeError, AttributeError):
            raise SqlRunnerError("unsafe_configuration") from None
        self._by_task = MappingProxyType(by_task)
        self._by_key = MappingProxyType(by_key)
        self._dsns = MappingProxyType(secrets)

    @property
    def enabled(self) -> bool:
        return bool(self._by_key)

    def resolve(self, task_stable_id: str) -> SqlExercise:
        if not self.enabled:
            raise SqlRunnerError("disabled")
        exercise = self._by_task.get(task_stable_id)
        if exercise is None:
            raise SqlRunnerError("unknown_exercise")
        return exercise

    def dsn_for(self, exercise: SqlExercise) -> str:
        if not self.enabled:
            raise SqlRunnerError("disabled")
        if self._by_key.get(exercise.key) != exercise:
            raise SqlRunnerError("unknown_exercise")
        return self._dsns[exercise.key].get_secret_value()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SqlExerciseCatalog:
        env = os.environ if environ is None else environ
        location = env.get("TAMFORGE_SQL_EXERCISE_CATALOG")
        raw_dsns = env.get("TAMFORGE_SQL_EXERCISE_DSNS")
        if not location or not raw_dsns:
            return cls()
        try:
            with Path(location).open("rb") as source:
                raw_catalog = source.read(_MAX_CONFIG_BYTES + 1).decode("utf-8")
            _read_json(raw_catalog)
            catalog = _CatalogFile.model_validate_json(raw_catalog)
            if not catalog.exercises:
                raise ValueError("empty configured catalog")
            parsed_dsns = _read_json(raw_dsns)
            if not isinstance(parsed_dsns, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in parsed_dsns.items()
            ):
                raise ValueError("invalid connection mapping")
            return cls(exercises=catalog.exercises, dsns=parsed_dsns)
        except (OSError, ValueError, UnicodeError, ValidationError, RecursionError):
            raise SqlRunnerError("unsafe_configuration") from None
