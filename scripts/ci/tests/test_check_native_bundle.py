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

    assert calls[-1] == [
        "otool",
        "-L",
        str(app / "Contents" / "MacOS" / "TAMForge"),
    ]


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
