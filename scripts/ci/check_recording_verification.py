"""Validate privacy-safe evidence for the issue 36 recording matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from pydantic import ValidationError as PydanticValidationError

REQUIRED_SCENARIO_KEYS = frozenset(
    {
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
    }
)

CAPTURE_SCENARIO_KEYS = frozenset(
    key
    for key in REQUIRED_SCENARIO_KEYS
    if key.startswith(("app.", "placement.", "display.", "output."))
) | {"permission.allowed", "startup.callback-order"}

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

SUPPORTED_MACHINE_PROFILE = "macbook-air-apple-m5-24gb"
UTC_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
COMMIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
BLOCKED_COMMIT_SENTINEL = "0" * 40
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

UtcTimestamp = Annotated[StrictStr, Field(pattern=UTC_TIMESTAMP_PATTERN)]
Sha256 = Annotated[StrictStr, Field(pattern=SHA256_PATTERN)]
MachineCode = Literal[
    "verified",
    "verification-not-run",
    "verification-failed",
    "verification-blocked",
    "source-unsupported",
    "required-tracks-unavailable",
]


class RecordingVerificationError(ValueError):
    """Raised when evidence is unsafe, malformed, incomplete in inventory, or inconsistent."""


class _ScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    key: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    status: Literal["pass", "fail", "unsupported", "blocked"]
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    microphone_track_present: StrictBool
    system_audio_track_present: StrictBool
    required_tracks_failure: StrictBool
    gap_count: Annotated[StrictInt, Field(ge=0, le=14_400)]
    sealed: StrictBool
    spool_retained: StrictBool
    upload_state: Literal[
        "not-started", "pending", "audio-accepted", "lineage-accepted", "released"
    ]
    machine_code: MachineCode
    artifact_sha256: Sha256


class _RecordingVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    commit_sha: Annotated[StrictStr, Field(pattern=COMMIT_SHA_PATTERN)]
    window_started_at: UtcTimestamp
    window_ended_at: UtcTimestamp
    machine_profile: Literal["macbook-air-apple-m5-24gb"]
    results: Annotated[list[_ScenarioResult], Field(min_length=1)]


@dataclass(frozen=True, slots=True)
class RecordingVerificationSummary:
    """Status counts for a structurally valid recording verification report."""

    total: int
    passed: int
    failed: int
    unsupported: int
    blocked: int
    complete: bool


_FORBIDDEN_KEY_MESSAGES = {
    "authorization": "bearer credentials are forbidden",
    "bearer": "bearer credentials are forbidden",
    "cookie": "cookie data is forbidden",
    "cookies": "cookie data is forbidden",
    "set_cookie": "cookie data is forbidden",
    "transcript": "transcript data is forbidden",
    "transcripts": "transcript data is forbidden",
    "participant": "participant data is forbidden",
    "participant_name": "participant names are forbidden",
    "participant_names": "participant names are forbidden",
    "device_name": "device names are forbidden",
    "device_names": "device names are forbidden",
    "meeting_title": "meeting titles are forbidden",
    "meeting_titles": "meeting titles are forbidden",
    "raw_audio": "raw audio is forbidden",
}
_FREE_FORM_KEYS = frozenset(
    {"comment", "comments", "description", "details", "evidence", "message", "notes"}
)
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_BEARER_VALUE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_RAW_AUDIO_VALUE = re.compile(
    r"(?:data:audio/|\.(?:aac|aiff|flac|m4a|mp3|pcm|wav)\b)", re.IGNORECASE
)


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _scan_for_private_data(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if normalized in _FREE_FORM_KEYS:
                raise RecordingVerificationError("free-form evidence is forbidden")
            if normalized in _FORBIDDEN_KEY_MESSAGES:
                raise RecordingVerificationError(_FORBIDDEN_KEY_MESSAGES[normalized])
            _scan_for_private_data(child)
        return
    if isinstance(value, list):
        for child in value:
            _scan_for_private_data(child)
        return
    if not isinstance(value, str):
        return

    if value.startswith(("/", "file:/")) or _ABSOLUTE_WINDOWS_PATH.match(value):
        raise RecordingVerificationError("absolute paths are forbidden")
    if _BEARER_VALUE.search(value):
        raise RecordingVerificationError("bearer credentials are forbidden")
    if _RAW_AUDIO_VALUE.search(value):
        raise RecordingVerificationError("raw audio is forbidden")

    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        if parsed.username is not None or parsed.password is not None:
            raise RecordingVerificationError("URL user-info is forbidden")
        if parsed.query:
            raise RecordingVerificationError("URL query data is forbidden")
        if parsed.fragment:
            raise RecordingVerificationError("URL fragment data is forbidden")


def _timestamp(value: str, field: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RecordingVerificationError(
            f"{field} must be a valid UTC timestamp"
        ) from exc


def _validated_report(payload: object) -> _RecordingVerification:
    _scan_for_private_data(payload)
    try:
        return _RecordingVerification.model_validate(payload, strict=True)
    except PydanticValidationError as exc:
        raise RecordingVerificationError(str(exc)) from exc


def _validate_inventory(results: list[_ScenarioResult]) -> None:
    keys = [result.key for result in results]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise RecordingVerificationError(
            f"duplicate scenario keys are forbidden: {', '.join(duplicates)}"
        )

    actual = set(keys)
    unknown = sorted(actual - REQUIRED_SCENARIO_KEYS)
    if unknown:
        raise RecordingVerificationError(f"unknown scenario keys: {', '.join(unknown)}")
    missing = sorted(REQUIRED_SCENARIO_KEYS - actual)
    if missing:
        raise RecordingVerificationError(f"missing scenario keys: {', '.join(missing)}")


def _validate_time_bounds(report: _RecordingVerification) -> None:
    window_start = _timestamp(report.window_started_at, "window_started_at")
    window_end = _timestamp(report.window_ended_at, "window_ended_at")
    if window_end <= window_start:
        raise RecordingVerificationError("window_ended_at must be after window_started_at")
    if window_end - window_start > timedelta(minutes=60):
        raise RecordingVerificationError("verification window cannot exceed 60 minutes")

    for result in report.results:
        started = _timestamp(result.started_at, f"{result.key}.started_at")
        ended = _timestamp(result.ended_at, f"{result.key}.ended_at")
        if ended < started or started < window_start or ended > window_end:
            raise RecordingVerificationError(
                f"scenario {result.key} timestamps must be ordered inside the verification window"
            )


def _validate_scenario_invariants(results: list[_ScenarioResult]) -> None:
    for result in results:
        if result.status == "pass" and result.key in CAPTURE_SCENARIO_KEYS and not (
            result.microphone_track_present and result.system_audio_track_present
        ):
            raise RecordingVerificationError(
                f"scenario {result.key} must contain both required tracks to pass"
            )
        # Only codes produced by running a scenario count as observations;
        # blocked and unsupported entries never have to claim fail-closed fields.
        evidence_was_observed = result.machine_code in {
            "verified",
            "verification-failed",
            "required-tracks-unavailable",
        }
        if (
            result.key in PRESTART_BLOCK_SCENARIO_KEYS
            and (result.status == "pass" or evidence_was_observed)
            and not (
                result.required_tracks_failure
                and not result.sealed
                and not result.spool_retained
                and result.upload_state == "not-started"
            )
        ):
            raise RecordingVerificationError(
                f"scenario {result.key} must fail closed before capture starts"
            )
        if (
            result.key in RETAINED_FAILURE_SCENARIO_KEYS
            and (result.status == "pass" or evidence_was_observed)
            and not (
                result.required_tracks_failure
                and not result.sealed
                and result.spool_retained
                and result.upload_state == "not-started"
            )
        ):
            raise RecordingVerificationError(
                f"scenario {result.key} must fail closed with its spool retained"
            )
        if result.sealed and (
            result.required_tracks_failure
            or not result.microphone_track_present
            or not result.system_audio_track_present
        ):
            raise RecordingVerificationError(
                f"scenario {result.key} must fail closed instead of sealing missing tracks"
            )
        if result.upload_state == "released" and (
            not result.sealed
            or result.required_tracks_failure
            or result.spool_retained
            or not result.microphone_track_present
            or not result.system_audio_track_present
        ):
            raise RecordingVerificationError(
                f"scenario {result.key} must fail closed instead of releasing unsafe evidence"
            )


def _canonical_result_sha256(result: _ScenarioResult) -> str:
    payload = result.model_dump(exclude={"artifact_sha256"}, mode="json")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_artifact_hashes(results: list[_ScenarioResult]) -> None:
    for result in results:
        if result.artifact_sha256 != _canonical_result_sha256(result):
            raise RecordingVerificationError(
                f"scenario {result.key} artifact_sha256 does not match canonical result"
            )


def _validated_repository_head(repository_head: object) -> str:
    if not isinstance(repository_head, str) or re.fullmatch(
        COMMIT_SHA_PATTERN, repository_head
    ) is None:
        raise RecordingVerificationError(
            "repository_head must be a full lowercase 40-character commit SHA"
        )
    return repository_head


def validate_recording_verification(
    payload: object,
    *,
    repository_head: str | None = None,
    is_verified_ancestor: Callable[[str], bool] | None = None,
) -> RecordingVerificationSummary:
    """Validate a report and return counts without treating incompleteness as validity.

    Non-blocked evidence must name the resolved repository head. Structural
    runs may also accept an ancestor of that head whose verified code is
    unchanged, because committing the evidence itself moves the head and
    pull-request CI checks out a merge commit; completion checks never use
    that allowance.
    """

    report = _validated_report(payload)
    _validate_inventory(report.results)
    _validate_time_bounds(report)
    _validate_scenario_invariants(report.results)
    _validate_artifact_hashes(report.results)

    counts = Counter(result.status for result in report.results)
    passed = counts["pass"]
    total = len(report.results)
    fully_blocked = counts["blocked"] == total
    if fully_blocked:
        if report.commit_sha != BLOCKED_COMMIT_SENTINEL:
            raise RecordingVerificationError(
                "fully blocked template must use the zero commit sentinel"
            )
    else:
        if repository_head is None:
            raise RecordingVerificationError(
                "repository_head is required for non-blocked evidence"
            )
        trusted_head = _validated_repository_head(repository_head)
        if report.commit_sha != trusted_head and not (
            is_verified_ancestor is not None and is_verified_ancestor(report.commit_sha)
        ):
            raise RecordingVerificationError("commit_sha does not match repository_head")
    return RecordingVerificationSummary(
        total=total,
        passed=passed,
        failed=counts["fail"],
        unsupported=counts["unsupported"],
        blocked=counts["blocked"],
        complete=passed == total,
    )


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordingVerificationError(f"cannot read recording verification: {exc}") from exc


def _resolve_repository_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RecordingVerificationError("cannot resolve repository_head from git")
    return _validated_repository_head(completed.stdout.strip())


# Evidence stays bound to code: an ancestor qualifies only when none of the
# paths the runtime window verifies changed between it and the head.
VERIFIED_CODE_PATHS = (
    "apps/macos",
    "apps/backend/src/tamforge_backend/recordings",
    "apps/backend/src/tamforge_backend/storage",
)


def _is_verified_ancestor(commit_sha: str) -> bool:
    def git(*arguments: str) -> int:
        return subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), *arguments],
            check=False,
            capture_output=True,
        ).returncode

    return (
        git("merge-base", "--is-ancestor", commit_sha, "HEAD") == 0
        and git("diff", "--quiet", commit_sha, "HEAD", "--", *VERIFIED_CODE_PATHS) == 0
    )


def main(*, repository_head_resolver: Callable[[], str] = _resolve_repository_head) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    # Structural CI runs never pass this flag: a parsed report is not evidence.
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        summary = validate_recording_verification(
            _load_json(args.report),
            repository_head=repository_head_resolver(),
            is_verified_ancestor=None if args.require_complete else _is_verified_ancestor,
        )
    except RecordingVerificationError as exc:
        parser.error(str(exc))
    if args.require_complete and not summary.complete:
        parser.error(
            "recording verification is not complete: "
            f"{summary.passed}/{summary.total} scenarios pass"
        )
    print(json.dumps(asdict(summary), sort_keys=True))


if __name__ == "__main__":
    main()
