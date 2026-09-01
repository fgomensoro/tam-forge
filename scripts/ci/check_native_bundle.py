"""Verify the standalone signed macOS Release app and reject test/runtime baggage."""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
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
ALLOWED_BINARY_PATHS = (
    Path("Contents/MacOS/TAMForge"),
    Path("Contents/Frameworks/libswiftCompatibilitySpan.dylib"),
)
SWIFT_COMPATIBILITY_PATH = ALLOWED_BINARY_PATHS[1]
SWIFT_COMPATIBILITY_IDENTIFIER = "com.apple.dt.runtime.swiftCompatibilitySpan"
SWIFT_COMPATIBILITY_INSTALL_NAME = "/usr/lib/swift/libswiftCompatibilitySpan.dylib"
APPLE_DEVELOPER_TEAM_IDENTIFIER = "59GAB85EFG"
APPLE_SWIFT_COMPATIBILITY_REQUIREMENT = (
    'anchor apple generic and identifier "com.apple.dt.runtime.swiftCompatibilitySpan"'
)
ALLOWED_RUNPATHS = frozenset(
    {"/usr/lib/swift", "@executable_path/../Frameworks"}
)
MACH_O_MAGICS = frozenset(
    {
        b"\xce\xfa\xed\xfe",  # MH_MAGIC, little-endian
        b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64, little-endian
        b"\xfe\xed\xfa\xce",  # MH_CIGAM, big-endian
        b"\xfe\xed\xfa\xcf",  # MH_CIGAM_64, big-endian
        b"\xca\xfe\xba\xbe",  # FAT_MAGIC, big-endian
        b"\xca\xfe\xba\xbf",  # FAT_MAGIC_64, big-endian
        b"\xbe\xba\xfe\xca",  # FAT_CIGAM, little-endian
        b"\xbf\xba\xfe\xca",  # FAT_CIGAM_64, little-endian
    }
)


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


def _is_executable_or_macho(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
        with path.open("rb") as payload:
            magic = payload.read(4)
    except OSError:
        return False
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)) or magic in MACH_O_MAGICS


def _binary_payloads(app: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(item for item in app.rglob("*") if item.is_file())
        if _is_executable_or_macho(path)
    )


def _allowed_binary_payloads(app: Path) -> tuple[Path, ...]:
    allowed = {app / relative for relative in ALLOWED_BINARY_PATHS}
    return tuple(path for path in _binary_payloads(app) if path in allowed)


def bundle_violations(
    app: Path,
    *,
    linked_libraries: str = "",
    load_commands: str = "",
) -> tuple[str, ...]:
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

    executable = app / ALLOWED_BINARY_PATHS[0]
    if not executable.is_file() or not os.access(executable, os.X_OK):
        violations.append("Release executable is missing or not executable")
    macos_files = (
        sorted(path.name for path in executable.parent.iterdir())
        if executable.parent.is_dir()
        else []
    )
    if macos_files != ["TAMForge"]:
        violations.append(f"Release MacOS payload drifted: {macos_files}")

    allowed_binaries = {app / relative for relative in ALLOWED_BINARY_PATHS}
    for path in _binary_payloads(app):
        if path not in allowed_binaries:
            violations.append(
                "unexpected executable or Mach-O payload: "
                f"{path.relative_to(app)}"
            )

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
    for link_marker in FORBIDDEN_LINK_MARKERS:
        if link_marker in lowered_links:
            violations.append(f"forbidden linked runtime: {link_marker}")
    for library in _linked_library_paths(linked_libraries):
        if not _is_standalone_library_reference(library):
            violations.append(f"non-standalone linked library: {library}")
    for runpath in _runpaths(load_commands):
        if runpath not in ALLOWED_RUNPATHS:
            violations.append(f"non-standalone Mach-O runpath: {runpath}")
    return tuple(violations)


def _linked_library_paths(details: str) -> tuple[str, ...]:
    libraries: list[str] = []
    for raw_line in details.splitlines():
        line = raw_line.strip()
        if not line or line.endswith(":"):
            continue
        libraries.append(line.split(" (compatibility version", 1)[0])
    return tuple(libraries)


def _is_standalone_library_reference(library: str) -> bool:
    if "/../" in library or library.endswith("/.."):
        return False
    return (
        library.startswith("/System/Library/Frameworks/")
        or library.startswith("/usr/lib/")
        or library == "@rpath/libswiftCompatibilitySpan.dylib"
    )


def _runpaths(details: str) -> tuple[str, ...]:
    runpaths: list[str] = []
    awaiting_path = False
    for raw_line in details.splitlines():
        line = raw_line.strip()
        if line == "cmd LC_RPATH":
            awaiting_path = True
            continue
        if awaiting_path and line.startswith("path "):
            runpaths.append(line[5:].split(" (offset ", 1)[0])
            awaiting_path = False
    return tuple(runpaths)


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout + completed.stderr


