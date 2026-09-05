# Issue #36 Recording Verification Handoff

**Updated:** 2026-09-04 (America/Los_Angeles)

This is the authoritative continuation point for GitHub issue [#36](https://github.com/fgomensoro/tam-forge/issues/36), E3-I10. The previous native-recording batch is already merged: issues #27–#35 landed through PRs #132–#136. Do not redo that batch and do not resume the unrelated local Phase 1 work described in another checkout.

## Exact workspace state

- Repository: `/Users/frank/Documents/mias/tam-forge`
- Continue in existing worktree: `/Users/frank/Documents/mias/tam-forge-issue-36`
- Branch: `codex/issue-36-recording-verification`
- Draft PR: [#151](https://github.com/fgomensoro/tam-forge/pull/151)
- Current base: `origin/main` at `022fcdb19b368fd2ed22939ba85a3f90f1736126`
- Current code/test head before this handoff document: `5abde0ecea1938d4bf9f45e66c5890418409643f`
- The branch was cleanly rebased from `a8312f3` onto `022fcdb` after PR #149 merged issue #54.
- The handoff commit is the branch `HEAD` whose subject is `docs(recording): hand off issue 36 to Claude Code`; determine it with `git rev-parse HEAD` rather than copying an older SHA from this document.

Do not use the primary checkout's local `main` as a base. It is intentionally divergent at local commit `d35de96`. Do not touch `/Users/frank/Documents/mias/tam-forge-issue-109`; another task owns it on `codex/issue-53-model-provenance` and PR #150.

Start with:

```bash
cd /Users/frank/Documents/mias/tam-forge-issue-36
git status --short
git branch --show-current
git rev-parse HEAD origin/main
gh pr view 151 --repo fgomensoro/tam-forge \
  --json isDraft,headRefOid,baseRefOid,mergeable,mergeStateStatus,statusCheckRollup
```

The worktree must be clean before implementation. Keep the same worktree and branch; do not create another issue #36 checkout.

## Read these files first, in order

1. `README.md`
2. `docs/project/native-recording-batch-03-handoff.md`
3. `docs/superpowers/plans/2026-09-01-tam-forge-native-recording-batch-03.md`
4. `docs/superpowers/specs/2026-09-01-r2-sealed-checkpoints-startup-origin.md`
5. `docs/superpowers/specs/2026-08-28-tam-forge-native-macos-redesign.md`
6. `docs/superpowers/plans/2026-09-04-tam-forge-issue-36-recording-verification.md`
7. This handoff.

`AGENTS.md` and `CODEX.md` did not exist at the repository root when this handoff was written. Check again, and follow them if they now exist. The requested `developing-ticket-batches`, Ponytail, and Caveman packages were not installed in the Codex environment that created this branch; do not claim they were used. If Claude Code has those capabilities, use them as the user requested without changing the locked plan.

## Binding execution constraints

- Coordinator: `gpt-5.6-sol`, `xhigh` effort. The issue routes coupled audio/concurrency/recovery work to that coordinator.
- Follow the locked issue #36 plan. Do not restart planning and do not modify the locked batch-03 plan.
- Work test-first. For Swift behavior, tests were committed before production and the required CI RED has already been observed.
- During development run only lightweight static checks and focused Docker-free Python tests.
- Do not run local Xcode, `xcodebuild`, UI automation, hardware capture, permission prompts, route/display tests, or heavy suites.
- Do not use Docker, Testcontainers, or Compose without separate explicit approval.
- Do not deploy or perform destructive, production, privacy-changing, or paid actions.
- Serialize changes to shared audio, cryptography, API, or recovery files. No parallel writer may touch them.
- Task-specific and final reviews must inspect exact SHAs independently. Any fix changes the reviewed SHA and requires a new review.
- Do not merge #36 until deterministic code, required CI, the single runtime window, final evidence, exact-head review, ancestry, and mergeability are all complete.

The user has standing authorization to push this branch, maintain PR #151, and merge it automatically after every gate above is satisfied. No separate merge confirmation is required. That authorization does not cover deployment, Docker, destructive operations, production access, privacy expansion, or spend.

## Completed work

### Locked plan

`docs/superpowers/plans/2026-09-04-tam-forge-issue-36-recording-verification.md` defines seven tasks:

1. privacy-safe evidence contract;
2. runtime environment-loss fail-closed behavior;
3. deterministic native failure coverage;
4. deterministic backend failure coverage;
5. exact-head evidence and CI gate;
6. independent code review and required CI;
7. one 45–60 minute runtime window after the user's `ready`.

### Task 1: complete and independently approved

The branch contains:

- `docs/project/recording-verification-v1.schema.json`
- `docs/project/recording-verification-v1.example.json`
- `scripts/ci/check_recording_verification.py`
- `scripts/ci/tests/test_check_recording_verification.py`

Fresh focused evidence before the rebase was 80 passing tests, Ruff clean, canonical digest audit clean, example CLI clean, and `git diff --check` clean. An independent Terra xhigh reviewer ultimately returned `SPEC: PASS` and `QUALITY: APPROVED` after three fix rounds.

The important contract decisions are:

- A fully blocked template uses a fixed forty-zero `commit_sha` sentinel.
- Any non-blocked evidence must match the actual repository HEAD resolved by the CLI; callers cannot supply an arbitrary expected head.
- Each scenario's `artifact_sha256` is recomputed from canonical JSON for that result, so it is not a free-form covert-data field.
- Python and JSON Schema both limit `gap_count` to `0...14_400`.
- Unknown fields, duplicate scenarios, missing scenarios, stale hashes, invalid UTC timestamps, unsafe fail-closed state, paths, private free text, and credential-like values are rejected.
- Structural validity never means issue completion. Every required scenario must pass on the exact head.

Re-run this lightweight check after further Python edits:

```bash
uv run pytest scripts/ci/tests/test_check_recording_verification.py -q
uv run ruff check scripts/ci/check_recording_verification.py \
  scripts/ci/tests/test_check_recording_verification.py
git diff --check
```

### Task 2: RED phase complete; production is next

Commit `5abde0ecea1938d4bf9f45e66c5890418409643f` is test-only after the rebase. It changes only `apps/macos/TAMForgeTests/RecordingFeatureTests.swift` and adds four coordinator tests:

- `testCoordinatorPermissionLostOrdersStopAfterAcceptedAudioDrainsRequiredTrackFailureAndNeverSeals`
- `testCoordinatorInputDeviceChangeOrdersExplicitRouteChangeGapBeforeStopAndNeverSeals`
- `testCoordinatorOutputRouteChangeDrainsExactNewLineageBoundaryBeforeStopAndNeverSeals`
- `testCoordinatorWillSleepStopsAfterDrainingAcceptedGapAndNeverSealsUnresolvedRequiredTrackFailure`

The tests exercise the real `RecordingCoordinator` with external-boundary fakes. They assert persisted ordering, drain behavior, route gap or lineage, final state, spool preservation, and no seal. They do not merely assert that a fake was called.

Before the rebase, required CI run `33934478041` on equivalent test-only SHA `06779e46b833dfd977f1f5a6455d904db978c247` confirmed the intended RED:

- `backend-unit`, `backend-integration`, `e2e`, `openapi`, and `secret-scan`: success.
- `macos-native` and `native-ui`: failed at compile time as intended.
- Representative errors at `RecordingFeatureTests.swift:1585...1596`:
  - `cannot find type 'RecordingEnvironmentMonitoring' in scope`
  - `cannot find type 'RecordingEnvironmentEvent' in scope`

This is the required observed RED. Do not delete, weaken, skip, or rewrite these tests merely to make them pass.

The ignored SDD artifacts remain locally available:

- `.superpowers/sdd/2026-09-04-tam-forge-issue-36-recording-verification/progress.md`
- `.superpowers/sdd/2026-09-04-tam-forge-issue-36-recording-verification/task-1-report.md`
- `.superpowers/sdd/2026-09-04-tam-forge-issue-36-recording-verification/task-2-report.md`

They are helpful local evidence but are not required in a fresh clone; this handoff carries their necessary state.

## Immediate next implementation

Continue Task 2 from GREEN implementation, not from new tests or planning.

Required interfaces from the locked plan:

```swift
enum RecordingEnvironmentEvent: Sendable {
    case permissionLost
    case inputDeviceChanged(route: String)
    case outputRouteChanged(route: String)
    case willSleep
}

protocol RecordingEnvironmentMonitoring: Sendable {
    func events() -> AsyncStream<RecordingEnvironmentEvent>
}
```

Implement them in a new `apps/macos/TAMForge/Features/Recording/RecordingEnvironmentMonitor.swift`, wire the monitor through `RecordingCoordinator.init`, and provide the live dependency in `apps/macos/TAMForge/App/TAMForgeApp.swift`.

The existing coordinator already owns a `lifecycleTask` that listens directly to `NSWorkspace.willSleepNotification`. Consolidate it into the injected monitor rather than leaving two independent sleep handlers. All environment events must enter one ordered coordinator path. Notification callbacks must not write crypto, spool, upload, or recovery state directly.

Behavior required by the RED tests and plan:

- Permission loss and sleep stop once, drain the already accepted prefix, consume final source events, preserve an unsafe/unsealed spool, and end in `needsAttention`.
- Input-device change updates the visible route, persists an exact `.routeChange` boundary after accepted audio, then stops without sealing.
- Output-route change preserves the exact source-lineage boundary for system audio and stops without sealing.
- An unresolved `requiredTracksMissing`, storage failure, gap-write failure, or source stop failure always blocks seal.
- Never delete the spool or key. Release still requires both authenticated gates: `audioCreatedOnServer` and `transcriptLineageAccepted`.

Use the test fixtures already appended near the end of `RecordingFeatureTests.swift`: `FakeRecordingEnvironmentMonitor`, multi-event `FakeCaptureSource`, and the gated recording spool. Do not move test-only lifecycle helpers into production.

Because local Xcode remains forbidden, after implementing production run only:

```bash
swiftc -parse apps/macos/TAMForge/Features/Recording/RecordingEnvironmentMonitor.swift
swiftc -parse apps/macos/TAMForge/Features/Recording/RecordingCoordinator.swift
swiftc -parse apps/macos/TAMForgeTests/RecordingFeatureTests.swift
python3 scripts/ci/check_swift_concurrency_patterns.py
git diff --check
```

If `scripts/ci/check_swift_concurrency_patterns.py` does not exist on the current base, do not invent a replacement or run Xcode; record that the static check is unavailable and use `swiftc -parse` plus `git diff --check`.

Commit the production GREEN separately. Push it to PR #151 and let required CI compile and execute the tests. CI, rather than local Xcode, is the GREEN gate. If CI exposes a real failure, fix it test-first and keep the PR draft.

## Remaining order after Task 2 GREEN

1. Request an independent task-scoped review of the exact Task 2 head. Fix every P0/P1/P2 and re-review the new exact SHA.
2. Complete Task 3 deterministic native failure matrix. Observe RED in CI before production changes when new Swift behavior is required.
3. Complete Task 4 Docker-free backend failure matrix with local pytest RED→GREEN.
4. Complete Task 5 runtime report template and structural CI gate. CI must validate structure/privacy without claiming live coverage passed.
5. Complete Task 6 broad exact-head independent review and required CI. Keep PR #151 draft and unmerged.
6. Tell the user that the one 45–60 minute verification window is ready to begin and wait for the exact response `ready`.
7. Only after `ready`, run Task 7 once on the exact reviewed head: shared Xcode with `-jobs 2`, installed apps, display/routes, permissions, sleep/wake, crash/relaunch, and the runtime matrix. Commit no audio or transcript.
8. Populate the final privacy-safe report, validate exact HEAD, request a new independent review because evidence changes HEAD, obtain all required CI green, confirm ancestry/mergeability, mark the PR ready, and merge automatically.

Do not begin issue #37 until #36 is merged. Issue #37 owns 10/60/120-minute resource measurements and PCM16-versus-PCM24. Issue #38 owns stable signing, DMG, and permission persistence across builds.

## Runtime-window boundary

No local runtime verification has been performed. Tests, CI compilation, source inspection, and old batch smoke notes are not substitutes for #36 runtime evidence. The single-stream ScreenCaptureKit topology remains provisional until the live matrix proves Zoom, Teams, Meet/browser call, TAM Forge TTS/interviewer, browser/local playback, foreground/background/minimized placement, and internal/external display coverage with both required tracks.

If that live evidence disproves the one-stream assumption, stop and return to Sol Ultra planning. Do not add a second stream ad hoc; deduplication and topology must be redesigned explicitly.
