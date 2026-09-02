# TAM Forge Native Recording Batch 03 Implementation Plan

> **Status:** Locked on 2026-09-01. D1–D4 approved by the user.
> **Planning model:** `gpt-5.6-sol` / `ultra`
> **Execution coordinator:** `gpt-5.6-sol` / `xhigh`
> **Communication:** Ponytail `full`; Caveman `ultra`

**Goal:** Finish native-only cutover, then implement the complete durable two-track recording pipeline from explicit Start through encrypted local recovery, authenticated resumable upload, and immutable server seal without repeatedly taking over the user's 8 GB Mac.

**Scope:** #126 plus #27–#35. Ten tickets, five stacked PRs. #36–#38 remain the next validation/release batch because all-app coverage, 10/60/120-minute benchmarks, stable signing, DMG installation, and permission-persistence drills require long dedicated Mac windows.

**Architecture:** SwiftUI owns visible recording state. ScreenCaptureKit emits separate system-audio and microphone sample buffers on one shared media timeline. A bounded callback handoff feeds conversion and timeline actors, then one-second PCM16 records enter an append-only CryptoKit AES-GCM spool. After Stop, bounded encrypted upload-part files go through `URLSessionUploadTask` to owner-scoped FastAPI routes. PostgreSQL reserves and finalizes each immutable part around existing private object storage. Seal stores one canonical manifest object per track referencing immutable PCM parts; no second full-size audio copy is created. The local spool remains until both server audio `201 Created` and later transcript-lineage acceptance exist.

**Primary stack:** Swift 6, SwiftUI, ScreenCaptureKit, AVFoundation/Core Media/Core Audio, CryptoKit, Security/Keychain, URLSession; FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, existing S3-compatible private object store.

## 1. Current facts and boundaries

- PR #131 is open at exact head `100f01969ba538805d63ebbcfbbdc25c9493b12c`. Local native/backend evidence and two exact-head reviews pass. GitHub Actions run `33527281734` failed before checkout with eight zero-step billing/spending-limit failures. It is not green and cannot merge yet.
- #126 C1 legacy-client removal is the remaining E10 work. It can be developed on a stacked branch while #131 waits, but it cannot merge first.
- #117–#125 are closed. After #126 merges, verify all children and close #116.
- `codex/recording-speech` is reference-only old Python/WSS/44.1 kHz work. Do not merge or cherry-pick it. Reuse only reviewed invariants such as deterministic identifiers, immutable ranges, idempotency, explicit gaps, and object-first acknowledgement.
- Recording captures all audio macOS exposes to ScreenCaptureKit plus the selected microphone. DRM/protected or otherwise non-shareable audio remains outside the technical contract and must be shown as an explicit limitation, never false success.
- Recording is always explicit Start/Stop with a persistent visible indicator. Never hidden, automatic, or consent-bypassing. No live audio monitoring/loopback.
- Canonical capture starts at signed PCM16, 48 kHz, microphone mono and system stereo. PCM24 remains rejected unless #37 later proves material analysis gain.
- Mac constraints: 8 GB RAM, serial Xcode with `-jobs 2`, one upload/conversion job at a time, no Docker/testcontainers without separate approval, no disruptive test per ticket.
- Production and preview API hosts remain `.invalid`; merged code is not deployment. No server provisioning, production credentials, paid service, Developer ID, notarization, local ASR, pronunciation, or AI feedback in this batch.

## 2. Locked cross-cutting contracts

### 2.1 Capture and timeline

