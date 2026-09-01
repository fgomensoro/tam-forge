"""Fail closed unless local Compose matches the approved development mapping."""

from __future__ import annotations

from dataclasses import dataclass

import yaml
from yaml.constructor import SafeConstructor
from yaml.events import AliasEvent
from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

APPROVED_MINIO_IMAGE = "minio/minio:RELEASE.2024-06-13T22-53-53Z"
MAX_COMPOSE_BYTES = 64 * 1024
MAX_COMPOSE_NESTING_DEPTH = 32
MAX_COMPOSE_NODES = 500
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


class _RestrictedComposeLoader(SafeLoader):
    """Compose a single safe document while rejecting YAML extensions early."""

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._compose_depth = 0
        self._node_count = 0

    def compose_node(self, parent: Node | None, index: int) -> Node:
        self._compose_depth += 1
        self._node_count += 1
        if self._compose_depth > MAX_COMPOSE_NESTING_DEPTH:
            raise ValueError("Compose YAML exceeds the maximum allowed nesting depth")
        if self._node_count > MAX_COMPOSE_NODES:
            raise ValueError("Compose YAML exceeds the maximum allowed node count")
        if self.check_event(AliasEvent):
            raise ValueError("YAML aliases and anchors are not supported")
        event = self.peek_event()  # type: ignore[no-untyped-call]
        if getattr(event, "anchor", None) is not None:
            raise ValueError("YAML aliases and anchors are not supported")
        if getattr(event, "tag", None) is not None:
            raise ValueError("YAML tags are not supported")
        try:
            node = super().compose_node(parent, index)
            assert node is not None
            return node
        finally:
            self._compose_depth -= 1


def verify_compose_text(compose: str) -> ComposeVerification:
    """Validate one plain YAML document against the closed local Compose allowlist."""
    try:
        encoded = compose.encode("utf-8")
        if len(encoded) > MAX_COMPOSE_BYTES:
            raise ValueError("Compose YAML exceeds the maximum allowed byte size")
        loader = _RestrictedComposeLoader(compose)
        document = loader.get_single_node()
        if document is None:
            raise ValueError("exactly one Compose YAML document is required")
        _reject_duplicate_or_custom_nodes(document)
        parsed = SafeConstructor.construct_document(loader, document)
    except yaml.YAMLError as exc:
        raise ValueError("Compose YAML could not be parsed") from exc
    finally:
        if "loader" in locals():
            loader.dispose()

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
