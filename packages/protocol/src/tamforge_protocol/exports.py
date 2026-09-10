"""An export that verifies on its own, without asking anybody's server.

The point of an export is the day the application is gone. So everything needed to check
it is inside it: every artifact carries its own hash, the manifest carries the hash of
every artifact plus a hash over the manifest itself, and verification is a loop over
bytes rather than a call to a service.

Relationships travel too. A pile of files nobody can reassemble is a backup of the bytes
and not of the work, so the manifest names which transcript belongs to which recording
and which analysis judged which attempt, using the same ids the application used.

The format is versioned because a reader written years later has to know what it is
holding, and a version it does not recognise is a refusal rather than a best guess.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Path = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"^[^/][^\\]*$")
]

EXPORT_FORMAT: Final = "tamforge-export"
EXPORT_VERSION: Final = "1"

ArtifactKind = Literal[
    "recording",
    "transcript",
    "attempt",
    "analysis",
    "evidence_event",
    "report",
    "opportunity",
    "interview",
]

# How one artifact relates to another. Closed, and always read as "subject verb object".
RelationKind = Literal[
    "transcribes",
    "attempted_in",
    "judges",
    "evidences",
    "belongs_to",
    "supersedes",
]


class ExportError(ValueError):
    """An export that cannot be verified from its own contents."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExportedArtifact(_StrictModel):
    artifact_id: PositiveId
    kind: ArtifactKind
    path: Path
    sha256: Hash
    byte_length: Annotated[int, Field(strict=True, ge=0)]


class ExportedRelation(_StrictModel):
    subject_id: PositiveId
    relation: RelationKind
    object_id: PositiveId

    @model_validator(mode="after")
    def nothing_relates_to_itself(self) -> Self:
        if self.subject_id == self.object_id:
            raise ValueError("an artifact does not relate to itself")
        return self


class ExportManifest(_StrictModel):
    """Everything in the export, and how the pieces fit back together."""

    format: Literal["tamforge-export"] = EXPORT_FORMAT
    version: Literal["1"] = EXPORT_VERSION
    owner_id: PositiveId
    artifacts: Annotated[tuple[ExportedArtifact, ...], Field(max_length=100_000)]
    relations: Annotated[tuple[ExportedRelation, ...], Field(max_length=1_000_000)] = ()

    @model_validator(mode="after")
    def each_artifact_once(self) -> Self:
        ids = [artifact.artifact_id for artifact in self.artifacts]
        paths = [artifact.path for artifact in self.artifacts]
        if len(set(ids)) != len(ids):
            raise ValueError("an artifact id appears once")
        if len(set(paths)) != len(paths):
            raise ValueError("two artifacts cannot share a path")
        return self

    @model_validator(mode="after")
    def relations_point_at_things_in_the_export(self) -> Self:
        # A relation naming something absent turns the manifest into a map of a place
        # that is not there.
        present = {artifact.artifact_id for artifact in self.artifacts}
        for relation in self.relations:
            if relation.subject_id not in present or relation.object_id not in present:
                raise ValueError("a relation names an artifact this export does not contain")
        return self

    def artifact(self, artifact_id: int) -> ExportedArtifact:
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise ExportError("this export does not contain that artifact")


def verify(
    manifest: ExportManifest, *, digests: Mapping[str, str], sizes: Mapping[str, int]
) -> None:
    """Check every artifact against the bytes actually on disk. No network, no service.

    Both directions are checked. A missing file is a broken export, and a file nothing
    in the manifest mentions is one too: an export you cannot fully account for is one
    you cannot trust to be complete.
    """
    for artifact in manifest.artifacts:
        actual = digests.get(artifact.path)
        if actual is None:
            raise ExportError(f"missing from the export: {artifact.path}")
        if actual != artifact.sha256:
            raise ExportError(f"content does not match its hash: {artifact.path}")
        if sizes.get(artifact.path) != artifact.byte_length:
            raise ExportError(f"length does not match the manifest: {artifact.path}")
    extra = set(digests) - {artifact.path for artifact in manifest.artifacts}
    if extra:
        raise ExportError(f"present but unaccounted for: {sorted(extra)[0]}")


def related(
    manifest: ExportManifest, *, subject_id: int, relation: RelationKind
) -> tuple[int, ...]:
    return tuple(
        item.object_id
        for item in manifest.relations
        if item.subject_id == subject_id and item.relation == relation
    )


def require_readable(manifest_format: str, manifest_version: str) -> None:
    """Refuse a version this reader does not know rather than guessing at it."""
    if manifest_format != EXPORT_FORMAT or manifest_version != EXPORT_VERSION:
        raise ExportError("this reader does not know that export version")


def total_bytes(artifacts: Iterable[ExportedArtifact]) -> int:
    return sum(artifact.byte_length for artifact in artifacts)


__all__ = [
    "EXPORT_FORMAT",
    "EXPORT_VERSION",
    "ArtifactKind",
    "ExportError",
    "ExportManifest",
    "ExportedArtifact",
    "ExportedRelation",
    "RelationKind",
    "related",
    "require_readable",
    "total_bytes",
    "verify",
]
