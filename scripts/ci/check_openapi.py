"""Fail when the checked-in web API types drift from FastAPI's OpenAPI schema."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.main import create_app

ROOT = Path(__file__).parents[2]
TARGET = ROOT / "apps" / "web" / "src" / "api" / "schema.d.ts"


def generated_schema() -> bytes:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    with tempfile.TemporaryDirectory(prefix="tamforge-openapi-") as directory:
        temporary = Path(directory)
        source = temporary / "openapi.json"
        output = temporary / "schema.d.ts"
        source.write_text(
            json.dumps(app.openapi(), ensure_ascii=True),
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
    generated = generated_schema()
    if arguments.write:
        TARGET.write_bytes(generated)
        print(f"updated {TARGET.relative_to(ROOT)}")
        return 0
    if not TARGET.exists() or TARGET.read_bytes() != generated:
        print("OpenAPI client types are out of date.")
        print("Regenerate them with: uv run python scripts/ci/check_openapi.py --write")
        return 1
    print("OpenAPI client types match the backend schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
