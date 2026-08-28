"""Fail when checked OpenAPI inputs drift from FastAPI's schema."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.main import create_app

ROOT = Path(__file__).parents[2]
WEB_TARGET = ROOT / "apps" / "web" / "src" / "api" / "schema.d.ts"
NATIVE_TARGET = ROOT / "apps" / "macos" / "TAMForge" / "openapi.yaml"


def generated_openapi_schema() -> dict[str, object]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    return app.openapi()


def normalized_openapi_document() -> bytes:
    return json.dumps(
        generated_openapi_schema(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def generated_web_schema() -> bytes:
    with tempfile.TemporaryDirectory(prefix="tamforge-openapi-") as directory:
        temporary = Path(directory)
        source = temporary / "openapi.json"
        output = temporary / "schema.d.ts"
        source.write_text(
            json.dumps(generated_openapi_schema(), ensure_ascii=True),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "pnpm",
                "--filter",
                "@tam-forge/web",
                "exec",
                "openapi-typescript",
                str(source),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
        )
        return output.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Replace the checked-in types with the generated schema.",
    )
    arguments = parser.parse_args()
    document = normalized_openapi_document()
    generated = generated_web_schema()
    if arguments.write:
        WEB_TARGET.write_bytes(generated)
        NATIVE_TARGET.write_bytes(document)
        print(f"updated {WEB_TARGET.relative_to(ROOT)}")
        print(f"updated {NATIVE_TARGET.relative_to(ROOT)}")
        return 0
    if not WEB_TARGET.exists() or WEB_TARGET.read_bytes() != generated:
        print("OpenAPI client types are out of date.")
        print("Regenerate them with: uv run python scripts/ci/check_openapi.py --write")
        return 1
    if not NATIVE_TARGET.exists() or NATIVE_TARGET.read_bytes() != document:
        print("Native OpenAPI input is out of date.")
        print("Regenerate it with: uv run python scripts/ci/check_openapi.py --write")
        return 1
    print("Web client types and native OpenAPI input match the backend schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
