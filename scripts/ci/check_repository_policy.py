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
FORBIDDEN_PRODUCT_NODE_PATHS = frozenset(
    {
        PurePosixPath("package.json"),
        PurePosixPath("pnpm-lock.yaml"),
        PurePosixPath("pnpm-workspace.yaml"),
    }
)
FORBIDDEN_PRODUCT_NODE_PREFIX = PurePosixPath("apps/web")
WORKFLOW_DIRECTORY = PurePosixPath(".github/workflows")
WORKFLOW_SUFFIXES = frozenset({".yml", ".yaml"})
NODE_LAUNCHER = re.compile(
    rb"(?:^|[;&|()]\s*)(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S+|command|env|exec|sudo|time)\s+)*(?:node|npm|pnpm|npx|yarn|bun)\b",
    re.IGNORECASE,
)
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


def _is_node_invocation_file(relative: PurePosixPath) -> bool:
    return relative == PurePosixPath("Makefile") or (
        relative.parent == WORKFLOW_DIRECTORY and relative.suffix.lower() in WORKFLOW_SUFFIXES
    )


def _active_command_lines(relative: PurePosixPath, data: bytes) -> tuple[bytes, ...]:
    lines = data.splitlines()
    if relative.name == "Makefile":
        return tuple(
            line.lstrip(b"\t@").lstrip(b"@")
            for line in lines
            if line.startswith(b"\t") and not line.lstrip(b"\t@").startswith(b"#")
        )

    commands: list[bytes] = []
    run_indent: int | None = None
    for line in lines:
        indentation = len(line) - len(line.lstrip(b" "))
        stripped = line.strip()
        if run_indent is not None:
            if stripped and indentation <= run_indent:
                run_indent = None
            elif stripped and not stripped.startswith(b"#"):
                commands.append(stripped)
                continue
        match = re.match(rb"^\s*(?:-\s*)?run\s*:\s*(.*)$", line)
        if match is None:
            continue
        command = match.group(1).strip()
        if command in {b"|", b">", b"|-", b">-", b"|+", b">+"}:
            run_indent = indentation
        elif command and not command.startswith(b"#"):
            commands.append(command)
    return tuple(commands)


def _contains_node_launcher(relative: PurePosixPath, data: bytes) -> bool:
    return any(NODE_LAUNCHER.search(line) for line in _active_command_lines(relative, data))


def violations(paths: tuple[PurePosixPath, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for relative in paths:
        if relative in FORBIDDEN_PRODUCT_NODE_PATHS or relative.is_relative_to(
            FORBIDDEN_PRODUCT_NODE_PREFIX
        ):
            found.append(f"forbidden product Node runtime: {relative}")
            continue
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
        if _is_node_invocation_file(relative) and _contains_node_launcher(relative, data):
            found.append(f"forbidden product Node invocation in {relative}")
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
