from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/dev/rotate_claude_token.sh")
TOKEN = "sk-ant-oat01-fixture"


@pytest.fixture
def fake_ssh(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "ssh-argv"
    stdin_log = tmp_path / "ssh-stdin"
    ssh = bin_dir / "ssh"
    ssh.write_text(
        "#!/bin/bash\nset -eu\n"
        'printf "%s\\n" "$@" > "$FAKE_SSH_ARGV"\n'
        'cat > "$FAKE_SSH_STDIN"\n'
        'printf "%s\\n" "${FAKE_SSH_RESULT:-ok none}"\n',
        encoding="utf-8",
    )
    ssh.chmod(0o700)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_SSH_ARGV": str(argv_log),
        "FAKE_SSH_STDIN": str(stdin_log),
        "TAMFORGE_SKIP_SETUP_TOKEN": "1",
    }
    return env, argv_log, stdin_log


def run(env: dict[str, str], token: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], input=f"{token}\n", env=env, capture_output=True, text=True
    )


def test_the_token_travels_only_on_ssh_stdin(fake_ssh: tuple[dict[str, str], Path, Path]) -> None:
    env, argv_log, stdin_log = fake_ssh
    result = run(env, TOKEN)
    assert result.returncode == 0, result.stderr
    assert stdin_log.read_text() == f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n"
    assert TOKEN not in argv_log.read_text()
    assert TOKEN not in result.stdout + result.stderr
    assert "ready" in result.stdout


def test_the_host_side_installs_the_file_atomically_and_restarts_the_worker(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, argv_log, _ = fake_ssh
    run(env, TOKEN)
    remote = argv_log.read_text()
    assert remote.splitlines()[0] == "hetzner-server-2"
    for fragment in (
        "umask 077",
        "chown root:tamforge-claude /etc/tamforge/secrets/claude-oauth.env.new",
        "chmod 0640 /etc/tamforge/secrets/claude-oauth.env.new",
        "mv -f /etc/tamforge/secrets/claude-oauth.env.new /etc/tamforge/secrets/claude-oauth.env",
        "systemctl restart tamforge-claude-worker",
        "worker_heartbeats",
    ):
        assert fragment in remote


def test_a_value_that_is_not_a_subscription_token_changes_nothing(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, argv_log, _ = fake_ssh
    result = run(env, "sk-ant-api03-fixture")
    assert result.returncode == 1
    assert not argv_log.exists()
    assert "Nothing changed" in result.stderr


def test_a_worker_that_is_not_ready_after_the_restart_fails_the_rotation(
    fake_ssh: tuple[dict[str, str], Path, Path],
) -> None:
    env, _, _ = fake_ssh
    result = run({**env, "FAKE_SSH_RESULT": "needs_attention auth"}, TOKEN)
    assert result.returncode == 1
    assert "needs_attention (auth)" in result.stderr
