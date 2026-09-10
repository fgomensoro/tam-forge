"""Guard the one placement rule that makes an integration marker actually run."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
INTEGRATION_SUITE = REPOSITORY_ROOT / "apps" / "backend" / "tests" / "integration"
MARKER = "pytest.mark.integration"
# This file spells the marker out in MARKER, so it would otherwise report itself.
SELF = Path(__file__).resolve()


def test_integration_markers_live_only_under_the_integration_suite() -> None:
    configuration = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    marked = [
        path
        for test_path in configuration["tool"]["pytest"]["ini_options"]["testpaths"]
        for path in (REPOSITORY_ROOT / test_path).rglob("*.py")
        if MARKER in path.read_text(encoding="utf-8")
    ]
    assert marked, "no marker found anywhere, so this guard is not reading the test tree"

    offenders = sorted(
        str(path.relative_to(REPOSITORY_ROOT))
        for path in marked
        if not path.is_relative_to(INTEGRATION_SUITE) and path.resolve() != SELF
    )
    assert not offenders, (
        "every configured pytest run either deselects the integration marker or "
        "limits itself to apps/backend/tests/integration, so these files run "
        f"nowhere; move them into the integration suite: {offenders}"
    )
