from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest

REQUIRED_SCENARIO_KEYS = (
    "app.zoom",
    "app.teams",
    "app.meet-browser-call",
    "app.tam-forge-tts-interviewer",
    "app.browser-local-playback",
    "placement.foreground",
    "placement.background",
    "placement.minimized",
    "display.internal",
    "display.external",
    "output.headphones",
    "output.speakers",
    "route.microphone-change",
    "route.output-change",
    "permission.allowed",
    "permission.denied",
    "permission.restricted",
    "microphone.absent",
    "microphone.in-use",
    "silence.microphone",
    "silence.system-audio",
    "lifecycle.sleep-wake",
    "lifecycle.app-crash-relaunch",
    "storage.disk-reserve-pressure",
    "storage.disk-write-pressure",
    "network.loss",
    "server.restart",
    "part.duplicate-identical",
    "part.duplicate-conflicting",
    "part.reordered",
    "corruption.ciphertext",
    "corruption.upload",
    "corruption.aligned-truncation",
    "tracks.missing-expected",
    "startup.callback-order",
    "startup.missing-track-bound",
    "finish.missing-track",
)

PRESTART_BLOCK_SCENARIO_KEYS = frozenset(
    {
        "permission.denied",
        "permission.restricted",
        "microphone.absent",
        "microphone.in-use",
    }
)

RETAINED_FAILURE_SCENARIO_KEYS = frozenset(
    {
        "silence.microphone",
        "silence.system-audio",
        "tracks.missing-expected",
        "startup.missing-track-bound",
        "finish.missing-track",
    }
)


def _validator() -> tuple[Callable[[object], object], type[Exception]]:
    module = importlib.import_module("scripts.ci.check_recording_verification")
    return module.validate_recording_verification, module.RecordingVerificationError


