"""Fail closed unless local Compose matches the approved development mapping."""

from __future__ import annotations

from dataclasses import dataclass

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

APPROVED_MINIO_IMAGE = "minio/minio:RELEASE.2024-06-13T22-53-53Z"
APPROVED_COMPOSE: dict[str, object] = {
    "services": {
        "postgres": {
            "image": "pgvector/pgvector:pg16",
            "environment": {
                "POSTGRES_DB": "tamforge",
                "POSTGRES_USER": "tamforge",
                "POSTGRES_PASSWORD": "tamforge",
            },
            "ports": ["127.0.0.1:54329:5432"],
            "volumes": ["tamforge-postgres:/var/lib/postgresql/data"],
        },
        "minio": {
            "image": APPROVED_MINIO_IMAGE,
            "command": 'server /data --console-address ":9001"',
            "environment": {
                "MINIO_ROOT_USER": "tamforge",
                "MINIO_ROOT_PASSWORD": "tamforge-local",
            },
            "ports": ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"],
            "volumes": ["tamforge-minio:/data"],
        },
    },
    "volumes": {"tamforge-postgres": None, "tamforge-minio": None},
}
@dataclass(frozen=True)
class ComposeVerification:
    published_ports: tuple[str, ...]
    minio_image: str


def verify_compose_text(compose: str) -> ComposeVerification:
    """Validate one plain YAML document against the closed local Compose allowlist."""
    try:
        _reject_yaml_extensions(compose)
        documents = list(yaml.compose_all(compose, Loader=yaml.SafeLoader))
        if len(documents) != 1 or documents[0] is None:
            raise ValueError("exactly one Compose YAML document is required")
        _reject_duplicate_or_custom_nodes(documents[0])
        parsed = yaml.safe_load(compose)
    except yaml.YAMLError as exc:
        raise ValueError("Compose YAML could not be parsed") from exc

    _assert_same_structure(parsed, APPROVED_COMPOSE, "Compose document")
    services = APPROVED_COMPOSE["services"]
    assert isinstance(services, dict)
    postgres = services["postgres"]
    minio = services["minio"]
    assert isinstance(postgres, dict)
    assert isinstance(minio, dict)
    postgres_ports = postgres["ports"]
    minio_ports = minio["ports"]
    assert isinstance(postgres_ports, list)
    assert isinstance(minio_ports, list)
    return ComposeVerification(
        published_ports=tuple((*postgres_ports, *minio_ports)),
        minio_image=APPROVED_MINIO_IMAGE,
    )


def _reject_yaml_extensions(compose: str) -> None:
    for event in yaml.parse(compose, Loader=yaml.SafeLoader):
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None):
            raise ValueError("YAML aliases and anchors are not supported")
        tag = getattr(event, "tag", None)
        if tag is not None:
            raise ValueError("YAML tags are not supported")


def _reject_duplicate_or_custom_nodes(node: Node) -> None:
    if isinstance(node, MappingNode):
        keys: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise ValueError("Compose mapping keys must be scalars")
            identity = (key.tag, key.value)
            if identity in keys:
                raise ValueError("Compose YAML contains duplicate keys")
            keys.add(identity)
            _reject_duplicate_or_custom_nodes(key)
            _reject_duplicate_or_custom_nodes(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_or_custom_nodes(value)


def _assert_same_structure(actual: object, expected: object, path: str) -> None:
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError(f"unexpected {path}; expected the approved mapping")
        for index, value in enumerate(expected):
            _assert_same_structure(actual[index], value, f"{path}[{index}]")
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ValueError(f"unexpected keys at {path}; expected the approved mapping")
        for key, value in expected.items():
            _assert_same_structure(actual[key], value, f"{path}.{key}")
        return
    if actual != expected:
        raise ValueError(f"unexpected {path}; expected the approved value")
