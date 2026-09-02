# Native Recording Batch 03 Handoff

> Snapshot: 2026-09-01
> Status: implementation in progress; no batch verification has been run.
> Resume coordinator: `gpt-5.6-sol` / `xhigh`.
> Authoritative locked plan: `docs/superpowers/plans/2026-09-01-tam-forge-native-recording-batch-03.md`.

This file is the operational handoff for continuing TAM Forge after the repository move and the interrupted R2 hardening pass. Read it before changing code. It records facts, deferred evidence, branch ancestry, and the exact continuation order. Do not treat a commit, authored test, static inspection, or old review as runtime verification.

## 1. Product and architecture decisions

- The complete product UI is native Swift + SwiftUI. React/Vite/Node are migration-only until issue #126 removes them from active runtime and CI.
- The macOS app talks directly to the remote FastAPI backend with generated OpenAPI types and `URLSession`.
- Permanent database and heavy services remain remote: FastAPI + PostgreSQL + private S3-compatible object storage on Hetzner. Do not add local PostgreSQL, Python runtime, Docker, Electron, or an embedded browser to the distributed app.
- Capture uses ScreenCaptureKit/Core Audio. It records the selected microphone and all macOS-shareable system audio as separate synchronized tracks. DRM/protected or otherwise non-shareable audio is an explicit limitation, never silent success.
- Canonical original audio is signed interleaved PCM16 at 48 kHz: microphone mono and system stereo. Keep source format, route/device, presentation timing, discontinuities, gaps, and conversion version as lineage.
- Recording is explicit Start/Stop, always visible, and never hidden or automatic. No live loopback/monitoring, video persistence, custom audio driver, BlackHole, aggregate device, waveform, live transcription, noise suppression, or automatic gain.
- The callback path performs only bounded validation/copy/handoff. Conversion, hashing, encryption, file I/O, network, and UI work happen off callback.
- Local recovery is a bounded encrypted AES-GCM spool with one random 256-bit Keychain root per recording, independently authenticated records of at most one second, exact gaps, owner-only files, a 120-minute cap, 2.5 GiB per recording, 5 GiB global pending cap, and 8 GiB free-disk reserve.
- Permanent originals are immutable PCM part objects plus one canonical manifest per track. Do not create a duplicate full-track PCM/WAV original. WAV/16 kHz/analysis files are later derivatives.
- Upload starts only after capture stops and the local spool seals. It is file-backed, encrypted, authenticated, idempotent, and at most 60 seconds/one track per part; process one part at a time.
- Local deletion has two independent authenticated gates: `audio_created_on_server` and `transcript_lineage_accepted`. This batch can set only the first. Never delete/crypto-shred until both are true.
- Local transcription is a later batch: pinned `whisper.cpp`, Metal and optional Core ML, one job after recording, one job at a time, model loaded only while processing. Base versus Small must be chosen by real voice-quality tests; 8 GB RAM changes scheduling, not automatic accuracy degradation.
- English-analysis quality is non-negotiable, but complexity must earn material value. Keep high-fidelity original audio and exact lineage; reject expensive features that add negligible analysis quality without evidence. Pronunciation/alignment uses original audio and a dedicated pipeline, not ASR probability alone.

## 2. Standing development process

Use the `developing-ticket-batches` skill, Ponytail `full`, and Caveman `ultra`.

1. Planning runs continuously in `gpt-5.6-sol` / `ultra`. Select a dependency-coherent batch by workload, not a fixed issue count; typical size is 10-15 ordinary tickets, fewer heavy tickets, or more small tickets.
2. The plan must record acceptance, dependencies, files/contracts, TDD and evidence, recovery/security/privacy/performance/UX constraints, and `owner + model + effort + reason + dispatch gate + escalation triggers` for each ticket/cluster.
3. Ask all material questions once at the end of planning, revise, lock, and stop. The user switches the parent task to `gpt-5.6-sol` / `xhigh`; the model cannot silently change itself.
4. Execution then runs the whole locked batch continuously. Do not stop between tickets/PRs for routine approval. Multiple PRs are review boundaries, not user checkpoints.
5. The Sol xhigh coordinator owns ordering, coupled/high-risk code, integration, conflicts, reviews, and final verification. Use `gpt-5.6-terra` / `xhigh` for well-specified production features and `gpt-5.6-terra` / `high` for narrow mechanical work with strong objective tests. Never downgrade because of price alone.
6. Subagents must have disjoint write scopes. Serialize shared audio/crypto/API/recovery files. Review every returned patch before integration.
7. Author tests before production code, but on this 8 GB Mac implement the complete batch before disruptive execution. During coding use only negligible checks such as file inspection, `git diff --check`, generated-file drift, AST/parse checks, and focused static inspection.
8. Consolidate Xcode/UI/resource work into one announced 45-60 minute end-of-batch window. Wait for the user's `ready`, build once with shared caches and `-jobs 2`, then run the smallest complete matrix.
9. Never run or touch Docker, Testcontainers, or Compose locally without a new explicit approval immediately before that command group. CI may use isolated services.
10. Standing authorization applies to every batch: after independent exact-final-head review, all required CI is present and green, ancestry/base is correct, and the PR is mergeable, merge automatically in dependency order without asking again. It does not authorize deployment, destructive actions, force-push, branch deletion, protection bypass, missing/failed CI, production changes, paid/privacy expansion, or scope drift.
11. A ticket closes only when its completion evidence exists. Missing CI is missing, not green; merged is not deployed.

