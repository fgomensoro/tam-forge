"""The Gastos archive: read-only on the host, encrypted here, and never partial."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from infra.gastos.archive import (
    EXPECTED_HOSTNAME,
    PAYLOADS,
    ArchiveError,
    Manifest,
    assert_read_only,
    create,
    require_gastos_host,
    restore_plaintexts,
    verify,
)
from infra.gastos.inventory import MUTATING_TOKENS

NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)


class FakeHost:
    """Answers every payload command with deterministic bytes and records what ran."""

    def __init__(self, hostname: str = EXPECTED_HOSTNAME) -> None:
        self.hostname = hostname
        self.commands: list[str] = []

    def __call__(self, host: str, command: str) -> bytes:
        self.commands.append(command)
        if command == "hostname":
            return f"{self.hostname}\n".encode()
        if ".env" in command:
            return b"POSTGRES_PASSWORD=hunter2\nN8N_ENCRYPTION_KEY=abc123\n"
        return f"payload for {command}".encode()


def make_archive(tmp_path: Path, **overrides: object) -> tuple[Path, Path, Manifest]:
    archive = tmp_path / "archive"
    key = tmp_path / "keys" / "gastos.key"
    runner = overrides.pop("runner", FakeHost())
    manifest = create(archive, key_path=key, runner=runner, now=lambda: NOW, **overrides)  # type: ignore[arg-type]
    return archive, key, manifest


# --- read-only on the host ----------------------------------------------------------------


def test_every_payload_command_is_an_allowlisted_read() -> None:
    assert_read_only(PAYLOADS)
    for command in PAYLOADS.values():
        assert not any(token in f" {command} " for token in MUTATING_TOKENS)


@pytest.mark.parametrize(
    "command",
    [
        "docker exec n8n-postgres-1 sh -c 'psql -c \"drop database n8n\"'",
        "docker compose down",
        "tar -C /root/n8n -cf - . > /tmp/out.tar",
        "docker exec n8n-n8n-1 rm -rf /home/node/.n8n",
        "cat /etc/shadow",
    ],
)
def test_a_command_outside_the_allowlist_is_refused(command: str) -> None:
    with pytest.raises(ArchiveError):
        assert_read_only({"bad": command})


def test_no_payload_writes_to_the_host_during_a_run(tmp_path: Path) -> None:
    host = FakeHost()
    make_archive(tmp_path, runner=host)
    assert host.commands[0] == "hostname"
    assert set(host.commands[1:]) == set(PAYLOADS.values())


# --- the wrong host is refused before anything runs ----------------------------------------


def test_lamas_is_refused_by_name() -> None:
    with pytest.raises(ArchiveError, match="Lamas, not Gastos"):
        require_gastos_host("lamas-prod")


def test_an_unexpected_hostname_is_refused(tmp_path: Path) -> None:
    host = FakeHost(hostname="some-other-box")
    with pytest.raises(ArchiveError, match="expected host"):
        make_archive(tmp_path, runner=host)
    # Nothing beyond the hostname probe ran, and nothing was written.
    assert host.commands == ["hostname"]
    assert not (tmp_path / "archive").exists()
    assert not (tmp_path / "keys" / "gastos.key").exists()


# --- encrypted here, key outside the manifest --------------------------------------------


def test_every_payload_is_encrypted_and_covered_by_recorded_hashes(tmp_path: Path) -> None:
    archive, key, manifest = make_archive(tmp_path)

    assert {p.name for p in manifest.payloads} == set(PAYLOADS)
    for record in manifest.payloads:
        ciphertext = (archive / "payloads" / f"{record.name}.enc").read_bytes()
        assert sha256(ciphertext).hexdigest() == record.ciphertext_sha256
        assert b"payload for" not in ciphertext
        assert record.plaintext_bytes > 0 and record.ciphertext_bytes > record.plaintext_bytes


def test_secrets_are_in_the_archive_and_not_in_the_manifest(tmp_path: Path) -> None:
    archive, key, _ = make_archive(tmp_path)
    manifest_text = (archive / "manifest.json").read_text()

    assert "hunter2" not in manifest_text
    assert "abc123" not in manifest_text
    assert key.read_bytes().hex() not in manifest_text
    restored = restore_plaintexts(archive, key_path=key, into=tmp_path / "restore")
    env = (tmp_path / "restore" / "config" / "n8n" / ".env").read_text()
    assert "POSTGRES_PASSWORD=hunter2" in env
    assert len(restored) == len(PAYLOADS)


def test_the_key_is_never_overwritten_and_the_archive_directory_must_be_empty(
    tmp_path: Path,
) -> None:
    archive, key, _ = make_archive(tmp_path)
    with pytest.raises(ArchiveError, match="existing key"):
        create(tmp_path / "other", key_path=key, runner=FakeHost(), now=lambda: NOW)
    with pytest.raises(ArchiveError, match="non-empty"):
        create(archive, key_path=tmp_path / "fresh.key", runner=FakeHost(), now=lambda: NOW)


def test_the_key_file_is_owner_only(tmp_path: Path) -> None:
    _, key, _ = make_archive(tmp_path)
    assert key.stat().st_mode & 0o777 == 0o600


# --- verification refuses anything less than the whole archive -----------------------------


def test_a_complete_archive_verifies_with_and_without_the_key(tmp_path: Path) -> None:
    archive, key, manifest = make_archive(tmp_path)
    assert verify(archive) == manifest
    assert verify(archive, key_path=key) == manifest


def test_a_missing_manifest_is_not_an_archive(tmp_path: Path) -> None:
    archive, _, _ = make_archive(tmp_path)
    (archive / "manifest.json").unlink()
    with pytest.raises(ArchiveError, match="not an archive"):
        verify(archive)


def test_a_missing_payload_makes_the_archive_partial(tmp_path: Path) -> None:
    archive, key, _ = make_archive(tmp_path)
    (archive / "payloads" / "postgres" / "n8n.dump.enc").unlink()
    with pytest.raises(ArchiveError, match="partial archive"):
        verify(archive, key_path=key)


def test_a_manifest_that_forgets_a_payload_is_partial_too(tmp_path: Path) -> None:
    archive, _, manifest = make_archive(tmp_path)
    trimmed = Manifest(
        host=manifest.host,
        hostname=manifest.hostname,
        captured_at=manifest.captured_at,
        cipher=manifest.cipher,
        payloads=manifest.payloads[1:],
    )
    (archive / "manifest.json").write_text(trimmed.to_json())
    with pytest.raises(ArchiveError, match="manifest lacks"):
        verify(archive)


def test_a_changed_byte_fails_verification(tmp_path: Path) -> None:
    archive, key, _ = make_archive(tmp_path)
    path = archive / "payloads" / "volumes" / "n8n_n8n_data.tar.enc"
    data = bytearray(path.read_bytes())
    data[5] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ArchiveError, match="does not match"):
        verify(archive)


def test_a_ciphertext_moved_under_another_name_does_not_decrypt(tmp_path: Path) -> None:
    archive, key, manifest = make_archive(tmp_path)
    first_name, second_name = "config/n8n/Caddyfile", "config/n8n/docker-compose.yml"
    first = archive / "payloads" / f"{first_name}.enc"
    second = archive / "payloads" / f"{second_name}.enc"
    first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
    first.write_bytes(second_bytes)
    second.write_bytes(first_bytes)

    # Re-record the swapped hashes and nonces so only the associated data can catch it.
    by_name = {p.name: p for p in manifest.payloads}
    swapped = tuple(
        replace(
            record,
            ciphertext_sha256=by_name[other].ciphertext_sha256,
            ciphertext_bytes=by_name[other].ciphertext_bytes,
            nonce_hex=by_name[other].nonce_hex,
        )
        if (other := {first_name: second_name, second_name: first_name}.get(record.name))
        else record
        for record in manifest.payloads
    )
    (archive / "manifest.json").write_text(replace(manifest, payloads=swapped).to_json())

    with pytest.raises(ArchiveError, match="decryption failed"):
        verify(archive, key_path=key)


def test_an_empty_payload_is_refused(tmp_path: Path) -> None:
    class EmptyHost(FakeHost):
        def __call__(self, host: str, command: str) -> bytes:
            if command.startswith("cat /root/n8n/Caddyfile"):
                return b""
            return super().__call__(host, command)

    with pytest.raises(ArchiveError, match="came back empty"):
        make_archive(tmp_path, runner=EmptyHost())


def test_the_manifest_round_trips_and_names_the_capture_time(tmp_path: Path) -> None:
    archive, _, manifest = make_archive(tmp_path)
    parsed = Manifest.from_json((archive / "manifest.json").read_text())
    assert parsed == manifest
    assert manifest.captured_at == "20260911T010000Z"
    assert manifest.hostname == EXPECTED_HOSTNAME