def _mach_o_uuids(details: str) -> frozenset[tuple[str, str]]:
    return frozenset(
        (match.group(2), match.group(1).upper())
        for match in re.finditer(
            r"UUID: ([0-9A-Fa-f-]+) \(([^)]+)\)",
            details,
        )
    )


def _signature_stripped_sha256(path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="tamforge-native-bundle-") as directory:
        unsigned = Path(directory) / path.name
        shutil.copy2(path, unsigned)
        _run(["codesign", "--remove-signature", str(unsigned)])
        with unsigned.open("rb") as payload:
            return hashlib.file_digest(payload, "sha256").hexdigest()


def _swift_compatibility_violations(app: Path) -> tuple[str, ...]:
    bundled = app / SWIFT_COMPATIBILITY_PATH
    if not bundled.is_file():
        return ()

    violations: list[str] = []
    bundled_signature = _run(["codesign", "-dv", "--verbose=4", str(bundled)])
    if f"Identifier={SWIFT_COMPATIBILITY_IDENTIFIER}" not in bundled_signature:
        violations.append("Swift compatibility library identifier is not trusted")

    install_names = {
        line.strip() for line in _run(["otool", "-D", str(bundled)]).splitlines()
    }
    if SWIFT_COMPATIBILITY_INSTALL_NAME not in install_names:
        violations.append("Swift compatibility library install name is not trusted")

    swiftc = Path(_run(["xcrun", "--find", "swiftc"]).strip())
    toolchain = swiftc.parents[2] if len(swiftc.parents) >= 3 else Path()
    candidates = tuple(
        sorted(
            toolchain.glob(
                "usr/lib/swift-*/macosx/libswiftCompatibilitySpan.dylib"
            )
        )
    )
    trusted_uuids: set[frozenset[tuple[str, str]]] = set()
    trusted_digests: set[str] = set()
    for candidate in candidates:
        signature = _run(["codesign", "-dv", "--verbose=4", str(candidate)])
        if (
            f"Identifier={SWIFT_COMPATIBILITY_IDENTIFIER}" in signature
            and f"TeamIdentifier={APPLE_DEVELOPER_TEAM_IDENTIFIER}" in signature
        ):
            try:
                _run(
                    [
                        "codesign",
                        "--verify",
                        "--strict",
                        "--verbose=4",
                        f"-R={APPLE_SWIFT_COMPATIBILITY_REQUIREMENT}",
                        str(candidate),
                    ]
                )
            except subprocess.CalledProcessError:
                continue
            trusted_uuids.add(
                _mach_o_uuids(_run(["dwarfdump", "--uuid", str(candidate)]))
            )
            trusted_digests.add(_signature_stripped_sha256(candidate))
    bundled_uuids = _mach_o_uuids(_run(["dwarfdump", "--uuid", str(bundled)]))
    if not bundled_uuids or bundled_uuids not in trusted_uuids:
        violations.append(
            "Swift compatibility library does not match the signed Xcode toolchain"
        )
    if _signature_stripped_sha256(bundled) not in trusted_digests:
        violations.append(
            "Swift compatibility library content differs from the signed Xcode toolchain"
        )
    return tuple(violations)


def check_bundle(app: Path, *, require_ad_hoc: bool) -> None:
    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    signature_details = _run(["codesign", "-dv", "--verbose=4", str(app)])
    if require_ad_hoc and "Signature=adhoc" not in signature_details:
        raise NativeBundleError("Release app does not have the required ad-hoc signature")
    violations = bundle_violations(app)
    if violations:
        raise NativeBundleError("; ".join(violations))

    binaries = _allowed_binary_payloads(app)
    links_by_binary = {
        binary: _run(["otool", "-L", str(binary)]) for binary in binaries
    }
    main = app / ALLOWED_BINARY_PATHS[0]
    main_links = _linked_library_paths(links_by_binary.get(main, ""))
    compatibility = app / SWIFT_COMPATIBILITY_PATH
    compatibility_linked = "@rpath/libswiftCompatibilitySpan.dylib" in main_links
    if compatibility_linked != compatibility.is_file():
        raise NativeBundleError(
            "Swift compatibility library payload and executable link must agree"
        )

    load_commands_by_binary = {
        binary: _run(["otool", "-l", str(binary)]) for binary in binaries
    }
    if (
        compatibility_linked
        and "@executable_path/../Frameworks"
        not in _runpaths(load_commands_by_binary.get(main, ""))
    ):
        raise NativeBundleError(
            "linked Swift compatibility library requires the bundled Frameworks runpath"
        )

    compatibility_violations = _swift_compatibility_violations(app)
    if compatibility_violations:
        raise NativeBundleError("; ".join(compatibility_violations))

    links = "\n".join(links_by_binary.values())
    load_commands = "\n".join(load_commands_by_binary.values())
    violations = bundle_violations(
        app,
        linked_libraries=links,
        load_commands=load_commands,
    )
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
