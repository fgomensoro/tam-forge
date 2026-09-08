"""Contract tests for scoring the base.en/small.en benchmark and its evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import check_model_benchmark
from scripts.ci.check_model_benchmark import (
    CRITICAL_TERMS,
    WORD_ERROR_RATE_MARGIN,
    ModelBenchmarkError,
    build_report,
    build_report_from_runs,
    critical_term_recall,
    decide,
    normalise,
    score_run,
    validate_report,
    word_error_rate,
)
from scripts.ci.check_model_benchmark import _reference_passages as _read_reference_passages

BASE_FILENAME = "ggml-base.en-q5_1.bin"
BASE_SHA256 = "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f"
BASE_BYTES = 59721011
CANDIDATE_FILENAME = "ggml-small.en-q5_1.bin"
CANDIDATE_SHA256 = "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30"
CANDIDATE_BYTES = 190098681

# Read straight from the reading script (via the module's own parser) rather
# than retyped here, so a fixture can never silently drift from the real
# text the runner would actually score against.
_REFERENCE_PASSAGES = _read_reference_passages()
PASSAGE_1_TEXT = _REFERENCE_PASSAGES["passage-1"]
PASSAGE_2_TEXT = _REFERENCE_PASSAGES["passage-2"]


# --- normalise ---------------------------------------------------------------


def test_normalise_strips_punctuation_lowercases_and_spells_a_teen_digit() -> None:
    assert normalise("The TAM was 12% — really!") == [
        "the",
        "tam",
        "was",
        "twelve",
        "really",
    ]


def test_normalise_spells_a_compound_number_as_two_words() -> None:
    # "35" has no single English word, so it must split into two tokens the
    # same way the reading script spells it out ("thirty five percent").
    assert normalise("35% churn") == ["thirty", "five", "churn"]


# --- word_error_rate -----------------------------------------------------


def test_word_error_rate_identical_lists_have_no_edits() -> None:
    words = ["the", "cat", "sat", "on", "the", "mat"]

    rate, substitutions, deletions, insertions = word_error_rate(words, list(words))

    assert (rate, substitutions, deletions, insertions) == (0.0, 0, 0, 0)


def test_word_error_rate_counts_one_substitution_in_five_words() -> None:
    reference = ["one", "two", "three", "four", "five"]
    hypothesis = ["one", "two", "zero", "four", "five"]

    rate, substitutions, deletions, insertions = word_error_rate(reference, hypothesis)

    assert (rate, substitutions, deletions, insertions) == (0.2, 1, 0, 0)


def test_word_error_rate_counts_a_deletion_and_an_insertion_separately() -> None:
    # Hand-computed via the Levenshtein DP table (not against the implementation):
    # reference "a b c" vs hypothesis "b c d" costs 2 - delete leading "a",
    # match "b" and "c", insert trailing "d" - never as a pair of substitutions,
    # because two substitutions would cost 3 (worse) so the optimum never picks it.
    reference = ["a", "b", "c"]
    hypothesis = ["b", "c", "d"]

    rate, substitutions, deletions, insertions = word_error_rate(reference, hypothesis)

    assert substitutions == 0
    assert deletions == 1
    assert insertions == 1
    assert rate == pytest.approx(2 / 3)


def test_word_error_rate_empty_hypothesis_against_five_words_is_total_loss() -> None:
    reference = ["one", "two", "three", "four", "five"]

    rate, substitutions, deletions, insertions = word_error_rate(reference, [])

    assert (rate, substitutions, deletions, insertions) == (1.0, 0, 5, 0)


def test_word_error_rate_rejects_an_empty_reference() -> None:
    with pytest.raises(ValueError, match="reference"):
        word_error_rate([], ["anything"])


# --- critical_term_recall -----------------------------------------------


def test_critical_term_recall_requires_adjacent_phrase_words_in_order() -> None:
    reference = normalise("The total addressable market is the full revenue opportunity available.")
    terms = ("total addressable market",)

    found_recall, found_count, found_expected = critical_term_recall(
        reference, normalise("Our total addressable market is huge."), terms
    )
    missed_recall, missed_count, missed_expected = critical_term_recall(
        reference, normalise("Our total market is huge."), terms
    )

    assert (found_expected, found_count, found_recall) == (1, 1, 1.0)
    assert (missed_expected, missed_count, missed_recall) == (1, 0, 0.0)


def test_critical_term_recall_is_vacuous_when_no_term_is_expected() -> None:
    reference = normalise("Nothing tracked here.")

    recall, found, expected = critical_term_recall(
        reference, normalise("Nothing tracked here."), ("churn",)
    )

    assert (recall, found, expected) == (1.0, 0, 0)


# --- CRITICAL_TERMS -------------------------------------------------------


def test_critical_terms_parses_the_reading_script() -> None:
    assert "total addressable market" in CRITICAL_TERMS
    assert "churn" in CRITICAL_TERMS
    assert "attach rate" in CRITICAL_TERMS
    assert len(CRITICAL_TERMS) == 20


# --- score_run -------------------------------------------------------------


def test_score_run_combines_word_error_rate_and_critical_term_recall() -> None:
    # Hand-computed: hypothesis drops "addressable" - one deletion out of six
    # reference words - and therefore misses the one critical term this
    # sentence contains.
    scored = score_run("The total addressable market is real.", "The total market is real.")

    assert scored["substitutions"] == 0
    assert scored["deletions"] == 1
    assert scored["insertions"] == 0
    assert scored["word_error_rate"] == pytest.approx(1 / 6)
    assert scored["critical_terms_expected"] == 1
    assert scored["critical_terms_found"] == 0
    assert scored["critical_term_recall"] == 0.0


# --- decide ------------------------------------------------------------------


def _figures(**overrides: object) -> dict[str, object]:
    figures: dict[str, object] = {
        "word_error_rate": 0.30,
        "critical_terms_found": 18,
        "substitutions": 10,
    }
    figures.update(overrides)
    return figures


def test_decide_keeps_base_on_an_exact_tie() -> None:
    chosen, reason = decide(_figures(), _figures())

    assert chosen == "base"
    assert reason.startswith("base wins:")


def test_decide_keeps_base_when_the_candidate_gain_is_under_the_margin() -> None:
    base = _figures(word_error_rate=0.30)
    candidate = _figures(word_error_rate=0.30 - (WORD_ERROR_RATE_MARGIN - 0.01))

    chosen, reason = decide(base, candidate)

    assert chosen == "base"
    assert reason.startswith("base wins:")


def test_decide_chooses_the_candidate_at_exactly_the_margin() -> None:
    base = _figures(word_error_rate=0.30)
    candidate = _figures(word_error_rate=0.30 - WORD_ERROR_RATE_MARGIN)

    chosen, reason = decide(base, candidate)

    assert chosen == "candidate"
    assert "word error rate" in reason


def test_decide_chooses_the_candidate_when_it_recovers_a_missed_critical_term() -> None:
    base = _figures(critical_terms_found=17)
    candidate = _figures(critical_terms_found=18)

    chosen, reason = decide(base, candidate)

    assert chosen == "candidate"
    assert "critical-term recall" in reason


def test_decide_chooses_the_candidate_when_it_makes_fewer_substitutions() -> None:
    base = _figures(substitutions=10)
    candidate = _figures(substitutions=9)

    chosen, reason = decide(base, candidate)

    assert chosen == "candidate"
    assert "meaning-changing substitutions" in reason


# --- build_report / validate_report fixtures --------------------------------


def _model_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "filename": BASE_FILENAME,
        "sha256": BASE_SHA256,
        "bytes": BASE_BYTES,
        "word_error_rate": 0.081,
        "substitutions": 40,
        "deletions": 12,
        "insertions": 8,
        "critical_term_recall": 0.95,
        "critical_terms_expected": 20,
        "critical_terms_found": 19,
        "audio_seconds": 360.0,
        "transcription_seconds": 42.5,
        "peak_resident_bytes": 210_000_000,
    }
    result.update(overrides)
    return result


def _candidate_result(**overrides: object) -> dict[str, object]:
    result = _model_result(
        filename=CANDIDATE_FILENAME,
        sha256=CANDIDATE_SHA256,
        bytes=CANDIDATE_BYTES,
        word_error_rate=0.065,
        critical_terms_found=20,
        peak_resident_bytes=540_000_000,
    )
    result.update(overrides)
    return result


def _payload(**overrides: object) -> dict[str, object]:
    base = _model_result()
    candidate = _candidate_result()
    chosen, reason = decide(base, candidate)
    payload: dict[str, object] = {
        "schema_version": 1,
        "script_version": "voice-benchmark-script-v1",
        "runtime_version": "b4938",
        "machine_profile": "macbook-air-apple-m5-24gb",
        "models": {"base": base, "candidate": candidate},
        "passages": 6,
        "chosen_model": chosen,
        "decision_reason": reason,
    }
    payload.update(overrides)
    return payload


# --- build_report --------------------------------------------------------


def test_build_report_assembles_the_contract_and_names_the_winning_rule() -> None:
    base = _model_result(word_error_rate=0.30, critical_terms_found=18, substitutions=10)
    candidate = _candidate_result(
        word_error_rate=0.27,  # clears the 0.02 margin by exactly 0.01
        critical_terms_found=18,
        substitutions=10,
    )

    report = build_report(
        script_version="voice-benchmark-script-v1",
        runtime_version="b4938",
        machine_profile="macbook-air-apple-m5-24gb",
        passages=6,
        models={"base": base, "candidate": candidate},
    )

    assert report["schema_version"] == 1
    assert report["chosen_model"] == "candidate"
    assert "word error rate" in report["decision_reason"]

    summary = validate_report(report)
    assert summary.passages == 6
    assert summary.chosen_model == "candidate"


def test_build_report_requires_exactly_the_base_and_candidate_keys() -> None:
    with pytest.raises(ModelBenchmarkError):
        build_report(
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
            passages=6,
            models={"base": _model_result()},
        )


# --- validate_report: accepts a well-formed report --------------------------


def test_validate_report_accepts_a_well_formed_report() -> None:
    summary = validate_report(_payload())

    assert summary.passages == 6
    assert summary.base_word_error_rate == 0.081
    assert summary.candidate_word_error_rate == 0.065


# --- validate_report: unexpected keys ----------------------------------


def test_validate_report_rejects_an_unknown_top_level_key() -> None:
    payload = _payload()
    payload["operator"] = "synthetic-user"

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


def test_validate_report_rejects_an_unknown_key_inside_a_model_result() -> None:
    payload = _payload()
    payload["models"]["base"]["notes"] = "sounded fine"

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


# --- validate_report: privacy gate --------------------------------------


def test_validate_report_rejects_a_transcript_key() -> None:
    payload = _payload()
    payload["models"]["base"]["transcript"] = "synthetic transcript text"

    with pytest.raises(ModelBenchmarkError, match="transcript"):
        validate_report(payload)


def test_validate_report_rejects_a_filesystem_path() -> None:
    payload = _payload()
    payload["models"]["base"]["filename"] = "/Users/synthetic/ggml-base.en-q5_1.bin"

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


def test_validate_report_rejects_transcript_like_free_text_in_decision_reason() -> None:
    payload = _payload()
    payload["decision_reason"] = (
        "The total addressable market is the full revenue opportunity available."
    )

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


# --- validate_report: schema gate ---------------------------------------


@pytest.mark.parametrize(
    "bad_sha256",
    [
        "A" * 64,  # uppercase is not accepted
        "a" * 63,  # too short
        ("g" * 63) + "a",  # non-hex character
        "a" * 65,  # too long
    ],
)
def test_validate_report_rejects_a_sha256_that_is_not_64_lowercase_hex(
    bad_sha256: str,
) -> None:
    payload = _payload()
    payload["models"]["base"]["sha256"] = bad_sha256

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


def test_validate_report_rejects_a_chosen_model_outside_the_two_model_keys() -> None:
    payload = _payload()
    payload["chosen_model"] = "small_en"

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


def test_validate_report_rejects_more_critical_terms_found_than_expected() -> None:
    payload = _payload()
    payload["models"]["base"]["critical_terms_found"] = 25
    payload["models"]["base"]["critical_terms_expected"] = 20

    with pytest.raises(ModelBenchmarkError):
        validate_report(payload)


def test_validate_report_rejects_a_model_that_does_not_match_its_pinned_artifact() -> None:
    payload = _payload()
    payload["models"]["base"]["bytes"] = 1

    with pytest.raises(ModelBenchmarkError, match="pin"):
        validate_report(payload)


def test_validate_report_rejects_a_decision_inconsistent_with_its_own_figures() -> None:
    # The report claims base won, but candidate's figures actually clear the
    # word-error-rate margin - the recomputed decision must not agree.
    payload = _payload(chosen_model="base", decision_reason="base wins: synthetic override.")
    payload["models"]["candidate"]["word_error_rate"] = 0.01

    with pytest.raises(ModelBenchmarkError, match="decision"):
        validate_report(payload)


# --- CLI ---------------------------------------------------------------------


def test_cli_prints_a_machine_readable_summary_for_a_valid_report(tmp_path: Path) -> None:
    payload = _payload()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/ci/check_model_benchmark.py", str(report_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    printed = json.loads(completed.stdout)
    assert printed["chosen_model"] == payload["chosen_model"]
    assert printed["passages"] == 6


def test_cli_rejects_an_invalid_report_without_a_traceback(tmp_path: Path) -> None:
    payload = _payload()
    payload["chosen_model"] = "small_en"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/ci/check_model_benchmark.py", str(report_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr


# --- build_report_from_runs: aggregating the runner's per-file JSON --------
#
# Never real audio: every fixture here is a hand-built JSON file the Swift
# runner's output shape describes, written under tmp_path.


def _passage_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "transcript": PASSAGE_1_TEXT,
        "audio_seconds": 30.0,
        "transcription_seconds": 2.0,
        "peak_resident_bytes": 200_000_000,
        "model_filename": BASE_FILENAME,
        "model_sha256": BASE_SHA256,
    }
    payload.update(overrides)
    return payload


def _write_passage(directory: Path, stem: str, **overrides: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}.json").write_text(
        json.dumps(_passage_payload(**overrides)), encoding="utf-8"
    )


def _write_base_passage(results_dir: Path, stem: str, **overrides: object) -> None:
    overrides.setdefault("model_filename", BASE_FILENAME)
    overrides.setdefault("model_sha256", BASE_SHA256)
    _write_passage(results_dir / "base", stem, **overrides)


def _write_candidate_passage(results_dir: Path, stem: str, **overrides: object) -> None:
    overrides.setdefault("model_filename", CANDIDATE_FILENAME)
    overrides.setdefault("model_sha256", CANDIDATE_SHA256)
    _write_passage(results_dir / "candidate", stem, **overrides)


def test_build_report_from_runs_sums_and_takes_the_maximum_across_passages(
    tmp_path: Path,
) -> None:
    # base's passage-2 drops exactly one word ("fourteen" from "under
    # fourteen months") - a single deletion, no critical term touched -
    # while its passage-1 and candidate's both passages match verbatim.
    base_passage_2 = PASSAGE_2_TEXT.replace("under fourteen months", "under months")
    assert base_passage_2 != PASSAGE_2_TEXT  # the substitution actually landed

    _write_base_passage(
        tmp_path, "passage-1",
        transcript=PASSAGE_1_TEXT, audio_seconds=30.0,
        transcription_seconds=2.0, peak_resident_bytes=200_000_000,
    )
    _write_base_passage(
        tmp_path, "passage-2",
        transcript=base_passage_2, audio_seconds=25.0,
        transcription_seconds=1.5, peak_resident_bytes=210_000_000,
    )
    _write_candidate_passage(
        tmp_path, "passage-1",
        transcript=PASSAGE_1_TEXT, audio_seconds=30.0,
        transcription_seconds=3.0, peak_resident_bytes=500_000_000,
    )
    _write_candidate_passage(
        tmp_path, "passage-2",
        transcript=PASSAGE_2_TEXT, audio_seconds=25.0,
        transcription_seconds=2.8, peak_resident_bytes=480_000_000,
    )

    report = build_report_from_runs(
        tmp_path,
        script_version="voice-benchmark-script-v1",
        runtime_version="b4938",
        machine_profile="macbook-air-apple-m5-24gb",
    )

    assert report["passages"] == 2
    base = report["models"]["base"]
    candidate = report["models"]["candidate"]

    total_reference_words = len(normalise(PASSAGE_1_TEXT)) + len(normalise(PASSAGE_2_TEXT))
    assert base["substitutions"] == 0
    assert base["deletions"] == 1
    assert base["insertions"] == 0
    assert base["word_error_rate"] == pytest.approx(1 / total_reference_words)
    assert base["audio_seconds"] == pytest.approx(55.0)
    assert base["transcription_seconds"] == pytest.approx(3.5)
    assert base["peak_resident_bytes"] == 210_000_000  # max(200_000_000, 210_000_000)
    assert base["critical_term_recall"] == 1.0  # the dropped word is not a critical term

    assert candidate["substitutions"] == 0
    assert candidate["deletions"] == 0
    assert candidate["insertions"] == 0
    assert candidate["word_error_rate"] == 0.0
    assert candidate["audio_seconds"] == pytest.approx(55.0)
    assert candidate["transcription_seconds"] == pytest.approx(5.8)
    assert candidate["peak_resident_bytes"] == 500_000_000  # max(500_000_000, 480_000_000)
    assert candidate["critical_term_recall"] == 1.0

    # A single dropped filler word is well inside measurement noise, so the
    # existing decision rule keeps base - proves the aggregate wires cleanly
    # into build_report/decide, not just into raw sums.
    assert report["chosen_model"] == "base"
    summary = validate_report(report)
    assert summary.passages == 2


def test_build_report_from_runs_rejects_a_result_missing_a_required_key(
    tmp_path: Path,
) -> None:
    _write_candidate_passage(tmp_path, "passage-1")
    directory = tmp_path / "base"
    directory.mkdir(parents=True)
    incomplete = _passage_payload()
    del incomplete["peak_resident_bytes"]
    (directory / "passage-1.json").write_text(json.dumps(incomplete), encoding="utf-8")

    with pytest.raises(ModelBenchmarkError, match="peak_resident_bytes"):
        build_report_from_runs(
            tmp_path,
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
        )


def test_build_report_from_runs_rejects_a_model_pin_that_does_not_match_its_directory(
    tmp_path: Path,
) -> None:
    _write_candidate_passage(tmp_path, "passage-1")
    # A passage lands in "base/" but actually carries the candidate's pin -
    # the kind of mistake a mixed-up output directory would produce.
    _write_passage(
        tmp_path / "base", "passage-1",
        model_filename=CANDIDATE_FILENAME, model_sha256=CANDIDATE_SHA256,
    )

    with pytest.raises(ModelBenchmarkError, match="pin"):
        build_report_from_runs(
            tmp_path,
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
        )


def test_build_report_from_runs_rejects_a_passage_with_no_reference_text(
    tmp_path: Path,
) -> None:
    _write_candidate_passage(tmp_path, "passage-99")
    _write_base_passage(tmp_path, "passage-99")

    with pytest.raises(ModelBenchmarkError, match="passage-99"):
        build_report_from_runs(
            tmp_path,
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
        )


def test_build_report_from_runs_rejects_passages_that_differ_between_models(
    tmp_path: Path,
) -> None:
    _write_base_passage(tmp_path, "passage-1")
    _write_base_passage(tmp_path, "passage-2")
    _write_candidate_passage(tmp_path, "passage-1")

    with pytest.raises(ModelBenchmarkError, match="same passages"):
        build_report_from_runs(
            tmp_path,
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
        )


def test_build_report_from_runs_rejects_a_missing_model_directory(tmp_path: Path) -> None:
    _write_base_passage(tmp_path, "passage-1")
    # No "candidate" directory at all.

    with pytest.raises(ModelBenchmarkError, match="candidate"):
        build_report_from_runs(
            tmp_path,
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
        )


def test_build_report_from_runs_rejects_an_empty_model_directory(tmp_path: Path) -> None:
    _write_base_passage(tmp_path, "passage-1")
    (tmp_path / "candidate").mkdir(parents=True)  # present but empty

    with pytest.raises(ModelBenchmarkError, match="no benchmark results"):
        build_report_from_runs(
            tmp_path,
            script_version="voice-benchmark-script-v1",
            runtime_version="b4938",
            machine_profile="macbook-air-apple-m5-24gb",
        )


# --- CLI: --build ------------------------------------------------------------


def test_cli_build_flag_aggregates_and_writes_a_report_that_then_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results_dir = tmp_path / "results"
    _write_base_passage(results_dir, "passage-1", transcript=PASSAGE_1_TEXT)
    _write_candidate_passage(
        results_dir, "passage-1", transcript=PASSAGE_1_TEXT, peak_resident_bytes=400_000_000
    )
    report_path = tmp_path / "out" / "model-benchmark-v1.json"  # parent must be created for us

    monkeypatch.setattr(check_model_benchmark, "BENCHMARK_RESULTS_DIR", results_dir)
    monkeypatch.setattr(sys, "argv", ["check_model_benchmark.py", "--build", str(report_path)])

    check_model_benchmark.main()

    written = json.loads(report_path.read_text(encoding="utf-8"))
    summary = validate_report(written)
    assert summary.passages == 1

    printed = json.loads(capsys.readouterr().out)
    assert printed["wrote"] == str(report_path)
    assert printed["chosen_model"] == written["chosen_model"]
