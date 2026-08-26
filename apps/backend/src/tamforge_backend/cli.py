"""Small administrative CLI with safe dry-run defaults."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .database import validate_test_database_url
from .evidence.config_loader import ConfigError, load_config_bundle
from .evidence.seed import SeedConfigError, SeedResult, seed_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tamforge")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed-config")
    seed.add_argument("--config-dir", type=Path, required=True)
    mode = seed.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def _async_url(raw_url: str) -> str:
    url = make_url(raw_url)
    if url.drivername not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise SeedConfigError("seed apply requires PostgreSQL")
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


async def _apply(config_dir: Path, raw_url: str) -> SeedResult:
    bundle = load_config_bundle(config_dir)
    engine = create_async_engine(_async_url(raw_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            return await seed_config(bundle, owner_id=None, session=session, apply=True)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "seed-config" and not args.apply:
            bundle = load_config_bundle(args.config_dir)
            result = asyncio.run(seed_config(bundle, owner_id=None, session=None, apply=False))
        elif args.command == "seed-config":
            test_url = os.getenv("TEST_DATABASE_URL")
            runtime_url = os.getenv("TAMFORGE_DATABASE_URL")
            if test_url:
                raw_url = validate_test_database_url(test_url)
            elif runtime_url:
                raw_url = runtime_url
            else:
                raise SeedConfigError(
                    "seed apply requires explicit TEST_DATABASE_URL or TAMFORGE_DATABASE_URL"
                )
            result = asyncio.run(_apply(args.config_dir, raw_url))
        else:  # pragma: no cover - argparse rejects this path
            raise SeedConfigError("unsupported command")
    except (ConfigError, SeedConfigError, ValueError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
