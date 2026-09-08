"""Score the base.en/small.en voice benchmark and validate its committed evidence.

The reading script (`docs/project/voice-benchmark-script-v1.md`) is the
reference transcript, so scoring never needs a manual transcription: each
model's own output is compared against that fixed text. This module is pure
scoring plus an evidence-contract gate; it never touches audio or transcripts,
which stay under the gitignored `apps/macos/PrivateAudio/`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic import ValidationError as PydanticValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
READING_SCRIPT_PATH = REPOSITORY_ROOT / "docs/project/voice-benchmark-script-v1.md"
READING_SCRIPT_VERSION = "voice-benchmark-script-v1"
SPEECH_MODELS_MANIFEST_PATH = REPOSITORY_ROOT / "config/speech-models.yaml"
# Where scripts/dev/benchmark_whisper_models.sh writes each model's per-passage
# JSON (scripts/dev/benchmark_whisper_models.swift), one subdirectory per
# MODEL_KEYS entry. Gitignored, holds transcript text; --build aggregates it
# into the committed, aggregate-only report.
BENCHMARK_RESULTS_DIR = REPOSITORY_ROOT / "apps/macos/PrivateAudio/benchmark"

MODEL_KEYS = ("base", "candidate")

SHA256_PATTERN = r"^[0-9a-f]{64}$"
MODEL_FILENAME_PATTERN = r"^ggml-[a-z0-9._-]+\.bin$"
# No slashes and no spaces, so a path or a sentence of transcript cannot hide
# inside a version or machine-profile token.
VERSION_TOKEN_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"
MACHINE_PROFILE_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class ModelBenchmarkError(ValueError):
    """Raised when benchmark evidence is unsafe, malformed, or inconsistent."""


# --- normalise ---------------------------------------------------------------

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()


def _spell(number: int) -> str:
    if number < 20:
        return _ONES[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]} {_ONES[ones]}"
    return "one hundred"


# The reading script only ever speaks numbers 0-100 as standalone words
# (percentages, months, small counts); larger amounts are already spelled
# out in the script itself ("fourteen thousand"), so they are out of scope.
NUMBER_WORDS = {number: _spell(number) for number in range(101)}

_NON_WORD_CHARACTER = re.compile(r"[^a-z0-9\s]")


def normalise(text: str) -> list[str]:
    """Lowercase, drop punctuation, and spell 0-100 so digits and words compare equal."""
    lowered = _NON_WORD_CHARACTER.sub(" ", text.lower())
    words: list[str] = []
    for token in lowered.split():
        spelled = NUMBER_WORDS.get(int(token)) if token.isdigit() else None
        words.extend(spelled.split() if spelled is not None else [token])
    return words


# --- word_error_rate -----------------------------------------------------


def word_error_rate(reference: list[str], hypothesis: list[str]) -> tuple[float, int, int, int]:
    """Return (rate, substitutions, deletions, insertions) from Levenshtein alignment."""
    if len(reference) == 0:
        raise ValueError("reference must not be empty")

    rows, cols = len(reference) + 1, len(hypothesis) + 1
    distance = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        distance[i][0] = i
    for j in range(cols):
        distance[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                distance[i][j] = distance[i - 1][j - 1]
            else:
                distance[i][j] = 1 + min(
                    distance[i - 1][j - 1],  # substitution
                    distance[i - 1][j],  # deletion
                    distance[i][j - 1],  # insertion
                )

    substitutions = deletions = insertions = 0
    i, j = len(reference), len(hypothesis)
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and reference[i - 1] == hypothesis[j - 1]
            and distance[i][j] == distance[i - 1][j - 1]
        ):
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and distance[i][j] == distance[i - 1][j - 1] + 1:
            substitutions += 1
            i, j = i - 1, j - 1
        elif i > 0 and distance[i][j] == distance[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1

    rate = (substitutions + deletions + insertions) / len(reference)
    return rate, substitutions, deletions, insertions


# --- critical_term_recall -------------------------------------------------


def _contains_phrase(tokens: list[str], phrase: list[str]) -> bool:
    span = len(phrase)
    if span == 0 or span > len(tokens):
        return False
    return any(tokens[start : start + span] == phrase for start in range(len(tokens) - span + 1))


def critical_term_recall(
    reference: list[str], hypothesis: list[str], terms: tuple[str, ...]
) -> tuple[float, int, int]:
    """Return (recall, found, expected), counting multi-word terms as adjacent phrases."""
    expected_terms = [term for term in terms if _contains_phrase(reference, term.split())]
    found = sum(1 for term in expected_terms if _contains_phrase(hypothesis, term.split()))
    expected = len(expected_terms)
    recall = 1.0 if expected == 0 else found / expected
    return recall, found, expected


# --- CRITICAL_TERMS, parsed from the reading script at import -----------

_CRITICAL_TERMS_LINE = re.compile(r"^\*\*Critical terms\*\*.*?:\s*(.+)$", re.MULTILINE)


def _parse_critical_terms(script_text: str) -> tuple[str, ...]:
    match = _CRITICAL_TERMS_LINE.search(script_text)
    if match is None:
        raise ModelBenchmarkError("reading script is missing its Critical terms line")
    raw_terms = match.group(1).rstrip(".").split(",")
    return tuple(" ".join(normalise(term)) for term in raw_terms)


CRITICAL_TERMS: tuple[str, ...] = _parse_critical_terms(
    READING_SCRIPT_PATH.read_text(encoding="utf-8")
)


# --- score_run -------------------------------------------------------------


def score_run(reference_text: str, transcript: str) -> dict[str, object]:
    """Score one passage's transcript against its reference text."""
    reference = normalise(reference_text)
    hypothesis = normalise(transcript)
    rate, substitutions, deletions, insertions = word_error_rate(reference, hypothesis)
    recall, found, expected = critical_term_recall(reference, hypothesis, CRITICAL_TERMS)
    return {
        "word_error_rate": rate,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "critical_term_recall": recall,
        "critical_terms_expected": expected,
        "critical_terms_found": found,
    }


