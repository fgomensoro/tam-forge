"""Canonical roadmap manifest construction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from .schemas import ManifestFile, RoadmapManifest


class ManifestError(ValueError):
    """Raised when file metadata cannot form one canonical manifest."""


def build_manifest(files: Iterable[ManifestFile]) -> RoadmapManifest:
    ordered = tuple(sorted(files, key=lambda item: item.path))
    seen: set[str] = set()
    seen_casefolded: set[str] = set()
    for item in ordered:
        if item.path in seen:
            raise ManifestError(f"duplicate normalized path: {item.path}")
        casefolded = item.path.casefold()
        if casefolded in seen_casefolded:
            raise ManifestError(f"case-colliding normalized path: {item.path}")
        seen.add(item.path)
        seen_casefolded.add(casefolded)

    payload = {
        "schema_version": 1,
        "files": [item.to_dict() for item in ordered],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return RoadmapManifest(
        schema_version=1,
        content_hash=hashlib.sha256(canonical).hexdigest(),
        files=ordered,
    )
