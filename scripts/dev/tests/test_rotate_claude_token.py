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


def fake_command(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o700)


def test_the_host_script_installs_0640_before_the_restart_and_reads_only_newer_beats(
    fake_ssh: tuple[dict[str, str], Path, Path], tmp_path: Path
) -> None:
    env, argv_log, stdin_log = fake_ssh
    run(env, TOKEN)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    remote = "\n".join(argv_log.read_text().splitlines()[1:]).replace(
        "/etc/tamforge/secrets", str(secrets)
    )
    host_bin = tmp_path / "host-bin"
    host_bin.mkdir()
    log = tmp_path / "host.log"
    target = secrets / "claude-oauth.env"
    fake_command(host_bin / "chown", f'ls -l "$2" | cut -c1-10 >> {log}\n')
    fake_command(host_bin / "systemctl", f'echo "$@" >> {log}; ls {secrets} >> {log}\n')
    fake_command(host_bin / "sleep", "")
    fake_command(
        host_bin / "sudo",
        f'echo "${{@: -1}}" >> {log}\n'
        'case "${@: -1}" in *clock_timestamp*) echo "2026-09-24 01:14:20.88667+00" ;;'
        ' *) echo "ok none" ;; esac\n',
    )
    result = subprocess.run(
        ["bash", "-c", remote],
        stdin=stdin_log.open(),
        env={**os.environ, "PATH": f"{host_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok none\n"
    assert target.read_text() == f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n"
    assert oct(target.stat().st_mode & 0o777) == "0o640"
    assert log.read_text().splitlines() == [
        "-rw-------",
        "restart tamforge-claude-worker",
        "claude-oauth.env",
        "select clock_timestamp()",
        "select status || ' ' || reason from worker_heartbeats where worker = 'claude' "
        "and observed_at > '2026-09-24 01:14:20.88667+00'",
    ]
