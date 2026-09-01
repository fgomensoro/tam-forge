"""Verify the standalone signed macOS Release app and reject test/runtime baggage."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path
from typing import Any

FIXTURE_MARKERS = (
    b"-ui-test-",
    b"TAMFORGE_UI_FIXTURE_BASE64",
    b"ui-test-only",
    b"NativeUIFixtureProtocol",
    b"NativeParityUIFixture",
    b"native-foundation-month1-v1",
)
FORBIDDEN_SUFFIXES = frozenset(
    {".css", ".db", ".html", ".js", ".jsx", ".py", ".pyc", ".sql", ".sqlite", ".ts", ".tsx"}
)
FORBIDDEN_COMPONENTS = frozenset(
    {
        "chromium",
        "electron framework.framework",
        "node",
        "node_modules",
        "postgres",
        "postgresql",
        "python",
        "python3",
    }
)
FORBIDDEN_LINK_MARKERS = ("chromium", "electron", "node", "postgres", "python")


class NativeBundleError(RuntimeError):
    """Raised when a Release app is incomplete or contains forbidden baggage."""


def _plist(path: Path) -> dict[str, Any]:
    try:
        payload = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise NativeBundleError("Release Info.plist is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise NativeBundleError("Release Info.plist is not a dictionary")
    return payload


def bundle_violations(app: Path, *, linked_libraries: str = "") -> tuple[str, ...]:
    violations: list[str] = []
    if not app.is_dir() or app.suffix != ".app":
        return ("Release app bundle does not exist",)

    info = _plist(app / "Contents" / "Info.plist")
    expected_info = {
        "CFBundleIdentifier": "com.fgomensoro.tamforge",
        "CFBundleExecutable": "TAMForge",
        "CFBundlePackageType": "APPL",
    }
    for key, expected in expected_info.items():
        if info.get(key) != expected:
            violations.append(f"Release Info.plist {key} is not {expected}")

    executable = app / "Contents" / "MacOS" / "TAMForge"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        violations.append("Release executable is missing or not executable")
    macos_files = (
        sorted(path.name for path in executable.parent.iterdir())
        if executable.parent.is_dir()
        else []
    )
    if macos_files != ["TAMForge"]:
        violations.append(f"Release MacOS payload drifted: {macos_files}")

    for path in sorted(item for item in app.rglob("*") if item.is_file()):
        relative = path.relative_to(app)
        components = {part.casefold() for part in relative.parts}
        if components & FORBIDDEN_COMPONENTS:
            violations.append(f"forbidden embedded runtime: {relative}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            violations.append(f"forbidden runtime/tooling artifact: {relative}")
        try:
            contents = path.read_bytes()
        except OSError:
            violations.append(f"Release bundle file is unreadable: {relative}")
            continue
        for marker in FIXTURE_MARKERS:
            if marker in contents:
                violations.append(
                    f"DEBUG fixture seam {marker.decode('ascii')} leaked into {relative}"
                )

    lowered_links = linked_libraries.casefold()
    for marker in FORBIDDEN_LINK_MARKERS:
        if marker in lowered_links:
            violations.append(f"forbidden linked runtime: {marker}")
    return tuple(violations)


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout + completed.stderr


def check_bundle(app: Path, *, require_ad_hoc: bool) -> None:
    executable = app / "Contents" / "MacOS" / "TAMForge"
    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    signature_details = _run(["codesign", "-dv", "--verbose=4", str(app)])
    if require_ad_hoc and "Signature=adhoc" not in signature_details:
        raise NativeBundleError("Release app does not have the required ad-hoc signature")
    links = _run(["otool", "-L", str(executable)])
    violations = bundle_violations(app, linked_libraries=links)
    if violations:
        raise NativeBundleError("; ".join(violations))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("--require-ad-hoc", action="store_true")
    args = parser.parse_args()
    check_bundle(args.app, require_ad_hoc=args.require_ad_hoc)
    print(f"native Release bundle is standalone and signed: {args.app}")


if __name__ == "__main__":
    main()