Stop and return to Sol Ultra only if a material architecture assumption fails, including one-stream ScreenCaptureKit coverage, stable separate outputs, encrypted file-backed upload feasibility, or downstream suitability of part+manifest originals.

## 3. Locked batch scope

This batch is issue #126 plus #27-#35:

- #126 native-only cutover.
- #27 manifest/HTTPS contract.
- #28-#31 permissions, two-track capture, callback/timeline, encrypted spool.
- #33-#35 authenticated server ingest, immutable storage, seal/reconciliation.
- #32 native upload/relaunch/recovery integration after the server contract.

Issues #36-#38 are deliberately later: all-app/failure coverage, 10/60/120-minute benchmarks and PCM16-vs-PCM24 evidence, then stable signing/DMG/permission persistence.

At this snapshot #27-#38, #116, and #126 are open on GitHub.

## 4. Repository and worktrees

The primary repository moved from `/Users/frank/Documents/ChatGPT/TAM Project` to:

```text
/Users/frank/Documents/Mias/tam-forge
```

The move left absolute `.git` pointers stale. On 2026-09-01 they were repaired from the new primary checkout with `git worktree repair`; no source change was lost. Existing batch worktrees:

```text
/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-plan
/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-contract
/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-capture-spool
/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-server-ingest
/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-upload
```

If Git again reports the old path, do not clone over or delete a worktree. From the primary checkout run `git worktree list --porcelain`, inspect both pointer directions, then use `git worktree repair <affected-worktree-path>`.

## 5. Exact branch stack and current state

Merge order is C0 -> R1 -> R2 -> R3 -> R4. No force-push.

| Layer | Branch | Snapshot head | State |
|---|---|---:|---|
| C0 | `codex/native-cutover-batch-02-c` | `e13a03fa2cb47ebdebaa5365b7aba3cf2a2b67b9` | Implementation complete in the prior pass; based on PR #131 head. |
| R1 | `codex/native-recording-batch-03-contract` | `2406ebf25d9592ecdec7f39a6dfa70be974538f4` | Complete and independently approved at this exact head by static review; runtime suites deferred. |
| R2 | `codex/native-recording-batch-03-capture-spool` | `f15a1d06d174ae2b0bc96dc9c25f957e4fde0cb9` | **WIP snapshot, not complete and expected not to compile yet.** Continue here first. |
| R3 | `codex/native-recording-batch-03-server-ingest` | `99daa1eb6c38bffa497d834a0c7607eb457b6a57` | Clean/static checks passed, but based on pre-WIP R2 `5f8c9ed`; rebase after final R2. |
| R4 | `codex/native-recording-batch-03-upload` | `99b79dd982f7e6ea4386f9708f7319be12c0d8af` | Older approved implementation; must rebase and adapt after final R3. |

R1 contains the canonical manifest/OpenAPI contract: exact two-track lineage, one-sample timing tolerance, UTC/120-minute bounds, mandatory release gates, status/seal consistency, canonical unpadded 32-byte base64url keys, chronological non-overlapping parts, native bearer security, and exact int64 OpenAPI bounds.

R3 already includes owner-scoped native bearer routes, safe problem responses, PostgreSQL migration/repository/service, immutable object reservation/finalization, two-track seal, reconciliation, source-lineage integration fixtures, timeline-hash participation, and precise OpenAPI regressions. Its lightweight AST/generation/drift/diff checks passed before the handoff. No test suite or Docker integration was run.

## 6. R2 WIP: exact continuation

The prior R2 head `5f8c9ed398818cb83da09fec02539fbddf9482a8` received a second static review. Everything was accepted except two P1 findings:

1. A sealed spool could not detect removal of a complete aligned record suffix or an entire track file.
2. The shared timeline origin depended on callback arrival order; a later callback with an earlier timestamp could fail or shift ranges, and one-track startup could partially seal.

Commit `f15a1d0` preserves an interrupted test-first amendment. It currently contains:

- schema-3 authenticated per-track checkpoint work in `EncryptedRecordingSpool.swift`;
- checkpoint fields for exact record count, physical file bytes, and terminal canonical sample end;
- missing-file/checkpoint-mismatch unrecoverable corruption handling;
- tests for aligned truncation, missing track, matching-checkpoint ciphertext corruption, callback-order-independent startup, startup bound failure, missing-track finish, and coordinator no-seal;
- the focused spec and plan under `docs/superpowers/specs/` and `docs/superpowers/plans/`.

It is intentionally marked WIP because the interruption occurred before capture/coordinator production code was added. The new tests refer to startup-gate APIs and `requiredTracksMissing` behavior that do not exist yet. Do not run the final matrix or claim this head green.

Continue R2 in this order:

1. Read `docs/superpowers/specs/2026-09-01-r2-sealed-checkpoints-startup-origin.md` and its adjacent plan.
2. Finish and review checkpoint persistence/recovery. A sealed state must have exactly one checkpoint for each track. Recovery must scan trusted complete record metadata, compare record count/file bytes/terminal end, reject a missing expected file, suppress exact corrupt gaps when the checkpoint mismatches, and still permit an exact corrupt-ciphertext gap when independently authenticated metadata and the full checkpoint match.
3. Add a bounded two-track startup gate in the capture pipeline. Buffer chunks, dropped intervals, and failed intervals until both tracks have anchors; use the minimum presentation anchor independent of arrival order; replay deterministically by anchor/insertion order.
4. Bound startup memory to at most one canonical second per track and a fixed event count. If the second track never appears by the bound or by finish, emit one terminal `requiredTracksMissing`, discard buffered startup audio, and fail closed.
5. Ensure dropped/failure intervals can establish a startup anchor; do not let any event silently establish a one-track origin.
6. Propagate the terminal startup failure through the source/coordinator. Drain already accepted work and pending gap writes, but never seal; preserve the unsealed spool in `NeedsAttention`.
7. Preserve all earlier invariants: one-second accumulation, exact separated gaps, stop-acceptance boundary, callback close/drain barrier, bounded callback handoff, source lineage, authenticated gap journal, storage caps, and no seal after storage persistence failure.
8. Use only `git diff --check`, Swift parser/AST inspection, and manual diff inspection now. Commit a normal follow-up after `f15a1d0`; no force-push or history rewrite is needed.
9. Obtain a new independent exact-head review. The former R2 reviewer must verify both P1s, not merely review the diff superficially.

## 7. R3 rebase after final R2

R3 is clean at `99daa1e` and currently descends from `5f8c9ed`. After R2 is complete and exactly reviewed:

```bash
cd '/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-server-ingest'
git status --short
git rebase --onto <FINAL_R2_HEAD> 5f8c9ed398818cb83da09fec02539fbddf9482a8
```

Expected conflict areas are the checked OpenAPI and recording fixture/hash tests. Regenerate OpenAPI with the existing lightweight script after resolving real route components; do not hand-edit generated drift. Keep the canonical standalone Pydantic recording components because FastAPI previously rounded the signed-int64 maximum through IEEE floating-point representation.

After rebase, re-run only static AST/OpenAPI generation/drift/diff checks, inspect ancestry, and obtain an independent exact-head R3 review. PostgreSQL/object-store execution stays deferred to CI or a separately approved Docker window.

## 8. R4 rebase and adaptation

R4 has four upload commits after old R3 base `817e24c3a03abd6fc2ecf30b47f6fcc41c65a11b`. After final R3:

```bash
cd '/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-upload'
git status --short
git rebase --onto <FINAL_R3_HEAD> 817e24c3a03abd6fc2ecf30b47f6fcc41c65a11b
```

Then adapt R4, test-first, without running the heavy suite:

- Add the native source-lineage payload with sample start/count, source rate/channels, device ID, route, presentation start/end/timescale, and conversion version.
- Build/coalesce lineage from each original authenticated one-second record **before** grouping records into upload parts. Coalesce only contiguous records with equal source metadata. Lineage covers audio only, excludes gaps, uses timescale `1_000_000_000`, and computes presentation end from exact 48 kHz sample duration within the R1 tolerance.
- Map conversion version 1 to `tamforge-pcm16-v1`; unknown versions fail upload.
- Include lineage in manifest validation and the canonical timeline hash.
- Port final R2 schema/state/gap-journal/checkpoint/tamper/structural-corruption rules into R4's streaming `RecordReader`. Do not call a whole-recording recovery API or load a multi-gigabyte recording into RAM.
- Block upload on any unrecoverable corruption or ignored sealed tail. Preserve exact recoverable corrupt gaps only when all authentication/checkpoint rules allow them.
- Preserve R2 timestamps and both release gates. Never delete after audio `201`; expose waiting for transcript lineage.
- Keep one encrypted upload file/part in memory or on disk at a time and the existing 60-second maximum.
- Generate canonical base64url part keys and reject noncanonical trailing characters.
- Preserve replay after relaunch, idempotent identity, file mutation checks, 401 refresh behavior, redacted sensitive headers, and no root-key transmission.
- Preserve final checked OpenAPI components and regenerate after route conflicts.
- Extend focused tests for v3 tamper/checkpoints, route/format lineage changes and coalescing, unknown conversion, unrecoverable upload block, release gates/no early deletion, and HTTP replay/relaunch.