# --- decide ------------------------------------------------------------------

# "small.en wins only if it reduces critical-term misses or meaning-changing
# errors beyond measurement noise, or cuts absolute word error rate by a
# stated margin" (design spec). About six minutes of read speech produces
# enough run-to-run jitter that anything under two absolute WER points is
# noise, not a real improvement, so base keeps its pin on a practical tie.
WORD_ERROR_RATE_MARGIN = 0.02


def decide(base: dict[str, object], candidate: dict[str, object]) -> tuple[str, str]:
    """Return (chosen_model_key, reason); ties keep base per the spec."""
    base_wer = base["word_error_rate"]
    candidate_wer = candidate["word_error_rate"]
    if base_wer - candidate_wer >= WORD_ERROR_RATE_MARGIN:
        return "candidate", (
            f"candidate wins on word error rate: {candidate_wer:.3f} beats base's "
            f"{base_wer:.3f} by at least the {WORD_ERROR_RATE_MARGIN:.2f} margin."
        )

    base_found = base["critical_terms_found"]
    candidate_found = candidate["critical_terms_found"]
    if candidate_found > base_found:
        return "candidate", (
            f"candidate wins on critical-term recall: it found {candidate_found} terms "
            f"against base's {base_found}, with no other rule favouring base."
        )

    base_substitutions = base["substitutions"]
    candidate_substitutions = candidate["substitutions"]
    if candidate_substitutions < base_substitutions:
        return "candidate", (
            "candidate wins on meaning-changing substitutions: "
            f"{candidate_substitutions} against base's {base_substitutions}."
        )

    return "base", (
        f"base wins: candidate did not clear the {WORD_ERROR_RATE_MARGIN:.2f} "
        "word-error-rate margin, find more critical terms, or make fewer "
        "substitutions."
    )


# --- build_report --------------------------------------------------------


