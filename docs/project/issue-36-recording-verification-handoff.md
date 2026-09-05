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

Evidence may accumulate across several bounded windows on the same verified head (owner decision, 2026-09-05): the report's `additional_windows` list holds later 60-minute windows, each after the previous one, and every scenario must lie inside one window. This lets a later Zoom-only window add keys without repeating the physical scenarios.

### Task 6: broad independent review — approved with fixes, fixes applied

The review of the pre-rebase head found one Critical (the evidence gate above) and Important items (rebase, stale handoff, honest matrix docstring, plan Task 7 command). All are fixed in `2184dc3`, `ac3bcad`, and the verified-ancestor tightening that followed the re-review. The final head needs a fresh exact-SHA review and all seven checks green before the window.

## Task 7: runtime window executed (2026-09-05, one window, incomplete by contract)

The single window ran on the exact verified code of `1660618` (verified paths byte-identical to the reviewed `e0dca81`), on the MacBook Air profile, in the Debug build launched with `-ui-test-signed-in -ui-test-native-features` because no live backend exists for a production sign-in. Evidence lives in `docs/project/recording-verification-v1.json` and validates structurally; `--require-complete` fails by design.

| Result | Count | Keys |
|---|---|---|
| pass | 31 | all placement, display, output, route, silence, permission.allowed/denied, sleep/wake, crash/relaunch, browser playback, Meet browser call, network loss, storage, deterministic and backend scenarios |
| blocked | 3 | app.zoom, app.teams (not installed), microphone.in-use (no second capture tool) |
| unsupported | 3 | app.tam-forge-tts-interviewer (feature absent from the build), microphone.absent (built-in microphone cannot be removed), permission.restricted (no MDM restriction available) |

Provenance of the entries: one live recording may evidence several keys, so identical timestamps are shared recordings, not copies. `server.restart`, `part.*`, `corruption.ciphertext`, and `corruption.upload` were evidenced by the Docker-free backend matrix and validator suites run locally inside the window (04:47:11–04:47:14Z) on top of the required CI backend-integration job on the same verified code; they are not live server restarts. `corruption.aligned-truncation`, `tracks.missing-expected`, `startup.missing-track-bound`, `finish.missing-track`, `storage.disk-reserve-pressure`, and `storage.disk-write-pressure` were evidenced by the TAMForgeTests XCTest run inside the window (04:54:23–04:54:55Z) after the one full-scheme run. `network.loss` records the upload queue holding sealed spools in "waiting for a network connection" against the unreachable fixture server while the other scenarios ran. Blocked and unsupported entries carry only what was observed; the contract was corrected so unobserved entries never have to claim a required-track failure, and the silence entries pass as the sealed, both-track recordings that were captured.

Live observations worth keeping:

- Task 2 environment-loss paths fired exactly as designed on real hardware: output route change, microphone change, and Mac sleep each stopped once, left the spool unsealed and retained, and showed the reason in `needsAttention`.
- Crash (`kill -9`) and relaunch listed every spool for recovery, never deleted anything; recovery reports "needs attention" because the fixture key store is ephemeral by design.
- Silence scenarios: the merged design records a `silentInput` warning and still seals. Decision (owner, 2026-09-05): keep the design; the contract now treats `silence.*` as capture keys, and the two sealed two-track recordings observed in the window pass.
- Disk pressure: no safe local injection exists on a machine with 815 GB free. Decision (owner, 2026-09-05): `storage.disk-reserve-pressure` is evidenced as a pre-start block and `storage.disk-write-pressure` as an unsealed retained stop by the TAMForgeTests run inside the window (preflight reserve refusal and append-failure coordinator tests on the exact verified code).
- Permission denial after the initial grant surfaced twice: once as `Recording could not start` (source start failed after a denied macOS consent dialog; no spool left behind) and later, after the window, as the preflight block "Microphone access is denied". Both fail closed.
- Recording is unreachable without a live backend; the ad-hoc Debug signature also blocks TCC registration until the app is copied to `~/Applications` and added manually. Issue #38 owns both.
- The first attempt overran the 60-minute contract limit while permissions were being granted; the reported window is the second, contiguous 60-minute span in which every automatable scenario was re-run.

Issue #36 therefore cannot close on this head. Closing needs Zoom and Teams installed for a consenting-call window, a second capture tool for `microphone.in-use`, and a decision on the three `unsupported` keys (TTS interviewer absent from the build, no removable microphone, no MDM restriction).

## Remaining order

1. Install Zoom and Teams and repeat a short window with consenting calls for `app.zoom` and `app.teams`, plus a second capture tool for `microphone.in-use`. Grant Screen Recording and Microphone to the `~/Applications/TAMForge.app` copy before starting the clock.
2. Decide the three `unsupported` keys: `app.tam-forge-tts-interviewer` needs the interviewer feature to exist, `microphone.absent` cannot happen on a MacBook Air, `permission.restricted` needs an MDM profile; either supply them in a later window or amend the contract.
3. Any commit that touches `apps/macos`, `apps/backend/src/tamforge_backend/recordings`, or `apps/backend/src/tamforge_backend/storage` invalidates the committed evidence in CI: either revert the report to the sentinel template or repeat the window on the new head.
4. Keep PR #151 draft and unmerged until every required scenario passes on an exact head with fresh review and green CI; the completion gate is intentionally unmet.
5. Before a repeat window: grant Screen Recording and Microphone to the `~/Applications/TAMForge.app` copy first, then start the 60-minute clock. Issue #38 removes the ad-hoc-signature cause.

Do not begin issue #37 until #36 is merged.
