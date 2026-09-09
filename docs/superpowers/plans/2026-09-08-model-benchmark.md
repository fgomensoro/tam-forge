# Base.en versus Small.en Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure `base.en` against `small.en` on the owner's recorded voice and record privacy-safe evidence for which model TAM Forge ships.

**Architecture:** The reading script is the reference transcript, so scoring needs no manual transcription. A shell script converts QuickTime recordings to canonical audio; a standalone Swift runner compiled against the production Speech sources transcribes with each model into a gitignored private directory; a Python module scores those local results and emits an aggregate-only committed report that CI validates.

**Tech Stack:** Python 3.14 + pytest, Swift 6 compiled with raw `swiftc` against `apps/macos/Vendor/whisper.xcframework`, `afconvert` and QuickTime Player from macOS.

**Spec:** `docs/superpowers/specs/2026-09-08-model-benchmark-design.md`

## Global Constraints

- The `small.en` pin, verbatim: `ggml-small.en-q5_1.bin`, `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q5_1.bin`, 190098681 bytes, sha256 `bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30`, MIT. Same `q5_1` quantization as the existing `base.en` pin, so the comparison isolates model size.
- The reference text is `docs/project/voice-benchmark-script-v1.md`, version string `voice-benchmark-script-v1`.
- Audio, per-file transcripts, and any file names live only under `apps/macos/PrivateAudio/` (already gitignored). The committed report carries counts, rates, durations, byte figures, hashes, and version strings, and nothing else.
- Never run `xcodebuild`. The Swift runner is built with raw `swiftc`, which is proven to work: `swiftc -parse-as-library -swift-version 6 -target arm64-apple-macosx15.0 -sdk "$(xcrun --show-sdk-path)" -F apps/macos/Vendor/whisper.xcframework/macos-arm64_x86_64 -framework whisper -o <out> <runner>.swift apps/macos/TAMForge/Features/Speech/{ASRAudioDerivation,AudioQualityObservations,SpeechTranscription,SpeechModelCatalog,WhisperTranscriber}.swift apps/macos/TAMForge/Features/Recording/RecordingModels.swift`, run with `DYLD_FRAMEWORK_PATH=apps/macos/Vendor/whisper.xcframework/macos-arm64_x86_64`.
- `WhisperTranscriber(catalog:runtimeVersion:)` resolves its model through `SpeechModelCatalog`, whose `transcriptionModelFilename` is fixed to the base model. The runner therefore selects a model by pointing a `SpeechModelCatalog` at a directory that contains only the model under test; do not change production code to make the benchmark easier.
- Do not touch `apps/backend/`, `packages/protocol/`, `apps/macos/TAMForge/openapi.yaml`, or `apps/macos/TAMForge.xcodeproj`: another session owns those files right now.
- Commit messages are plain prose ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Pin the second model and prepare audio

**Files:**
- Modify: `config/speech-models.yaml`, `scripts/dev/fetch_whisper_models.sh`, `scripts/ci/tests/test_speech_models_manifest.py`
- Create: `scripts/dev/prepare_benchmark_audio.sh`

**Interfaces:**
- Produces: a `benchmark_model` entry in `config/speech-models.yaml` with the same field set as the existing artifacts, and `scripts/dev/prepare_benchmark_audio.sh` (no arguments) converting every `apps/macos/PrivateAudio/*.m4a` to `apps/macos/PrivateAudio/canonical/<name>.wav` at 48 kHz mono PCM16.

- [ ] **Step 1: Extend the manifest test first**

Add to `scripts/ci/tests/test_speech_models_manifest.py`:

```python
def test_benchmark_model_is_pinned_with_the_same_quantization() -> None:
    artifacts = manifest()["artifacts"]
    assert "benchmark_model" in artifacts
    benchmark = artifacts["benchmark_model"]
    assert benchmark["filename"] == "ggml-small.en-q5_1.bin"
    assert benchmark["bytes"] == 190098681
    assert benchmark["sha256"] == (
        "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30"
    )
    # Same quantization as the shipped model, so the comparison isolates size.
    assert benchmark["version"] == artifacts["transcription_model"]["version"]
    assert benchmark["installs_to"] == artifacts["transcription_model"]["installs_to"]
```

Update `REQUIRED_KEYS` in that file to include `benchmark_model`.

Run: `uv run pytest scripts/ci/tests/test_speech_models_manifest.py -q`
Expected: FAIL because the entry does not exist.

- [ ] **Step 2: Add the pin and fetch it**

Add the `benchmark_model` entry to `config/speech-models.yaml` using the Global Constraints values, with `consumed_by: model benchmark (#43)`. Extend `scripts/dev/fetch_whisper_models.sh` so it installs every model artifact in the manifest rather than a hardcoded pair: iterate the artifacts whose `installs_to` is the models directory. Keep the existing verification, idempotence, and staging behaviour.

