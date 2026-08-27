"""Bounded, disk-backed inspection for roadmap ZIP and browser-folder uploads."""

from __future__ import annotations

import hashlib
import re
import stat
import struct
import unicodedata
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from .manifest import build_manifest
from .schemas import (
    BrowserFolderEntry,
    InspectedRoadmapPackage,
    ManifestFile,
    PackageLimits,
    StagedRoadmapFile,
    ValidationIssue,
)

_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".sql": "application/sql",
}
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_ZIP_END_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_END_BYTES = 22
_ZIP_CENTRAL_HEADER_BYTES = 46
_ZIP_MAX_COMMENT_BYTES = 65_535


def _issue(code: str, message: str, path: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, severity="error", message=message)


def _new_staging() -> tuple[TemporaryDirectory[str], Path]:
    temporary_directory = TemporaryDirectory(prefix="tamforge-roadmap-")
    root = Path(temporary_directory.name)
    (root / "files").mkdir()
    return temporary_directory, root


def _result(
    *,
    temporary_directory: TemporaryDirectory[str],
    root: Path,
    files: list[StagedRoadmapFile],
    issues: list[ValidationIssue],
    archive_path: Path | None = None,
    archive_sha256: str | None = None,
) -> InspectedRoadmapPackage:
    if not issues and not files:
        issues.append(
            _issue(
                "empty_package",
                "The roadmap package does not contain any supported files.",
            )
        )
    manifest = build_manifest(item.manifest for item in files) if not issues else None
    return InspectedRoadmapPackage(
        staging_root=root,
        files=tuple(files),
        issues=tuple(issues),
        manifest=manifest,
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        _temporary_directory=temporary_directory,
    )


def _normalize_path(
    raw_path: str,
    limits: PackageLimits,
) -> tuple[str | None, ValidationIssue | None]:
    if not isinstance(raw_path, str) or not raw_path:
        return None, _issue("invalid_path", "File path must be a non-empty string.")
    path = unicodedata.normalize("NFC", raw_path.replace("\\", "/"))
    if len(path.encode("utf-8")) > limits.max_path_bytes:
        return None, _issue("path_too_long", "File path is too long.")
    if path.startswith("/") or path.startswith("//") or _WINDOWS_DRIVE.match(path):
        return None, _issue("absolute_path", "Absolute file paths are not allowed.", raw_path)
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        return None, _issue("invalid_path", "File path contains control characters.", raw_path)
    raw_parts = path.split("/")
    if ".." in raw_parts:
        return None, _issue("path_traversal", "Parent path traversal is not allowed.", raw_path)
    parts = [part for part in raw_parts if part not in {"", "."}]
    if not parts:
        return None, _issue("invalid_path", "File path does not identify a file.", raw_path)
    normalized = PurePosixPath(*parts).as_posix()
    if len(normalized.encode("utf-8")) > limits.max_path_bytes:
        return None, _issue("path_too_long", "Normalized file path is too long.", normalized)
    suffix = PurePosixPath(normalized).suffix.lower()
    if suffix not in _MEDIA_TYPES:
        return None, _issue(
            "unsupported_file_type",
            "Only Markdown and SQL roadmap files are supported.",
            normalized,
        )
    return normalized, None


def _path_collision_issue(
    normalized: str,
    seen: set[str],
    seen_casefolded: dict[str, str],
) -> ValidationIssue | None:
    if normalized in seen:
        return _issue("duplicate_path", "Duplicate normalized file path.", normalized)
    casefolded = normalized.casefold()
    if casefolded in seen_casefolded:
        return _issue(
            "case_collision",
            f"File path collides by case with {seen_casefolded[casefolded]}.",
            normalized,
        )
    seen.add(normalized)
    seen_casefolded[casefolded] = normalized
    return None


def _write_bounded_stream(
    chunks: Iterable[bytes],
    destination: Path,
    *,
    limit: int,
) -> tuple[int, str, bool]:
    size = 0
    digest = hashlib.sha256()
    exceeded = False
    with destination.open("xb") as output:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise TypeError("upload chunks must be bytes")
            if not chunk:
                continue
            if size + len(chunk) > limit:
                exceeded = True
                break
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest(), exceeded


def _manifest_file(path: str, size: int, digest: str) -> ManifestFile:
    return ManifestFile(
        path=path,
        original_filename=PurePosixPath(path).name,
        byte_size=size,
        media_type=_MEDIA_TYPES[PurePosixPath(path).suffix.lower()],
        sha256=digest,
    )


def _find_zip_end_offset(tail: bytes) -> int | None:
    search_start = 0
    valid_candidate: int | None = None
    while search_start < len(tail):
        candidate = tail.find(_ZIP_END_SIGNATURE, search_start)
        if candidate < 0:
            break
        if len(tail) - candidate >= _ZIP_END_BYTES:
            comment_size = struct.unpack_from("<H", tail, candidate + 20)[0]
            if candidate + _ZIP_END_BYTES + comment_size == len(tail):
                valid_candidate = candidate
        search_start = candidate + 1
    return valid_candidate


