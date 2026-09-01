from __future__ import annotations

import os
import plistlib
from pathlib import Path

from scripts.ci import check_native_bundle
from scripts.ci.check_native_bundle import NativeBundleError, bundle_violations, check_bundle


def _app(tmp_path: Path) -> Path:
    app = tmp_path / "TAMForge.app"
    executable = app / "Contents" / "MacOS" / "TAMForge"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"Mach-O production payload")
    executable.chmod(0o755)
    info = {
        "CFBundleIdentifier": "com.fgomensoro.tamforge",
        "CFBundleExecutable": "TAMForge",
        "CFBundlePackageType": "APPL",
    }
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    return app


def test_minimal_standalone_app_passes(tmp_path: Path) -> None:
    app = _app(tmp_path)

    assert bundle_violations(app, linked_libraries="/usr/lib/libSystem.B.dylib") == ()
    assert os.access(app / "Contents" / "MacOS" / "TAMForge", os.X_OK)


def test_fixture_seam_in_executable_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    executable = app / "Contents" / "MacOS" / "TAMForge"
    executable.write_bytes(b"Mach-O TAMFORGE_UI_FIXTURE_BASE64")

    assert bundle_violations(app) == (
        "DEBUG fixture seam TAMFORGE_UI_FIXTURE_BASE64 leaked into Contents/MacOS/TAMForge",
    )


def test_embedded_web_and_python_runtimes_are_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    runtime = app / "Contents" / "Resources" / "node_modules" / "server.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("pass\n", encoding="utf-8")

    violations = bundle_violations(app, linked_libraries="@rpath/Python.framework/Python")

    assert "forbidden embedded runtime: Contents/Resources/node_modules/server.py" in violations
    assert (
        "forbidden runtime/tooling artifact: Contents/Resources/node_modules/server.py"
        in violations
    )
    assert "forbidden linked runtime: python" in violations
    assert "non-standalone linked library: @rpath/Python.framework/Python" in violations


def test_non_system_linked_library_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)

    violations = bundle_violations(
        app,
        linked_libraries="/usr/local/lib/libnotstandalone.dylib (compatibility version 1.0.0)",
    )

    assert violations == (
        "non-standalone linked library: /usr/local/lib/libnotstandalone.dylib",
    )


def test_external_macho_runpath_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)

    violations = bundle_violations(
        app,
        load_commands="Load command 1\n      cmd LC_RPATH\n  cmdsize 32\n"
        "     path /usr/local/lib (offset 12)",
    )

    assert violations == ("non-standalone Mach-O runpath: /usr/local/lib",)


def test_unexpected_second_product_executable_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    helper = app / "Contents" / "MacOS" / "postgres"
    helper.write_bytes(b"helper")
    helper.chmod(0o755)

    violations = bundle_violations(app)

    assert "Release MacOS payload drifted: ['TAMForge', 'postgres']" in violations
    assert "forbidden embedded runtime: Contents/MacOS/postgres" in violations


def test_executable_and_macho_outside_macos_are_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    executable = app / "Contents" / "Resources" / "Telemetry"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    macho = app / "Contents" / "Helpers" / "Metadata"
    macho.parent.mkdir(parents=True)
    macho.write_bytes(b"\xcf\xfa\xed\xfe payload")

    violations = bundle_violations(app)

    assert "unexpected executable or Mach-O payload: Contents/Resources/Telemetry" in violations
    assert "unexpected executable or Mach-O payload: Contents/Helpers/Metadata" in violations


def test_apple_swift_compatibility_library_is_allowed(tmp_path: Path) -> None:
    app = _app(tmp_path)
    compatibility = app / "Contents" / "Frameworks" / "libswiftCompatibilitySpan.dylib"
    compatibility.parent.mkdir(parents=True)
    compatibility.write_bytes(b"\xcf\xfa\xed\xfe Apple Swift compatibility")

    assert bundle_violations(app) == ()