- Ask for microphone permission only after a user recording action. Check `AVCaptureDevice.authorizationStatus(for: .audio)` before requesting. Treat denied, restricted, missing device, silent/zero-level input, and device-in-use conditions as distinct visible preflight results.
- Check screen-capture authorization and enumerate `SCShareableContent`. Use the broadest authorized display filter. Keep TAM Forge audio included because interviewer/TTS audio belongs in the permanent original.
- Prototype one `SCStream` first with `.audio` and `.microphone` outputs. Retain no video frames. If ScreenCaptureKit requires a screen output for stable audio, configure the minimum viable discarded frame stream; do not persist pixels.
- A single display-scoped stream is provisional until #28 proves internal/external-display placement. Add a second stream only if real coverage evidence requires it and deterministic duplicate prevention is proven.
- Inspect actual `CMAudioFormatDescription` on every buffer. Convert off callback to canonical 48 kHz signed interleaved PCM16. Preserve source sample rate, channels, device ID, presentation timestamp, route changes, discontinuities, and conversion version in lineage.
- Common timeline origin is the first accepted host/media timestamp. Each track uses integer sample ranges. Missing or dropped ranges become explicit gaps; never synthesize hidden continuity or silently pad.
- Callback path validates, copies one bounded chunk into a fixed-capacity handoff, and returns. No encryption, hashing, conversion, JSON, file I/O, network, or UI work in callbacks. Queue overflow emits an exact gap and health error.

### 2.2 Encrypted local spool

- One random 256-bit root key per recording, stored in the Data Protection Keychain under a recording-specific account. Never store key material in preferences, manifests, logs, task descriptions, crash text, or source.
- App-container Application Support spool directories and files use owner-only permissions. Audio remains AES-GCM encrypted even when FileVault is present.
- Track logs contain independently authenticated records of at most one second. Fixed binary versioned headers and AES-GCM associated data bind recording ID, track, sequence, sample start/count, canonical/source format identity, presentation timestamp, and payload length/hash.
- Recovery scans length-prefixed records, authenticates each complete record, ignores only an incomplete trailing write, and emits explicit missing/corrupt ranges. It never guesses audio. State changes use atomic metadata replacement or append-only journal entries.
- Start preflight reserves the configured worst-case size: 120-minute session cap, 2.5 GiB per-recording cap, 5 GiB global cap, and 8 GiB free-disk reserve. Pending recordings are never silently evicted. They become `NeedsAttention` with explicit Retry or Discard.
- `audio_created_on_server` and `transcript_lineage_accepted` are separate release gates. This batch can set only the first. Until E4 supplies the second, crypto-shred/delete remains forbidden.

### 2.3 Upload part and REST contract

- Upload begins only after local capture stops and local spool seal succeeds.
- Upload grouping reads authenticated one-second records and creates at most 60 seconds of one track per upload part. At 48 kHz PCM16 this bounds plaintext near 5.76 MiB mono or 11.52 MiB stereo. Process one part at a time.
- Upload files remain encrypted. Default recommendation D2 derives a unique per-part AES-GCM key from the spool root with HKDF-SHA256, writes only ciphertext to disk, and sends the derived part key only in a redacted authenticated HTTPS header. Canonical version/range/format/hash metadata is AES-GCM associated data and must match the typed request headers. FastAPI decrypts one bounded part in memory, verifies plaintext SHA-256/range, then persists canonical PCM bytes. The root key never leaves the Mac.
- Every mutation requires the existing native bearer identity. No recorder/device credential, cookie ambiguity, query token, or production fixture bypass.
- Proposed versioned endpoints:
  - `POST /api/v1/recordings` — idempotently reserve an owner-scoped recording and two declared tracks.
  - `PUT /api/v1/recordings/{recording_id}/tracks/{track_id}/parts/{sequence}` — encrypted binary body plus generated typed headers for immutable range, plaintext/ciphertext hashes, key, nonce/version, and idempotency.
  - `POST /api/v1/recordings/{recording_id}/seal` — complete manifest, ordered part identities, explicit gaps, PCM hash, timeline hash, capture/conversion lineage.
  - `GET /api/v1/recordings/pending` and `GET /api/v1/recordings/{recording_id}` — owner-scoped recovery/status without secrets.
- Use generated OpenAPI models for JSON and header contracts. File upload uses a narrow recording transport over an ephemeral/default `URLSessionUploadTask(fromFile:)` because it must remain file-backed. Do not use a background-session daemon that may persist the sensitive part-key header outside the encrypted spool. If the process exits, relaunch reconstructs the same idempotent part from the spool. Do not duplicate broad API/auth logic.
- One deterministic idempotency key per create/part/seal command. A retry with identical identity/content returns existing state; reused identity with different bytes/range returns `409`.
- Client persists only non-secret task identity, recording/track/part IDs, file identity, retry count, and expected hashes. Reconcile active tasks while the process lives; relaunch converts prior in-flight journal entries back to pending and recreates them idempotently. A `401` refreshes native auth and creates a new task; it never changes part identity.