Run: `uv run pytest scripts/ci/tests/test_speech_models_manifest.py -q` (PASS) and `scripts/dev/fetch_whisper_models.sh` (installs the new model, then re-run for idempotence).

- [ ] **Step 3: Write the audio preparation script**

`scripts/dev/prepare_benchmark_audio.sh`: `#!/bin/zsh`, `set -euo pipefail`, `cd "$(dirname "$0")/../.."`. For every `apps/macos/PrivateAudio/*.m4a`, run `afconvert -f WAVE -d LEI16@48000 -c 1 "<input>" "apps/macos/PrivateAudio/canonical/<name>.wav"`, creating the directory first. Skip a file whose canonical output already exists and is newer than its input. Print one line per converted file and a final count. Exit 2 with a clear message when `apps/macos/PrivateAudio` holds no `.m4a` file, naming the reading script so the owner knows what to record.

Run: `zsh -n scripts/dev/prepare_benchmark_audio.sh`, then run it for real to confirm the friendly failure with no recordings present.

- [ ] **Step 4: Commit**

```bash
git add config/speech-models.yaml scripts/dev/fetch_whisper_models.sh scripts/dev/prepare_benchmark_audio.sh scripts/ci/tests/test_speech_models_manifest.py
git commit -m "feat(speech): pin the benchmark model and prepare its audio"
```

### Task 2: Scoring and the report contract

**Files:**
- Create: `scripts/ci/check_model_benchmark.py`, `scripts/ci/tests/test_check_model_benchmark.py`

**Interfaces:**
- Produces:
  ```python
  def normalise(text: str) -> list[str]: ...          # lowercase, strip punctuation, collapse whitespace, spell digits
  def word_error_rate(reference: list[str], hypothesis: list[str]) -> tuple[float, int, int, int]:
      """Returns (rate, substitutions, deletions, insertions) from Levenshtein alignment."""
  def critical_term_recall(reference: list[str], hypothesis: list[str], terms: tuple[str, ...]) -> tuple[float, int, int]:
      """Returns (recall, found, expected) counting multi-word terms as phrases."""
  CRITICAL_TERMS: tuple[str, ...]                      # parsed from the reading script's Critical terms line
  def score_run(reference_text: str, transcript: str) -> dict[str, object]: ...
  def build_report(...) -> dict[str, object]: ...
  def validate_report(payload: object) -> ModelBenchmarkSummary: ...
  def decide(base: dict[str, object], candidate: dict[str, object]) -> tuple[str, str]:
      """Returns (chosen_model_key, reason); ties keep base per the spec."""
  ```
- The committed report shape, exactly these keys: `schema_version` (1), `script_version`, `runtime_version`, `machine_profile`, `models` (a mapping of `base`/`candidate`, each with `filename`, `sha256`, `bytes`, `word_error_rate`, `substitutions`, `deletions`, `insertions`, `critical_term_recall`, `critical_terms_expected`, `critical_terms_found`, `audio_seconds`, `transcription_seconds`, `peak_resident_bytes`), `passages` (an integer count), `chosen_model`, `decision_reason`.

- [ ] **Step 1: Write the failing tests**

Cover with real, hand-computed assertions:
- `normalise("The TAM was 12% — really!")` drops punctuation, lowercases, and spells `12` as `twelve`, so digits never count as errors against a spelled-out reference.
- `word_error_rate` on hand-worked cases: identical lists give 0.0 with zero edits; one substitution in five words gives 0.2; a deletion and an insertion are counted separately; an empty hypothesis against five reference words gives 1.0.
- `critical_term_recall` finds a multi-word term only when its words appear in order and adjacent, so "total addressable market" is found in a transcript containing it and missed when the transcript says "total market".
- `CRITICAL_TERMS` parses the reading script and contains at least `total addressable market`, `churn`, and `attach rate`.
- `decide` keeps base on a tie, keeps base when the candidate wins by less than the stated margin, and chooses the candidate when it reduces critical-term misses; the returned reason is a sentence naming the deciding measure.
- `validate_report` rejects a payload containing any key not in the contract, any string that looks like a path or a sentence of transcript, a model sha256 that is not 64 lowercase hex, and a `chosen_model` that is not one of the two model keys; it accepts a well-formed report.

Run: `uv run pytest scripts/ci/tests/test_check_model_benchmark.py -q`
Expected: FAIL, module absent.

- [ ] **Step 2: Implement the module**

Write `scripts/ci/check_model_benchmark.py`. Details that matter:
- `normalise` lowercases, replaces every character that is not a letter, digit, or space with a space, spells integers 0-100 with a fixed table so "12" and "twelve" compare equal, and splits on whitespace.
- `word_error_rate` is standard Levenshtein over word lists with backtracking to count substitutions, deletions, and insertions; rate is `(S + D + I) / len(reference)`, and a zero-length reference raises `ValueError`.
- `CRITICAL_TERMS` is parsed at import from `docs/project/voice-benchmark-script-v1.md` by reading the line beginning `**Critical terms**` and splitting the comma-separated list after the colon, normalised the same way as the text.
- The decision margin: the candidate must cut absolute word error rate by at least 2 percentage points, or find at least one critical term the base model missed without losing another, or reduce meaning-changing substitutions. Otherwise base wins. State the margin in a module constant with a comment, and make `decide` return the sentence that names which rule fired.
- A CLI: `python scripts/ci/check_model_benchmark.py REPORT` validates a committed report and prints a machine-readable summary, mirroring `check_recording_verification.py`'s shape.