def test_checker_rejects_compatibility_library_trusted_only_by_filename(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = _app(tmp_path)
    compatibility = app / "Contents" / "Frameworks" / "libswiftCompatibilitySpan.dylib"
    compatibility.parent.mkdir(parents=True)
    compatibility.write_bytes(b"\xcf\xfa\xed\xfe attacker payload")

    def fake_run(command: list[str]) -> str:
        if command[:3] == ["codesign", "-dv", "--verbose=4"]:
            if command[-1] == str(app):
                return "Signature=adhoc"
            return "Signature=adhoc\nIdentifier=attacker.library"
        if command[:2] == ["xcrun", "--find"]:
            return str(tmp_path / "Xcode.xctoolchain" / "usr" / "bin" / "swiftc")
        if command[:2] == ["otool", "-L"] and command[-1].endswith("/TAMForge"):
            return "@rpath/libswiftCompatibilitySpan.dylib"
        return ""

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    try:
        check_bundle(app, require_ad_hoc=True)
    except NativeBundleError as exc:
        assert "identifier is not trusted" in str(exc)
        assert "does not match the signed Xcode toolchain" in str(exc)
    else:
        raise AssertionError("filename-only compatibility payload was accepted")


def test_checker_accepts_compatibility_library_matching_signed_xcode_copy(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = _app(tmp_path)
    compatibility = app / "Contents" / "Frameworks" / "libswiftCompatibilitySpan.dylib"
    compatibility.parent.mkdir(parents=True)
    compatibility.write_bytes(b"\xcf\xfa\xed\xfe Apple Swift compatibility")
    toolchain = tmp_path / "Xcode.xctoolchain"
    swiftc = toolchain / "usr" / "bin" / "swiftc"
    source = (
        toolchain
        / "usr"
        / "lib"
        / "swift-6.2"
        / "macosx"
        / "libswiftCompatibilitySpan.dylib"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"\xcf\xfa\xed\xfe Apple Swift compatibility")
    uuid_details = "UUID: 35FDD7FE-B26C-3F04-AA72-2DB973F905B1 (arm64) payload"

    def fake_run(command: list[str]) -> str:
        if command[:3] == ["codesign", "-dv", "--verbose=4"]:
            if command[-1] == str(app):
                return "Signature=adhoc"
            if command[-1] == str(source):
                return (
                    "Identifier=com.apple.dt.runtime.swiftCompatibilitySpan\n"
                    "TeamIdentifier=59GAB85EFG"
                )
            return "Identifier=com.apple.dt.runtime.swiftCompatibilitySpan"
        if command[:2] == ["otool", "-D"]:
            return "/usr/lib/swift/libswiftCompatibilitySpan.dylib"
        if command[:2] == ["xcrun", "--find"]:
            return str(swiftc)
        if command[:2] == ["dwarfdump", "--uuid"]:
            return uuid_details
        if command[:2] == ["otool", "-L"] and command[-1].endswith("/TAMForge"):
            return (
                "/usr/lib/libSystem.B.dylib\n"
                "@rpath/libswiftCompatibilitySpan.dylib"
            )
        if command[:2] == ["otool", "-l"]:
            return (
                "Load command 1\n      cmd LC_RPATH\n  cmdsize 32\n"
                "     path @executable_path/../Frameworks (offset 12)"
            )
        return "/usr/lib/libSystem.B.dylib"

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    check_bundle(app, require_ad_hoc=True)


def test_checker_rejects_modified_compatibility_content_with_trusted_metadata(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = _app(tmp_path)
    compatibility = app / "Contents" / "Frameworks" / "libswiftCompatibilitySpan.dylib"
    compatibility.parent.mkdir(parents=True)
    compatibility.write_bytes(b"\xcf\xfa\xed\xfe modified payload")
    toolchain = tmp_path / "Xcode.xctoolchain"
    swiftc = toolchain / "usr" / "bin" / "swiftc"
    source = (
        toolchain
        / "usr"
        / "lib"
        / "swift-6.2"
        / "macosx"
        / "libswiftCompatibilitySpan.dylib"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"\xcf\xfa\xed\xfe trusted payload")
    uuid_details = "UUID: 35FDD7FE-B26C-3F04-AA72-2DB973F905B1 (arm64) payload"

    def fake_run(command: list[str]) -> str:
        if command[:3] == ["codesign", "-dv", "--verbose=4"]:
            if command[-1] == str(app):
                return "Signature=adhoc"
            return (
                "Identifier=com.apple.dt.runtime.swiftCompatibilitySpan\n"
                "TeamIdentifier=59GAB85EFG"
            )
        if command[:2] == ["otool", "-D"]:
            return "/usr/lib/swift/libswiftCompatibilitySpan.dylib"
        if command[:2] == ["xcrun", "--find"]:
            return str(swiftc)
        if command[:2] == ["dwarfdump", "--uuid"]:
            return uuid_details
        if command[:2] == ["otool", "-L"] and command[-1].endswith("/TAMForge"):
            return "@rpath/libswiftCompatibilitySpan.dylib"
        return ""

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    try:
        check_bundle(app, require_ad_hoc=True)
    except NativeBundleError as exc:
        assert "content differs from the signed Xcode toolchain" in str(exc)
    else:
        raise AssertionError("modified compatibility content was accepted")


def test_checker_requires_linked_compatibility_payload(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = _app(tmp_path)

    def fake_run(command: list[str]) -> str:
        if command[:3] == ["codesign", "-dv", "--verbose=4"]:
            return "Signature=adhoc"
        if command[:2] == ["otool", "-L"]:
            return "@rpath/libswiftCompatibilitySpan.dylib"
        return ""

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    try:
        check_bundle(app, require_ad_hoc=True)
    except NativeBundleError as exc:
        assert "payload and executable link must agree" in str(exc)
    else:
        raise AssertionError("missing linked compatibility payload was accepted")


def test_checker_inspects_only_allowed_binary_dependencies(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = _app(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        calls.append(command)
        if command[0] == "codesign" and "-dv" in command:
            return "Signature=adhoc"
        return "/usr/lib/libSystem.B.dylib"

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    check_bundle(app, require_ad_hoc=True)

    assert ["otool", "-L", str(app / "Contents" / "MacOS" / "TAMForge")] in calls
    assert ["otool", "-l", str(app / "Contents" / "MacOS" / "TAMForge")] in calls


def test_checker_does_not_inspect_rejected_binary(tmp_path: Path, monkeypatch: object) -> None:
    app = _app(tmp_path)
    helper = app / "Contents" / "Resources" / "Telemetry"
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        calls.append(command)
        return "Signature=adhoc"

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    try:
        check_bundle(app, require_ad_hoc=True)
    except NativeBundleError as exc:
        assert "Contents/Resources/Telemetry" in str(exc)
    else:
        raise AssertionError("unexpected binary payload was accepted")

    assert all(command[0] != "otool" for command in calls)