### 2.4 PostgreSQL and immutable object storage

- New Alembic revision follows `20260828_0012_native_auth.py`; no runtime schema creation.
- Tables: `recordings`, `recording_tracks`, `recording_parts`, and `recording_gaps`. Use owner FKs, UUID client identities, exact check/unique constraints, UTC lifecycle timestamps, immutable provenance, bounded states, and indexes for owner/state plus pending reconciliation.
- Reserve the expected part row in PostgreSQL before object persistence. Store to a deterministic content-addressed key. In a second transaction, mark stored and advance contiguous high-water state. External ACK happens only after both storage confirmation and DB commit.
- This is not a distributed transaction. If DB finalize fails after object persistence, the reserved row and deterministic key make retry/reconciliation converge. Never claim atomic S3/PostgreSQL commit.
- Same range plus same hash is idempotent. Same logical range plus different hash is a conflict. Overlaps, format changes, owner mismatches, sequence regressions, impossible sample arithmetic, and unknown versions fail closed.
- Seal locks the aggregate, validates exact ordered coverage by stored parts plus explicit gaps, then streams immutable parts to recompute byte and timeline hashes. Store one immutable canonical JSON manifest object per track; part objects plus manifest are the permanent original. Do not create a duplicate full-track PCM/WAV object in this batch.
- Final `201 Created` occurs only after both canonical track manifests exist and the recording DB aggregate is `stored`. The response distinguishes complete coverage from durable `stored_with_gaps`; degraded audio remains visible and cannot masquerade as complete. A retry may adopt an identical existing manifest; conflicting content never wins.
- Object-provider errors stay internal. Public RFC 9457-style problems expose stable safe codes only. Sensitive part-key headers must be redacted from diagnostics and access-log tests.

### 2.5 UI and app lifecycle

- `NativeShellComposition`, not route-scoped `NativeWorkspaceState`, owns the recording coordinator for the app-process lifetime. Navigation, feature refresh, session-view recreation, or authentication expiry cannot deallocate active capture or its spool writer.
- Add a Recording destination using existing shell patterns. Start shows a single preflight/consent summary; active state shows elapsed time, both track levels/health, selected microphone, route, disk reserve, and Stop.
- Recording status is global inside the app so navigation cannot hide active capture. Closing a view never stops capture. Quit/sleep/route/interruption events transition through the coordinator and preserve recoverable state.
- Explicit sign-out while recording requires Stop-and-seal confirmation; an unexpected bearer expiry pauses only upload and requests reauthentication, never discards or silently stops local capture.
- Stop is idempotent. Disable duplicate starts. App relaunch discovers pending encrypted spools and offers Resume Upload, Inspect problem, or explicit Discard. Discard is the only local destructive action and always requires confirmation.
- Do not add waveform rendering, video preview, live transcription, noise suppression, automatic gain, cloud AI, custom audio-device drivers, BlackHole, or aggregate devices.

## 3. PR stack and continuous execution

Exact stack:

1. `codex/native-cutover-batch-02-c`, based on PR #131 head `100f01969ba538805d63ebbcfbbdc25c9493b12c`.
2. `codex/native-recording-batch-03-contract`, based on the final C0 head.
3. `codex/native-recording-batch-03-capture-spool`, based on the final R1 head.
4. `codex/native-recording-batch-03-server-ingest`, based on the final R2 head.
5. `codex/native-recording-batch-03-upload`, based on the final R3 head.

Branches may be developed while an ancestor waits on external CI, but merge only in this order. Never force-push or pretend descendant evidence makes an ancestor green.

### PR C0 — Finish #126 native-only cutover

**Base:** exact PR #131 head `100f019`; merge only after #131.

