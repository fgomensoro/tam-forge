"""A deterministic, one-way projection that always says where it came from."""

from __future__ import annotations

from hashlib import sha256

import pytest
from tamforge_backend.exports import okf
from tamforge_backend.exports.okf import (
    OKF_VERSION,
    OkfProjectionError,
    project,
    render,
)
from tamforge_protocol.exports import ExportManifest

BODIES = {
    "recordings/11.bin": b"audio-bytes",
    "transcripts/21.json": b'{"segments": []}',
    "analyses/31.json": b'{"verdict": "clear"}',
}


def artifact(artifact_id: int, kind: str, path: str) -> dict:
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "path": path,
        "sha256": sha256(BODIES[path]).hexdigest(),
        "byte_length": len(BODIES[path]),
    }


def manifest(**overrides: object) -> ExportManifest:
    data: dict[str, object] = {
        "owner_id": 1,
        "artifacts": (
            artifact(31, "analysis", "analyses/31.json"),
            artifact(11, "recording", "recordings/11.bin"),
            artifact(21, "transcript", "transcripts/21.json"),
        ),
        "relations": (
            {"subject_id": 31, "relation": "judges", "object_id": 21},
            {"subject_id": 21, "relation": "transcribes", "object_id": 11},
        ),
    }
    data.update(overrides)
    return ExportManifest.model_validate(data)


def test_the_projection_declares_the_format_it_is() -> None:
    assert project(manifest())["okf_version"] == OKF_VERSION == "0.2"


def test_the_same_manifest_always_renders_the_same_bytes() -> None:
    # A projection nobody can diff is a projection nobody can check.
    assert render(manifest()) == render(manifest())


def test_the_order_the_manifest_happened_to_be_built_in_does_not_show() -> None:
    shuffled = manifest(
        artifacts=(
            artifact(21, "transcript", "transcripts/21.json"),
            artifact(31, "analysis", "analyses/31.json"),
            artifact(11, "recording", "recordings/11.bin"),
        ),
        relations=(
            {"subject_id": 21, "relation": "transcribes", "object_id": 11},
            {"subject_id": 31, "relation": "judges", "object_id": 21},
        ),
    )

    assert render(shuffled) == render(manifest())


def test_nodes_are_ordered_by_id_rather_than_by_arrival() -> None:
    ids = [node["provenance"]["artifact_id"] for node in project(manifest())["nodes"]]

    assert ids == sorted(ids)


def test_every_node_says_which_canonical_artifact_it_came_from() -> None:
    # Without provenance the file is a plausible document about a workspace rather than
    # a view of one.
    for node in project(manifest())["nodes"]:
        provenance = node["provenance"]
        assert provenance["artifact_id"] > 0
        assert len(provenance["sha256"]) == 64
        assert provenance["path"]


def test_the_edges_carry_the_relationships_the_canonical_record_had() -> None:
    edges = project(manifest())["edges"]

    assert {"type": "derivedFrom", "from": 21, "to": 11} in edges
    assert {"type": "assesses", "from": 31, "to": 21} in edges


def test_projecting_never_touches_the_manifest() -> None:
    source = manifest()
    before = source.model_dump_json()

    project(source)
    render(source)

    assert source.model_dump_json() == before


def test_this_module_can_only_read() -> None:
    """The absence is the design.

    The moment a foreign format can write back, it stops being a projection and becomes
    a second system of record that has to be reconciled with the first.
    """
    exported = set(okf.__all__)

    assert exported & {"project", "render"}
    for writing in ("import_okf", "apply", "merge", "ingest", "load", "restore", "write"):
        assert writing not in exported
        assert not hasattr(okf, writing)


def test_a_kind_with_no_honest_equivalent_is_refused_rather_than_guessed() -> None:
    # Emitting it as something else would put a claim in the file that the canonical
    # record never made.
    from tamforge_backend.exports.okf import NODE_TYPES

    original = NODE_TYPES.pop("analysis")
    try:
        with pytest.raises(OkfProjectionError, match="no OKF node type"):
            project(manifest())
    finally:
        NODE_TYPES["analysis"] = original
