"""Reject tracked secrets and source audio/object-store artifacts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).parents[2]
FORBIDDEN_SUFFIXES = frozenset(
    {".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
)
FORBIDDEN_PARTS = frozenset({"audio", "object-data", "local-object-data", "spools"})
SECRET_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Anthropic API key", re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(rb"gh[opurs]_[A-Za-z0-9]{20,}")),
    ("AWS access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
)


def _is_obvious_placeholder(label: str, value: bytes) -> bool:
    if label != "GitHub token":
        return False
    suffix = value.split(b"_", 1)[-1]
    return len(set(suffix.lower())) <= 2


def tracked_files() -> tuple[PurePosixPath, ...]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return tuple(
        PurePosixPath(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def violations(paths: tuple[PurePosixPath, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for relative in paths:
        if relative.name == ".env" or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            found.append(f"forbidden tracked artifact: {relative}")
            continue
        if FORBIDDEN_PARTS.intersection(relative.parts):
            found.append(f"forbidden tracked data directory: {relative}")
            continue
        path = ROOT / relative
        try:
            data = path.read_bytes()
        except OSError:
            found.append(f"tracked file cannot be inspected: {relative}")
            continue
        if len(data) > 5 * 1024 * 1024 or b"\0" in data:
            continue
        for label, pattern in SECRET_PATTERNS:
            matches = pattern.finditer(data)
            if any(
                not _is_obvious_placeholder(label, match.group(0))
                for match in matches
            ):
                found.append(f"{label} pattern in {relative}")
    return tuple(found)


def main() -> int:
    found = violations(tracked_files())
    if found:
        print("Repository policy check failed:")
        for item in found:
            print(f"- {item}")
        return 1
    print("Repository contains no tracked source audio, object data, or known secret patterns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