- Add this locked plan.
- Port `scripts/verify_bootstrap.mjs`, `scripts/verify_compose.mjs`, and compose rejection coverage to focused Python modules/tests before deleting Node versions.
- Remove tracked `apps/web/`, root product package/pnpm manifests, TypeScript OpenAPI generation, Vite/Playwright steps, and web-only CI job.
- Preserve durable backend journey as `e2e`, native UI, native unit, backend unit/integration, OpenAPI, secret scan, signed Release bundle, Compose safety, backend browser-auth compatibility, and historical records.
- Make demo seeding data-only; no browser cookie output. Make OpenAPI drift native-only. Add narrow repository-policy regression against reintroduced product web/Node runtime.
- Update maintained README/testing/development docs and Makefile. No Node invocation remains in active install/check paths.
- Exact completion: no tracked active product Node/web runtime, reviewable deletion inventory, all #126 acceptance evidence, exact-head reviews and green CI. Close #126, then #116 only after every E10 child is verified closed.

**Routing:** Terra `high` worker may own the explicit mechanical port/deletion file set. Sol `xhigh` owns inventory, CI/security semantics, integration, review, and closure.

### PR R1 — #27 recording manifest and HTTP contract

- Create `apps/backend/src/tamforge_backend/recordings/contracts.py` and `schemas.py`; register only routes that have executable service behavior in later PRs, never placeholder-success endpoints.
- Add canonical fixture `tests/fixtures/recordings/recording-manifest-v1.json` plus invalid-version/range/gap/hash fixtures.
- Define UUID/idempotency, format, part, gap, timeline, seal, status, and safe problem contracts once in Pydantic/OpenAPI; generated Swift consumes them.
- Document canonical byte encoding and hash domains. Golden tests prove stable serialization, unknown-version rejection, integer/range overflow checks, exact two-track identities, no overlap, and deterministic hash input.
- Correct live issue dependencies per D3 before implementation if approved.

**Files:** backend recordings package/tests, checked-in OpenAPI, generated Swift contract, fixture and maintained API docs.

**Routing:** Sol `xhigh`; crypto/privacy/audio/API architecture. No delegation.

### PR R2 — #28–#31 native capture, timeline, and encrypted spool

- Add `Features/Recording/` models, permissions/preflight, ScreenCaptureKit source, bounded callback queue, converter/timeline, Keychain key store, encrypted spool, recovery, coordinator, SwiftUI destination, and focused fakes.
- Add screen-recording permission diagnostics, microphone selection/authorization, route/free-space checks, explicit coverage probe state, no-audio/zero-level warnings, global active indicator, idempotent Start/Stop, sleep/wake and interruption handling.
- Capture `.audio` and `.microphone` separately, convert outside callbacks, create exact gaps, write one-second authenticated records, and recover crash tails.
- Unit tests are authored before production code but execution is deferred to the one end-of-batch test window. Tests cover permissions, topology selection, callback overflow, conversion arithmetic, drift/gaps, format/route changes, AES-GCM tamper/AAD failures, crash-tail recovery, caps/reserve, Keychain lifecycle, cancellation, and state races.

**Files:** new recording feature/core files, `TAMForgeApp.swift`, `AppDependencies.swift`, Info.plist/entitlements only as required, Xcode project, focused unit/UI test sources.

**Routing:** Sol `xhigh`; ScreenCaptureKit, real-time callback, concurrency, encryption and recovery stay coordinator-owned. A Terra `xhigh` worker may implement only isolated SwiftUI presentation after state contracts lock.

### PR R3 — #33–#35 authenticated durable server ingest and seal

- Add Alembic `20260901_0013_recording_ingest.py`, ORM models/validators, repository/service/routes, bounded AES-GCM part decode, object-store adapter use, reconciliation, manifest seal, dependencies, exception mapping, model registry, settings and API registration.
- Reuse `get_authenticated_owner`/`require_csrf_owner`, `ObjectStore`, immutable object keys, audit/outbox patterns, transaction scopes, safe diagnostics, and existing fake/S3 contract style.
- Add unit tests for every trust boundary and state transition. Add integration tests for real native bearer owner scoping, migration constraints, duplicate/reorder/conflict, object-write/DB-failure recovery, exact high-water progression, seal gaps, manifest identity, and fresh-session persistence reads.
- Docker-marked PostgreSQL/MinIO execution remains remote CI unless the user separately approves one local final integration window.

