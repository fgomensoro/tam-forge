# Local whisper.cpp Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a pinned, Metal-accelerated `whisper.cpp` runtime callable from the macOS app with English-only word timestamps and whisper's built-in VAD, with no Python runtime and no network inference.

**Architecture:** A pinned XCFramework fetched by script into a gitignored vendor directory and embedded in the app; a Swift `SpeechTranscribing` seam whose only whisper-importing implementation is an actor that owns the context; models fetched by script into Application Support. CI fetches and caches the framework so the real adapter compiles there, while unit tests use a fake engine.

**Tech Stack:** Swift 6 strict concurrency, XCTest, whisper.cpp `b4938` XCFramework (module map, no bridging header), Python 3.14 + PyYAML for the manifest check, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-08-whisper-runtime-design.md`

## Global Constraints

- Pinned artifacts, verbatim, are the single source of truth in `config/speech-models.yaml`:
  - whisper.cpp XCFramework `b4938`, `https://github.com/ggml-org/whisper.cpp/releases/download/b4938/whisper-b4938-xcframework.zip`, 53621479 bytes, sha256 `dcc6cdc6d6902d11893434ceda70c23a2a64450f65a1b570035c9908988dfedd`, MIT.
  - `ggml-base.en-q5_1.bin`, `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en-q5_1.bin`, 59721011 bytes, sha256 `4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f`, MIT.
  - `ggml-silero-v5.1.2.bin`, `https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin`, 885098 bytes, sha256 `29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf`, MIT.
- Nothing downloads at app runtime. No OpenVINO, no telemetry, no network call from the transcription path.
- The framework unpacks to `apps/macos/Vendor/whisper.xcframework` (gitignored). Models install to `~/Library/Application Support/TAM Forge/Models/` (never in the repo).
- Transcription is English-only (`language = "en"`, `translate = false`), requests word timestamps, and runs off the main actor.
- Locally run only `swiftc -parse`, the standalone `swiftc -typecheck` command shown in Task 2, `uv run pytest`/`ruff`, `plutil -lint`, `zsh -n`, and `git diff --check`. XCTest and xcodebuild run in required CI only.
- New Swift files are registered by hand in `apps/macos/TAMForge.xcodeproj/project.pbxproj` in both Sources phases, following the existing `F6…` Speech entries; new object IDs must be unique 24-hex strings.
- Commit messages are plain prose ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Pinned artifact manifest and fetch scripts

**Files:**
- Create: `config/speech-models.yaml`
- Create: `scripts/dev/fetch_whisper_framework.sh`
- Create: `scripts/dev/fetch_whisper_models.sh`
- Create: `scripts/ci/tests/test_speech_models_manifest.py`
- Modify: `.gitignore`, `Makefile`, `README.md`

**Interfaces:**
- Produces: `config/speech-models.yaml` with top-level `schema_version: 1` and an `artifacts` mapping whose keys are `whisper_framework`, `transcription_model`, `vad_model`; each value has `version`, `url`, `filename`, `bytes`, `sha256`, `license`, `installs_to`, and `consumed_by`.
- Produces: `scripts/dev/fetch_whisper_framework.sh` (no arguments, idempotent) and `scripts/dev/fetch_whisper_models.sh` (no arguments, idempotent).

- [ ] **Step 1: Write the failing manifest test**

