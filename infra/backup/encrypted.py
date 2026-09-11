"""Daily encrypted backup: dump, encrypt here, verify, publish the manifest last.

A backup is a set of payloads (the PostgreSQL custom-format dump and a nonsecret
configuration inventory) each encrypted with AES-256-GCM under a key that never enters the
manifest, plus a manifest with hashes, sizes, tool versions and the capture moment. The
manifest is written last and atomically, so a backup directory either has a manifest that
describes complete, verified ciphertext or has no manifest at all; there is no partial
backup that looks finished.

Nothing secret is human-readable here. The configuration inventory records which keys
exist, never their values, and the manifest text is scanned for anything shaped like a
credential before it is published.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .drill import (
    BackupArtifact,
    DrillResult,
    Environment,
    Thresholds,
    require_clean_environment,
    run_drill,
)

MANIFEST_VERSION: Final = 1
CIPHER: Final = "AES-256-GCM"

_SECRET_SHAPES: Final = re.compile(
    r"(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"
    r"|BEGIN [A-Z ]*PRIVATE KEY"
    r"|sk-[A-Za-z0-9-]{16,}",
    re.IGNORECASE,
)


class BackupError(ValueError):
    """A backup that is incomplete, altered, or would publish a secret."""


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    name: str
    plaintext_bytes: int
    plaintext_sha256: str
    ciphertext_bytes: int
    ciphertext_sha256: str
    nonce_hex: str


@dataclass(frozen=True, slots=True)
class BackupManifest:
    captured_at: datetime
    cipher: str
    tool_versions: dict[str, str]
    schema_head: str
    config_keys: tuple[str, ...]
    payloads: tuple[PayloadRecord, ...]

    def to_json(self) -> str:
        body = {
            "manifest_version": MANIFEST_VERSION,
            "captured_at": self.captured_at.isoformat(),
            "cipher": self.cipher,
            "tool_versions": self.tool_versions,
            "schema_head": self.schema_head,
            "config_keys": list(self.config_keys),
            "payloads": [asdict(p) for p in self.payloads],
        }
        return json.dumps(body, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> BackupManifest:
        body = json.loads(text)
        if body.get("manifest_version") != MANIFEST_VERSION:
            raise BackupError("manifest version is not one this tool understands")
        return cls(
            captured_at=datetime.fromisoformat(body["captured_at"]),
            cipher=body["cipher"],
            tool_versions=dict(body["tool_versions"]),
            schema_head=body["schema_head"],
            config_keys=tuple(body["config_keys"]),
            payloads=tuple(PayloadRecord(**p) for p in body["payloads"]),
        )


def assert_no_secret(text: str) -> None:
    match = _SECRET_SHAPES.search(text)
    if match:
        raise BackupError("the manifest would publish something shaped like a credential")


def _encrypt(key: bytes, name: str, plaintext: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, name.encode("utf-8"))


def _decrypt(key: bytes, name: str, nonce: bytes, ciphertext: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, name.encode("utf-8"))


def backup(
    destination: Path,
    *,
    key: bytes,
    dump: Callable[[], bytes],
    config: Mapping[str, str],
    tool_versions: Mapping[str, str],
    schema_head: str,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BackupManifest:
    """Dump, encrypt, write ciphertext, then publish the manifest last and atomically."""
    if len(key) != 32:
        raise BackupError("the backup key is 32 bytes")
    if destination.exists() and any(destination.iterdir()):
        raise BackupError("a backup directory is written once; versioning means a new directory")
    captured_at = now()
    if captured_at.tzinfo is None:
        raise BackupError("the capture moment is timezone-aware")
    payloads: dict[str, bytes] = {
        "db/tamforge.dump": dump(),
        # Names only. The values are what a restore needs and what a manifest must not hold.
        "config/inventory.json": json.dumps({"keys": sorted(config)}, sort_keys=True).encode(
            "utf-8"
        ),
    }
    if not payloads["db/tamforge.dump"]:
        raise BackupError("an empty dump is not a backup")
    records: list[PayloadRecord] = []
    for name, plaintext in payloads.items():
        nonce, ciphertext = _encrypt(key, name, plaintext)
        target = destination / "payloads" / f"{name}.enc"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".enc.tmp")
        tmp.write_bytes(ciphertext)
        os.replace(tmp, target)
        records.append(
            PayloadRecord(
                name=name,
                plaintext_bytes=len(plaintext),
                plaintext_sha256=sha256(plaintext).hexdigest(),
                ciphertext_bytes=len(ciphertext),
                ciphertext_sha256=sha256(ciphertext).hexdigest(),
                nonce_hex=nonce.hex(),
            )
        )
    manifest = BackupManifest(
        captured_at=captured_at,
        cipher=CIPHER,
        tool_versions=dict(tool_versions),
        schema_head=schema_head,
        config_keys=tuple(sorted(config)),
        payloads=tuple(records),
    )
    text = manifest.to_json()
    assert_no_secret(text)
    tmp_manifest = destination / "manifest.json.tmp"
    tmp_manifest.write_text(text, encoding="utf-8")
    os.replace(tmp_manifest, destination / "manifest.json")
    return manifest


def verify(destination: Path, *, key: bytes | None = None) -> BackupManifest:
    """Every ciphertext present and matching; with the key, every plaintext too."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.exists():
        raise BackupError("no manifest: this directory is not a finished backup")
    manifest = BackupManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    for record in manifest.payloads:
        path = destination / "payloads" / f"{record.name}.enc"
        if not path.exists():
            raise BackupError(f"partial backup: {record.name} is missing")
        ciphertext = path.read_bytes()
        if sha256(ciphertext).hexdigest() != record.ciphertext_sha256:
            raise BackupError(f"{record.name}: ciphertext does not match the manifest")
        if key is not None:
            try:
                plaintext = _decrypt(key, record.name, bytes.fromhex(record.nonce_hex), ciphertext)
            except Exception as error:
                raise BackupError(f"{record.name}: decryption failed") from error
            if sha256(plaintext).hexdigest() != record.plaintext_sha256:
                raise BackupError(f"{record.name}: plaintext does not match the manifest")
    return manifest