def _artifact_sha256(result: dict[str, object]) -> str:
    canonical = json.dumps(
        {key: value for key, value in result.items() if key != "artifact_sha256"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _rehash(result: dict[str, object]) -> None:
    result["artifact_sha256"] = _artifact_sha256(result)


def _repository_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _result(key: str) -> dict[str, object]:
    result: dict[str, object] = {
        "key": key,
        "status": "pass",
        "started_at": "2026-09-04T19:00:00Z",
        "ended_at": "2026-09-04T19:00:30Z",
        "microphone_track_present": True,
        "system_audio_track_present": True,
        "required_tracks_failure": False,
        "gap_count": 0,
        "sealed": True,
        "spool_retained": False,
        "upload_state": "released",
        "machine_code": "verified",
    }
    if key in PRESTART_BLOCK_SCENARIO_KEYS | RETAINED_FAILURE_SCENARIO_KEYS:
        result.update(
            microphone_track_present=False,
            system_audio_track_present=False,
            required_tracks_failure=True,
            sealed=False,
            spool_retained=key in RETAINED_FAILURE_SCENARIO_KEYS,
            upload_state="not-started",
            machine_code="required-tracks-unavailable",
        )
    _rehash(result)
    return result


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "window_started_at": "2026-09-04T19:00:00Z",
        "window_ended_at": "2026-09-04T20:00:00Z",
        "machine_profile": "macbook-air-apple-m5-24gb",
        "results": [_result(key) for key in REQUIRED_SCENARIO_KEYS],
    }


def _blocked_payload() -> dict[str, object]:
    payload = _payload()
    payload["commit_sha"] = "0" * 40
    results = payload["results"]
    assert isinstance(results, list)
    for result in results:
        result.update(
            status="blocked",
            microphone_track_present=False,
            system_audio_track_present=False,
            required_tracks_failure=False,
            gap_count=0,
            sealed=False,
            spool_retained=False,
            upload_state="not-started",
            machine_code="verification-not-run",
        )
        _rehash(result)
    return payload


def _result_for(payload: dict[str, object], key: str) -> dict[str, object]:
    results = payload["results"]
    assert isinstance(results, list)
    return next(result for result in results if result["key"] == key)


def test_complete_payload_returns_complete_summary() -> None:
    validate, _ = _validator()
    payload = _payload()

    summary = validate(payload, repository_head=payload["commit_sha"])

    assert summary.total == 37
    assert summary.passed == 37
    assert summary.failed == 0
    assert summary.unsupported == 0
    assert summary.blocked == 0
    assert summary.complete is True


def test_complete_payload_requires_repository_head() -> None:
    validate, error = _validator()

    with pytest.raises(error, match="repository_head.*required"):
        validate(_payload())


def test_complete_payload_rejects_stale_repository_head() -> None:
    validate, error = _validator()

    with pytest.raises(error, match="commit_sha.*repository_head"):
        validate(
            _payload(),
            repository_head="fedcba9876543210fedcba9876543210fedcba98",
        )


def test_partly_observed_payload_requires_repository_head() -> None:
    validate, error = _validator()
    payload = _payload()
    result = _result_for(payload, "app.zoom")
    result.update(
        status="blocked",
        microphone_track_present=False,
        system_audio_track_present=False,
        required_tracks_failure=False,
        sealed=False,
        spool_retained=False,
        upload_state="not-started",
        machine_code="verification-not-run",
    )
    _rehash(result)

    with pytest.raises(error, match="repository_head.*non-blocked evidence"):
        validate(payload)


def test_fully_blocked_template_requires_zero_commit_sentinel() -> None:
    validate, error = _validator()
    payload = _blocked_payload()
    payload["commit_sha"] = "1" * 40

    with pytest.raises(error, match="blocked template.*zero commit sentinel"):
        validate(payload)


def test_fully_blocked_template_accepts_only_zero_commit_sentinel() -> None:
    validate, _ = _validator()

    summary = validate(_blocked_payload())

    assert summary.blocked == 37
    assert summary.complete is False


@pytest.mark.parametrize("schema_version", [0, 2, "1", True])
def test_schema_version_must_be_exact_integer_one(schema_version: object) -> None:
    validate, error = _validator()
    payload = _payload()
    payload["schema_version"] = schema_version

    with pytest.raises(error, match="schema_version"):
        validate(payload)


@pytest.mark.parametrize(
    "commit_sha",
    [
        "0123456789abcdef0123456789abcdef0123456",
        "0123456789abcdef0123456789abcdef012345678",
        "0123456789ABCDEF0123456789ABCDEF01234567",
        "g123456789abcdef0123456789abcdef01234567",
    ],
)
def test_commit_sha_must_be_a_full_lowercase_git_sha(commit_sha: str) -> None:
    validate, error = _validator()
    payload = _payload()
    payload["commit_sha"] = commit_sha

    with pytest.raises(error, match="commit_sha"):
        validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("window_started_at", "2026-09-04T19:00:00-07:00"),
        ("window_ended_at", "2026-09-04T20:00:00+00:00"),
        ("window_started_at", "2026-09-04 19:00:00Z"),
    ],
)
def test_window_timestamps_require_canonical_utc(field: str, value: str) -> None:
    validate, error = _validator()
    payload = _payload()
    payload[field] = value

    with pytest.raises(error, match=field):
        validate(payload)


def test_window_cannot_exceed_sixty_minutes() -> None:
    validate, error = _validator()
    payload = _payload()
    payload["window_ended_at"] = "2026-09-04T20:00:01Z"

    with pytest.raises(error, match="60 minutes"):
        validate(payload)


def test_window_end_must_follow_start() -> None:
    validate, error = _validator()
    payload = _payload()
    payload["window_ended_at"] = payload["window_started_at"]

    with pytest.raises(error, match="after"):
        validate(payload)


def test_machine_profile_must_be_the_supported_private_window_profile() -> None:
    validate, error = _validator()
    payload = _payload()
    payload["machine_profile"] = "unknown-machine"

    with pytest.raises(error, match="machine_profile"):
        validate(payload)


