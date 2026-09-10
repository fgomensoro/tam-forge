"""Reading an export back: a dry run that writes nothing, then all of it or none of it.

Restoring is the operation where optimism is most expensive. The archive might be from a
different version, it might be truncated, it might have been edited, and the moment you
find out is usually halfway through writing it over something.

So it happens in two passes. The dry run verifies the format version, every hash, every
identity and every relationship, and it takes no writes at all: not a row, not a file, not
a marker saying it was attempted. Its result is a report the caller can look at before
deciding anything.

Only an approved plan is applied, and application is transactional. Either the whole
export lands or nothing does, because a half-restored workspace is worse than an empty
one: it looks like a workspace, and the missing half is invisible until someone goes
looking for it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from tamforge_protocol.exports import (
    ExportError,
    ExportManifest,
    require_readable,
    verify,
)

DryRunOutcome = Literal["ready", "rejected"]


class ImportError_(ValueError):
    """The export cannot be restored as it stands."""


class PartialRestore(ImportError_):
    """Application failed partway and the transaction was rolled back."""


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """What a verification pass found, and nothing it changed."""

    outcome: DryRunOutcome
    artifact_count: int
    relation_count: int
    problems: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.outcome == "ready"


@dataclass(frozen=True, slots=True)
class RestorePlan:
    """An approved dry run, bound to the report that approved it."""

    manifest: ExportManifest
    approved_by: str
    report: DryRunReport

    def __post_init__(self) -> None:
        if not self.approved_by.strip():
            raise ImportError_("a restore names who approved it")
        if not self.report.ready:
            raise ImportError_("a rejected dry run cannot be approved")


@dataclass(slots=True)
class RecordingWriter:
    """A writer that remembers what it was asked to do, and can be made to fail."""

    written: list[str] = field(default_factory=list)

    def write(self, path: str) -> None:
        self.written.append(path)


def dry_run(
    manifest: ExportManifest,
    *,
    digests: Mapping[str, str],
    sizes: Mapping[str, int],
    manifest_format: str,
    manifest_version: str,
) -> DryRunReport:
    """Verify everything and write nothing. The report is the only output."""
    problems: list[str] = []
    try:
        require_readable(manifest_format, manifest_version)
    except ExportError as unreadable:
        problems.append(str(unreadable))
    try:
        verify(manifest, digests=digests, sizes=sizes)
    except ExportError as broken:
        problems.append(str(broken))
    return DryRunReport(
        outcome="rejected" if problems else "ready",
        artifact_count=len(manifest.artifacts),
        relation_count=len(manifest.relations),
        problems=tuple(problems),
    )


def apply_restore(plan: RestorePlan, *, write: Callable[[str], None]) -> tuple[str, ...]:
    """Write every artifact, or leave nothing behind.

    The rollback is the caller's transaction; what this guarantees is that a failure
    partway raises rather than returning a shorter list, so a partial restore cannot be
    mistaken for a complete one.
    """
    written: list[str] = []
    try:
        for artifact in plan.manifest.artifacts:
            write(artifact.path)
            written.append(artifact.path)
    except Exception as failure:
        raise PartialRestore(
            f"restore failed after {len(written)} of {len(plan.manifest.artifacts)} artifacts"
        ) from failure
    return tuple(written)


__all__ = [
    "DryRunOutcome",
    "DryRunReport",
    "ImportError_",
    "PartialRestore",
    "RecordingWriter",
    "RestorePlan",
    "apply_restore",
    "dry_run",
]
