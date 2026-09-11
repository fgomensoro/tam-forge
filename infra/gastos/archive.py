"""Pull an encrypted, verifiable archive of the Gastos stack off hetzner-server-2.

Everything the host would need to come back somewhere else is pulled over one SSH session
as a set of named payloads: a custom-format `pg_dump` per database, the role definitions,
the n8n, NocoDB and Caddy data directories as tar streams, and the compose files, Caddyfile
and environment files that wire them together. Nothing on the host is written, stopped or
restarted: every command is a read (`pg_dump`, `tar -c`, `cat`) screened against the same
mutating-token list the inventory uses.

Each payload is encrypted on this machine with AES-256-GCM under a key generated for the
archive and written only to a path outside the repository. The manifest that sits next to
the ciphertext, and the copy committed under `docs/project/`, holds names, sizes, hashes
and the exact command that produced each payload, and nothing else. Environment files and
role definitions contain live secrets, which is why they are in the archive and not in the
manifest.

Verification is what makes this an archive rather than a directory: every ciphertext must
be present and match its recorded hash, and with the key every plaintext must match too.
A missing payload, a missing manifest, or a changed byte is a refusal, not a warning.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from infra.gastos.inventory import _CONTROL, HOST, MUTATING_TOKENS

# The only host this module will ever archive. Lamas lives on a different server, and a
# resolved hostname that is not this one is refused before any command runs.
EXPECTED_HOSTNAME: Final = "n8n-prod-gastos"
FORBIDDEN_HOSTNAMES: Final[frozenset[str]] = frozenset({"lamas-prod"})

# Every payload command starts with one of these. Anything else is refused.
READ_ONLY_PREFIXES: Final[tuple[str, ...]] = (
    "docker exec n8n-postgres-1 sh -c 'pg_dump ",
    "docker exec n8n-postgres-1 sh -c 'pg_dumpall ",
    "docker exec n8n-n8n-1 tar -C ",
    "docker exec n8n-nocodb-1 tar -C ",
    "docker exec n8n-caddy-1 tar -C ",
    "cat /root/n8n/",
    "cat /root/gapfiller-bridge/",
    "tar -C /root/gapfiller-bridge -cf - ",
    "docker inspect ",
)

# Name -> the exact command whose stdout becomes that payload. Databases are the three the
# inventory listed; the role dump carries password hashes and is therefore never rendered
# into the manifest.
PAYLOADS: Final[dict[str, str]] = {
    "postgres/n8n.dump": "docker exec n8n-postgres-1 sh -c 'pg_dump -U \"$POSTGRES_USER\" -Fc n8n'",
    "postgres/leadgen.dump": (
        "docker exec n8n-postgres-1 sh -c 'pg_dump -U \"$POSTGRES_USER\" -Fc leadgen'"
    ),
    "postgres/postgres.dump": (
        "docker exec n8n-postgres-1 sh -c 'pg_dump -U \"$POSTGRES_USER\" -Fc postgres'"
    ),
    "postgres/globals.sql": (
        "docker exec n8n-postgres-1 sh -c 'pg_dumpall -U \"$POSTGRES_USER\" --globals-only'"
    ),
    "volumes/n8n_n8n_data.tar": "docker exec n8n-n8n-1 tar -C /home/node/.n8n -cf - .",
    "volumes/n8n_nocodb_data.tar": "docker exec n8n-nocodb-1 tar -C /usr/app/data -cf - .",
    "volumes/n8n_caddy_data.tar": "docker exec n8n-caddy-1 tar -C /data -cf - .",
    "volumes/n8n_caddy_config.tar": "docker exec n8n-caddy-1 tar -C /config -cf - .",
    "config/n8n/docker-compose.yml": "cat /root/n8n/docker-compose.yml",
    "config/n8n/Caddyfile": "cat /root/n8n/Caddyfile",
    "config/n8n/.env": "cat /root/n8n/.env",
    "config/gapfiller-bridge/source.tar": "tar -C /root/gapfiller-bridge -cf - .",
    "config/containers.json": (
        "docker inspect n8n-n8n-1 n8n-nocodb-1 n8n-caddy-1 n8n-postgres-1 gapfiller-bridge"
    ),
}

MANIFEST_VERSION: Final = 1


class ArchiveError(ValueError):
    """An archive that is not one: missing, partial, altered, or aimed at the wrong host."""


def assert_read_only(payloads: dict[str, str]) -> None:
    """Refuse a payload list that could write to the host. Called before anything runs."""
    for name, command in payloads.items():
        if not command.startswith(READ_ONLY_PREFIXES):
            raise ArchiveError(f"{name}: command is not an allowlisted read: {command!r}")
        padded = f" {command} "
        for token in MUTATING_TOKENS:
            if token in padded:
                raise ArchiveError(f"{name} is not read-only: contains {token.strip()!r}")


def require_gastos_host(hostname: str) -> None:
    resolved = hostname.strip()
    if resolved in FORBIDDEN_HOSTNAMES:
        raise ArchiveError(f"refusing to archive {resolved}: that is Lamas, not Gastos")
    if resolved != EXPECTED_HOSTNAME:
        raise ArchiveError(f"expected host {EXPECTED_HOSTNAME}, resolved {resolved!r}")


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    name: str
    command: str
    plaintext_bytes: int
    plaintext_sha256: str
    ciphertext_bytes: int
    ciphertext_sha256: str
    nonce_hex: str


@dataclass(frozen=True, slots=True)
class Manifest:
    host: str
    hostname: str
    captured_at: str
    cipher: str
    payloads: tuple[PayloadRecord, ...]

    def to_json(self) -> str:
        body = {
            "manifest_version": MANIFEST_VERSION,
            "host": self.host,
            "hostname": self.hostname,
            "captured_at": self.captured_at,
            "cipher": self.cipher,
            "payloads": [
                {
                    "name": p.name,
                    "command": p.command,
                    "plaintext_bytes": p.plaintext_bytes,
                    "plaintext_sha256": p.plaintext_sha256,
                    "ciphertext_bytes": p.ciphertext_bytes,
                    "ciphertext_sha256": p.ciphertext_sha256,
                    "nonce_hex": p.nonce_hex,
                }
                for p in self.payloads
            ],
        }
        return json.dumps(body, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        body = json.loads(text)
        if body.get("manifest_version") != MANIFEST_VERSION:
            raise ArchiveError("manifest version is not one this tool understands")
        return cls(
            host=body["host"],
            hostname=body["hostname"],
            captured_at=body["captured_at"],
            cipher=body["cipher"],
            payloads=tuple(PayloadRecord(**p) for p in body["payloads"]),
        )


def run_remote_bytes(host: str, command: str) -> bytes:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", *_CONTROL, host, command],
        capture_output=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise ArchiveError(
            f"{command!r} failed on {host}: exit {completed.returncode}"
            f" {completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    return completed.stdout


def _encrypt(key: bytes, name: str, plaintext: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    # The payload name is bound as associated data, so a ciphertext moved under another
    # name fails to decrypt instead of quietly restoring the wrong thing.
    return nonce, AESGCM(key).encrypt(nonce, plaintext, name.encode("utf-8"))


def _decrypt(key: bytes, name: str, nonce: bytes, ciphertext: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, name.encode("utf-8"))


def create(
    destination: Path,
    *,
    key_path: Path,
    host: str = HOST,
    payloads: dict[str, str] = PAYLOADS,
    runner: Callable[[str, str], bytes] = run_remote_bytes,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Manifest:
    """Pull every payload, encrypt it under a fresh key, and write manifest and ciphertexts."""
    assert_read_only(payloads)
    hostname = runner(host, "hostname").decode("utf-8", "replace")
    require_gastos_host(hostname)
    if key_path.exists():
        raise ArchiveError(f"refusing to overwrite an existing key at {key_path}")
    if destination.exists() and any(destination.iterdir()):
        raise ArchiveError(f"refusing to write into a non-empty archive directory {destination}")

    key = AESGCM.generate_key(bit_length=256)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.touch(mode=0o600)
    key_path.write_bytes(key)

    records: list[PayloadRecord] = []
    for name, command in payloads.items():
        plaintext = runner(host, command)
        if not plaintext:
            raise ArchiveError(f"{name} came back empty; an empty payload is not an archive")
        nonce, ciphertext = _encrypt(key, name, plaintext)
        target = destination / "payloads" / f"{name}.enc"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(ciphertext)
        records.append(
            PayloadRecord(
                name=name,
                command=command,
                plaintext_bytes=len(plaintext),
                plaintext_sha256=sha256(plaintext).hexdigest(),
                ciphertext_bytes=len(ciphertext),
                ciphertext_sha256=sha256(ciphertext).hexdigest(),
                nonce_hex=nonce.hex(),
            )
        )

    manifest = Manifest(
        host=host,
        hostname=hostname.strip(),
        captured_at=now().strftime("%Y%m%dT%H%M%SZ"),
        cipher="AES-256-GCM, payload name as associated data",
        payloads=tuple(records),
    )
    (destination / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def verify(archive: Path, *, key_path: Path | None = None) -> Manifest:
    """Refuse anything less than a complete, unaltered archive; with the key, prove plaintexts."""
    manifest_path = archive / "manifest.json"
    if not manifest_path.exists():
        raise ArchiveError("no manifest.json: this directory is not an archive")
    manifest = Manifest.from_json(manifest_path.read_text(encoding="utf-8"))
    expected = set(PAYLOADS)
    recorded = {p.name for p in manifest.payloads}
    if recorded != expected:
        missing = sorted(expected - recorded)
        raise ArchiveError(f"partial archive: manifest lacks {missing}")

    key = key_path.read_bytes() if key_path is not None else None
    for record in manifest.payloads:
        path = archive / "payloads" / f"{record.name}.enc"
        if not path.exists():
            raise ArchiveError(f"partial archive: {record.name} is missing on disk")
        ciphertext = path.read_bytes()
        if sha256(ciphertext).hexdigest() != record.ciphertext_sha256:
            raise ArchiveError(f"{record.name}: ciphertext does not match the manifest")
        if key is not None:
            try:
                plaintext = _decrypt(key, record.name, bytes.fromhex(record.nonce_hex), ciphertext)
            except Exception as error:
                raise ArchiveError(f"{record.name}: decryption failed") from error
            if sha256(plaintext).hexdigest() != record.plaintext_sha256:
                raise ArchiveError(f"{record.name}: plaintext does not match the manifest")
    return manifest


def restore_plaintexts(archive: Path, *, key_path: Path, into: Path) -> tuple[Path, ...]:
    """Decrypt every payload into `into`, after a full verification. Never touches a host."""
    manifest = verify(archive, key_path=key_path)
    key = key_path.read_bytes()
    written: list[Path] = []
    for record in manifest.payloads:
        ciphertext = (archive / "payloads" / f"{record.name}.enc").read_bytes()
        plaintext = _decrypt(key, record.name, bytes.fromhex(record.nonce_hex), ciphertext)
        target = into / record.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(plaintext)
        written.append(target)
    return tuple(written)


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Encrypted, verifiable Gastos archive.")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create", help="pull and encrypt a new archive")
    make.add_argument("destination", type=Path)
    make.add_argument("--key-out", type=Path, required=True)
    check = sub.add_parser("verify", help="verify an archive; with --key, prove the plaintexts")
    check.add_argument("archive", type=Path)
    check.add_argument("--key", type=Path)
    rest = sub.add_parser("restore", help="decrypt every payload into a directory")
    rest.add_argument("archive", type=Path)
    rest.add_argument("--key", type=Path, required=True)
    rest.add_argument("--into", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "create":
        manifest = create(args.destination, key_path=args.key_out)
        print(f"archived {len(manifest.payloads)} payloads at {manifest.captured_at}")
    elif args.command == "verify":
        manifest = verify(args.archive, key_path=args.key)
        depth = "ciphertext and plaintext" if args.key else "ciphertext"
        print(f"verified {len(manifest.payloads)} payloads ({depth})")
    else:
        written = restore_plaintexts(args.archive, key_path=args.key, into=args.into)
        print(f"restored {len(written)} payloads into {args.into}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