def test_scenario_timestamps_must_be_utc_and_inside_the_window() -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["started_at"] = "2026-09-04T18:59:59Z"

    with pytest.raises(error, match="app.zoom"):
        validate(payload)


def test_missing_required_scenario_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    results = payload["results"]
    assert isinstance(results, list)
    results.pop()

    with pytest.raises(error, match="missing.*finish.missing-track"):
        validate(payload)


def test_duplicate_scenario_key_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    results = payload["results"]
    assert isinstance(results, list)
    results[-1] = deepcopy(results[0])

    with pytest.raises(error, match="duplicate.*app.zoom"):
        validate(payload)


def test_unknown_scenario_key_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    results = payload["results"]
    assert isinstance(results, list)
    results[-1] = _result("app.unapproved")

    with pytest.raises(error, match="unknown.*app.unapproved"):
        validate(payload)


@pytest.mark.parametrize("location", ["root", "result"])
def test_unknown_fields_are_rejected(location: str) -> None:
    validate, error = _validator()
    payload = _payload()
    if location == "root":
        payload["operator"] = "synthetic-user"
    else:
        _result_for(payload, "app.zoom")["duration_seconds"] = 30

    with pytest.raises(error, match="extra|unknown"):
        validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("path", "/Users/synthetic/private.wav", "absolute path"),
        ("evidence", "capture sounded correct", "free-form evidence"),
        ("evidence_url", "https://example.invalid/run?token=synthetic", "query"),
        ("evidence_url", "https://user@example.invalid/run", "user-info"),
        ("evidence_url", "https://example.invalid/run#result", "fragment"),
        ("authorization", "Bearer synthetic.token.value", "bearer"),
        ("cookie", "session=synthetic-cookie", "cookie"),
        ("transcript", "synthetic transcript text", "transcript"),
        ("participant_name", "Synthetic Person", "participant"),
        ("device_name", "Synthetic Microphone", "device name"),
        ("meeting_title", "Synthetic Interview", "meeting title"),
        ("raw_audio", "synthetic.wav", "raw audio"),
    ],
)
def test_private_or_free_form_evidence_is_rejected(
    field: str, value: str, message: str
) -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")[field] = value

    with pytest.raises(error, match=message):
        validate(payload)


def test_plural_artifact_hash_channel_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["artifact_hashes"] = ["a" * 64]

    with pytest.raises(error, match="artifact_hashes"):
        validate(payload)


def test_artifact_sha256_is_required() -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom").pop("artifact_sha256")

    with pytest.raises(
        error, match=r"(?s)results\.0\.artifact_sha256.*Field required"
    ):
        validate(payload)


def test_arbitrary_artifact_sha256_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["artifact_sha256"] = "a" * 64

    with pytest.raises(error, match="artifact_sha256 does not match canonical result"):
        validate(payload)


def test_mutating_result_without_rehash_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["gap_count"] = 1

    with pytest.raises(error, match="artifact_sha256 does not match canonical result"):
        validate(payload)


def test_gap_count_decimal_above_disk_policy_limit_is_rejected() -> None:
    validate, error = _validator()
    payload = _payload()
    result = _result_for(payload, "app.zoom")
    result["gap_count"] = 14_401
    _rehash(result)

    with pytest.raises(error, match=r"(?s)gap_count.*less than or equal to 14400"):
        validate(payload, repository_head=payload["commit_sha"])


@pytest.mark.parametrize(
    "machine_code",
    [
        "participant-synthetic-person",
        "device-synthetic-microphone",
        "meeting-synthetic-interview",
        "synthetic-transcript",
        "synthetic-session-cookie",
        "raw-audio-capture",
    ],
)
def test_machine_code_cannot_encode_private_free_form_values(machine_code: str) -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["machine_code"] = machine_code

    with pytest.raises(error, match="machine_code"):
        validate(payload)


