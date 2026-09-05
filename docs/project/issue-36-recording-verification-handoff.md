# Issue #36 Recording Verification Handoff

**Updated:** 2026-09-04 (America/Los_Angeles)

This is the authoritative continuation point for GitHub issue [#36](https://github.com/fgomensoro/tam-forge/issues/36), E3-I10. The native-recording batch for issues #27–#35 is already merged (PRs #132–#136); do not redo it, and do not resume the unrelated local Phase 1 work described in another checkout.

## Exact workspace state

- Repository: `/Users/frank/Documents/mias/tam-forge`
- Worktree: `/Users/frank/Documents/mias/tam-forge-issue-36`
- Branch: `codex/issue-36-recording-verification`
- Draft PR: [#151](https://github.com/fgomensoro/tam-forge/pull/151)
- Base: `origin/main` at `dd9552dd5d438e9951ce56a6bace85abc6734e98` (PR #150, model provenance, merged after the earlier base `022fcdb`; the branch was rebased cleanly onto it).
- Deterministic code head before this handoff commit: `2184dc3a7ee0acd2533c60a8ba8eb432966f14c1`. The handoff commit itself is `HEAD`; resolve it with `git rev-parse HEAD`.

Do not use the primary checkout's local `main` as a base; it is intentionally divergent. Do not touch `/Users/frank/Documents/mias/tam-forge-issue-109`.

Start with:

```bash
cd /Users/frank/Documents/mias/tam-forge-issue-36
git status --short
git rev-parse HEAD origin/main
gh pr view 151 --repo fgomensoro/tam-forge \
  --json isDraft,headRefOid,mergeable,mergeStateStatus,statusCheckRollup
```

## Read these files first, in order

1. `README.md`
2. `docs/superpowers/specs/2026-08-28-tam-forge-native-macos-redesign.md`
3. `docs/superpowers/plans/2026-09-04-tam-forge-issue-36-recording-verification.md` (locked; do not edit)
4. This handoff.

## Binding execution constraints

- Follow the locked issue #36 plan. Do not restart planning.
- Work test-first. Every new Swift behavior had its RED observed in required CI before production changed.
- During development run only lightweight static checks and focused Docker-free Python tests: `swiftc -parse`, `git diff --check`, `uv run ruff check`, focused `uv run pytest`. `scripts/ci/check_swift_concurrency_patterns.py` does not exist on this base.
- Do not run local Xcode, `xcodebuild`, UI automation, hardware capture, permission prompts, route/display tests, or heavy suites before the user's exact `ready`.
- No Docker, Testcontainers, or Compose without separate explicit approval. No deploys, destructive, production, privacy-changing, or paid actions.
- Serialize changes to shared audio, cryptography, API, or recovery files.
- Every fix changes the reviewed SHA and requires a fresh independent review of the exact new SHA.
- The user has standing authorization to push this branch, maintain PR #151, and merge it automatically once every gate below is satisfied.

## Completed work (all independently reviewed at the exact SHA)

### Task 1: privacy-safe evidence contract — approved

`docs/project/recording-verification-v1.schema.json`, `docs/project/recording-verification-v1.example.json`, `scripts/ci/check_recording_verification.py`, `scripts/ci/tests/test_check_recording_verification.py`. Fully blocked templates use the forty-zero `commit_sha` sentinel; callers cannot supply an expected head; per-scenario hashes are recomputed from canonical JSON; `gap_count` is bounded to 0…14_400.

### Task 2: runtime environment loss fails closed — approved, CI green

- RED tests (four coordinator tests) were observed failing at compile time in required CI.
- `apps/macos/TAMForge/Features/Recording/RecordingEnvironmentMonitor.swift` adds `RecordingEnvironmentEvent`, `RecordingEnvironmentMonitoring`, and `LiveRecordingEnvironmentMonitor` (NSWorkspace sleep via `NSWorkspace.shared.notificationCenter`, permission re-check on `NSApplication.didBecomeActiveNotification`, audio-device disconnect, CoreAudio default input/output changes). It emits machine events only.
- `RecordingCoordinator` takes `environmentMonitor:` and routes every event through one ordered `handle(_:)` path: stop once, drain the accepted prefix and the source's final events, never seal, end in `needsAttention` with the spool and key retained. The old direct sleep listener is gone. Environment events that arrive while preflighting or starting the source are latched and applied when the recording phase begins.
- Known ceiling (documented in code): any audio-device disconnect stops the recording, not only the selected microphone; the visible route string is the CoreAudio default device name. Watch both in the runtime window.
- The file is registered in `TAMForge.xcodeproj` for both targets; `TAMForgeApp.swift` passes the live monitor.

### Task 3: deterministic native failure coverage — CI green

Seven new coordinator tests (preflight reserve refusal, append failure while recording, app-style destruction and relaunch with a pending unsealed spool, sleep and permission loss after only one track, source stop failure after both tracks, environment loss during source start) and one upload test (relaunch after audio 201 without transcript lineage keeps the spool and never resubmits parts). The startup-window test was RED in CI 3/3 iterations before the coordinator fix.

### Task 4: Docker-free backend failure matrix — green on first run

`apps/backend/tests/recordings/test_failure_matrix.py` drives the real `RecordingService` with `InMemoryObjectStore` and an in-memory repository double. It pins identical-duplicate replay, conflicting-duplicate rejection, reorder high-water, corrupt ciphertext/hash/length never reaching storage, seal replay, and restart resume. No production defect was exposed; the docstring states which rules live in the double.

### Task 5: exact-head evidence gate — green

- `docs/project/recording-verification-v1.json` is the blocked runtime template (37/37 blocked, sentinel commit).
- `backend-unit` validates it structurally on every PR and never passes `--require-complete`.
- `--require-complete` fails unless every scenario passes on the exact repository head.
- Structural runs accept non-blocked evidence whose `commit_sha` is an ancestor of the checked-out head with no change under `apps/macos`, `apps/backend/src/tamforge_backend/recordings`, or `apps/backend/src/tamforge_backend/storage` between the two (resolved by the CLI through `git merge-base --is-ancestor` and `git diff --quiet`; `backend-unit` checks out full history). This is required because the evidence commit can never name itself and pull-request CI checks out a merge commit. Completion still requires the exact head. Any later change under those paths invalidates the committed evidence in CI until the window is repeated.

### Task 6: broad independent review — approved with fixes, fixes applied

The review of the pre-rebase head found one Critical (the evidence gate above) and Important items (rebase, stale handoff, honest matrix docstring, plan Task 7 command). All are fixed in `2184dc3`, `ac3bcad`, and the verified-ancestor tightening that followed the re-review. The final head needs a fresh exact-SHA review and all seven checks green before the window.

## Remaining order

1. Confirm required CI is green on the exact PR head and obtain an independent review of that exact SHA. Fix anything P0–P2 test-first and re-review.
2. Tell the user the single 45–60 minute verification window is ready and wait for the exact response `ready`.
3. Only after `ready`, run Task 7 once on the exact reviewed head: shared Xcode with `-jobs 2`, one DerivedData root, installed apps, display/routes, permissions, sleep/wake, crash/relaunch, disk pressure, network loss, backend restart through the approved isolated CI backend. Commit no audio or transcript.
4. Populate `docs/project/recording-verification-v1.json` with `commit_sha` equal to the verified code head and validate **before** committing the evidence:

   ```bash
   uv run python scripts/ci/check_recording_verification.py \
     docs/project/recording-verification-v1.json --require-complete
   ```

   The locked plan's Task 7 text still shows an `--expected-head` flag; the CLI rejects it by design. The CLI resolves the head itself.
5. Commit the evidence, push, obtain a fresh exact-head review (the evidence commit changes HEAD), confirm all required checks green (structural CI accepts the ancestor-bound evidence), confirm ancestry and mergeability, mark PR #151 ready, and merge.
6. If live evidence disproves the single-stream ScreenCaptureKit topology, stop and return to planning. Do not add a second stream ad hoc.

Do not begin issue #37 until #36 is merged.