def decrypt_dump(destination: Path, *, key: bytes) -> bytes:
    manifest = verify(destination, key=key)
    record = next(p for p in manifest.payloads if p.name == "db/tamforge.dump")
    ciphertext = (destination / "payloads" / f"{record.name}.enc").read_bytes()
    return _decrypt(key, record.name, bytes.fromhex(record.nonce_hex), ciphertext)


def restore_drill(
    destination: Path,
    *,
    key: bytes,
    environment: Environment,
    restore: Callable[[bytes], None],
    thresholds: Thresholds,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DrillResult:
    """Decrypt, restore through the injected step, and measure RPO and RTO for the drill."""
    require_clean_environment(environment)
    manifest = verify(destination, key=key)
    artifacts = tuple(
        BackupArtifact(path=p.name, sha256=p.plaintext_sha256, captured_at=manifest.captured_at)
        for p in manifest.payloads
    )
    started = clock()
    dump = decrypt_dump(destination, key=key)
    restore(dump)
    finished = clock()
    digests = {
        p.name: sha256(
            _decrypt(
                key,
                p.name,
                bytes.fromhex(p.nonce_hex),
                (destination / "payloads" / f"{p.name}.enc").read_bytes(),
            )
        ).hexdigest()
        for p in manifest.payloads
    }
    return run_drill(
        artifacts,
        environment=environment,
        digests=digests,
        thresholds=thresholds,
        started_at=started,
        finished_at=finished,
        now=finished if finished >= started else started + timedelta(0),
    )


__all__ = [
    "CIPHER",
    "BackupError",
    "BackupManifest",
    "PayloadRecord",
    "assert_no_secret",
    "backup",
    "decrypt_dump",
    "restore_drill",
    "verify",
]