@pytest.mark.parametrize(
    "field", ["microphone_track_present", "system_audio_track_present"]
)
def test_passing_capture_scenario_requires_both_tracks(field: str) -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")[field] = False

    with pytest.raises(error, match="app.zoom.*both required tracks"):
        validate(payload)


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("required_tracks_failure", False),
        ("sealed", True),
        ("spool_retained", False),
        ("upload_state", "released"),
    ],
)
def test_passing_negative_scenario_requires_fail_closed_state(
    field: str, unsafe_value: object
) -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "finish.missing-track")[field] = unsafe_value

    with pytest.raises(error, match="finish.missing-track.*fail closed"):
        validate(payload)


@pytest.mark.parametrize("status", ["fail", "unsupported", "blocked"])
@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("required_tracks_failure", False),
        ("sealed", True),
        ("spool_retained", False),
        ("upload_state", "released"),
    ],
)
def test_nonpassing_observed_track_failure_cannot_declare_unsafe_state(
    status: str, field: str, unsafe_value: object
) -> None:
    validate, error = _validator()
    payload = _payload()
    result = _result_for(payload, "finish.missing-track")
    result["status"] = status
    result[field] = unsafe_value

    with pytest.raises(error, match="finish.missing-track.*fail closed"):
        validate(payload)


@pytest.mark.parametrize(
    ("status", "summary_field"),
    [("fail", "failed"), ("unsupported", "unsupported"), ("blocked", "blocked")],
)
def test_nonpassing_required_scenario_prevents_completion(
    status: str, summary_field: str
) -> None:
    validate, _ = _validator()
    payload = _payload()
    result = _result_for(payload, "app.zoom")
    result["status"] = status
    _rehash(result)

    summary = validate(payload, repository_head=payload["commit_sha"])

    assert summary.complete is False
    assert summary.passed == 36
    assert getattr(summary, summary_field) == 1


def test_cli_prints_machine_readable_incomplete_summary(tmp_path: Path) -> None:
    payload = _payload()
    payload["commit_sha"] = _repository_head()
    result = _result_for(payload, "app.zoom")
    result["status"] = "blocked"
    _rehash(result)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_recording_verification.py",
            str(report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "blocked": 1,
        "complete": False,
        "failed": 0,
        "passed": 36,
        "total": 37,
        "unsupported": 0,
    }


def test_cli_rejects_caller_supplied_expected_head(tmp_path: Path) -> None:
    payload = _payload()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_recording_verification.py",
            str(report),
            "--expected-head",
            "fedcba9876543210fedcba9876543210fedcba98",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "unrecognized arguments: --expected-head" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_resolves_repository_head_for_complete_report(tmp_path: Path) -> None:
    payload = _payload()
    payload["commit_sha"] = _repository_head()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/ci/check_recording_verification.py", str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["complete"] is True


def test_cli_rejects_nonblocked_report_for_stale_commit(tmp_path: Path) -> None:
    payload = _payload()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/ci/check_recording_verification.py", str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "commit_sha does not match repository_head" in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("window_started_at", "2026-02-30T19:00:00Z"),
        ("window_ended_at", "2026-13-04T20:00:00Z"),
    ],
)
def test_invalid_calendar_window_date_raises_contract_error(
    field: str, value: str
) -> None:
    validate, error = _validator()
    payload = _payload()
    payload[field] = value

    with pytest.raises(error, match=f"{field}.*valid UTC timestamp"):
        validate(payload)


def test_invalid_calendar_scenario_date_raises_contract_error() -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["started_at"] = "2026-02-30T19:00:00Z"

    with pytest.raises(error, match="app.zoom.started_at.*valid UTC timestamp"):
        validate(payload)