def _zip_directory_issue(archive_path: Path, limits: PackageLimits) -> ValidationIssue | None:
    """Bound central-directory work before Python materializes every ZipInfo."""
    archive_size = archive_path.stat().st_size
    tail_size = min(archive_size, _ZIP_END_BYTES + _ZIP_MAX_COMMENT_BYTES)
    with archive_path.open("rb") as archive:
        archive.seek(archive_size - tail_size)
        tail = archive.read(tail_size)

    end_offset = _find_zip_end_offset(tail)
    if end_offset is None:
        return _issue("invalid_zip", "The uploaded file is not a valid ZIP archive.")
    (
        signature,
        disk_number,
        central_disk,
        entries_on_disk,
        total_entries,
        central_size,
        central_offset,
        comment_size,
    ) = struct.unpack_from("<4s4H2LH", tail, end_offset)
    absolute_end_offset = archive_size - tail_size + end_offset
    if (
        signature != _ZIP_END_SIGNATURE
        or absolute_end_offset + _ZIP_END_BYTES + comment_size != archive_size
        or disk_number != 0
        or central_disk != 0
        or entries_on_disk != total_entries
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or central_offset + central_size != absolute_end_offset
    ):
        return _issue(
            "invalid_zip",
            "The uploaded file is not a supported single-disk ZIP archive.",
        )
    if total_entries > limits.max_members:
        return _issue("too_many_members", "ZIP archive contains too many members.")

    remaining = central_size
    observed_entries = 0
    with archive_path.open("rb") as archive:
        archive.seek(central_offset)
        while remaining:
            if remaining < _ZIP_CENTRAL_HEADER_BYTES:
                return _issue("invalid_zip", "ZIP central directory is malformed.")
            header = archive.read(_ZIP_CENTRAL_HEADER_BYTES)
            if len(header) != _ZIP_CENTRAL_HEADER_BYTES or not header.startswith(
                _ZIP_CENTRAL_SIGNATURE
            ):
                return _issue("invalid_zip", "ZIP central directory is malformed.")
            filename_size, extra_size, member_comment_size = struct.unpack_from("<HHH", header, 28)
            record_size = (
                _ZIP_CENTRAL_HEADER_BYTES + filename_size + extra_size + member_comment_size
            )
            if record_size > remaining:
                return _issue("invalid_zip", "ZIP central directory is malformed.")
            archive.seek(record_size - _ZIP_CENTRAL_HEADER_BYTES, 1)
            remaining -= record_size
            observed_entries += 1
            if observed_entries > limits.max_members:
                return _issue("too_many_members", "ZIP archive contains too many members.")
    if observed_entries != total_entries:
        return _issue("invalid_zip", "ZIP central directory member count is inconsistent.")
    return None