Finish with exact-head R4 review. Do not rely on its old approval after this rebase/adaptation.

## 9. Verification and delivery gates

No Xcode suite, UI automation, hardware capture, Docker/Testcontainers, or full backend suite was run for R1-R4 before this handoff. Tests were authored; that is not passing evidence.

After all five heads stabilize and all static reviews approve:

1. Announce a single 45-60 minute Mac-impact window and wait for `ready`.
2. Run Python unit/security/OpenAPI/policy checks once for the combined stack, without Docker.
3. Build the native app once using shared DerivedData and `-jobs 2`; run all affected Swift unit targets together.
4. Run one short real-Mac explicit Start/Stop smoke with browser/local playback plus microphone, separate levels, encrypted spool recovery, and isolated/mock upload UI.
5. Run affected native UI journeys once. Do not run the 10/60/120-minute benchmark; that is #37.
6. Fix failures and rerun only failing slices. Then run one final exact-head combined matrix.
7. Let required remote CI run PostgreSQL/object-store integration. Local Docker still requires a separate explicit approval.
8. Bind independent review and CI to each exact final SHA, create/update the stacked PRs, and merge automatically C0 -> R1 -> R2 -> R3 -> R4 only when every required check is present/green and each PR is mergeable.

## 10. Current GitHub blocker

PR #131 (`codex/native-parity-batch-02` -> `main`) is open at exact head `100f01969ba538805d63ebbcfbbdc25c9493b12c`. At the 2026-09-01 snapshot, run `33527281734` still shows eight failed required jobs and merge state `UNSTABLE`. The user reports the GitHub budget was fixed, but the checks shown by GitHub have not yet been rerun successfully. Rerun required checks at the same exact head and verify actual job execution; old zero-step/billing failures are not green.

C0 depends on PR #131. Descendant development and review may continue, but merge order cannot bypass it.

## 11. Safe resume checklist

```bash
cd /Users/frank/Documents/Mias/tam-forge
git fetch origin --prune
git worktree list --porcelain

cd '/Users/frank/.config/superpowers/worktrees/TAM Project/native-recording-batch-03-capture-spool'
git status --short
git branch --show-current
git rev-parse HEAD
```

Expected first working branch is `codex/native-recording-batch-03-capture-spool` at or after `f15a1d0`, clean before new edits. Read this handoff, the locked batch plan, and the focused R2 spec. Revalidate GitHub PR/issues/heads because those facts can drift.

Do not restart planning, rewrite finished R1, run per-ticket heavy tests, use the obsolete `codex/recording-speech` implementation, or merge/deploy from this WIP snapshot.

## 12. Copy/paste resume prompt

```text
Continue TAM Forge from docs/project/native-recording-batch-03-handoff.md.

Use the repository at /Users/frank/Documents/Mias/tam-forge and the existing native-recording-batch-03 worktrees. Read README.md, AGENTS.md, CODEX.md, the handoff, the locked plan at docs/superpowers/plans/2026-09-01-tam-forge-native-recording-batch-03.md, and the focused R2 checkpoint/startup spec before editing. Use the developing-ticket-batches process, Ponytail full, and Caveman ultra.

The parent coordinator must be gpt-5.6-sol xhigh. Planning is already locked; do not restart it. Continue autonomously through the complete batch. Start on codex/native-recording-batch-03-capture-spool at or after WIP f15a1d0, finish the authenticated sealed checkpoints and bounded two-track startup-origin/fail-closed coordinator work test-first, perform only lightweight static checks, commit, and obtain an independent exact-head review. Then rebase/review R3 exactly as documented, rebase and fully adapt R4 source-lineage/streaming-recovery/release-gate behavior, and finish all code before asking me for one final test window.

Do not run Xcode/UI/hardware/heavy suites during implementation. When all code and exact-head reviews are ready, tell me the expected 45-60 minute impact and wait for my ready. Do not run Docker/Testcontainers/Compose without separate explicit approval. Merge every stacked PR automatically in order only after exact-final-head review, required CI green, correct ancestry, and mergeability; do not ask for merge approval. Do not deploy or perform destructive/production/privacy/spend actions.

Use Terra xhigh subagents only for well-specified production features and Terra high only for narrow mechanical work with strong tests; serialize overlapping audio/crypto/API/recovery files. Preserve the 8 GB Mac and do not waste tokens on repeated planning or tests.
```
