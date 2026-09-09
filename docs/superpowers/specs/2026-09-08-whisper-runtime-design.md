# Local whisper.cpp transcription runtime (issue #42, E4-I03)

**Date:** 2026-09-08. Follows the 2026-08-28 redesign spec, sections 7.1 and 7.2, and the owner decision of 2026-09-08 that transcription runs on the Mac.

## Goal

Make a pinned `whisper.cpp` runtime available to the macOS app: Metal-accelerated, English-only, word timestamps, whisper's built-in VAD, no Python runtime and no network inference. Transcription consumes the 16 kHz mono blocks produced by `ASRAudioDeriver` (issue #41).

## Scope

In: the pinned artifact manifest and fetch scripts, the Xcode integration of the XCFramework, the Swift transcription seam and its whisper adapter, CI changes that keep the macOS jobs building, and the bundle checker allowance for the embedded framework.
Out: choosing between base.en and small.en (#43), persisting transcripts and lineage to the backend (#44), metrics (#45), job scheduling and memory pressure (#51), bundling the model inside the shipped app (release concern, tracked with #43).

## Pinned artifacts

`config/speech-models.yaml` is the single source of truth. Every entry carries a URL, byte size, SHA-256, license, and the component that consumes it.

| Artifact | Version | Bytes | SHA-256 |
|---|---|---|---|
| whisper.cpp XCFramework | `b4938` | 53 621 479 | `dcc6cdc6d6902d11893434ceda70c23a2a64450f65a1b570035c9908988dfedd` |
| `ggml-base.en-q5_1.bin` | q5_1 | 59 721 011 | `4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f` |
| `ggml-silero-v5.1.2.bin` | v5.1.2 | 885 098 | `29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf` |

The macOS slice of the XCFramework is 5.9 MB, ships a framework module map (so Swift imports it directly, with no bridging header), embeds its Metal shaders, and exposes the built-in VAD and Core ML entry points.

## Components

- `scripts/dev/fetch_whisper_framework.sh` unpacks the XCFramework into `apps/macos/Vendor/whisper.xcframework` after verifying size and hash. The directory is gitignored; the script is idempotent and refuses to install an artifact whose hash does not match.
- `scripts/dev/fetch_whisper_models.sh` places the transcription and VAD models in `~/Library/Application Support/TAM Forge/Models/` with the same verification. Nothing downloads at app runtime.
- `apps/macos/TAMForge/Features/Speech/SpeechTranscription.swift`: `SpeechTranscribing` protocol, `SpeechTranscriptionRequest` (16 kHz mono samples plus the derivation lineage), `SpeechTranscriptionResult` (segments, words with times and probabilities, model and config identity), `SpeechTranscriptionError`.
- `apps/macos/TAMForge/Features/Speech/WhisperTranscriber.swift`: the only file importing `whisper`. An actor that owns the context, runs Metal, fixes English, requests word timestamps, enables the built-in VAD when the VAD model is present, and releases the context deterministically.
- `apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift`: resolves model paths and reports what is installed, so the UI and tests can tell "no model" from "transcription failed".

## Privacy and safety

The runtime never opens a network connection: no OpenVINO initialisation, no model download path, no telemetry. Model and framework identity (version, SHA-256) travel with every result so a transcript can always be traced to the exact runtime that produced it. Audio stays in memory; nothing new is written to disk.

## Testing

`SpeechTranscriptionTests` run in CI against a fake engine and cover the contract: English fixed, word timestamps requested, VAD flag follows model availability, cancellation, error mapping, and lineage propagation. `WhisperRuntimeSmokeTests` exercise the real framework and model, and skip cleanly when either is absent, so CI stays green while the owner's Mac can prove real transcription.

CI fetches and caches the XCFramework before the macOS jobs, so the real adapter compiles in CI. The bundle checker allows exactly one embedded framework, `whisper.framework`, and still rejects any other third-party payload.
