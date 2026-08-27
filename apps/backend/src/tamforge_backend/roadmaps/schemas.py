"""Value objects for safe, immutable roadmap package inspection."""

from __future__ import annotations

import re
import shutil
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Literal

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PackageLimits:
    """Hard resource limits applied before a package can be approved."""

    max_archive_bytes: int = 32 * 1024 * 1024
    max_members: int = 512
    max_member_bytes: int = 16 * 1024 * 1024
    max_total_uncompressed_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: int = 200
    max_path_bytes: int = 1024
    read_chunk_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_archive_bytes",
            "max_members",
            "max_member_bytes",
            "max_total_uncompressed_bytes",
            "max_compression_ratio",
            "max_path_bytes",
            "read_chunk_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str | None
    severity: Literal["error", "warning"]
    message: str

    def __post_init__(self) -> None:
        if not self.code or not self.message:
            raise ValueError("validation issue code and message are required")


@dataclass(frozen=True, slots=True)
class BrowserFolderEntry:
    """One browser-selected file; paths are client metadata, never server paths."""

    path: str
    chunks: Iterable[bytes]
    is_symlink: bool = False


@dataclass(frozen=True, slots=True)
class ManifestFile:
    path: str
    original_filename: str
    byte_size: int
    media_type: str
    sha256: str

    def __post_init__(self) -> None:
        normalized_path = unicodedata.normalize("NFC", self.path)
        parts = PurePosixPath(normalized_path).parts
        canonical_posix_path = PurePosixPath(*parts).as_posix()
        if (
            not normalized_path
            or normalized_path != self.path
            or normalized_path != canonical_posix_path
            or normalized_path.startswith("/")
            or "\\" in normalized_path
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized_path)
        ):
            raise ValueError("manifest path must be a normalized relative POSIX path")
        if self.original_filename != parts[-1]:
            raise ValueError("original filename must match the normalized path basename")
        if self.byte_size < 0:
            raise ValueError("manifest byte size cannot be negative")
        if (
            not self.media_type
            or len(self.media_type) > 255
            or any(ord(character) < 32 or ord(character) == 127 for character in self.media_type)
        ):
            raise ValueError("manifest media type is invalid")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("manifest SHA-256 must be lowercase hexadecimal")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "original_filename": self.original_filename,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class RoadmapManifest:
    schema_version: int
    content_hash: str
    files: tuple[ManifestFile, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported roadmap manifest schema")
        if not _SHA256.fullmatch(self.content_hash):
            raise ValueError("manifest content hash must be lowercase hexadecimal")
        if tuple(sorted(self.files, key=lambda item: item.path)) != self.files:
            raise ValueError("manifest files must be sorted by normalized path")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True, slots=True)
class StagedRoadmapFile:
    manifest: ManifestFile
    staged_path: Path


@dataclass(slots=True)
class InspectedRoadmapPackage:
    """Disk-backed inspection result whose staging lifetime is explicit."""

    staging_root: Path
    files: tuple[StagedRoadmapFile, ...]
    issues: tuple[ValidationIssue, ...]
    manifest: RoadmapManifest | None
    archive_path: Path | None
    archive_sha256: str | None
    _temporary_directory: TemporaryDirectory[str] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def accepted(self) -> bool:
        return not self.issues and self.manifest is not None

    def close(self) -> None:
        if not self._closed:
            self._temporary_directory.cleanup()
            self._closed = True

    def __enter__(self) -> InspectedRoadmapPackage:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        if not getattr(self, "_closed", True):
            try:
                self.close()
            except (OSError, shutil.Error):
                pass
