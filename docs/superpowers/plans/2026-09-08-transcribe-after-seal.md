# Transcribe After Seal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a recording seals, the app transcribes its microphone track locally and shows the text, so the owner can read what was captured without a server.

**Architecture:** A narrow `RecordingAudioReading` seam returns the sealed microphone chunks; `RecordingCoordinator` gains an optional reader and transcriber and, on seal, runs one background task that derives 16 kHz audio and transcribes it, publishing a state the view renders. Everything is optional: with no transcriber injected the recording flow is byte-identical to today.

**Tech Stack:** Swift 6 strict concurrency, SwiftUI, XCTest.

**Spec:** `docs/superpowers/specs/2026-08-28-tam-forge-native-macos-redesign.md` section 7.1, and the runtime landed by issues #41, #42 and #43.

## Global Constraints

- Microphone track only. System audio is transcribed only when authoritative prompt text is unavailable, which this change does not decide.
- Transcription never changes the recording outcome: a failure leaves the sealed spool, the phase, and the upload queue exactly as they are, and surfaces as a visible reason.
- Nothing new is written to disk. The transcript lives in memory until issue #44 persists it.
- Do not touch `apps/backend/`, `packages/protocol/`, or `apps/macos/TAMForge/openapi.yaml`: another session owns those.
- Locally run only `swiftc -parse`, the standalone `swiftc -typecheck` shown below, `plutil -lint`, and `git diff --check`. XCTest runs in required CI.
- New Swift files are registered by hand in `apps/macos/TAMForge.xcodeproj/project.pbxproj` in both Sources phases, following the existing `F6…`/`F7…` Speech entries; new object IDs must be unique 24-hex strings, grepped as absent first.
- The unit test target compiles the app sources directly: never write `@testable import TAMForge`.
- Commit messages are plain prose ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: The sealed-audio seam

**Files:**
- Create: `apps/macos/TAMForge/Features/Speech/RecordingAudioReading.swift`
- Create: `apps/macos/TAMForgeTests/RecordingAudioReadingTests.swift`
- Modify: `apps/macos/TAMForge.xcodeproj/project.pbxproj`

**Interfaces:**
- Produces:
  ```swift
  protocol RecordingAudioReading: Sendable {
      /// Ordered canonical chunks of one track from a sealed recording.
      func sealedChunks(recordingID: UUID, track: RecordingTrackKind) async throws -> [RecordingPCMChunk]
  }
  extension EncryptedRecordingSpoolFactory: RecordingAudioReading {}
  ```
- The extension calls `EncryptedRecordingSpool.recover(recordingID:rootURL:keyStore:)` with its own `rootURL` and `keyStore`, keeps only records whose `chunk.track` matches, and returns them ordered by `chunk.sampleStart`. It throws whatever recovery throws; it never repairs or invents audio.

- [ ] **Step 1: Write the failing tests**

Using the existing in-memory key store and spool helpers in `RecordingFeatureTests.swift` as the pattern (read that file first), write tests that: seal a two-track spool through the real `EncryptedRecordingSpoolFactory` with a temporary root, then assert `sealedChunks` returns only the microphone chunks, in ascending `sampleStart` order, with payloads byte-identical to what was appended; assert asking for `.systemAudio` returns only that track; assert a recording that was never created throws rather than returning an empty array.

- [ ] **Step 2: Parse-check and commit the RED test**

Run: `swiftc -parse apps/macos/TAMForgeTests/RecordingAudioReadingTests.swift`
Expected: parses; CI would fail to compile with `cannot find type 'RecordingAudioReading' in scope`.

```bash
git add apps/macos/TAMForgeTests/RecordingAudioReadingTests.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "test(speech): specify reading sealed audio for transcription"
```

- [ ] **Step 3: Implement and commit**

Write the protocol and the extension, register the file in both Sources phases, then:

```bash
swiftc -parse apps/macos/TAMForge/Features/Speech/RecordingAudioReading.swift
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
git diff --check
git add apps/macos/TAMForge/Features/Speech/RecordingAudioReading.swift apps/macos/TAMForge.xcodeproj/project.pbxproj
git commit -m "feat(speech): read sealed microphone audio for transcription"
```

### Task 2: Transcribe on seal

**Files:**
- Modify: `apps/macos/TAMForge/Features/Recording/RecordingCoordinator.swift`
- Modify: `apps/macos/TAMForgeTests/RecordingFeatureTests.swift`

**Interfaces:**
- Consumes: `RecordingAudioReading` from Task 1, `SpeechTranscribing`, `ASRAudioDeriver`.
- Produces, on `RecordingCoordinator`:
  ```swift
  enum RecordingTranscriptState: Equatable, Sendable {
      case idle
      case running(UUID)
      case ready(UUID, SpeechTranscriptionResult)
      case failed(UUID, String)      // human-readable, no paths
  }
  @Published private(set) var transcriptState: RecordingTranscriptState = .idle
  ```
  and two new `init` parameters, both defaulting to `nil` so every existing call site is unchanged:
  `audioReader: (any RecordingAudioReading)? = nil, transcriber: (any SpeechTranscribing)? = nil`.

- [ ] **Step 1: Write the failing tests**

