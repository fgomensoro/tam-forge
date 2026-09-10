from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest
import yaml

MANIFEST = Path("config/speech-models.yaml")
REQUIRED_KEYS = {"whisper_framework", "transcription_model", "vad_model", "benchmark_model"}
FIELDS = {"version", "url", "filename", "bytes", "sha256", "license", "installs_to", "consumed_by"}


def manifest() -> dict[str, object]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def install_dir(artifact: str) -> Path:
    raw = manifest()["artifacts"][artifact]["installs_to"]
    return Path(raw.replace("~", str(Path.home()), 1)) if raw.startswith("~") else Path(raw)


def test_every_artifact_is_pinned_by_size_and_hash() -> None:
    document = manifest()
    assert document["schema_version"] == 1
    artifacts = document["artifacts"]
    assert set(artifacts) == REQUIRED_KEYS
    for name, entry in artifacts.items():
        assert set(entry) == FIELDS, name
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), name
        assert isinstance(entry["bytes"], int) and entry["bytes"] > 0, name
        assert entry["url"].startswith("https://"), name
        assert entry["license"], name


def test_pins_match_the_reviewed_artifacts() -> None:
    artifacts = manifest()["artifacts"]
    assert artifacts["whisper_framework"]["version"] == "b4938"
    assert artifacts["whisper_framework"]["sha256"] == (
        "dcc6cdc6d6902d11893434ceda70c23a2a64450f65a1b570035c9908988dfedd"
    )
    # The #43 benchmark on the owner's voice chose small.en, so it is the
    # shipped model; base.en stays pinned as the comparison it beat.
    assert artifacts["transcription_model"]["filename"] == "ggml-small.en-q5_1.bin"
    assert artifacts["transcription_model"]["sha256"] == (
        "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30"
    )
    assert artifacts["vad_model"]["sha256"] == (
        "29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf"
    )


def test_fetch_scripts_read_their_pins_from_the_manifest() -> None:
    for script in ("fetch_whisper_framework.sh", "fetch_whisper_models.sh"):
        source = Path("scripts/dev") / script
        assert source.exists(), script
        text = source.read_text(encoding="utf-8")
        assert "config/speech-models.yaml" in text, script
        assert "shasum" in text or "sha256sum" in text, script
        # Pins live in the manifest, never duplicated in the script.
        assert "dcc6cdc6d690" not in text, script
        assert "4baf70dd0d7c" not in text, script


def test_installed_artifacts_match_their_pins_when_present(tmp_path: Path) -> None:
    artifacts = manifest()["artifacts"]
    vendor = Path("apps/macos/Vendor/whisper.xcframework")
    if vendor.is_dir():
        macos = vendor / "macos-arm64_x86_64" / "whisper.framework"
        assert macos.is_dir(), "installed XCFramework is missing its macOS slice"
    # Hashing the installed models reads ~190 MB out of the app's sandbox
    # container, a path that lives outside the repository and can stop
    # responding: on 2026-09-09 every open under it blocked for minutes while
    # stat stayed instant, so this test silently turned a 35-second suite into
    # an indefinite hang. Machine state must never be able to wedge the default
    # run, so the read is opt-in.
    if not os.environ.get("TAMFORGE_VERIFY_INSTALLED_MODELS"):
        pytest.skip("set TAMFORGE_VERIFY_INSTALLED_MODELS=1 to hash the installed models")
    models = install_dir("transcription_model")
    for name in ("transcription_model", "vad_model"):
        entry = artifacts[name]
        installed = models / entry["filename"]
        if not installed.is_file():
            pytest.skip(f"{entry['filename']} is not installed on this machine")
        assert installed.stat().st_size == entry["bytes"]
        # Streamed rather than read_bytes(): a 190 MB allocation is what makes
        # this hurt most on a machine that is already short of memory.
        with installed.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        assert digest == entry["sha256"]


def test_transcription_model_sha256_constant_matches_the_manifest() -> None:
    # SpeechModelCatalog.transcriptionModelSHA256 (issue #42 Task 3) is recorded
    # by hand rather than hashed at runtime; this pins it against the manifest
    # so the two can never silently drift apart.
    catalog_source = Path(
        "apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift"
    ).read_text(encoding="utf-8")
    match = re.search(
        r'static let transcriptionModelSHA256 = "([0-9a-f]{64})"', catalog_source
    )
    assert match, "transcriptionModelSHA256 constant not found in SpeechModelCatalog.swift"
    artifacts = manifest()["artifacts"]
    assert match.group(1) == artifacts["transcription_model"]["sha256"]


def test_benchmark_model_is_pinned_with_the_same_quantization() -> None:
    artifacts = manifest()["artifacts"]
    assert "benchmark_model" in artifacts
    benchmark = artifacts["benchmark_model"]
    assert benchmark["filename"] == "ggml-base.en-q5_1.bin"
    assert benchmark["bytes"] == 59721011
    assert benchmark["sha256"] == (
        "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f"
    )
    # Same quantization as the shipped model, so the comparison isolates size.
    assert benchmark["version"] == artifacts["transcription_model"]["version"]
    assert benchmark["installs_to"] == artifacts["transcription_model"]["installs_to"]


def test_models_install_inside_the_app_sandbox_container() -> None:
    # TAMForge.app is sandboxed, so SpeechModelCatalog.defaultDirectory resolves
    # .applicationSupportDirectory to the container-redirected path. A model
    # installed anywhere else is unreadable by the app, WhisperTranscriber is
    # never constructed, and transcription silently stays off with no error.
    container = (
        Path.home()
        / "Library"
        / "Containers"
        / "com.fgomensoro.tamforge"
        / "Data"
        / "Library"
        / "Application Support"
    )
    for name in ("transcription_model", "vad_model", "benchmark_model"):
        assert container in install_dir(name).parents, name
