"""A one-way OKF 0.2 projection of the canonical export.

This module reads and never writes. There is no import, no apply, no merge, and that
absence is the design: the moment a foreign format can write back, it stops being a
projection and starts being a second system of record that has to be reconciled with the
first. A test asserts no such function appears here later.

The projection is deterministic. The same manifest produces byte-identical output every
time, because a projection nobody can diff is a projection nobody can check, and a
verifier that has to normalise before comparing is a verifier that can be argued with.
Ordering is by id, serialisation has sorted keys and no incidental whitespace, and
nothing is stamped with the moment of projection.

Every node carries provenance: the id and hash of the canonical artifact it came from.
That is what makes the output answerable. Without it the OKF file is a plausible document
about a workspace rather than a view of one.
"""

from __future__ import annotations

import json
from typing import Any, Final

from tamforge_protocol.exports import ExportManifest, RelationKind

OKF_VERSION: Final = "0.2"
OKF_PROFILE: Final = "tamforge"

# Canonical artifact kinds mapped onto the OKF node types. A kind with no mapping is a
# refusal rather than a guess: emitting it as something else would put a claim in the
# file that the canonical record never made.
NODE_TYPES: Final[dict[str, str]] = {
    "recording": "Recording",
    "transcript": "Transcript",
    "attempt": "Work",
    "analysis": "Assessment",
    "evidence_event": "Evidence",
    "report": "Report",
    "opportunity": "Opportunity",
    "interview": "Interview",
}

EDGE_TYPES: Final[dict[str, str]] = {
    "transcribes": "derivedFrom",
    "attempted_in": "partOf",
    "judges": "assesses",
    "evidences": "supports",
    "belongs_to": "partOf",
    "supersedes": "replaces",
}


class OkfProjectionError(ValueError):
    """Something in the canonical record has no honest OKF equivalent."""


def _node(manifest: ExportManifest, artifact_id: int) -> dict[str, Any]:
    artifact = manifest.artifact(artifact_id)
    node_type = NODE_TYPES.get(artifact.kind)
    if node_type is None:
        raise OkfProjectionError(f"no OKF node type for {artifact.kind}")
    return {
        "id": f"tamforge:{artifact.kind}:{artifact.artifact_id}",
        "type": node_type,
        "provenance": {
            "artifact_id": artifact.artifact_id,
            "sha256": artifact.sha256,
            "path": artifact.path,
        },
    }


def _edge(relation: RelationKind, subject: int, object_id: int) -> dict[str, Any]:
    edge_type = EDGE_TYPES.get(relation)
    if edge_type is None:
        raise OkfProjectionError(f"no OKF edge type for {relation}")
    return {"type": edge_type, "from": subject, "to": object_id}


def project(manifest: ExportManifest) -> dict[str, Any]:
    """Return the OKF view of one manifest. The manifest itself is never touched."""
    nodes = [
        _node(manifest, artifact.artifact_id)
        for artifact in sorted(manifest.artifacts, key=lambda item: item.artifact_id)
    ]
    edges = [
        _edge(relation.relation, relation.subject_id, relation.object_id)
        for relation in sorted(
            manifest.relations,
            key=lambda item: (item.subject_id, item.relation, item.object_id),
        )
    ]
    return {
        "okf_version": OKF_VERSION,
        "profile": OKF_PROFILE,
        "nodes": nodes,
        "edges": edges,
    }


def render(manifest: ExportManifest) -> bytes:
    """The bytes of the projection, stable enough to diff and to hash."""
    return json.dumps(
        project(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


__all__ = [
    "EDGE_TYPES",
    "NODE_TYPES",
    "OKF_PROFILE",
    "OKF_VERSION",
    "OkfProjectionError",
    "project",
    "render",
]