```python
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import yaml

MANIFEST = Path("config/speech-models.yaml")
REQUIRED_KEYS = {"whisper_framework", "transcription_model", "vad_model"}
FIELDS = {"version", "url", "filename", "bytes", "sha256", "license", "installs_to", "consumed_by"}


def manifest() -> dict[str, object]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_every_artifact_is_pinned_by_size_and_hash() -> None:
    document = manifest()
    assert document["schema_version"] == 1
    artifacts = document["artifacts"]
    assert set(artifacts) == REQUIRED_KEYS
    for name, entry in artifacts.items():
        assert set(entry) == FIELDS, name
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), name
        assert isinstance(entry["bytes"], int) and entry["bytes"] > 0, name
        assert entry["url"].startswith("https://"), name
        assert entry["license"], name


def test_pins_match_the_reviewed_artifacts() -> None:
    artifacts = manifest()["artifacts"]
    assert artifacts["whisper_framework"]["version"] == "b4938"
    assert artifacts["whisper_framework"]["sha256"] == (
        "dcc6cdc6d6902d11893434ceda70c23a2a64450f65a1b570035c9908988dfedd"
    )
    assert artifacts["transcription_model"]["filename"] == "ggml-base.en-q5_1.bin"
    assert artifacts["transcription_model"]["sha256"] == (
        "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f"
    )
    assert artifacts["vad_model"]["sha256"] == (
        "29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf"
    )


def test_fetch_scripts_read_their_pins_from_the_manifest() -> None:
    for script in ("fetch_whisper_framework.sh", "fetch_whisper_models.sh"):
        source = Path("scripts/dev") / script
        assert source.exists(), script
        text = source.read_text(encoding="utf-8")
        assert "config/speech-models.yaml" in text, script
        assert "shasum" in text or "sha256sum" in text, script
        # Pins live in the manifest, never duplicated in the script.
        assert "dcc6cdc6d690" not in text, script
        assert "4baf70dd0d7c" not in text, script


def test_installed_artifacts_match_their_pins_when_present(tmp_path: Path) -> None:
    artifacts = manifest()["artifacts"]
    vendor = Path("apps/macos/Vendor/whisper.xcframework")
    if vendor.is_dir():
        macos = vendor / "macos-arm64_x86_64" / "whisper.framework"
        assert macos.is_dir(), "installed XCFramework is missing its macOS slice"
    models = Path.home() / "Library" / "Application Support" / "TAM Forge" / "Models"
    for name in ("transcription_model", "vad_model"):
        entry = artifacts[name]
        installed = models / entry["filename"]
        if not installed.is_file():
            pytest.skip(f"{entry['filename']} is not installed on this machine")
        assert installed.stat().st_size == entry["bytes"]
        digest = hashlib.sha256(installed.read_bytes()).hexdigest()
        assert digest == entry["sha256"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest scripts/ci/tests/test_speech_models_manifest.py -q`
Expected: FAIL because `config/speech-models.yaml` does not exist.

- [ ] **Step 3: Write the manifest**

`config/speech-models.yaml` with exactly the three artifacts and fields from the Global Constraints. Use `installs_to: apps/macos/Vendor/whisper.xcframework` for the framework and `installs_to: ~/Library/Application Support/TAM Forge/Models` for both models. `consumed_by` names the component: `WhisperTranscriber`, `whisper_full`, `whisper built-in VAD`. Head the file with a comment saying that changing any pin requires re-running both fetch scripts and re-reviewing the artifact.

- [ ] **Step 4: Write both fetch scripts**

Each script: `#!/bin/zsh`, `set -euo pipefail`, `cd "$(dirname "$0")/../.."`, read its pins from `config/speech-models.yaml` with `python3 -c` and PyYAML (fall back to `uv run python` when PyYAML is missing from the system interpreter), download to a `mktemp -d` staging directory with `curl -sSL --fail`, verify byte size and `shasum -a 256`, and only then move the artifact into place. A hash mismatch must delete the download and exit non-zero with a clear message. Both scripts must be idempotent: if the artifact is already installed with the right size and hash, print that and exit 0 without downloading. `trap 'rm -rf "$STAGE"' EXIT` in both.

- [ ] **Step 5: Wire the ignore rules, Makefile, and README**

Add `apps/macos/Vendor/` to `.gitignore` under the native section. Add two phony Makefile targets, `whisper-framework` and `whisper-models`, each invoking its script. Add a short README paragraph under the native macOS section explaining that both are one-time fetches, that pins live in `config/speech-models.yaml`, and that nothing downloads at app runtime.

- [ ] **Step 6: Run the checks**

```bash
uv run pytest scripts/ci/tests/test_speech_models_manifest.py -q
uv run ruff check scripts/ci/tests/test_speech_models_manifest.py
zsh -n scripts/dev/fetch_whisper_framework.sh && zsh -n scripts/dev/fetch_whisper_models.sh
scripts/dev/fetch_whisper_framework.sh && scripts/dev/fetch_whisper_models.sh
git diff --check && git status --short
```
Expected: tests pass, lint clean, both scripts install their artifacts and pass verification, and `git status` shows no vendor or model file staged.

- [ ] **Step 7: Commit**

```bash
git add config/speech-models.yaml scripts/dev/fetch_whisper_framework.sh scripts/dev/fetch_whisper_models.sh scripts/ci/tests/test_speech_models_manifest.py .gitignore Makefile README.md
git commit -m "feat(speech): pin and fetch the whisper runtime artifacts"
```

### Task 2: Transcription contract and fake engine

