# Native Recording Issue 36 Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close E3-I10 with fail-closed deterministic coverage plus one bounded runtime evidence window proving that microphone and system-audio tracks survive the supported application, route, display, permission, interruption, storage, network, replay, and corruption matrix.

**Architecture:** Keep the capture, spool, upload, and backend contracts from merged issues #27–#35 unchanged. Add injectable environment interruption handling and a privacy-safe acceptance-evidence contract so deterministic tests can prove failure behavior before the live matrix runs. The runtime matrix records only identifiers, timestamps, booleans, counts, hashes, and machine codes; it never commits audio, device names, meeting names, participant data, transcript text, tokens, or local paths.

**Tech Stack:** Swift 6, XCTest, ScreenCaptureKit, AVFoundation, AppKit notifications, Python 3.14, Pydantic v2, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-28-tam-forge-native-macos-redesign.md`

## Global Constraints

- Issue: GitHub #36 / E3-I10; dependency #35 is closed and merged.
- Preserve exactly two required tracks: `microphone` PCM16/48 kHz mono and `system_audio` PCM16/48 kHz stereo.
- Preserve the R2 common-origin, authenticated-checkpoint, required-track, recovery-v3, source-lineage, replay, release-gate, and no-early-delete behavior already merged.
- Do not introduce a second `SCStream` unless live evidence disproves the single-stream topology and a new Sol Ultra design explicitly defines deterministic deduplication.
- DRM or audio macOS does not expose is outside the coverage promise and must be reported as unsupported, never as success.
- No Xcode, UI automation, hardware capture, full suites, Docker, Testcontainers, or Compose during implementation.
- Local Docker integration requires separate explicit user approval. Until then, PostgreSQL/object-store integration evidence comes from required CI only.
- After deterministic code and exact-head review are ready, announce one 45–60 minute verification window and wait for the user's exact `ready` before running any Xcode, app, permission, route, display, sleep/wake, or hardware checks.
- Issue #37 owns 10/60/120-minute benchmarks and PCM16-versus-PCM24. Issue #38 owns stable signing, DMG, clean-user smoke, and cross-build permission persistence.
- Every commit and PR head requires independent review of the exact SHA. Merge only after required CI is present and green, ancestry is correct, and GitHub reports mergeability.

---

### Task 1: Lock a privacy-safe E3-I10 evidence contract

**Files:**
- Create: `docs/project/recording-verification-v1.schema.json`
- Create: `scripts/ci/check_recording_verification.py`
- Create: `scripts/ci/tests/test_check_recording_verification.py`
- Create: `docs/project/recording-verification-v1.example.json`

**Interfaces:**
- Consumes: scenario keys and invariants in this plan.
- Produces: `validate_recording_verification(payload: object) -> RecordingVerificationSummary`; CLI `python scripts/ci/check_recording_verification.py PATH`.

- [ ] **Step 1: Write failing validator tests.** Require schema version `1`, exact final commit SHA, UTC window timestamps no longer than 60 minutes, supported machine profile, and one result for every required scenario key. Reject duplicate keys, missing scenarios, unknown fields, absolute paths, free-form evidence, URLs with query/fragment/user-info, and keys or values resembling bearer tokens, cookies, transcripts, participant names, device names, meeting titles, or raw audio.
- [ ] **Step 2: Run the focused tests and confirm RED.**

  ```bash
  uv run pytest scripts/ci/tests/test_check_recording_verification.py -q
  ```

- [ ] **Step 3: Implement the strict schema and validator.** The only per-scenario fields are `key`, `status` (`pass`, `fail`, `unsupported`, `blocked`), `started_at`, `ended_at`, `microphone_track_present`, `system_audio_track_present`, `required_tracks_failure`, `gap_count`, `sealed`, `spool_retained`, `upload_state`, `machine_code`, and lowercase SHA-256 artifact hashes. The validator requires `pass` to have both tracks for capture scenarios, requires fail-closed fields for negative scenarios, and refuses issue completion when any required scenario is not `pass`.
- [ ] **Step 4: Run focused tests and confirm GREEN.** Add the example fixture as a deliberately incomplete non-completion example with synthetic hashes and no private data.
- [ ] **Step 5: Commit.**

  ```bash
  git add docs/project/recording-verification-v1.schema.json docs/project/recording-verification-v1.example.json scripts/ci/check_recording_verification.py scripts/ci/tests/test_check_recording_verification.py
  git commit -m "test(recording): define private verification evidence contract"
  ```

### Task 2: Fail closed on runtime environment loss

**Files:**
- Modify: `apps/macos/TAMForge/Features/Recording/RecordingModels.swift`
- Modify: `apps/macos/TAMForge/Features/Recording/RecordingCoordinator.swift`
- Create: `apps/macos/TAMForge/Features/Recording/RecordingEnvironmentMonitor.swift`
- Modify: `apps/macos/TAMForge/App/TAMForgeApp.swift`
- Modify: `apps/macos/TAMForgeTests/RecordingFeatureTests.swift`

**Interfaces:**
- Produces: `enum RecordingEnvironmentEvent { case permissionLost, inputDeviceChanged(route: String), outputRouteChanged(route: String), willSleep }`.
- Produces: `protocol RecordingEnvironmentMonitoring: Sendable { func events() -> AsyncStream<RecordingEnvironmentEvent> }`.
- `RecordingCoordinator` accepts `environmentMonitor:` and maps terminal environment loss to an unsealed `needsAttention` recording after draining accepted audio and persisted gaps.

- [ ] **Step 1: Add RED coordinator tests.** Inject a fake monitor and prove permission loss, input-device change, output-route change, and sleep during recording are serialized with capture events. Permission loss and sleep stop capture; route/device changes create an exact lineage boundary or an explicit `.routeChange` gap before stop. No terminal case seals a recording with an unresolved required-track failure.
- [ ] **Step 2: Run only the named tests and confirm RED.** Do not invoke `xcodebuild`; use static parsing/type-aware checks available without a build. Record the expected compile failures in the task notes.
- [ ] **Step 3: Implement the minimal monitor.** Use `NSWorkspace.willSleepNotification`, `AVCaptureDevice.wasConnectedNotification`, `AVCaptureDevice.wasDisconnectedNotification`, and audio route/device notifications available on macOS. Emit machine events only; do not retain device names beyond the already-visible bounded route string.
- [ ] **Step 4: Route events through the coordinator's existing single writer ordering.** Do not write crypto, spool, or upload state from notification callbacks. A terminal event must call the existing bounded stop/drain path once and leave the spool recoverable when sealing is unsafe.
- [ ] **Step 5: Run lightweight checks.**

  ```bash
  git diff --check
  python3 scripts/ci/check_swift_concurrency_patterns.py
  ```

- [ ] **Step 6: Commit.**

  ```bash
  git add apps/macos/TAMForge/Features/Recording apps/macos/TAMForge/App/TAMForgeApp.swift apps/macos/TAMForgeTests/RecordingFeatureTests.swift
  git commit -m "feat(recording): fail closed on capture environment loss"
  ```

### Task 3: Complete deterministic native failure coverage

**Files:**
- Modify: `apps/macos/TAMForgeTests/RecordingFeatureTests.swift`
- Modify: `apps/macos/TAMForgeTests/RecordingUploadTests.swift`
- Modify only if a RED test exposes a defect: files under `apps/macos/TAMForge/Features/Recording/`

**Interfaces:**
- Consumes: existing fake source, spool, server, and uploader fixtures.
- Produces: named XCTest cases matching the evidence scenario keys.

- [ ] **Step 1: Add RED tests for disk and lifecycle boundaries.** Cover preflight reserve refusal, append-time disk failure, app-style coordinator destruction/relaunch with a pending unsealed spool, sleep during startup before both anchors, permission loss after only one track, and source stop failure after both tracks. Assert no silent deletion and no unsafe seal.
- [ ] **Step 2: Add RED tests for replay and transport.** Cover offline retry, 401 refresh, cancellation, duplicate identical part, conflicting duplicate bytes, reordered part submission, server status replay after relaunch, audio-201 without transcript lineage, and both release gates. Assert one file/part at a time and spool retention until both authenticated gates.
- [ ] **Step 3: Run no Xcode locally.** Use source/static checks only; CI supplies compilation and XCTest evidence for the exact head.
- [ ] **Step 4: Implement only defects proven by RED tests, one cycle at a time.** Preserve record authentication and checkpoint comparison; never weaken a test to match unsafe behavior.
- [ ] **Step 5: Commit.**

  ```bash
  git add apps/macos/TAMForge/Features/Recording apps/macos/TAMForgeTests/RecordingFeatureTests.swift apps/macos/TAMForgeTests/RecordingUploadTests.swift
  git commit -m "test(recording): cover interruption and replay failures"
  ```

### Task 4: Complete deterministic backend failure coverage

**Files:**
- Modify: `apps/backend/tests/recordings/test_part_persistence.py`
- Modify: `apps/backend/tests/recordings/test_manifest.py`
- Modify: `apps/backend/tests/recordings/test_session_routes.py`
- Create: `apps/backend/tests/recordings/test_failure_matrix.py`
- Modify only if RED proves a defect: `apps/backend/src/tamforge_backend/recordings/`

**Interfaces:**
- Consumes: in-memory repository/object-store doubles and existing recording schemas.
- Produces: a Docker-free unit matrix for duplicate, reorder, corrupt upload, interrupted finalization, and restart/replay behavior.

- [ ] **Step 1: Add RED unit tests.** Prove identical duplicate parts are idempotent, conflicting duplicates fail closed, reordering cannot advance a hidden high-water gap, corrupt ciphertext/hash/length never reaches immutable storage, finalization replay returns the same receipt, and a simulated service restart resumes from durable status without choosing between conflicting bytes.
- [ ] **Step 2: Run focused pytest and confirm RED.**

  ```bash
  PYTHONPATH=apps/backend/src:packages/protocol/src uv run pytest apps/backend/tests/recordings/test_failure_matrix.py -q
  ```

- [ ] **Step 3: Implement minimal fixes only where RED exposes a defect.** Keep owner scoping, authentication order, immutable object keys, bounded streaming, and typed safe problems unchanged.
- [ ] **Step 4: Run focused backend recording tests and confirm GREEN.**

  ```bash
  PYTHONPATH=apps/backend/src:packages/protocol/src uv run pytest apps/backend/tests/recordings -q
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add apps/backend/src/tamforge_backend/recordings apps/backend/tests/recordings
  git commit -m "test(recordings): cover ingest and recovery failure matrix"
  ```

### Task 5: Add the exact-head runtime matrix template and CI gate

**Files:**
- Create: `docs/project/recording-verification-v1.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci/tests/test_check_recording_verification.py`

**Interfaces:**
- CI validates contract structure and privacy on every PR.
- The runtime file remains `blocked` until the one approved window populates exact-head results.

- [ ] **Step 1: Add a RED CI-policy test that requires the validator invocation and rejects a completed report whose `commit_sha` differs from `git rev-parse HEAD` when `--require-complete --expected-head` is used.**
- [ ] **Step 2: Implement the CLI flags and CI invocation in structural mode.** PR CI must never claim live scenarios passed merely because the JSON parses.
- [ ] **Step 3: Add every required scenario key:** Zoom, Teams, Meet/browser call, TAM Forge TTS/interviewer, browser/local playback; foreground/background/minimized; internal/external display; headphones/speakers; microphone change; output change; permission allowed/denied/restricted; microphone absent/in use; silent microphone/system track; sleep/wake; app crash/relaunch; disk reserve and write pressure; network loss; server restart; identical/conflicting duplicate; reordered part; corrupt ciphertext; corrupt upload; aligned truncation; missing expected track; callback-order startup; missing-track bound and finish.
- [ ] **Step 4: Run lightweight policy checks.**

  ```bash
  uv run pytest scripts/ci/tests/test_check_recording_verification.py -q
  uv run ruff check scripts/ci/check_recording_verification.py scripts/ci/tests/test_check_recording_verification.py
  git diff --check
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add .github/workflows/ci.yml docs/project/recording-verification-v1.json scripts/ci/check_recording_verification.py scripts/ci/tests/test_check_recording_verification.py
  git commit -m "ci(recording): gate exact-head verification evidence"
  ```

### Task 6: Review code before occupying the Mac

- [ ] Run only the agreed lightweight static checks and focused Docker-free Python tests.
- [ ] Request independent review against `origin/main...HEAD`, naming issue #36 and the exact HEAD SHA.
- [ ] Fix every P0/P1/P2 finding test-first, rerun the permitted checks, commit, and request a fresh independent review of the new exact HEAD.
- [ ] Push and open the issue #36 PR. Let required CI run the macOS build/XCTest and isolated backend integration jobs; do not substitute missing CI with local claims.
- [ ] Confirm required CI is green on the exact PR head before the runtime window. Do not merge yet because the acceptance report is still blocked.

### Task 7: Run the single 45–60 minute verification window after `ready`

- [ ] Announce that the single 45–60 minute verification window is beginning and wait for the user's exact `ready`.
- [ ] Use one DerivedData root and `-jobs 2`. Run the full macOS scheme once on the exact PR head.
- [ ] Execute the runtime matrix with synthetic/local playback and consenting test calls only. Inspect microphone and system tracks separately through aggregate level, sample count, gap, seal, upload, and recovery evidence. Commit no audio or transcript.
- [ ] Exercise permission states, route changes, display placement, app placement, sleep/wake, crash/relaunch, disk-pressure injection, network loss, and backend restart. Do not use Docker locally; use the already-approved isolated CI backend for server scenarios.
- [ ] Populate `docs/project/recording-verification-v1.json` with the exact commit SHA and privacy-safe results. Validate it with:

  ```bash
  uv run python scripts/ci/check_recording_verification.py docs/project/recording-verification-v1.json --require-complete --expected-head "$(git rev-parse HEAD)"
  ```

- [ ] If one-stream ScreenCaptureKit coverage fails for a supported app/display topology, stop the matrix and return to Sol Ultra. Do not add a second stream ad hoc.
- [ ] Commit the evidence, rerun exact-head independent review and required CI, confirm ancestry and mergeability, merge the PR automatically, and close #36 through the PR.

## Completion Gate

Issue #36 is complete only when the exact merged head has: every required deterministic scenario green, every runtime scenario `pass`, no privacy-contract violation, independent exact-head approval, required CI present and green, correct `origin/main` ancestry, and GitHub mergeability. A partial, blocked, unsupported supported-source, stale-head, or synthetic runtime report cannot close the issue.