def build_report(
    *,
    script_version: str,
    runtime_version: str,
    machine_profile: str,
    passages: int,
    models: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Assemble the committed report shape, deciding the winner from the model figures."""
    if set(models) != set(MODEL_KEYS):
        raise ModelBenchmarkError(f"models must have exactly the keys {MODEL_KEYS}")

    chosen_model, decision_reason = decide(models["base"], models["candidate"])
    return {
        "schema_version": 1,
        "script_version": script_version,
        "runtime_version": runtime_version,
        "machine_profile": machine_profile,
        "models": models,
        "passages": passages,
        "chosen_model": chosen_model,
        "decision_reason": decision_reason,
    }


# --- validate_report: schema gate and privacy gate -----------------------

# Global Constraints pin, verbatim - the only two models this benchmark ever
# compares, so evidence naming any other artifact is rejected outright.
_EXPECTED_MODEL_PINS: dict[str, dict[str, object]] = {
    "base": {
        "filename": "ggml-base.en-q5_1.bin",
        "sha256": "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f",
        "bytes": 59721011,
    },
    "candidate": {
        "filename": "ggml-small.en-q5_1.bin",
        "sha256": "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30",
        "bytes": 190098681,
    },
}

# The only sentences decide() can produce; any other decision_reason value is
# either hand-edited or free text, both of which the evidence must reject.
DECISION_REASON_PATTERN = (
    r"^(candidate wins on (word error rate|critical-term recall|"
    r"meaning-changing substitutions)|base wins):"
)


class _ModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    filename: Annotated[StrictStr, Field(pattern=MODEL_FILENAME_PATTERN)]
    sha256: Annotated[StrictStr, Field(pattern=SHA256_PATTERN)]
    bytes: Annotated[StrictInt, Field(gt=0)]
    word_error_rate: Annotated[StrictFloat, Field(ge=0.0)]
    substitutions: Annotated[StrictInt, Field(ge=0)]
    deletions: Annotated[StrictInt, Field(ge=0)]
    insertions: Annotated[StrictInt, Field(ge=0)]
    critical_term_recall: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    critical_terms_expected: Annotated[StrictInt, Field(ge=0)]
    critical_terms_found: Annotated[StrictInt, Field(ge=0)]
    audio_seconds: Annotated[StrictFloat, Field(gt=0.0)]
    transcription_seconds: Annotated[StrictFloat, Field(gt=0.0)]
    peak_resident_bytes: Annotated[StrictInt, Field(gt=0)]


class _Models(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    base: _ModelResult
    candidate: _ModelResult


class _ModelBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    script_version: Literal["voice-benchmark-script-v1"]
    runtime_version: Annotated[StrictStr, Field(pattern=VERSION_TOKEN_PATTERN)]
    machine_profile: Annotated[StrictStr, Field(pattern=MACHINE_PROFILE_PATTERN)]
    models: _Models
    # The reading script has exactly six passages; see voice-benchmark-script-v1.md.
    passages: Annotated[StrictInt, Field(ge=1, le=6)]
    chosen_model: Literal["base", "candidate"]
    decision_reason: Annotated[StrictStr, Field(pattern=DECISION_REASON_PATTERN, max_length=240)]


@dataclass(frozen=True, slots=True)
class ModelBenchmarkSummary:
    """Key figures from a structurally valid model benchmark report."""

    chosen_model: str
    decision_reason: str
    base_word_error_rate: float
    candidate_word_error_rate: float
    passages: int


_FORBIDDEN_KEY_MESSAGES = {
    "transcript": "transcript text is forbidden",
    "transcripts": "transcript text is forbidden",
    "text": "transcript text is forbidden",
    "reference_text": "transcript text is forbidden",
    "hypothesis": "transcript text is forbidden",
    "path": "filesystem paths are forbidden",
    "paths": "filesystem paths are forbidden",
    "file_path": "filesystem paths are forbidden",
    "audio_path": "filesystem paths are forbidden",
    "participant": "participant data is forbidden",
    "speaker": "participant data is forbidden",
    "notes": "free-form evidence is forbidden",
    "comment": "free-form evidence is forbidden",
    "comments": "free-form evidence is forbidden",
    "description": "free-form evidence is forbidden",
    "details": "free-form evidence is forbidden",
    "evidence": "free-form evidence is forbidden",
    "message": "free-form evidence is forbidden",
}
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _scan_for_private_data(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if normalized in _FORBIDDEN_KEY_MESSAGES:
                raise ModelBenchmarkError(_FORBIDDEN_KEY_MESSAGES[normalized])
            _scan_for_private_data(child)
        return
    if isinstance(value, list):
        for child in value:
            _scan_for_private_data(child)
        return
    if not isinstance(value, str):
        return
    if value.startswith(("/", "file:/")) or _ABSOLUTE_WINDOWS_PATH.match(value):
        raise ModelBenchmarkError("absolute paths are forbidden")


def _validate_model_pins(report: _ModelBenchmarkReport) -> None:
    for key in MODEL_KEYS:
        result = getattr(report.models, key)
        expected = _EXPECTED_MODEL_PINS[key]
        actual = (result.filename, result.sha256, result.bytes)
        if actual != (expected["filename"], expected["sha256"], expected["bytes"]):
            raise ModelBenchmarkError(f"{key} model does not match its pinned artifact")


def _validate_term_counts(report: _ModelBenchmarkReport) -> None:
    for key in MODEL_KEYS:
        result = getattr(report.models, key)
        if result.critical_terms_found > result.critical_terms_expected:
            raise ModelBenchmarkError(f"{key} model found more critical terms than were expected")


def _validate_decision(report: _ModelBenchmarkReport) -> None:
    expected_chosen, expected_reason = decide(
        report.models.base.model_dump(), report.models.candidate.model_dump()
    )
    if (report.chosen_model, report.decision_reason) != (expected_chosen, expected_reason):
        raise ModelBenchmarkError(
            "chosen_model and decision_reason do not match the recomputed decision"
        )


def validate_report(payload: object) -> ModelBenchmarkSummary:
    """Validate the committed benchmark report as both a schema gate and a privacy gate."""
    _scan_for_private_data(payload)
    try:
        report = _ModelBenchmarkReport.model_validate(payload, strict=True)
    except PydanticValidationError as exc:
        raise ModelBenchmarkError(str(exc)) from exc

    _validate_model_pins(report)
    _validate_term_counts(report)
    _validate_decision(report)

    return ModelBenchmarkSummary(
        chosen_model=report.chosen_model,
        decision_reason=report.decision_reason,
        base_word_error_rate=report.models.base.word_error_rate,
        candidate_word_error_rate=report.models.candidate.word_error_rate,
        passages=report.passages,
    )


# --- build_report_from_runs: aggregate the runner's per-file JSON --------

# Matches "## Passage 1 - steady technical explanation" and captures the
# number so a result file "passage-1.json" (scripts/dev/prepare_benchmark_audio.sh
# names canonical audio after the source recording, e.g. "passage-1.m4a")
# finds the text it was actually read from.
_PASSAGE_HEADING = re.compile(r"^## Passage (\d+)\b.*$", re.MULTILINE)
# Stage directions such as "[Pause for three seconds.]" tell the reader what
# to do; they are never spoken, so they must not count as reference words.
_STAGE_DIRECTION = re.compile(r"\[[^\]]*\]")

_PER_FILE_RESULT_KEYS = (
    "transcript",
    "audio_seconds",
    "transcription_seconds",
    "peak_resident_bytes",
    "model_filename",
    "model_sha256",
)


def _reference_passages() -> dict[str, str]:
    """Split the reading script into its numbered passages, keyed like the
    canonical audio files it is recorded as ("passage-1", ...), with
    bracketed stage directions removed."""
    text = READING_SCRIPT_PATH.read_text(encoding="utf-8")
    headings = list(_PASSAGE_HEADING.finditer(text))
    passages: dict[str, str] = {}
    for index, match in enumerate(headings):
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = _STAGE_DIRECTION.sub(" ", text[start:end])
        passages[f"passage-{match.group(1)}"] = body.strip()
    return passages


def _load_passage_result(path: Path) -> dict[str, object]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ModelBenchmarkError(f"{path}: benchmark result must be a JSON object")
    missing = [key for key in _PER_FILE_RESULT_KEYS if key not in payload]
    if missing:
        raise ModelBenchmarkError(f"{path}: missing {missing}")
    return payload


def _aggregate_model_results(
    directory: Path, model_key: str
) -> tuple[dict[str, object], frozenset[str]]:
    """Score and sum every passage result in `directory` into one model
    entry for build_report, and return which passages it covered."""
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ModelBenchmarkError(f"no benchmark results found in {directory}")

    reference_passages = _reference_passages()
    expected_pin = _EXPECTED_MODEL_PINS[model_key]

    total_reference_words = 0
    substitutions = deletions = insertions = 0
    critical_terms_expected = critical_terms_found = 0
    audio_seconds = transcription_seconds = 0.0
    peak_resident_bytes = 0
    passages: set[str] = set()

    for path in paths:
        passage = path.stem
        reference_text = reference_passages.get(passage)
        if reference_text is None:
            raise ModelBenchmarkError(f"{path}: no reference text for passage '{passage}'")

        result = _load_passage_result(path)
        pin = (result["model_filename"], result["model_sha256"])
        if pin != (expected_pin["filename"], expected_pin["sha256"]):
            raise ModelBenchmarkError(f"{path}: model pin does not match the {model_key} artifact")

        scored = score_run(reference_text, str(result["transcript"]))
        total_reference_words += len(normalise(reference_text))
        substitutions += int(scored["substitutions"])
        deletions += int(scored["deletions"])
        insertions += int(scored["insertions"])
        critical_terms_expected += int(scored["critical_terms_expected"])
        critical_terms_found += int(scored["critical_terms_found"])
        audio_seconds += float(result["audio_seconds"])
        transcription_seconds += float(result["transcription_seconds"])
        peak_resident_bytes = max(peak_resident_bytes, int(result["peak_resident_bytes"]))
        passages.add(passage)

    if total_reference_words == 0:
        raise ModelBenchmarkError(f"{directory}: reference text is empty")

    model_result = {
        "filename": expected_pin["filename"],
        "sha256": expected_pin["sha256"],
        "bytes": expected_pin["bytes"],
        "word_error_rate": (substitutions + deletions + insertions) / total_reference_words,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "critical_term_recall": (
            1.0 if critical_terms_expected == 0 else critical_terms_found / critical_terms_expected
        ),
        "critical_terms_expected": critical_terms_expected,
        "critical_terms_found": critical_terms_found,
        "audio_seconds": audio_seconds,
        "transcription_seconds": transcription_seconds,
        "peak_resident_bytes": peak_resident_bytes,
    }
    return model_result, frozenset(passages)


def build_report_from_runs(
    results_dir: Path, *, script_version: str, runtime_version: str, machine_profile: str
) -> dict[str, object]:
    """Aggregate scripts/dev/benchmark_whisper_models.sh's per-passage JSON
    (results_dir/base/*.json, results_dir/candidate/*.json) into the
    committed report shape via build_report: sum audio seconds,
    transcription seconds, edit counts, and critical-term counts across
    passages; take the maximum peak resident bytes.
    """
    models: dict[str, dict[str, object]] = {}
    passage_sets: dict[str, frozenset[str]] = {}
    for key in MODEL_KEYS:
        model_dir = results_dir / key
        if not model_dir.is_dir():
            raise ModelBenchmarkError(f"missing benchmark results directory: {model_dir}")
        models[key], passage_sets[key] = _aggregate_model_results(model_dir, key)

    if passage_sets["base"] != passage_sets["candidate"]:
        raise ModelBenchmarkError("base and candidate results do not cover the same passages")

    return build_report(
        script_version=script_version,
        runtime_version=runtime_version,
        machine_profile=machine_profile,
        passages=len(passage_sets["base"]),
        models=models,
    )


def _runtime_version() -> str:
    """The whisper.cpp release pin, read from the manifest so it is never
    duplicated (config/speech-models.yaml is the single source of truth)."""
    manifest = yaml.safe_load(SPEECH_MODELS_MANIFEST_PATH.read_text(encoding="utf-8"))
    return str(manifest["artifacts"]["whisper_framework"]["version"])


def _machine_profile() -> str:
    """A machine_profile token derived only from hardware/OS facts (never a
    hostname, which could carry the owner's name into a committed report)."""
    machine = platform.machine().lower() or "unknown"
    macos_version = platform.mac_ver()[0] or "0.0"
    version_token = "-".join(macos_version.split(".")[:2])
    memory_gib = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3))
    return f"{machine}-macos-{version_token}-{memory_gib}gib"


# --- CLI -----------------------------------------------------------------


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelBenchmarkError(f"cannot read model benchmark report: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--build",
        action="store_true",
        help=(
            "aggregate apps/macos/PrivateAudio/benchmark/{base,candidate}/*.json "
            "into REPORT instead of validating an existing REPORT"
        ),
    )
    args = parser.parse_args()
    try:
        if args.build:
            report = build_report_from_runs(
                BENCHMARK_RESULTS_DIR,
                script_version=READING_SCRIPT_VERSION,
                runtime_version=_runtime_version(),
                machine_profile=_machine_profile(),
            )
            validate_report(report)  # never write a report that would fail its own gate
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            summary = {"wrote": str(args.report), "chosen_model": report["chosen_model"]}
            print(json.dumps(summary, sort_keys=True))
            return
        summary = validate_report(_load_json(args.report))
    except ModelBenchmarkError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(asdict(summary), sort_keys=True))


if __name__ == "__main__":
    main()
