# ASR audio derivation on the Mac (issue #41, E4-I02)

**Date:** 2026-09-08. **Owner decision:** local transcription runs on the Mac (redesign spec of 2026-08-28, section 7.1), so the 16 kHz derivation is Swift in the native app, not Python in the backend. This supersedes the 2026-08-25 speech plan's Task 14 and the issue's original pytest verification.

## Goal

Produce a versioned, deterministic 16 kHz mono signed PCM16 stream for ASR from one canonical recording track (48 kHz PCM16, microphone mono or system stereo) without changing the originals, while retaining source-track, quality, and conversion lineage.

## Scope

In: the derivation transform, its lineage record, versioned quality observations, and XCTest coverage.
Out: whisper.cpp integration (#42), persisting lineage or transcripts to the backend (#44), VAD, memory scheduling (#51), any disk persistence of derived audio.

## Components (`apps/macos/TAMForge/Features/Speech/`)

- `ASRAudioDerivation.swift`
  - `ASRAudioDeriver`: consumes ordered `RecordingPCMChunk` values of one track plus the track's persisted gaps and yields bounded blocks of `Int16` samples at 16 kHz mono. Stateless between recordings; holds only the FIR history between blocks.
  - `ASRDerivationVersion.current = "tamforge-asr16k-v1"`: fixed (L+R)/2 downmix before rate reduction, linear-phase windowed-sinc low-pass FIR (Kaiser window, cutoff below 8 kHz), integer 3:1 decimation. Pure integer/float arithmetic in Swift; no `AVAudioConverter`, so output bytes do not depend on the macOS version.
  - Gaps and discontinuities in the canonical timeline are zero-filled so output sample `n` corresponds to canonical sample `3n`.
  - `ASRDerivationLineage`: recording ID, track, derivation version, source sample rate and channel count, source sample count, output sample count, zero-filled gap intervals (in source samples), SHA-256 of the whole derivative, SHA-256 of the concatenated source PCM.
- `AudioQualityObservations.swift`
  - `AudioQualityObservations` with `version = "audio-quality-v1"`: duration seconds, all-silence flag, clipped-sample ratio, DC offset (normalised), channel energy imbalance measured before downmix (stereo only), discontinuity count, and per-dimension availability flags derived from versioned thresholds. Observations never lower a learner score; a failed threshold only marks the dimension unavailable.

## Data flow

Sealed spool records (already decrypted by the existing spool recovery/reader) → per-track chunk sequence → `ASRAudioDeriver` → blocks of 16 kHz mono Int16 for the transcription job (#42) → lineage and observations attached to the transcript (#44).

## Error handling

Chunks out of order, overlapping, or in a non-canonical format throw `ASRDerivationError` and abort the derivation; nothing partial is reported as complete. Zero-length input yields an empty derivative with `allSilence = true` and duration 0.

## Testing (XCTest `ASRAudioDerivationTests`)

- 1 kHz sine at 48 kHz derives to 16 kHz with the same frequency, duration within one output sample, and no timing shift.
- DC input and all-zero input; stereo with a signal on one channel downmixes with the fixed matrix and reports channel imbalance.
- Gaps and a discontinuity are zero-filled and mapped to `sampleStart / 3`.
- Block boundaries do not change output versus one-shot processing.
- A fixed synthetic input produces a fixed SHA-256 (byte stability).
- Quality thresholds flip availability flags; source chunks are never mutated.

## Verification

`xcodebuild -jobs 2 -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests/ASRAudioDerivationTests test`, run by required CI on the exact head; locally only `swiftc -parse` and `git diff --check`.
