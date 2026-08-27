from __future__ import annotations

from dataclasses import replace

import pytest
from tamforge_backend.roadmaps.manifest import ManifestError, build_manifest
from tamforge_backend.roadmaps.schemas import ManifestFile


def _file(path: str, *, digest: str = "a" * 64, size: int = 4) -> ManifestFile:
    return ManifestFile(
        path=path,
        original_filename=path.rsplit("/", 1)[-1],
        byte_size=size,
        media_type="text/markdown" if path.endswith(".md") else "application/sql",
        sha256=digest,
    )


def test_manifest_is_sorted_and_hash_is_independent_of_upload_order() -> None:
    readme = _file("README.md")
    sql = _file("sql/setup.sql", digest="b" * 64, size=9)

    first = build_manifest([sql, readme])
    second = build_manifest([readme, sql])

    assert [item.path for item in first.files] == ["README.md", "sql/setup.sql"]
    assert first == second
    assert len(first.content_hash) == 64
    assert first.to_dict() == {
        "schema_version": 1,
        "content_hash": first.content_hash,
        "files": [
            {
                "path": "README.md",
                "original_filename": "README.md",
                "byte_size": 4,
                "media_type": "text/markdown",
                "sha256": "a" * 64,
            },
            {
                "path": "sql/setup.sql",
                "original_filename": "setup.sql",
                "byte_size": 9,
                "media_type": "application/sql",
                "sha256": "b" * 64,
            },
        ],
    }


def test_manifest_hash_changes_when_original_bytes_change() -> None:
    original = _file("README.md")
    changed = replace(original, sha256="c" * 64)

    assert build_manifest([original]).content_hash != build_manifest([changed]).content_hash


@pytest.mark.parametrize(
    "files",
    [
        [_file("README.md"), _file("README.md", digest="b" * 64)],
        [_file("README.md"), _file("readme.md", digest="b" * 64)],
    ],
)
def test_manifest_rejects_duplicate_and_case_colliding_paths(
    files: list[ManifestFile],
) -> None:
    with pytest.raises(ManifestError):
        build_manifest(files)


def test_manifest_values_are_immutable_and_strictly_validated() -> None:
    for invalid_path in (
        "../README.md",
        "notes//README.md",
        "notes/./README.md",
        "notes/bad\x00.md",
    ):
        with pytest.raises(ValueError):
            _file(invalid_path)
    with pytest.raises(ValueError):
        _file("README.md", digest="A" * 64)
    with pytest.raises(ValueError):
        ManifestFile(
            path="README.md",
            original_filename="other.md",
            byte_size=1,
            media_type="text/markdown",
            sha256="a" * 64,
        )
