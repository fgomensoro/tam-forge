# Base.en versus Small.en model benchmark (issue #43, E4-I04)

**Date:** 2026-09-08. Implements section 7.2 of the 2026-08-28 redesign spec on the runtime landed by issue #42.

## Goal

Decide which pinned quantized English model TAM Forge ships, using the owner's own voice, and record privacy-safe evidence for the decision. The spec's rule stands: ship `base.en` unless `small.en` materially reduces meaning-changing errors, absolute word error rate, or critical-term misses.

## Scope

In: the `small.en` pin, a reading script, a benchmark runner over both models, scoring with word error rate and critical-term recall, resource observations, and an aggregate-only evidence report.
Out: blinded multi-rater adjudication (#47), pronunciation scoring (#48, #49), transcript persistence (#44), and any change to the shipped runtime beyond the model pin.

## Pinned artifacts

Added to `config/speech-models.yaml` beside the existing entries:

| Artifact | Bytes | SHA-256 |
|---|---|---|
| `ggml-small.en-q5_1.bin` | 190 098 681 | `bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30` |

Both models use the same `q5_1` quantization, so the comparison isolates model size rather than quantization.

## How the audio is produced

The app's spool is encrypted with a key that never leaves the Keychain, and fixture-mode keys are ephemeral, so recorded audio cannot be extracted from it for measurement. Rather than add a recorder, the owner records with QuickTime Player and `scripts/dev/prepare_benchmark_audio.sh` converts each file to canonical 48 kHz mono PCM16 with `afconvert`, both already present on macOS. Audio lands in `apps/macos/PrivateAudio/`, which is already gitignored, and never enters the repository.

The reading script is `docs/project/voice-benchmark-script-v1.md`: versioned, about six minutes, phonetically varied, carrying TAM vocabulary and deliberate pauses, restarts, and fast passages. It contains no employer, customer, or participant data. Its exact text is the reference transcript, so scoring needs no manual transcription.

## Measurement

`scripts/dev/benchmark_whisper_models.sh` compiles a small Swift runner against the production Speech sources and the vendored framework, transcribes every prepared file with each model, and writes per-file results to `apps/macos/PrivateAudio/benchmark/` (gitignored, contains transcript text).

`scripts/ci/check_model_benchmark.py` scores those local results and produces the committed report:

- Word error rate over normalised text: lowercase, punctuation stripped, numbers spelled consistently, computed with Levenshtein distance over word tokens.
- Critical-term recall over a versioned term list drawn from the script's TAM vocabulary; a missed critical term is the error that matters most for this product.
- Meaning-changing error count, counted as substitutions that are not in a versioned list of harmless variants.
- Wall-clock seconds per audio minute and peak resident memory per run.

The same module validates a committed report: schema, aggregate-only fields, no free text, no paths, and the exact model pins it was produced from.

## Evidence and decision

`docs/project/model-benchmark-v1.json` carries only counts, rates, durations, and byte figures, plus the two model SHA-256 values and the script version. It never carries audio, transcripts, or file names.

The decision rule is recorded with the evidence: `small.en` wins only if it reduces critical-term misses or meaning-changing errors beyond measurement noise, or cuts absolute word error rate by a stated margin. A practical tie keeps `base.en`, and the report states the chosen model and why.

## Testing

`scripts/ci/tests/test_check_model_benchmark.py` runs in CI with no models and no audio: it covers the normaliser, the word-error-rate distance on hand-computed cases, critical-term recall, the tie-breaking decision rule, and rejection of a report that carries transcripts, paths, or a model pin that does not match the manifest.