**Files:**
- Create: `apps/macos/TAMForge/Features/Speech/SpeechTranscription.swift`
- Create: `apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift`
- Create: `apps/macos/TAMForgeTests/SpeechTranscriptionTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: `ASRDerivationLineage` and `ASRDerivedBlock` from `ASRAudioDerivation.swift`.
- Produces:
  ```swift
  struct SpeechTranscriptionRequest: Sendable, Equatable {
      let samples: [Int16]            // 16 kHz mono, the whole derived stream
      let lineage: ASRDerivationLineage
  }
  struct SpeechTranscribedWord: Sendable, Equatable {
      let text: String
      let startMilliseconds: Int64    // relative to the derived stream
      let endMilliseconds: Int64
      let probability: Double
  }
  struct SpeechTranscribedSegment: Sendable, Equatable {
      let text: String
      let startMilliseconds: Int64
      let endMilliseconds: Int64
      let words: [SpeechTranscribedWord]
  }
  struct SpeechRuntimeIdentity: Sendable, Equatable {
      let runtimeVersion: String      // whisper.cpp release, e.g. "b4938"
      let modelFilename: String
      let modelSHA256: String
      let usedMetal: Bool
      let usedBuiltInVAD: Bool
      let language: String            // always "en"
  }
  struct SpeechTranscriptionResult: Sendable, Equatable {
      let segments: [SpeechTranscribedSegment]
      let identity: SpeechRuntimeIdentity
      let lineage: ASRDerivationLineage
      var text: String { /* segments joined with a single space, trimmed */ }
  }
  enum SpeechTranscriptionError: Error, Equatable {
      case modelUnavailable(String)   // human-readable reason, no paths
      case unsupportedSampleRate(Int)
      case emptyAudio
      case cancelled
      case runtimeFailure(code: Int32)
  }
  protocol SpeechTranscribing: Sendable {
      func transcribe(_ request: SpeechTranscriptionRequest) async throws -> SpeechTranscriptionResult
  }
  struct SpeechModelCatalog: Sendable {
      static let transcriptionModelFilename = "ggml-base.en-q5_1.bin"
      static let vadModelFilename = "ggml-silero-v5.1.2.bin"
      let directory: URL              // default: Application Support/TAM Forge/Models
      init(directory: URL = SpeechModelCatalog.defaultDirectory)
      static var defaultDirectory: URL { get }
      var transcriptionModelURL: URL? { get }   // nil when absent
      var vadModelURL: URL? { get }
      func requireTranscriptionModel() throws -> URL   // throws .modelUnavailable
  }
  ```

- [ ] **Step 1: Write the failing tests**

Cover, with a `FakeSpeechEngine` implementing `SpeechTranscribing` inside the test file:
- `SpeechTranscriptionResult.text` joins segment texts with a single space and trims, and is empty for no segments.
- A request built from a lineage whose `outputSampleRate` is not 16 000 is rejected by the shared validator with `.unsupportedSampleRate`, and empty samples give `.emptyAudio` (put that validation in a `SpeechTranscriptionRequest.validate()` used by every engine, and test it directly).
- `SpeechModelCatalog` with a temporary directory reports `nil` for both models when the directory is empty, reports the URLs once files exist, and `requireTranscriptionModel()` throws `.modelUnavailable` with a message containing no absolute path.
- `SpeechRuntimeIdentity` always carries `language == "en"`.
- The fake engine propagates the request lineage into the result unchanged.

Write real assertions; no placeholders.

- [ ] **Step 2: Parse-check and commit the RED test**

Run: `swiftc -parse apps/macos/TAMForgeTests/SpeechTranscriptionTests.swift`
Expected: parses. CI would fail to compile: `cannot find type 'SpeechTranscribing' in scope`. Register the test file in `project.pbxproj` (file reference, build file in the test target Sources phase, tests group children) and commit:

```bash
git add apps/macos/TAMForgeTests/SpeechTranscriptionTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "test(speech): specify the transcription contract"
```

- [ ] **Step 3: Implement the contract and the catalog**

Write both production files to the interfaces above. `SpeechModelCatalog.defaultDirectory` is `FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]` plus `TAM Forge/Models`. `requireTranscriptionModel()` throws `.modelUnavailable("Transcription model \(Self.transcriptionModelFilename) is not installed")` — the message names the file, never the directory. `SpeechTranscriptionRequest.validate()` throws `.emptyAudio` for no samples and `.unsupportedSampleRate(lineage.outputSampleRate)` when it is not 16 000.

- [ ] **Step 4: Register, parse-check, typecheck, commit**

Add both files to the `Speech` group and to BOTH Sources phases.

```bash
swiftc -parse apps/macos/TAMForge/Features/Speech/SpeechTranscription.swift apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift
swiftc -typecheck -parse-as-library -swift-version 6 -strict-concurrency=complete -target arm64-apple-macosx15.0 -sdk "$(xcrun --show-sdk-path)" apps/macos/TAMForge/Features/Speech/SpeechTranscription.swift apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift apps/macos/TAMForge/Features/Speech/ASRAudioDerivation.swift apps/macos/TAMForge/Features/Speech/AudioQualityObservations.swift apps/macos/TAMForge/Features/Recording/RecordingModels.swift
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
git diff --check
git add apps/macos/TAMForge/Features/Speech apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(speech): add the transcription contract and model catalog"
```

### Task 3: Whisper adapter, Xcode integration, CI, and bundle policy

**Files:**
- Create: `apps/macos/TAMForge/Features/Speech/WhisperTranscriber.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci/check_native_bundle.py`, `scripts/ci/tests/test_check_native_bundle.py`

**Interfaces:**
- Consumes: everything from Task 2 and the installed `apps/macos/Vendor/whisper.xcframework` from Task 1.
- Produces: `actor WhisperTranscriber: SpeechTranscribing` with `init(catalog: SpeechModelCatalog = .init(), runtimeVersion: String = "b4938") throws`.

- [ ] **Step 1: Extend the bundle checker test first**

Add cases to `scripts/ci/tests/test_check_native_bundle.py`:
- a fake app containing `Contents/Frameworks/whisper.framework/Versions/A/whisper` (Mach-O bytes) plus the `Versions/Current` and top-level symlinks passes `bundle_violations`;
- the same app with a second, unexpected framework binary is rejected;
- `@rpath/whisper.framework/Versions/A/whisper` is an accepted linked library while `@rpath/other.framework/other` is rejected;
- a symlink alone never counts as an extra payload.

Run: `uv run pytest scripts/ci/tests/test_check_native_bundle.py -q`
Expected: FAIL on the new cases.

- [ ] **Step 2: Allow exactly the whisper framework in the checker**

In `scripts/ci/check_native_bundle.py`: add `Path("Contents/Frameworks/whisper.framework/Versions/A/whisper")` to `ALLOWED_BINARY_PATHS`; make `_binary_payloads` skip symlinks (`item.is_file() and not item.is_symlink()`); accept `@rpath/whisper.framework/Versions/A/whisper` in `_is_standalone_library_reference`. Change nothing else — every other third-party payload must still be rejected.

Run: `uv run pytest scripts/ci/tests/test_check_native_bundle.py -q` (PASS) and `uv run ruff check scripts/ci`.

- [ ] **Step 3: Write the whisper adapter**

`WhisperTranscriber.swift` is the only file that may `import whisper`. Requirements:
- `init` resolves the transcription model through the catalog and throws `.modelUnavailable` when absent; it does not load the context yet.
- `transcribe` calls `request.validate()`, lazily creates the context with `whisper_context_default_params()` (leave `use_gpu = true` so Metal is used), converts `[Int16]` to `[Float]` by dividing by 32768, and runs `whisper_full` with `whisper_full_default_params(WHISPER_SAMPLING_GREEDY)` adjusted to: `language = "en"`, `translate = false`, `token_timestamps = true`, `no_timestamps = false`, `print_progress = false`, `print_realtime = false`, `single_segment = false`, and `n_threads` set to `max(1, ProcessInfo.processInfo.activeProcessorCount - 2)`.
- When `catalog.vadModelURL` is present, set `vad = true` and `vad_model_path`; keep the C strings alive for the whole call (hold them in local `[CChar]` arrays or use `withCString` nesting, never a dangling `strdup` free).
- Read segments with `whisper_full_n_segments` / `whisper_full_get_segment_t0` / `_t1` / `_get_segment_text`, and words with `whisper_full_n_tokens` / `whisper_full_get_token_text` / `whisper_full_get_token_data` (`t0`, `t1`, `p`), skipping special tokens (`whisper_token_eot`, and tokens whose id is at or above `whisper_token_eot(ctx)`). whisper times are centiseconds: multiply by 10 for milliseconds.
- Cancellation: check `Task.isCancelled` before starting and inside the `whisper_full` abort callback (`abort_callback` / `abort_callback_user_data`), throwing `.cancelled`.
- Free the context in `deinit` and in an explicit `release()` method; never leak it on a thrown error.
- Compute `SpeechRuntimeIdentity` with the model SHA-256 read from `config/speech-models.yaml`? No: hashing at runtime is expensive. Instead pass the expected hash in as a constant `SpeechModelCatalog.transcriptionModelSHA256` added in this task, and record it; add one test in Task 4 that the constant matches the manifest.
- Nothing in this file may reference OpenVINO, a URL, or `URLSession`.

- [ ] **Step 4: Integrate the XCFramework in the Xcode project**

In `project.pbxproj`: add a `PBXFileReference` for `Vendor/whisper.xcframework` (`lastKnownFileType = wrapper.xcframework`, path relative to the project directory), a `PBXBuildFile` in the app target's Frameworks build phase, a second `PBXBuildFile` with `settings = {ATTRIBUTES = (CodeSignOnCopy, RemoveHeadersOnCopy, ); }` in an `Embed Frameworks` copy-files phase (`dstSubfolderSpec = 10`), and `FRAMEWORK_SEARCH_PATHS = ("$(PROJECT_DIR)/Vendor", "$(inherited)")` in every build configuration of the app and unit-test targets. Register `WhisperTranscriber.swift` in both Sources phases as usual.

Run: `plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj` and `swiftc -parse apps/macos/TAMForge/Features/Speech/WhisperTranscriber.swift`.

- [ ] **Step 5: Make CI fetch and cache the framework**

In `.github/workflows/ci.yml`, in both `macos-native` and `native-ui`, after `actions/checkout` and before any `xcodebuild` step, add:

```yaml
      - name: Cache whisper framework
        uses: actions/cache@v4
        with:
          path: apps/macos/Vendor
          key: whisper-xcframework-b4938
      - name: Fetch whisper framework
        run: scripts/dev/fetch_whisper_framework.sh