Add to `RecordingFeatureTests.swift`, with a `FakeRecordingAudioReader` and a `FakeSealTranscriber` defined in that file:
- After a successful stop that seals, `transcriptState` reaches `.ready` and its result's text is the fake's text, while `phase` stays `.sealed` and the pending recordings are unchanged.
- A transcriber that throws leaves `transcriptState` at `.failed` with a non-empty reason, `phase` still `.sealed`, and the recording still pending for upload.
- A reader that throws does the same.
- With no transcriber injected, `transcriptState` stays `.idle` after sealing and no reader call happens.
- A recording that ends in `needsAttention` rather than sealed never starts transcription.
- Starting a new recording resets `transcriptState` to `.idle`.
- The samples handed to the transcriber are 16 kHz: assert the request lineage's `outputSampleRate` is 16 000 and that its `derivationVersion` is the current one, proving the audio went through `ASRAudioDeriver` rather than being passed raw.

Use the existing `waitUntilCoordinatorSettles` helper plus a short polling helper for the transcript state; do not sleep blindly.

- [ ] **Step 2: Parse-check and commit the RED tests**

Run: `swiftc -parse apps/macos/TAMForgeTests/RecordingFeatureTests.swift`

```bash
git add apps/macos/TAMForgeTests/RecordingFeatureTests.swift
git commit -m "test(recording): specify transcription after a recording seals"
```

- [ ] **Step 3: Implement**

In `RecordingCoordinator`:
- Store the two new dependencies and a `transcriptionTask: Task<Void, Never>?`.
- Reset `transcriptState = .idle` and cancel any running `transcriptionTask` at the top of `start()`.
- Immediately after `phase = .sealed(recordingID)`, call a new `private func beginTranscription(recordingID: UUID)`.
- `beginTranscription` returns immediately when either dependency is nil. Otherwise it sets `.running(recordingID)` and starts a task that: reads the microphone chunks, feeds them in order through one `ASRAudioDeriver`, collects the derived samples, calls `transcriber.transcribe(_:)`, and sets `.ready` or `.failed` back on the main actor.
- Empty audio must become `.failed` with a plain reason rather than a thrown error escaping.
- Cancel the task in `deinit` alongside the others.
- Never let transcription touch `spool`, `pendingRecordingIDs`, `uploadStates`, or `phase`.

- [ ] **Step 4: Check and commit**

```bash
swiftc -parse apps/macos/TAMForge/Features/Recording/RecordingCoordinator.swift
swiftc -typecheck -parse-as-library -swift-version 6 -strict-concurrency=complete -target arm64-apple-macosx15.0 -sdk "$(xcrun --show-sdk-path)" -F apps/macos/Vendor/whisper.xcframework/macos-arm64_x86_64 -framework whisper apps/macos/TAMForge/Features/Speech/*.swift apps/macos/TAMForge/Features/Recording/RecordingModels.swift
git diff --check
git add apps/macos/TAMForge/Features/Recording/RecordingCoordinator.swift
git commit -m "feat(recording): transcribe a sealed recording in the background"
```

Note: the typecheck command above covers the Speech files only; `RecordingCoordinator.swift` cannot be typechecked standalone because it depends on the rest of the app, so CI is its compile gate.

### Task 3: Show the transcript

**Files:**
- Modify: `apps/macos/TAMForge/Features/Recording/RecordingView.swift`, `apps/macos/TAMForge/App/TAMForgeApp.swift`
- Modify: `apps/macos/TAMForgeUITests/TAMForgeUITests.swift`

**Interfaces:**
- Consumes: `coordinator.transcriptState`.

- [ ] **Step 1: Wire the live dependencies**

In `TAMForgeApp.swift`, pass the existing `recordingSpool` as `audioReader:` and, when a transcription model is installed, `try? WhisperTranscriber()` as `transcriber:`. When the model is absent the app keeps working with transcription simply switched off.

- [ ] **Step 2: Render the state**

In `RecordingView.swift`, add a section below the existing recording controls, shown only when `transcriptState` is not `.idle`:
- `.running`: "Transcribing this recording on this Mac." with a progress indicator, identifier `recordingTranscriptStatus`.
- `.ready`: the transcript text in a selectable, scrollable text view with identifier `recordingTranscript`, above a line naming the model from `result.identity.modelFilename` with identifier `recordingTranscriptModel`.
- `.failed`: the reason with identifier `recordingTranscriptStatus`.

Keep the existing consent and coverage copy unchanged.

- [ ] **Step 3: Extend the UI test**

The UI target runs in fixture mode where no model is installed, so assert the honest thing: the transcript section is absent after launch, and the existing recording journey still passes. Do not assert a transcript appears.

- [ ] **Step 4: Check, commit, push**

```bash
swiftc -parse apps/macos/TAMForge/Features/Recording/RecordingView.swift apps/macos/TAMForge/App/TAMForgeApp.swift
plutil -lint apps/macos/TAMForge.xcodeproj/project.pbxproj
git diff --check
git add apps/macos/TAMForge/Features/Recording/RecordingView.swift apps/macos/TAMForge/App/TAMForgeApp.swift apps/macos/TAMForgeUITests/TAMForgeUITests.swift
git commit -m "feat(recording): show the local transcript after sealing"
git push -u origin fg/transcribe-after-seal
```