**Files:** backend recordings package, migration/model registry, settings/dependencies/API, unit/integration/security tests, OpenAPI regeneration.

**Routing:** Sol `xhigh` owns auth, migration, object/DB boundary, conflict semantics and integration. Terra `xhigh` may implement bounded Pydantic/route adapters or mechanical migration tests only after contracts lock; Sol reviews every security/state change.

### PR R4 — #32 resumable native upload and recovery integration

- Add encrypted upload-part builder, HKDF key derivation, redacted header construction, file identity checks, ephemeral/default URLSession abstraction, journal reconciliation, one-at-a-time retry policy, generated API status calls, and spool release-gate state.
- Integrate Stop to local seal to server create/part/seal. Preserve spool after final audio `201`; expose waiting-for-transcript state rather than delete.
- Tests cover file mutation, process/app restart, offline retry, duplicate completion, expired bearer/401, cancellation, server conflicts, partial track progress, task/session reconstruction, final 201 semantics, and forbidden early key/file deletion.
- Add one synthetic end-to-end fixture path joining native spools to mocked HTTP responses. Real service/database/object-store execution remains in R3 integration CI.

**Files:** recording upload/recovery Swift files, generated contract use, app wiring, focused tests and runbook.

**Routing:** Sol `xhigh`; URLSession lifecycle plus crypto/recovery coupling. Terra `xhigh` may implement isolated status presentation after coordinator locks state.

## 4. Ticket completion matrix

| Ticket | Completion evidence | Owner/model |
|---|---|---|
| #126 | Legacy runtime removed; replacements exact-head green; PR merged; #116 child audit | Sol xhigh + Terra high mechanical |
| #27 | Golden v1 contract/fixtures, generated Swift agreement, unknown/conflict cases | Sol xhigh |
| #28 | Permission/preflight diagnostics and coverage prototype; one final real-Mac smoke | Sol xhigh |
| #29 | Separate synchronized 48 kHz mic/system tracks with actual-format/timeline lineage | Sol xhigh |
| #30 | Bounded callback path; off-callback conversion/hash/I/O; explicit overflow gaps | Sol xhigh |
| #31 | AES-GCM one-second spool, recovery, Keychain, caps/reserve, no early deletion | Sol xhigh |
| #32 | File-backed encrypted idempotent upload, restart recovery, server-201 semantics | Sol xhigh |
| #33 | Native bearer owner-scoped create/part/seal/status routes | Sol xhigh |
| #34 | Reserved/stored immutable parts, deterministic retry, transactional high-water ACK | Sol xhigh |
| #35 | Exact seal/reconciliation, permanent part+manifest originals, final durable 201 | Sol xhigh |

## 5. Host-friendly verification window

No Xcode UI, long Xcode suite, resource receipt, Docker/testcontainers, or hardware capture is run during implementation. No PR/ticket is called verified from code existence.

During coding, permit only file inspection, `git diff --check`, generated-file comparison that does not build, and similarly negligible checks. Keep all test sources ready but deferred.

After all five PR heads stabilize:

1. Tell the user expected Mac impact and wait for `ready`. Initial estimate: one 45–60 minute interactive window, excluding failures.
2. Run Python unit/security/OpenAPI/policy checks once for the combined stack. No Docker.
3. Build native app once with shared DerivedData and `-jobs 2`; run all affected Swift unit targets together.
4. Run one short real-Mac recording smoke: explicit permission/preflight, browser/local playback plus microphone, separate track levels, Stop, encrypted spool recovery, and mocked/isolated upload UI. No 10/60/120-minute benchmark.
5. Run affected native UI journeys once. Do not repeat the old five-minute parity resource receipt unless app-shell/resource behavior changed materially and review cannot bind the prior executable evidence.
6. Fix failures and rerun only failing slices. After stabilization, run one exact-head combined matrix.
7. Remote CI executes PostgreSQL/MinIO integration and every required context on each merge candidate. If billing remains blocked, development/review may continue but merge and ticket closure remain blocked.
8. Independent exact-final-head review for each PR; merge automatically in stack order when base/dependencies, reviews, required CI and mergeability are all valid.