```

The fetch script is idempotent, so a cache hit costs nothing. Do not fetch models in CI: unit tests use the fake engine and the smoke tests skip.

- [ ] **Step 6: Commit and push, then read CI**

```bash
git add apps/macos/TAMForge/Features/Speech/WhisperTranscriber.swift apps/macos/TAMForge.xcodeproj/project.pbxproj .github/workflows/ci.yml scripts/ci/check_native_bundle.py scripts/ci/tests/test_check_native_bundle.py
git commit -m "feat(speech): run local transcription on pinned whisper.cpp"
git push -u origin codex/issue-42-whisper-runtime
```

Watch `macos-native` and `native-ui`. Compile errors in the C interop are expected on the first attempt: read the exact diagnostics from the job log, fix them in the adapter (never by loosening the tests or the bundle checker), and push again. At most four fix rounds; if the framework still does not link after that, stop and report what the linker says.

### Task 4: Real-model smoke test and documentation

**Files:**
- Create: `apps/macos/TAMForgeTests/WhisperRuntimeSmokeTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`, `scripts/ci/tests/test_speech_models_manifest.py`, `README.md`
- Comment on issue #42

**Interfaces:**
- Consumes: `WhisperTranscriber`, `SpeechModelCatalog`, `ASRAudioDeriver`.

- [ ] **Step 1: Write the opt-in smoke test**

`WhisperRuntimeSmokeTests` must skip with `throw XCTSkip("…")` when `SpeechModelCatalog().transcriptionModelURL` is nil, so CI stays green. When the model is present it: derives 16 kHz audio from a synthetic 48 kHz source through `ASRAudioDeriver`, runs `WhisperTranscriber`, and asserts the result carries `identity.language == "en"`, `identity.usedMetal == true`, a non-negative segment count, monotonic segment times, and the request lineage unchanged. Silence must produce zero segments rather than an error.

- [ ] **Step 2: Pin the model hash constant against the manifest**

Add to `scripts/ci/tests/test_speech_models_manifest.py` a test that reads `apps/macos/TAMForge/Features/Speech/SpeechModelCatalog.swift`, extracts `transcriptionModelSHA256`, and asserts it equals the manifest's `transcription_model.sha256`.

Run: `uv run pytest scripts/ci/tests/test_speech_models_manifest.py -q`

- [ ] **Step 3: Document and commit**

README: one paragraph saying transcription is local, which model is pinned, that `make whisper-framework` and `make whisper-models` install the artifacts once, and that the smoke test skips without the model. Then:

```bash
git add apps/macos/TAMForgeTests/WhisperRuntimeSmokeTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj scripts/ci/tests/test_speech_models_manifest.py README.md
git commit -m "test(speech): add the opt-in whisper runtime smoke test"
gh issue comment 42 --repo fgomensoro/tam-forge --body "Runtime is pinned whisper.cpp b4938 (XCFramework, Metal, built-in VAD, English word timestamps) behind the SpeechTranscribing seam; artifacts are pinned in config/speech-models.yaml and fetched by scripts/dev/fetch_whisper_*.sh. CI fetches and caches the framework so the adapter compiles there; unit tests use a fake engine and the real-model smoke test skips without the model. Bundling the model in the shipped app stays with #43."
```
