"""Take a real encrypted backup of a local database and prove it restores, with numbers.

This is the clean-environment drill the policy asks for, run against a local PostgreSQL
container rather than the host: dump through `docker exec` as the container's own role,
encrypt here under a fresh key written outside the repository, verify, then restore into
a throwaway `postgres:16` container with no network, count what came back, and remove it.
The evidence that is committed holds the manifest hash, the numbers and the verdict, and
never a row, a value or the key.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

from .drill import Environment, Thresholds
from .encrypted import backup, restore_drill

DRILL_PREFIX: Final = "backup-drill-"


class EvidenceError(ValueError):
    """The drill could not produce evidence it can stand behind."""


def _docker(
    *args: str, check: bool = True, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["docker", *args], capture_output=True, timeout=900, check=False, input=input_bytes
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace")[:300]
        raise EvidenceError(f"docker {' '.join(args[:3])} failed: {detail}")
    return completed


@dataclass(frozen=True, slots=True)
class DrillEvidenceRecord:
    drilled_at: str
    source_container: str
    manifest_sha256: str
    captured_at: str
    verified_artifacts: int
    rpo_minutes: int
    rto_minutes: int
    restored_tables: int
    thresholds: Thresholds
    met: bool
    encrypted_with: str
    drill_container: str

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "drilled_at": self.drilled_at,
                    "environment": "restore-drill",
                    "is_production": False,
                    "network": "none",
                    "source_container": self.source_container,
                    "manifest_sha256": self.manifest_sha256,
                    "captured_at": self.captured_at,
                    "encrypted_with": self.encrypted_with,
                    "verified_artifacts": self.verified_artifacts,
                    "restored_tables": self.restored_tables,
                    "rpo_minutes": self.rpo_minutes,
                    "rto_minutes": self.rto_minutes,
                    "thresholds": {
                        "max_rpo_minutes": self.thresholds.max_rpo_minutes,
                        "max_rto_minutes": self.thresholds.max_rto_minutes,
                    },
                    "met": self.met,
                    "drill_container": self.drill_container,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


def run(
    *, source_container: str, backups_root: Path, key_dir: Path, thresholds: Thresholds
) -> DrillEvidenceRecord:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    key = secrets.token_bytes(32)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / f"backup-{stamp}.key"
    key_path.touch(mode=0o600)
    key_path.write_bytes(key)

    def dump() -> bytes:
        return _docker(
            "exec", source_container, "sh", "-c", 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"'
        ).stdout

    versions = _docker("exec", source_container, "pg_dump", "--version").stdout.decode().strip()
    # The same image as the source, so extensions such as pgvector restore too.
    image = (
        _docker("inspect", source_container, "--format", "{{.Config.Image}}")
        .stdout.decode()
        .strip()
    )
    destination = backups_root / stamp
    manifest = backup(
        destination,
        key=key,
        dump=dump,
        config={"POSTGRES_USER": "present", "POSTGRES_DB": "present"},
        tool_versions={"pg_dump": versions, "cipher": "AES-256-GCM"},
        schema_head="local-test-database",
    )
    manifest_sha = sha256((destination / "manifest.json").read_bytes()).hexdigest()

    container = f"{DRILL_PREFIX}pg-{stamp}"
    restored_tables = 0

    def restore(dump_bytes: bytes) -> None:
        nonlocal restored_tables
        with tempfile.TemporaryDirectory(prefix="backup-drill-") as tmp:
            path = Path(tmp) / "tamforge.dump"
            path.write_bytes(dump_bytes)
            _docker(
                "run",
                "-d",
                "--network",
                "none",
                "--name",
                container,
                "-e",
                f"POSTGRES_PASSWORD={secrets.token_hex(8)}",
                "-v",
                f"{path}:/restore/tamforge.dump:ro",
                image,
            )
            for _ in range(60):
                if (
                    _docker(
                        "exec", container, "pg_isready", "-U", "postgres", check=False
                    ).returncode
                    == 0
                ):
                    break
                import time

                time.sleep(1)
            _docker("exec", container, "createdb", "-U", "postgres", "restored")
            _docker(
                "exec",
                container,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "restored",
                "--no-owner",
                "--no-privileges",
                "/restore/tamforge.dump",
            )
            out = (
                _docker(
                    "exec",
                    container,
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "restored",
                    "-tAc",
                    "select count(*) from information_schema.tables where table_schema='public'",
                )
                .stdout.decode()
                .strip()
            )
            restored_tables = int(out)

    try:
        result = restore_drill(
            destination,
            key=key,
            environment=Environment("restore-drill", is_production=False),
            restore=restore,
            thresholds=thresholds,
        )
    finally:
        _docker("rm", "-f", container, check=False)
    if restored_tables < 1:
        raise EvidenceError("the restore produced no tables")
    return DrillEvidenceRecord(
        drilled_at=stamp,
        source_container=source_container,
        manifest_sha256=manifest_sha,
        captured_at=manifest.captured_at.isoformat(),
        verified_artifacts=result.verified,
        rpo_minutes=result.rpo_minutes,
        rto_minutes=result.rto_minutes,
        restored_tables=restored_tables,
        thresholds=thresholds,
        met=result.met,
        encrypted_with=manifest.cipher,
        drill_container=container,
    )


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Encrypted backup + clean restore drill with measured RPO/RTO."
    )
    parser.add_argument("--source-container", required=True)
    parser.add_argument("--backups-root", type=Path, required=True)
    parser.add_argument("--key-dir", type=Path, required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    parser.add_argument("--max-rpo-minutes", type=int, default=1500)
    parser.add_argument("--max-rto-minutes", type=int, default=60)
    args = parser.parse_args(argv)
    record = run(
        source_container=args.source_container,
        backups_root=args.backups_root,
        key_dir=args.key_dir,
        thresholds=Thresholds(
            max_rpo_minutes=args.max_rpo_minutes, max_rto_minutes=args.max_rto_minutes
        ),
    )
    args.evidence_out.write_text(record.to_json(), encoding="utf-8")
    numbers = f"rpo {record.rpo_minutes} min, rto {record.rto_minutes} min"
    print(f"met: {record.met} ({numbers}, {record.restored_tables} tables)")
    return 0 if record.met else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
