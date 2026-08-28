from __future__ import annotations

import io
import stat
import struct
import warnings
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pytest
from tamforge_backend.roadmaps import package as package_module
from tamforge_backend.roadmaps.package import inspect_browser_folder, inspect_zip_stream
from tamforge_backend.roadmaps.schemas import BrowserFolderEntry, PackageLimits

FIXTURE = Path(__file__).parents[2] / "fixtures" / "roadmaps" / "minimal-month"


def _chunks(payload: bytes, size: int = 7) -> Iterable[bytes]:
    for offset in range(0, len(payload), size):
        yield payload[offset : offset + size]


def _fixture_entries(*, reverse: bool = False) -> list[tuple[str, bytes]]:
    entries = [
        (path.relative_to(FIXTURE).as_posix(), path.read_bytes())
        for path in FIXTURE.rglob("*")
        if path.is_file()
    ]
    return sorted(entries, reverse=reverse)


def _zip(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, payload in entries:
                archive.writestr(name, payload)
    return output.getvalue()


def _folder(entries: list[tuple[str, bytes]]) -> list[BrowserFolderEntry]:
    return [BrowserFolderEntry(path=path, chunks=_chunks(payload)) for path, payload in entries]


def _issue_codes(package: object) -> set[str]:
    return {issue.code for issue in package.issues}  # type: ignore[attr-defined]


def _mark_first_member_encrypted(payload: bytes) -> bytes:
    mutated = bytearray(payload)
    local = mutated.index(b"PK\x03\x04")
    central = mutated.index(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", mutated, local + 6)[0] | 0x1
    central_flags = struct.unpack_from("<H", mutated, central + 8)[0] | 0x1
    struct.pack_into("<H", mutated, local + 6, local_flags)
    struct.pack_into("<H", mutated, central + 8, central_flags)
    return bytes(mutated)


def test_zip_and_folder_adapters_preserve_bytes_and_build_same_manifest() -> None:
    entries = _fixture_entries()

    with inspect_zip_stream(_chunks(_zip(entries))) as zipped:
        with inspect_browser_folder(_folder(entries)) as folder:
            assert zipped.accepted
            assert folder.accepted
            assert zipped.manifest == folder.manifest
            assert zipped.manifest is not None
            assert zipped.archive_path is not None and zipped.archive_path.is_file()
            assert len(zipped.archive_sha256 or "") == 64
            assert folder.archive_path is None
            assert folder.archive_sha256 is None
            assert {
                item.manifest.path: item.staged_path.read_bytes() for item in zipped.files
            } == dict(entries)
            assert {
                item.manifest.path: item.staged_path.read_bytes() for item in folder.files
            } == dict(entries)


def test_differently_ordered_zip_members_have_same_content_hash() -> None:
    entries = _fixture_entries()

    with inspect_zip_stream(_chunks(_zip(entries))) as first:
        with inspect_zip_stream(_chunks(_zip(list(reversed(entries))))) as second:
            assert first.accepted and second.accepted
            assert first.manifest is not None and second.manifest is not None
            assert first.manifest.content_hash == second.manifest.content_hash
            assert first.archive_sha256 != second.archive_sha256


@pytest.mark.parametrize("adapter", ["zip", "folder"])
@pytest.mark.parametrize(
    ("paths", "expected_code"),
    [
        (["../escape.md"], "path_traversal"),
        (["/absolute.md"], "absolute_path"),
        (["notes/./same.md", "notes/same.md"], "duplicate_path"),
        (["README.md", "readme.md"], "case_collision"),
        (["payload.exe"], "unsupported_file_type"),
    ],
)
def test_adapters_reject_unsafe_paths_and_file_types(
    adapter: str,
    paths: list[str],
    expected_code: str,
) -> None:
    entries = [(path, b"content") for path in paths]

    package = (
        inspect_zip_stream(_chunks(_zip(entries)))
        if adapter == "zip"
        else inspect_browser_folder(_folder(entries))
    )
    with package:
        assert not package.accepted
        assert package.manifest is None
        assert expected_code in _issue_codes(package)


@pytest.mark.parametrize("adapter", ["zip", "folder"])
def test_adapters_normalize_paths_to_posix_nfc(adapter: str) -> None:
    decomposed = "templates/cafe\u0301.md"
    entries = [(decomposed, b"template")]

    package = (
        inspect_zip_stream(_chunks(_zip(entries)))
        if adapter == "zip"
        else inspect_browser_folder(_folder(entries))
    )
    with package:
        assert package.accepted
        assert package.manifest is not None
        assert package.manifest.files[0].path == "templates/caf\u00e9.md"
        assert package.manifest.files[0].original_filename == "caf\u00e9.md"


@pytest.mark.parametrize("adapter", ["zip", "folder"])
def test_adapters_bound_overlong_paths_before_reporting_them(adapter: str) -> None:
    overlong_path = "/" + ("a" * 80) + ".md"
    limits = PackageLimits(max_path_bytes=32)
    entries = [(overlong_path, b"content")]

    package = (
        inspect_zip_stream(_chunks(_zip(entries)), limits=limits)
        if adapter == "zip"
        else inspect_browser_folder(_folder(entries), limits=limits)
    )
    with package:
        assert not package.accepted
        issue = next(item for item in package.issues if item.code == "path_too_long")
        assert issue.path is None


@pytest.mark.parametrize("adapter", ["zip", "folder"])
@pytest.mark.parametrize(
    ("limits", "expected_code"),
    [
        (PackageLimits(max_members=1), "too_many_members"),
        (PackageLimits(max_member_bytes=4), "member_too_large"),
        (PackageLimits(max_total_uncompressed_bytes=8), "total_size_too_large"),
    ],
)
def test_adapters_enforce_member_count_member_size_and_total_size(
    adapter: str,
    limits: PackageLimits,
    expected_code: str,
) -> None:
    entries = [("one.md", b"12345"), ("two.md", b"67890")]

    package = (
        inspect_zip_stream(_chunks(_zip(entries)), limits=limits)
        if adapter == "zip"
        else inspect_browser_folder(_folder(entries), limits=limits)
    )
    with package:
        assert not package.accepted
        assert expected_code in _issue_codes(package)


def test_zip_rejects_excess_member_count_before_materializing_zip_infos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _zip([("one.md", b"1"), ("two.md", b"2")])

    def fail_if_zipfile_is_opened(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ZipFile must not parse an over-member-limit central directory")

    monkeypatch.setattr(package_module.zipfile, "ZipFile", fail_if_zipfile_is_opened)
    with inspect_zip_stream(_chunks(payload), limits=PackageLimits(max_members=1)) as package:
        assert not package.accepted
        assert _issue_codes(package) == {"too_many_members"}


def test_zip_rejects_archive_over_limit_without_retaining_unbounded_bytes() -> None:
    payload = _zip([("README.md", b"content")])
    package = inspect_zip_stream(_chunks(payload), limits=PackageLimits(max_archive_bytes=10))
    staging_root = package.staging_root

    with package:
        assert not package.accepted
        assert "archive_too_large" in _issue_codes(package)
        assert package.archive_path is None
        assert package.archive_sha256 is None
        assert sum(path.stat().st_size for path in staging_root.rglob("*") if path.is_file()) <= 10

    assert not staging_root.exists()


def test_zip_rejects_symlink_encrypted_and_suspiciously_compressed_members() -> None:
    symlink = zipfile.ZipInfo("templates/link.md")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    symlink_package = inspect_zip_stream(_chunks(_zip([(symlink, b"README.md")])))
    encrypted_package = inspect_zip_stream(
        _chunks(_mark_first_member_encrypted(_zip([("README.md", b"secret")])))
    )
    compressed_package = inspect_zip_stream(
        _chunks(_zip([("README.md", b"0" * 10_000)], compression=zipfile.ZIP_DEFLATED)),
        limits=PackageLimits(max_compression_ratio=2),
    )

    with symlink_package, encrypted_package, compressed_package:
        assert "symlink_member" in _issue_codes(symlink_package)
        assert "encrypted_member" in _issue_codes(encrypted_package)
        assert "suspicious_compression_ratio" in _issue_codes(compressed_package)
        assert not symlink_package.accepted
        assert not encrypted_package.accepted
        assert not compressed_package.accepted


def test_zip_rejects_symlink_metadata_even_when_name_looks_like_a_directory() -> None:
    symlink = zipfile.ZipInfo("templates/link/")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16

    with inspect_zip_stream(_chunks(_zip([(symlink, b"README.md")]))) as package:
        assert not package.accepted
        assert "symlink_member" in _issue_codes(package)


def test_folder_rejects_symlink_metadata() -> None:
    package = inspect_browser_folder(
        [BrowserFolderEntry(path="templates/link.md", chunks=_chunks(b"target"), is_symlink=True)]
    )

    with package:
        assert not package.accepted
        assert "symlink_member" in _issue_codes(package)


def test_invalid_zip_returns_stable_validation_issue() -> None:
    with inspect_zip_stream(_chunks(b"not a zip")) as package:
        assert not package.accepted
        assert package.manifest is None
        assert package.issues == (
            package.issues[0].__class__(
                code="invalid_zip",
                path=None,
                severity="error",
                message="The uploaded file is not a valid ZIP archive.",
            ),
        )


@pytest.mark.parametrize("adapter", ["zip", "folder"])
def test_empty_packages_are_rejected(adapter: str) -> None:
    package = (
        inspect_zip_stream(_chunks(_zip([("empty/", b"")])))
        if adapter == "zip"
        else inspect_browser_folder([])
    )

    with package:
        assert not package.accepted
        assert package.manifest is None
        assert package.issues == (
            package.issues[0].__class__(
                code="empty_package",
                path=None,
                severity="error",
                message="The roadmap package does not contain any supported files.",
            ),
        )
