"""Run native repository bootstrap safety checks without a Node runtime."""

from __future__ import annotations

from pathlib import Path

from scripts.ci.verify_compose import ComposeVerification, verify_compose_text

ROOT = Path(__file__).parents[2]


def verify_bootstrap(root: Path = ROOT) -> ComposeVerification:
    return verify_compose_text((root / "compose.dev.yml").read_text(encoding="utf-8"))


def main() -> int:
    result = verify_bootstrap()
    print(f"Bootstrap safety verified: ports={','.join(result.published_ports)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