def inspect_zip_stream(
    chunks: Iterable[bytes],
    *,
    limits: PackageLimits | None = None,
) -> InspectedRoadmapPackage:
    """Inspect a streamed ZIP after writing at most the configured archive limit to disk."""
    limits = limits or PackageLimits()
    temporary_directory, root = _new_staging()
    archive_path = root / "upload.zip"
    _, archive_sha256, archive_too_large = _write_bounded_stream(
        chunks,
        archive_path,
        limit=limits.max_archive_bytes,
    )
    if archive_too_large:
        archive_path.unlink(missing_ok=True)
        return _result(
            temporary_directory=temporary_directory,
            root=root,
            files=[],
            issues=[_issue("archive_too_large", "ZIP archive exceeds the upload size limit.")],
        )

    directory_issue = _zip_directory_issue(archive_path, limits)
    if directory_issue is not None:
        return _result(
            temporary_directory=temporary_directory,
            root=root,
            files=[],
            issues=[directory_issue],
            archive_path=archive_path,
            archive_sha256=archive_sha256,
        )

    issues: list[ValidationIssue] = []
    files: list[StagedRoadmapFile] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_members:
                issues.append(_issue("too_many_members", "ZIP archive contains too many members."))

            seen: set[str] = set()
            seen_casefolded: dict[str, str] = {}
            candidates: list[tuple[zipfile.ZipInfo, str]] = []
            total_size = 0
            for info in infos[: limits.max_members + 1]:
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    issues.append(
                        _issue(
                            "symlink_member",
                            "Symbolic links are not allowed.",
                            info.filename,
                        )
                    )
                    continue
                if info.flag_bits & 0x1:
                    issues.append(
                        _issue(
                            "encrypted_member",
                            "Encrypted ZIP members are not allowed.",
                            info.filename,
                        )
                    )
                    continue
                if info.is_dir():
                    continue
                normalized, path_issue = _normalize_path(info.filename, limits)
                if path_issue is not None:
                    issues.append(path_issue)
                    continue
                assert normalized is not None
                collision = _path_collision_issue(normalized, seen, seen_casefolded)
                if collision is not None:
                    issues.append(collision)
                    continue
                if info.file_size > limits.max_member_bytes:
                    issues.append(
                        _issue(
                            "member_too_large",
                            "File exceeds the per-file size limit.",
                            normalized,
                        )
                    )
                total_size += info.file_size
                if info.file_size and (
                    info.compress_size == 0
                    or info.file_size > info.compress_size * limits.max_compression_ratio
                ):
                    issues.append(
                        _issue(
                            "suspicious_compression_ratio",
                            "ZIP member has a suspicious compression ratio.",
                            normalized,
                        )
                    )
                candidates.append((info, normalized))

            if total_size > limits.max_total_uncompressed_bytes:
                issues.append(
                    _issue("total_size_too_large", "Package exceeds the total file size limit.")
                )

            if not issues:
                for index, (info, normalized) in enumerate(candidates):
                    staged_path = root / "files" / f"{index:06d}.bin"
                    digest = hashlib.sha256()
                    size = 0
                    try:
                        with archive.open(info, "r") as source, staged_path.open("xb") as output:
                            while chunk := source.read(limits.read_chunk_bytes):
                                size += len(chunk)
                                if size > limits.max_member_bytes or size > info.file_size:
                                    raise ValueError(
                                        "ZIP member exceeded its declared or allowed size"
                                    )
                                output.write(chunk)
                                digest.update(chunk)
                    except (
                        zipfile.BadZipFile,
                        EOFError,
                        OSError,
                        RuntimeError,
                        ValueError,
                        NotImplementedError,
                    ):
                        staged_path.unlink(missing_ok=True)
                        issues.append(
                            _issue(
                                "invalid_zip_member",
                                "ZIP member could not be read safely.",
                                normalized,
                            )
                        )
                        break
                    if size != info.file_size:
                        staged_path.unlink(missing_ok=True)
                        issues.append(
                            _issue(
                                "invalid_zip_member",
                                "ZIP member size did not match metadata.",
                                normalized,
                            )
                        )
                        break
                    files.append(
                        StagedRoadmapFile(
                            manifest=_manifest_file(normalized, size, digest.hexdigest()),
                            staged_path=staged_path,
                        )
                    )
    except zipfile.BadZipFile:
        return _result(
            temporary_directory=temporary_directory,
            root=root,
            files=[],
            issues=[_issue("invalid_zip", "The uploaded file is not a valid ZIP archive.")],
            archive_path=archive_path,
            archive_sha256=archive_sha256,
        )

    if issues:
        for staged in files:
            staged.staged_path.unlink(missing_ok=True)
        files.clear()
    return _result(
        temporary_directory=temporary_directory,
        root=root,
        files=files,
        issues=issues,
        archive_path=archive_path,
        archive_sha256=archive_sha256,
    )


def inspect_browser_folder(
    entries: Iterable[BrowserFolderEntry],
    *,
    limits: PackageLimits | None = None,
) -> InspectedRoadmapPackage:
    """Inspect streamed browser-selected files without accepting any server path."""
    limits = limits or PackageLimits()
    temporary_directory, root = _new_staging()
    issues: list[ValidationIssue] = []
    files: list[StagedRoadmapFile] = []
    seen: set[str] = set()
    seen_casefolded: dict[str, str] = {}
    total_size = 0
    member_count = 0

    for entry in entries:
        member_count += 1
        if member_count > limits.max_members:
            issues.append(_issue("too_many_members", "Folder contains too many files."))
            if member_count > limits.max_members + 1:
                break
        normalized, path_issue = _normalize_path(entry.path, limits)
        if path_issue is not None:
            issues.append(path_issue)
            continue
        assert normalized is not None
        collision = _path_collision_issue(normalized, seen, seen_casefolded)
        if collision is not None:
            issues.append(collision)
            continue
        if entry.is_symlink:
            issues.append(_issue("symlink_member", "Symbolic links are not allowed.", normalized))
            continue

        staged_path = root / "files" / f"{member_count - 1:06d}.bin"
        digest = hashlib.sha256()
        member_size = 0
        member_too_large = False
        total_too_large = False
        with staged_path.open("xb") as output:
            for chunk in entry.chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("upload chunks must be bytes")
                if not chunk:
                    continue
                member_size += len(chunk)
                total_size += len(chunk)
                member_too_large = member_size > limits.max_member_bytes
                total_too_large = total_size > limits.max_total_uncompressed_bytes
                if member_too_large or total_too_large:
                    break
                output.write(chunk)
                digest.update(chunk)

        if member_too_large:
            issues.append(
                _issue("member_too_large", "File exceeds the per-file size limit.", normalized)
            )
        if total_too_large:
            issues.append(
                _issue("total_size_too_large", "Package exceeds the total file size limit.")
            )
        if member_too_large or total_too_large:
            staged_path.unlink(missing_ok=True)
            continue
        files.append(
            StagedRoadmapFile(
                manifest=_manifest_file(normalized, member_size, digest.hexdigest()),
                staged_path=staged_path,
            )
        )

    if issues:
        for staged in files:
            staged.staged_path.unlink(missing_ok=True)
        files.clear()
    return _result(
        temporary_directory=temporary_directory,
        root=root,
        files=files,
        issues=issues,
    )
