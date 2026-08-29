from __future__ import annotations

import hashlib
from pathlib import Path


CONFIG_DIR = Path(__file__).parents[5] / "config"
PHASE1_RELEASE_DIR = CONFIG_DIR / "releases" / "phase-1-six-week-v1"

EXPECTED_ROOT_SHA256 = {
    "tam-skills.yaml": "6008a4b157272d3cb62685b647f1cf3dfd889dd79014a40cc9cd86083ea4fecf",
    "tam-exercise-types.yaml": "e0275f1c546f5899954f5e9b66f2f05db5a15d24465ed367acd6f36af8ba0e78",
    "tam-rubrics.yaml": "32767e6393475a6e1c9dda52aa5f638940a38dc7a0881657baeb4b3baba43a00",
    "tam-roadmap-task-map.yaml": "44206a242e9c6b9219b2de7cf27ff709e96e5f553ba4c378d3a83092d03fc814",
}
SCORING_FILES = (
    "tam-skills.yaml",
    "tam-exercise-types.yaml",
    "tam-rubrics.yaml",
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_phase1_release_freezes_legacy_scoring_bytes() -> None:
    root_bytes: dict[str, bytes] = {}
    for filename, expected_hash in EXPECTED_ROOT_SHA256.items():
        content = (CONFIG_DIR / filename).read_bytes()
        root_bytes[filename] = content
        assert _sha256(content) == expected_hash

    for filename in SCORING_FILES:
        release_path = PHASE1_RELEASE_DIR / filename
        assert release_path.is_file(), f"missing Phase 1 scoring freeze: {release_path}"
        release_bytes = release_path.read_bytes()
        assert release_bytes == root_bytes[filename]
        assert _sha256(release_bytes) == EXPECTED_ROOT_SHA256[filename]
