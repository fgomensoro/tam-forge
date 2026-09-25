from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path

RECEIVE = Path(__file__).resolve().parents[1] / "host" / "deploy-receive.sh"


def _tar_with(name: str, body: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _run(tmp_path: Path, release_id: str, payload: bytes) -> subprocess.CompletedProcess[bytes]:
    stub = tmp_path / "release.sh"
    stub.write_text('#!/bin/sh\necho "$1" > "$1/ran"\n')
    stub.chmod(0o755)
    env = {
        **os.environ,
        "TAMFORGE_ROOT": str(tmp_path),
        "TAMFORGE_RELEASE_SH": str(stub),
        "SSH_ORIGINAL_COMMAND": release_id,
    }
    return subprocess.run(
        ["bash", str(RECEIVE)], input=payload, env=env, capture_output=True, check=False
    )


def test_a_release_is_unpacked_and_handed_to_its_release_script(tmp_path: Path) -> None:
    result = _run(tmp_path, "20260925T010203Z-abcdef0", _tar_with("README.md", b"hi"))

    assert result.returncode == 0, result.stderr.decode()
    release = tmp_path / "releases" / "20260925T010203Z-abcdef0"
    assert (release / "README.md").read_text() == "hi"
    assert (release / "ran").read_text().strip() == str(release)


def test_a_malformed_release_id_is_refused_before_touching_disk(tmp_path: Path) -> None:
    result = _run(tmp_path, "../../etc", _tar_with("x", b""))

    assert result.returncode == 2
    assert b"release id" in result.stderr
    assert not (tmp_path / "releases").exists()


def test_a_release_id_is_installed_once(tmp_path: Path) -> None:
    (tmp_path / "releases" / "20260925T010203Z-abcdef0").mkdir(parents=True)

    result = _run(tmp_path, "20260925T010203Z-abcdef0", _tar_with("x", b""))

    assert result.returncode == 2
    assert b"already installed" in result.stderr