def test_cli_reports_invalid_calendar_date_without_traceback(tmp_path: Path) -> None:
    payload = _payload()
    payload["window_started_at"] = "2026-02-30T19:00:00Z"
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_recording_verification.py",
            str(report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "window_started_at must be a valid UTC timestamp" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_schema_is_closed_and_declares_the_validator_contract() -> None:
    schema_path = Path("docs/project/recording-verification-v1.schema.json")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "commit_sha",
        "window_started_at",
        "window_ended_at",
        "machine_profile",
        "results",
    }
    result_schema = schema["$defs"]["scenario_result"]
    assert result_schema["additionalProperties"] is False
    assert set(result_schema["properties"]) == {
        "key",
        "status",
        "started_at",
        "ended_at",
        "microphone_track_present",
        "system_audio_track_present",
        "required_tracks_failure",
        "gap_count",
        "sealed",
        "spool_retained",
        "upload_state",
        "machine_code",
        "artifact_sha256",
    }
    assert set(result_schema["properties"]["machine_code"]["enum"]) == {
        "verified",
        "verification-not-run",
        "verification-failed",
        "verification-blocked",
        "source-unsupported",
        "required-tracks-unavailable",
    }
    assert "artifact_sha256" in result_schema["required"]
    assert result_schema["properties"]["artifact_sha256"] == {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    assert result_schema["properties"]["gap_count"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 14_400,
    }


def test_example_is_safe_structurally_valid_and_deliberately_incomplete() -> None:
    validate, _ = _validator()
    example_path = Path("docs/project/recording-verification-v1.example.json")

    payload = json.loads(example_path.read_text(encoding="utf-8"))
    summary = validate(payload)

    assert payload["commit_sha"] == "0" * 40
    assert all(
        result["artifact_sha256"] == _artifact_sha256(result)
        for result in payload["results"]
    )
    assert summary.total == 37
    assert summary.blocked == 37
    assert summary.complete is False


RUNTIME_REPORT = Path("docs/project/recording-verification-v1.json")
CI_WORKFLOW = Path(".github/workflows/ci.yml")


def test_runtime_report_is_the_blocked_template_or_exact_ancestor_evidence() -> None:
    payload = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))

    assert {result["key"] for result in payload["results"]} == {
        result["key"] for result in _payload()["results"]
    }
    assert all(
        result["artifact_sha256"] == _artifact_sha256(result) for result in payload["results"]
    )
    blocked = sum(result["status"] == "blocked" for result in payload["results"])
    assert len(payload["results"]) == 37
    # The template stays on the sentinel until the one runtime window; after
    # it, the evidence must name a real commit in this history.
    assert (payload["commit_sha"] == "0" * 40) == (blocked == 37)
    assert _is_verified_ancestor_of_head(payload["commit_sha"]) or blocked == 37


VERIFIED_PATHS = (
    "apps/macos",
    "apps/backend/src/tamforge_backend/recordings",
    "apps/backend/src/tamforge_backend/storage",
)


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], check=False, capture_output=True, text=True)


def _is_verified_ancestor_of_head(commit_sha: str) -> bool:
    return (
        _git("merge-base", "--is-ancestor", commit_sha, "HEAD").returncode == 0
        and _git("diff", "--quiet", commit_sha, "HEAD", "--", *VERIFIED_PATHS).returncode == 0
    )


def _ancestor(*, verified_code_unchanged: bool) -> str:
    """Pick a real ancestor of HEAD (never HEAD) with or without verified-code changes."""
    history = _git("rev-list", "--max-count=200", "HEAD").stdout.split()[1:]
    for commit_sha in history:
        unchanged = _git("diff", "--quiet", commit_sha, "HEAD", "--", *VERIFIED_PATHS)
        if (unchanged.returncode == 0) == verified_code_unchanged:
            return commit_sha
    pytest.skip("history has no suitable ancestor commit")


