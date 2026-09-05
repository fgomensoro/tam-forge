import subprocess
from types import SimpleNamespace

import pytest


def test_gate_requires_safe_explicit_database_and_paths():
    from tamforge_backend.testing.plan03_integration_gate import run

    for url, paths in [
        (None, ["tests"]),
        ("postgresql://u:secret@localhost/live", ["tests"]),
        ("postgresql://u:secret@127.0.0.1:54329/tamforge_test", []),
        ("postgresql://u:secret@127.0.0.1:54329/tamforge_test", ["-k"]),
    ]:
        with pytest.raises(ValueError, match="explicit"):
            run(paths, test_database_url=url)


def test_gate_process_boundary_preserves_failure_without_credentials(capsys):
    from tamforge_backend.testing.plan03_integration_gate import run

    def process(command, *, env, check):
        assert command[1:3] == ["-m", "pytest"]
        assert "--strict-markers" in command
        assert env["TEST_DATABASE_URL"].endswith("/tamforge_test")
        return subprocess.CompletedProcess(command, 7)

    assert (
        run(
            ["apps/backend/tests/integration/agents"],
            test_database_url="postgresql://u:secret@127.0.0.1:54329/tamforge_test",
            process=process,
        )
        == 7
    )
    assert "secret" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "collected,passed,failed,skipped,want",
    [(0, 0, 0, 0, 1), (2, 1, 0, 1, 1), (2, 2, 0, 0, 0), (2, 1, 1, 0, 1), (2, 1, 0, 0, 1)],
)
def test_gate_rejects_empty_skipped_and_incomplete_results(
    collected, passed, failed, skipped, want
):
    from tamforge_backend.testing.plan03_integration_gate import IntegrationGate

    gate = IntegrationGate()
    gate.collected = collected
    gate.passed = passed
    gate.failed = failed
    gate.skipped = skipped
    session = SimpleNamespace(exitstatus=0)
    gate.pytest_sessionfinish(session, 0)
    assert session.exitstatus == want