Run: `uv run pytest scripts/ci/tests/test_check_model_benchmark.py -q` (PASS), `uv run ruff check scripts/ci`.

- [ ] **Step 3: Commit**

```bash
git add scripts/ci/check_model_benchmark.py scripts/ci/tests/test_check_model_benchmark.py
git commit -m "feat(speech): score model benchmarks and gate their evidence"
```

### Task 3: The benchmark runner

**Files:**
- Create: `scripts/dev/benchmark_whisper_models.swift`, `scripts/dev/benchmark_whisper_models.sh`
- Modify: `Makefile`, `README.md`

**Interfaces:**
- Consumes: the canonical WAVs from Task 1, both pinned models, the production Speech sources.
- Produces: `apps/macos/PrivateAudio/benchmark/<model-key>/<passage>.json`, each holding `transcript`, `audio_seconds`, `transcription_seconds`, `peak_resident_bytes`, `model_filename`, `model_sha256`.

- [ ] **Step 1: Write the Swift runner**

`benchmark_whisper_models.swift` takes `<models-dir> <model-filename> <canonical-audio-dir> <output-dir>`. For each `.wav` it reads the 44-byte-header PCM16 payload, feeds it through `ASRAudioDeriver` in one-second chunks exactly as a real recording would, transcribes with `WhisperTranscriber(catalog:)` built from a `SpeechModelCatalog` pointed at a temporary directory containing only the model under test, and writes the JSON above. Measure transcription wall time with `Date()` around the call, and peak resident memory with `mach_task_basic_info` (`MACH_TASK_BASIC_INFO`, field `resident_size_max`). Release the transcriber between files so each model's peak is its own.

- [ ] **Step 2: Write the shell wrapper**

`benchmark_whisper_models.sh`: `set -euo pipefail`, `cd "$(dirname "$0")/../.."`, refuse to run when `apps/macos/Vendor/whisper.xcframework` or the canonical audio directory is missing, naming the script that fixes each case. Build the runner with the exact `swiftc` command from the Global Constraints into a `mktemp -d` (with `trap ... EXIT`), then run it once per model, reading both model filenames from `config/speech-models.yaml`. Print a one-line summary per model.

- [ ] **Step 3: Check and commit**

```bash
zsh -n scripts/dev/benchmark_whisper_models.sh
swiftc -parse scripts/dev/benchmark_whisper_models.swift
git diff --check
git add scripts/dev/benchmark_whisper_models.swift scripts/dev/benchmark_whisper_models.sh Makefile README.md
git commit -m "feat(speech): run both pinned models over the benchmark audio"
```

Add a `whisper-benchmark` Makefile target and a README sentence pointing at the reading script and the private audio directory.

### Task 4: Run the benchmark and record the decision

**Files:**
- Create: `docs/project/model-benchmark-v1.json`
- Modify: `docs/superpowers/specs/2026-09-08-model-benchmark-design.md`, `README.md`
- Comment on issue #43

- [ ] **Step 1: Ask the owner to record**

Point the owner at `docs/project/voice-benchmark-script-v1.md` and wait. Do not synthesise speech as a substitute: a text-to-speech voice would measure the wrong thing and the evidence would be dishonest.

- [ ] **Step 2: Prepare, run, and score**

```bash
scripts/dev/prepare_benchmark_audio.sh
scripts/dev/benchmark_whisper_models.sh
uv run python scripts/ci/check_model_benchmark.py --build docs/project/model-benchmark-v1.json
uv run python scripts/ci/check_model_benchmark.py docs/project/model-benchmark-v1.json
```

- [ ] **Step 3: Record the decision**

Append a "Result" section to the design spec with the chosen model, both models' figures, and the rule that decided it. If `base.en` wins, say so plainly and note that the shipped pin is unchanged. If `small.en` wins, do not change the shipped model in this task: state that the change belongs to its own reviewed commit, because it moves what every future transcript is produced by.

- [ ] **Step 4: Commit and comment**

```bash
git add docs/project/model-benchmark-v1.json docs/superpowers/specs/2026-09-08-model-benchmark-design.md README.md
git commit -m "docs(speech): record the model benchmark result"
gh issue comment 43 --repo fgomensoro/tam-forge --body "Benchmarked base.en against small.en on the owner's recorded voice with the versioned reading script; aggregate-only evidence is in docs/project/model-benchmark-v1.json and the decision rule is recorded in the design spec."
```