#36 later runs Zoom/Teams/Meet/browser/display/route/interruption/failure coverage. #37 later reserves the Mac for 10/60/120-minute resource evidence and PCM16-vs-PCM24 value testing. #38 later handles stable signing, DMG and clean-user permission persistence. None is silently claimed by this batch.

## 6. Recovery, security and stop conditions

- Never print bearer tokens, part keys, spool keys, audio bytes, signed upload URLs, or sensitive headers. Diagnostics contain method, redacted path, stable IDs and safe status only.
- Every local destructive discard requires explicit confirmation. No production bucket/DB/config/deployment mutation in this batch.
- Stop for new consent/privacy scope, hidden/automatic recording, paid Apple/GitHub/runner action, production provisioning, force push, branch protection change, destructive cleanup, Docker approval, or a required architecture change.
- Return to Sol Ultra and revise the locked plan if the hardware prototype disproves one-stream coverage, ScreenCaptureKit cannot provide stable separate outputs, encrypted file-backed upload is infeasible, or canonical manifest originals cannot support downstream speech consumers.
- A failed/missing CI check remains failed/missing. Never bypass protection or merge from local evidence alone.

## 7. Decision packet

### D1 — Batch scope

**Decision:** Approved on 2026-09-01.

**Recommendation:** Lock #126 + #27–#35. Ten tickets: one nearly-complete cutover plus nine coupled recording implementation tickets. Leave #36–#38 for the dedicated verification/release batch.

**Alternative:** Include #36–#38 now. This adds hours of Mac occupation and release decisions before the core pipeline stabilizes.

**Impact/reversibility:** Planning/branch grouping only; reversible before implementation.

### D2 — Encrypted file-backed upload

**Decision:** Approved on 2026-09-01.

**Recommendation:** Keep plaintext off disk. Derive a unique per-part key with HKDF from the Keychain spool root, encrypt each bounded upload file with AES-GCM, send only the derived part key in a strictly redacted native-bearer HTTPS header, decrypt bounded data in FastAPI memory, and persist verified canonical PCM.

**Alternatives:** Plaintext staging file is simpler but weakens the encrypted-local-storage rule. Server public-key envelope avoids sending a symmetric part key directly but adds key provisioning/rotation and more code without meaningful protection beyond authenticated TLS for this single-user app.

**Impact/reversibility:** Changes protocol, backend dependency (`cryptography`), tests and threat model. Versioned, therefore reversible through v2; expensive after data exists.

### D3 — Correct upload/server dependency order

**Decision:** Approved on 2026-09-01.

**Recommendation:** Update issue relationships so #33 depends on #27, #32 depends on #31 and #33, #34 depends on #33, and #35 depends on #32 and #34. Implement server contract before generated native upload integration.

**Alternative:** Preserve current linear #31 -> #32 -> #33 chain and implement #32 against mocks/manual duplicate types. This creates avoidable contract drift and later rewrite.

**Impact/reversibility:** GitHub metadata and PR order only; easily reversible. No scope change.

### D4 — Permanent original shape

**Decision:** Approved on 2026-09-01.

**Recommendation:** Immutable PCM part objects plus one canonical manifest object per track are the permanent original. Seal verifies whole-track bytes/timeline and stores manifests; no duplicate full-track PCM/WAV object. Later 16 kHz/WAV/analysis files are versioned derivatives.

**Alternative:** Build a second monolithic WAV at seal. Easier manual playback, but doubles temporary/permanent I/O and storage, increases server disk needs, and adds no English-analysis fidelity.

**Impact/reversibility:** Storage contract. A later export/derivative job can create WAV without changing the original.

## 8. Execution handoff after decisions

D1–D4 are locked. Live issue dependencies must match D3 before implementation. Commit this planning state on the C0 branch and stop. Execution uses `gpt-5.6-sol` / `xhigh`. Planned narrow mechanical lanes use Terra `high`; well-specified isolated production UI/schema lanes may use Terra `xhigh`. The coordinator integrates all shared contracts and executes the whole batch continuously until the single final verification window or a true stop condition.
