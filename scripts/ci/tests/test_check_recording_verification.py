from __future__ import annotations

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
        "artifact_hashes": ["a" * 64],
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
    return result


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "window_started_at": "2026-09-04T19:00:00Z",
        "window_ended_at": "2026-09-04T20:00:00Z",
        "machine_profile": "macbook-pro-apple-m2-8gb",
        "results": [_result(key) for key in REQUIRED_SCENARIO_KEYS],
    }


def _result_for(payload: dict[str, object], key: str) -> dict[str, object]:
    results = payload["results"]
    assert isinstance(results, list)
    return next(result for result in results if result["key"] == key)


def test_complete_payload_returns_complete_summary() -> None:
    validate, _ = _validator()

    summary = validate(_payload())

    assert summary.total == 37
    assert summary.passed == 37
    assert summary.failed == 0
    assert summary.unsupported == 0
    assert summary.blocked == 0
    assert summary.complete is True


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


@pytest.mark.parametrize(
    "artifact_hash",
    ["A" * 64, "a" * 63, "g" * 64, "sha256:" + "a" * 64],
)
def test_artifact_hashes_are_bare_lowercase_sha256(artifact_hash: str) -> None:
    validate, error = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["artifact_hashes"] = [artifact_hash]

    with pytest.raises(error, match="artifact_hashes"):
        validate(payload)


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


@pytest.mark.parametrize(
    ("status", "summary_field"),
    [("fail", "failed"), ("unsupported", "unsupported"), ("blocked", "blocked")],
)
def test_nonpassing_required_scenario_prevents_completion(
    status: str, summary_field: str
) -> None:
    validate, _ = _validator()
    payload = _payload()
    _result_for(payload, "app.zoom")["status"] = status

    summary = validate(payload)

    assert summary.complete is False
    assert summary.passed == 36
    assert getattr(summary, summary_field) == 1


def test_cli_prints_machine_readable_incomplete_summary(tmp_path: Path) -> None:
    payload = _payload()
    _result_for(payload, "app.zoom")["status"] = "blocked"
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
        "artifact_hashes",
    }
    assert set(result_schema["properties"]["machine_code"]["enum"]) == {
        "verified",
        "verification-not-run",
        "verification-failed",
        "verification-blocked",
        "source-unsupported",
        "required-tracks-unavailable",
    }


def test_example_is_safe_structurally_valid_and_deliberately_incomplete() -> None:
    validate, _ = _validator()
    example_path = Path("docs/project/recording-verification-v1.example.json")

    payload = json.loads(example_path.read_text(encoding="utf-8"))
    summary = validate(payload)

    assert summary.total == 37
    assert summary.blocked == 37
    assert summary.complete is False