def test_cli_structural_mode_accepts_evidence_recorded_on_an_ancestor_commit(
    tmp_path: Path,
) -> None:
    # Committing the evidence moves HEAD past the verified head, and pull
    # request CI checks out a merge commit; ancestry keeps the binding honest.
    payload = _payload()
    payload["commit_sha"] = _ancestor(verified_code_unchanged=True)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/ci/check_recording_verification.py", str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["complete"] is True


def test_cli_structural_mode_rejects_ancestor_evidence_once_verified_code_changed(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["commit_sha"] = _ancestor(verified_code_unchanged=False)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/ci/check_recording_verification.py", str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "commit_sha does not match repository_head" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_require_complete_still_requires_the_exact_repository_head(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["commit_sha"] = _ancestor(verified_code_unchanged=True)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_recording_verification.py",
            str(report),
            "--require-complete",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "commit_sha does not match repository_head" in completed.stderr


def test_ci_checks_out_full_history_so_evidence_ancestry_can_be_verified() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    backend_unit = workflow.split("  backend-unit:", 1)[1].split("\n  backend-integration:", 1)[0]

    assert "fetch-depth: 0" in backend_unit


def test_ci_validates_runtime_report_structure_without_requiring_completion() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    invocation = f"scripts/ci/check_recording_verification.py {RUNTIME_REPORT}"

    assert invocation in workflow
    assert "--require-complete" not in workflow


def test_cli_require_complete_rejects_blocked_runtime_report() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_recording_verification.py",
            "docs/project/recording-verification-v1.example.json",
            "--require-complete",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "recording verification is not complete" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_require_complete_accepts_complete_report_on_repository_head(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["commit_sha"] = _repository_head()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_recording_verification.py",
            str(report),
            "--require-complete",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["complete"] is True


WINDOW_MACHINE_PROFILE = "macbook-air-apple-m5-24gb"


def test_supported_machine_profile_names_the_real_window_machine() -> None:
    # The single runtime window runs on the owner's MacBook Air (Apple M5,
    # 24 GB); evidence may never claim a machine the window did not use.
    module = importlib.import_module("scripts.ci.check_recording_verification")
    validate, _ = _validator()
    schema = json.loads(
        Path("docs/project/recording-verification-v1.schema.json").read_text(encoding="utf-8")
    )
    payload = _payload()
    payload["machine_profile"] = WINDOW_MACHINE_PROFILE

    assert module.SUPPORTED_MACHINE_PROFILE == WINDOW_MACHINE_PROFILE
    assert schema["properties"]["machine_profile"] == {"const": WINDOW_MACHINE_PROFILE}
    assert validate(payload, repository_head=payload["commit_sha"]).complete is True
    for report in (
        "docs/project/recording-verification-v1.json",
        "docs/project/recording-verification-v1.example.json",
    ):
        assert json.loads(Path(report).read_text())["machine_profile"] == WINDOW_MACHINE_PROFILE


@pytest.mark.parametrize(
    ("key", "status", "machine_code"),
    [
        ("permission.restricted", "unsupported", "source-unsupported"),
        ("microphone.in-use", "blocked", "verification-blocked"),
        ("silence.microphone", "blocked", "verification-blocked"),
    ],
)
def test_unobserved_scenarios_never_have_to_claim_a_required_track_failure(
    key: str, status: str, machine_code: str
) -> None:
    # Blocked and unsupported entries record that nothing was observed; the
    # fail-closed field rules apply only to evidence that was actually run.
    validate, _ = _validator()
    payload = _payload()
    result = _result_for(payload, key)
    result.update(
        {
            "status": status,
            "machine_code": machine_code,
            "microphone_track_present": False,
            "system_audio_track_present": False,
            "required_tracks_failure": False,
            "sealed": False,
            "spool_retained": False,
            "upload_state": "not-started",
        }
    )
    _rehash(result)

    summary = validate(payload, repository_head=payload["commit_sha"])

    assert summary.complete is False
    assert getattr(summary, status) == 1
