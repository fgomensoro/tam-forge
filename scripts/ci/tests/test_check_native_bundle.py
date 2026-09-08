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
        if command[:2] == ["otool", "-l"]:
            return (
                "cmd LC_RPATH\n"
                "path @executable_path/../Frameworks (offset 12)"
            )
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
        if command[:2] == ["otool", "-l"]:
            return (
                "cmd LC_RPATH\n"
                "path @executable_path/../Frameworks (offset 12)"
            )
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


def test_checker_requires_frameworks_runpath_for_linked_compatibility_payload(
    tmp_path: Path, monkeypatch: object
) -> None:
    app = _app(tmp_path)
    compatibility = app / "Contents" / "Frameworks" / "libswiftCompatibilitySpan.dylib"
    compatibility.parent.mkdir(parents=True)
    compatibility.write_bytes(b"\xcf\xfa\xed\xfe Apple Swift compatibility")

    def fake_run(command: list[str]) -> str:
        if command[:3] == ["codesign", "-dv", "--verbose=4"]:
            return "Signature=adhoc"
        if command[:2] == ["otool", "-L"] and command[-1].endswith("/TAMForge"):
            return "@rpath/libswiftCompatibilitySpan.dylib"
        if command[:2] == ["otool", "-l"]:
            return "cmd LC_RPATH\npath /usr/lib/swift (offset 12)"
        return ""

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        check_native_bundle,
        "_swift_compatibility_violations",
        lambda _app: (),
    )

    try:
        check_bundle(app, require_ad_hoc=True)
    except NativeBundleError as exc:
        assert "requires the bundled Frameworks runpath" in str(exc)
    else:
        raise AssertionError("linked compatibility payload without bundle runpath was accepted")


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


def test_signature_identity_check_requires_the_stable_local_identity() -> None:
    from scripts.ci.check_native_bundle import signature_identity_violation

    stable = (
        "Identifier=com.fgomensoro.tamforge\n"
        "Authority=TAM Forge Local Development\n"
        "Signature size=8981\n"
    )
    adhoc = "Identifier=com.fgomensoro.tamforge\nSignature=adhoc\n"
    other = "Identifier=com.fgomensoro.tamforge\nAuthority=Apple Development: Someone\n"

    assert signature_identity_violation(stable, "TAM Forge Local Development") is None
    assert "ad-hoc" in signature_identity_violation(adhoc, "TAM Forge Local Development")
    assert "TAM Forge Local Development" in signature_identity_violation(
        other, "TAM Forge Local Development"
    )


def test_check_bundle_rejects_ad_hoc_when_identity_is_required(
    tmp_path: Path, monkeypatch: object
) -> None:
    import pytest

    app = _app(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        calls.append(command)
        return "Identifier=com.fgomensoro.tamforge\nSignature=adhoc\n"

    monkeypatch.setattr(check_native_bundle, "_run", fake_run)  # type: ignore[attr-defined]

    with pytest.raises(NativeBundleError, match="ad-hoc"):
        check_bundle(app, require_ad_hoc=False, require_identity="TAM Forge Local Development")
    assert calls[0][:2] == ["codesign", "--verify"]


def _whisper_framework(app: Path) -> Path:
    """Lay out the bundled framework the way the real XCFramework installs it:
    the real binary under Versions/A, plus the Versions/Current and top-level
    symlinks Xcode's Embed Frameworks phase copies alongside it."""
    framework = app / "Contents" / "Frameworks" / "whisper.framework"
    versioned = framework / "Versions" / "A"
    versioned.mkdir(parents=True)
    binary = versioned / "whisper"
    binary.write_bytes(b"\xcf\xfa\xed\xfe whisper dylib payload")
    binary.chmod(0o755)
    (framework / "Versions" / "Current").symlink_to("A")
    (framework / "whisper").symlink_to("Versions/Current/whisper")
    return framework


def test_whisper_framework_binary_is_allowed(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _whisper_framework(app)

    assert bundle_violations(app) == ()


def test_second_unexpected_framework_binary_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _whisper_framework(app)
    other = app / "Contents" / "Frameworks" / "openvino.framework" / "Versions" / "A" / "openvino"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"\xcf\xfa\xed\xfe openvino dylib payload")
    other.chmod(0o755)

    violations = bundle_violations(app)

    assert (
        "unexpected executable or Mach-O payload: "
        "Contents/Frameworks/openvino.framework/Versions/A/openvino"
    ) in violations


def test_whisper_framework_linked_library_reference_is_allowed(tmp_path: Path) -> None:
    app = _app(tmp_path)

    violations = bundle_violations(
        app, linked_libraries="@rpath/whisper.framework/Versions/Current/whisper"
    )

    assert violations == ()


def test_other_framework_linked_library_reference_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)

    violations = bundle_violations(app, linked_libraries="@rpath/other.framework/other")

    assert violations == ("non-standalone linked library: @rpath/other.framework/other",)


def test_symlink_to_allowed_binary_is_not_counted_as_extra_payload(tmp_path: Path) -> None:
    app = _app(tmp_path)
    # A symlink elsewhere pointing at the already-allowed executable must not
    # itself be treated as a second, unexpected payload. Contents/Frameworks
    # (unlike Contents/MacOS) has no "exact contents" check, so this isolates
    # the symlink-skipping behavior from the unrelated MacOS payload check.
    alias = app / "Contents" / "Frameworks" / "TAMForgeAlias"
    alias.parent.mkdir(parents=True)
    alias.symlink_to("../MacOS/TAMForge")

    assert bundle_violations(app) == ()


def test_only_the_real_whisper_install_name_is_accepted(tmp_path: Path) -> None:
    # The framework records @rpath/whisper.framework/Versions/Current/whisper;
    # no other spelling of the same payload may pass.
    app = _app(tmp_path)
    for rejected in (
        "@rpath/whisper.framework/Versions/A/whisper",
        "@rpath/whisper.framework/Versions/B/whisper",
        "@rpath/whisper.framework/whisper",
    ):
        violations = bundle_violations(app, linked_libraries=rejected)
        assert any("non-standalone linked library" in item for item in violations), rejected
