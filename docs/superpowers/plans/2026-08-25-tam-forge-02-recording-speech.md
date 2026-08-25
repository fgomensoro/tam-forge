# TAM Forge Recording and Speech Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the paired macOS recorder, loss-bounded dual-track streaming path, durable remote audio store, local versioned transcription and speech metrics, calibrated controlled-pronunciation diagnostic, and turn-priority speech interfaces for TAM Forge.

**Architecture:** The recorder writes every captured PCM frame through a bounded queue into an encrypted local recovery spool, then a background WebSocket client resends numbered frames until the backend acknowledges a contiguous sequence only after immutable object persistence and a PostgreSQL commit. The backend finalizes verified track manifests and WAV derivatives asynchronously, then a single resource-aware speech worker runs Silero VAD, `faster-whisper small.en` CPU INT8, deterministic metrics, and a separately gated controlled-pronunciation adapter. Fixed protocol, transcript, metric, and model-run schemas keep every derived result versioned and replaceable.

**Tech Stack:** Python 3.12, Tkinter, `sounddevice.RawInputStream`, `websockets`, `keyring`, `cryptography`, SQLite recovery spool, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, boto3-compatible Hetzner Object Storage, `wave`, PyAV, NumPy, Silero VAD ONNX Runtime, `faster-whisper`, pytest, Hypothesis, Ruff, mypy, React/TypeScript browser SpeechSynthesis interface, PyInstaller.

---

## Preconditions, ownership, and safety gates

- This child plan depends on the repository/bootstrap, authentication, artifact-catalog, durable PostgreSQL job service, shared `outbox_events` model/poller, and configuration foundations from the preceding implementation-plan slice. Execute Plan 1 Task 20 before this plan's Task 13. This plan registers recording/speech handlers and adds a database-clock scheduler and worker; it does not create a competing queue or outbox.
- Canonical package layout is `apps/backend/src/tamforge_backend/` for FastAPI and worker modules, `apps/recorder/src/tamforge_recorder/` for the Mac app, and `packages/protocol/src/tamforge_protocol/` for shared wire/message contracts. There is no separate worker package.
- The immutable original is ordered PCM plus its signed/versioned manifest. A finalized WAV is a derived artifact and never replaces source segments.
- The server ACK means both the immutable object and PostgreSQL catalog/high-water transaction are durable. Never ACK an in-memory frame or an object without its database commit.
- `stable-ts` is not installed in the baseline. The owner archived the repository on 2026-05-30 and paused development indefinitely. Although the archived implementation includes a faster-whisper adapter, evaluate it only as an explicitly pinned legacy experiment behind TAM Forge's transcript adapter if the supported VAD/word-timestamp baseline fails its gold-set gate.
- Free-speech Whisper probability is never a pronunciation score. Until the controlled diagnostic passes its calibration gate, pronunciation remains `not_measured` and low-confidence free-speech words remain `listen_and_verify` candidates only.
- This plan directly computes timing/fluency measures and transparent lexical/turn proxies. Grammar accuracy and communication effectiveness are later rubric-based transcript evaluations, not acoustic facts; Plan 3 must consume this plan's immutable evidence/version IDs after the learner's self-review. Listening is scored only for a versioned stimulus plus expected-proposition contract; otherwise it is `N/A`.
- No paid/external speech service, external GPU, new server, or automatic fallback may be introduced by this plan.
- Do not repurpose or delete Gastos workloads under this plan. That remains a separately approved destructive operation.
- **Docker approval gate:** no command labeled `[REQUIRES EXPLICIT DOCKER APPROVAL]` may run until the user explicitly approves Docker/Testcontainers/Compose for that execution turn. Unit tests and fakes must run first. CI may run container-backed tests on its isolated runner.
- Private gold audio, real credentials, device tokens, encryption keys, object-store payloads, and generated evaluation reports containing personal speech stay outside Git. Only synthetic fixtures and redacted aggregate reports may be committed.

## Initial stacked branch and pull-request contract

Plan 1's exact remote head is the immutable prerequisite for this slice. Before Task 1, require a clean worktree, fetch without deleting any prerequisite branch, record the prerequisite SHA, and create Plan 2's branch from that exact remote commit:

```bash
git status --short
git fetch origin --prune
git rev-parse --verify origin/feat/foundation-learning-workspace
git switch --detach origin/feat/foundation-learning-workspace
git switch -c feat/recording-speech
git rev-parse HEAD | tee /tmp/tamforge-plan-02-prerequisite-sha.txt
git status --short --branch
```

Expected: the initial `feat/recording-speech` HEAD equals `origin/feat/foundation-learning-workspace`, the worktree is clean, and the recorded SHA is copied into the eventual PR body. If either local branch already exists, the worktree is dirty, or the remote prerequisite cannot be resolved, stop and reconcile rather than reset, overwrite, or invent a base. All Plan 2 commits remain on `feat/recording-speech`.

At Task 23, push without force and open a draft stacked PR with `--base feat/foundation-learning-workspace --head feat/recording-speech`. Do not merge it before the Plan 1 PR. After an explicitly approved Plan 1 merge, perform this exact no-rewrite transition:

```bash
git switch feat/recording-speech
git status --short
git fetch origin --prune
git merge --no-edit origin/main
git push origin feat/recording-speech
gh pr edit --repo fgomensoro/tam-forge --base main
gh pr view --repo fgomensoro/tam-forge --json baseRefName,headRefName,headRefOid,isDraft
git diff --name-status origin/main...HEAD
```

Expected: the current branch remains `feat/recording-speech`, push is non-force, the PR is still draft with base `main`, and the three-dot diff contains only Plan 2 work. Stop on a dirty tree, conflict, unexpected base/head, or prerequisite content in the diff. Never delete the Plan 1 branch until this check passes.

## Fixed contracts

### Binary PCM frame v1

Every WebSocket binary message is one header followed by exactly one PCM block. Network byte order is fixed:

```text
struct !4sBBH16s16sQQQIHHI32s  # 108-byte header

magic                    4 bytes   b"TFAR"
protocol_version          uint8     1
message_type              uint8     1 = PCM_FRAME
flags                     uint16    reserved; must be zero in v1
session_id                UUID      16 raw bytes
track_id                  UUID      16 raw bytes
sequence                  uint64    starts at 0, increments by 1 per track
sample_start              uint64    first PCM frame position in this track
capture_monotonic_ns      uint64    local monotonic timestamp at callback entry
sample_rate               uint32    v1 capture default 44100
channels                  uint16    actual track channel count
sample_width_bytes        uint16    v1 value 2 (signed PCM16 little-endian)
payload_length            uint32    exact trailing byte count
payload_sha256            32 bytes  SHA-256 of trailing PCM payload
```

`sample_start` advances by `payload_length / (channels * sample_width_bytes)`. A frame whose arithmetic, format, UUID binding, size, checksum, or sequence is invalid is rejected without persistence or ACK.

### Text control messages v1

Pydantic discriminated unions own these JSON messages:

```text
client: hello, resume, stop_capture, seal_track, heartbeat
server: ready, durable_ack, resend_from, sealed, protocol_error, heartbeat_ack
```

`durable_ack.next_sequence` is the first sequence the server does not yet durably own; it starts at `0`. The client may delete only rows with `sequence < next_sequence`. The server rejects a duplicate sequence with a different payload checksum as `CHECKSUM_CONFLICT`; it never silently chooses one copy.

### Deterministic object keys

```text
recordings/{session_uuid}/tracks/{track_uuid}/segments/
  {first_sequence:020d}-{last_sequence:020d}/{batch_sha256}.pcm

recordings/{session_uuid}/tracks/{track_uuid}/manifests/
  {manifest_version:08d}/{whole_pcm_sha256}.json

recordings/{session_uuid}/tracks/{track_uuid}/derived/
  wav/{derivation_version}/{whole_pcm_sha256}.wav
```

Object metadata includes content SHA-256, byte count, format, session/track IDs, inclusive sequence range, and schema version. No user text, company, prompt, or transcript appears in an object key.

## File map

### Shared protocol

- `packages/protocol/pyproject.toml` — isolated protocol dependencies and test configuration.
- `packages/protocol/src/tamforge_protocol/audio.py` — fixed binary header, enums, pack/unpack, validation.
- `packages/protocol/src/tamforge_protocol/control.py` — versioned client/server control-message models.
- `packages/protocol/src/tamforge_protocol/turns.py` — question playback, answer sealing, and priority-transcript contracts.
- `packages/protocol/src/tamforge_protocol/errors.py` — stable error codes safe to show in the recorder.

### Backend recording and speech

- `apps/backend/src/tamforge_backend/recordings/models.py` — recording/device/track/batch persistence models.
- `apps/backend/src/tamforge_backend/recordings/repository.py` — transactional state and high-water operations.
- `apps/backend/src/tamforge_backend/recordings/pairing.py` — one-time pairing tickets and scoped device credentials.
- `apps/backend/src/tamforge_backend/recordings/routes.py` — authenticated REST session/pairing routes.
- `apps/backend/src/tamforge_backend/recordings/websocket.py` — WebSocket lifecycle and protocol handling.
- `apps/backend/src/tamforge_backend/recordings/batcher.py` — bounded contiguous five-second batch assembly.
- `apps/backend/src/tamforge_backend/recordings/durability.py` — object-first/transaction-second durability and ACK decisions.
- `apps/backend/src/tamforge_backend/recordings/reconciliation.py` — orphan/missing/conflicting object reconciliation.
- `apps/backend/src/tamforge_backend/recordings/recovery.py` — stale-session reconnect grace and honest incomplete finalization.
- `apps/backend/src/tamforge_backend/recordings/manifest.py` — canonical ordered PCM manifest and whole-stream hash.
- `apps/backend/src/tamforge_backend/recordings/finalize.py` — streaming WAV derivative creation.
- `apps/backend/src/tamforge_backend/storage/ports.py` — Plan 1 immutable object-store port, extended only if streaming metadata needs a compatible method.
- `apps/backend/src/tamforge_backend/storage/s3.py` — Plan 1 S3-compatible adapter, reused for Hetzner and contract-tested for recording segments.
- `apps/backend/src/tamforge_backend/jobs/scheduler.py` — database-clock stale-session and due-job scheduling.
- `apps/backend/src/tamforge_backend/speech/audio.py` — verified PCM-to-16-kHz analysis derivation.
- `apps/backend/src/tamforge_backend/speech/vad.py` — Silero VAD adapter and speech interval schema.
- `apps/backend/src/tamforge_backend/speech/transcription.py` — transcript-engine port and faster-whisper adapter.
- `apps/backend/src/tamforge_backend/speech/transcripts.py` — transcript/version/token persistence and selection.
- `apps/backend/src/tamforge_backend/speech/speakers.py` — deterministic track-level attribution and human-correctable remote labels.
- `apps/backend/src/tamforge_backend/speech/metrics/` — deterministic, versioned metric calculators.
- `apps/backend/src/tamforge_backend/speech/pronunciation/` — controlled diagnostic ports, candidate adapters, calibration, and service.
- `apps/backend/src/tamforge_backend/speech/jobs.py` — finalization/transcription/metric/pronunciation job handlers.
- `apps/backend/src/tamforge_backend/workers/speech.py` — single-concurrency, recording-aware worker entrypoint.
- `apps/backend/src/tamforge_backend/interviewer/turn_audio.py` — playback timing and priority-turn transcript orchestration.
- `apps/backend/alembic/versions/20260825_0006_recording_ingest.py` — recorder and durable-ingest tables.
- `apps/backend/alembic/versions/20260825_0007_transcript_metrics.py` — transcript, token, uncertainty, VAD, and metrics tables.
- `apps/backend/alembic/versions/20260825_0008_pronunciation_diagnostics.py` — controlled diagnostic and calibration tables.

### macOS recorder and web timing client

- `apps/recorder/src/tamforge_recorder/credentials.py` — Keychain-backed token and spool-key storage.
- `apps/recorder/src/tamforge_recorder/pairing.py` — ticket redemption and revocable device identity.
- `apps/recorder/src/tamforge_recorder/audio/devices.py` — device discovery/fingerprinting/preflight.
- `apps/recorder/src/tamforge_recorder/audio/capture.py` — two RawInputStream callbacks and sample clocks.
- `apps/recorder/src/tamforge_recorder/audio/sync.py` — non-destructive shared-timeline mapping and drift evidence.
- `apps/recorder/src/tamforge_recorder/spool/crypto.py` — AES-GCM record encryption.
- `apps/recorder/src/tamforge_recorder/spool/store.py` — bounded durable SQLite recovery spool.
- `apps/recorder/src/tamforge_recorder/streaming/client.py` — background asyncio/WebSocket client.
- `apps/recorder/src/tamforge_recorder/controller.py` — recorder state machine and thread coordination.
- `apps/recorder/src/tamforge_recorder/app.py` — minimal always-on-top Tkinter UI.
- `apps/recorder/src/tamforge_recorder/__main__.py` — application entrypoint.
- `apps/recorder/TAMForgeRecorder.spec` — reproducible PyInstaller bundle definition.
- `apps/recorder/assets/Info.plist` — bundle identifier and microphone permission description.
- `apps/web/src/features/interviewer/audio/LocalQuestionPlayer.ts` — browser-local TTS port and timing callbacks.
- `apps/web/src/features/pronunciation/PronunciationDiagnostic.tsx` — controlled-script evidence and human-correction UI.

### Evaluation and operations

- `scripts/recording_failure_harness.py` — reorder/duplicate/disconnect/process-kill test driver.
- `scripts/speech_benchmark.py` — 10/60-minute CPU, memory, WER, timing, and priority-turn benchmark.
- `scripts/pronunciation_benchmark.py` — candidate-adapter calibration harness.
- `evaluation/speech/README.md` — private gold-set manifest instructions and redacted aggregate schema.
- `evaluation/speech/schemas/` — annotation and benchmark-result JSON Schemas.
- `docs/runbooks/recording-recovery.md` — interrupted recording and spool recovery.
- `docs/runbooks/speech-worker.md` — worker resource, retry, and score-availability behavior.
- `docs/decisions/0003-pronunciation-adapter.md` — evidence-backed adapter decision or documented blocker.

### Task 1: Establish the fixed audio/control protocol package

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `packages/protocol/pyproject.toml`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Create: `packages/protocol/src/tamforge_protocol/audio.py`
- Create: `packages/protocol/src/tamforge_protocol/control.py`
- Create: `packages/protocol/src/tamforge_protocol/errors.py`
- Create: `packages/protocol/tests/test_audio_protocol.py`
- Create: `packages/protocol/tests/test_control_protocol.py`

- [ ] **Step 1: Write binary round-trip and fixed-size tests**

```python
def test_pcm_frame_v1_round_trip_is_exact() -> None:
    frame = PCMFrameV1.for_test(payload=b"\x00\x01" * 4410)
    encoded = frame.pack()
    assert PCM_HEADER_V1.size == 108
    assert len(encoded) == 108 + len(frame.payload)
    assert PCMFrameV1.unpack(encoded) == frame
```

- [ ] **Step 2: Write rejection tests for checksum, length, format, sample arithmetic, and unknown version**

Use parametrized cases and Hypothesis payload sizes. Assert stable `ProtocolErrorCode` values rather than exception prose.

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run: `uv run --project packages/protocol pytest packages/protocol/tests/test_audio_protocol.py -q`

Expected: FAIL because `tamforge_protocol.audio` does not exist.

- [ ] **Step 4: Implement the 108-byte header and immutable `PCMFrameV1` value object**

Use one module-level `struct.Struct("!4sBBH16s16sQQQIHHI32s")`; enforce `flags == 0`, UUID binding, PCM16 little-endian, and exact sample-position arithmetic. Do not add extensible headers or compression to v1.

Register `packages/protocol` as a workspace member, pin Pydantic/Hypothesis/test dependencies in its project file, and refresh `uv.lock`.

- [ ] **Step 5: Run the audio protocol tests**

Run: `uv run --project packages/protocol pytest packages/protocol/tests/test_audio_protocol.py -q`

Expected: PASS with all round-trip/property/rejection cases green.

- [ ] **Step 6: Write failing discriminated-union tests for every control message**

Assert that unknown message types, extra fields, negative sequence values, and a `durable_ack` without `next_sequence` fail Pydantic validation.

- [ ] **Step 7: Run the control tests and confirm they fail**

Run: `uv run --project packages/protocol pytest packages/protocol/tests/test_control_protocol.py -q`

Expected: FAIL because control models are absent.

- [ ] **Step 8: Implement strict versioned control models and stable safe error codes**

Configure Pydantic with `extra="forbid"`; keep authentication out of message bodies; model `next_sequence` rather than `-1` sentinels.

- [ ] **Step 9: Run protocol quality checks**

Run: `uv run --project packages/protocol pytest packages/protocol/tests -q && uv run --project packages/protocol ruff check packages/protocol && uv run --project packages/protocol mypy packages/protocol/src`

Expected: PASS, Ruff clean, mypy clean.

- [ ] **Step 10: Commit the protocol contract**

```bash
git add pyproject.toml uv.lock packages/protocol
git commit -m "feat(protocol): define durable audio stream v1"
```

### Task 2: Add recording-domain persistence and invariants

**Files:**
- Create: `apps/backend/alembic/versions/20260825_0006_recording_ingest.py`
- Modify: `apps/backend/pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/backend/src/tamforge_backend/recordings/__init__.py`
- Create: `apps/backend/src/tamforge_backend/recordings/models.py`
- Create: `apps/backend/src/tamforge_backend/recordings/repository.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`
- Create: `apps/backend/tests/recordings/test_models.py`
- Create: `apps/backend/tests/recordings/test_repository.py`

- [ ] **Step 1: Write state-transition tests for devices, sessions, tracks, and batches**

Cover `Created -> Capturing -> Stopping -> IngestSealed -> Finalizing -> Stored`, reconnect/interruption, honest incomplete finalization, and forbidden skips.

- [ ] **Step 2: Write repository contract tests for contiguous high-water behavior**

```python
async def test_commit_batch_advances_only_contiguous_high_water(repo, track):
    await repo.commit_batch(track.id, first=2, last=3, checksums=["c2", "c3"])
    assert await repo.next_sequence(track.id) == 0
    await repo.commit_batch(track.id, first=0, last=1, checksums=["c0", "c1"])
    assert await repo.next_sequence(track.id) == 4
```

Also test duplicate same-checksum success and duplicate different-checksum conflict.

- [ ] **Step 3: Run model-only tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_models.py -q`

Expected: FAIL because recording models do not exist.

- [ ] **Step 4: Implement focused SQLAlchemy models and pure transition guards**

Create tables for `recorder_devices`, `recorder_pairing_tickets`, `recording_sessions`, `audio_tracks`, and `audio_segment_batches`. Reuse the foundation `Artifact` table; do not create a competing artifact catalog. Store per-frame sequence/checksum/sample metadata as a bounded JSONB list on each five-second batch so duplicate conflicts remain inspectable without one PostgreSQL row per 100 ms frame. Register all new model modules through the canonical `tamforge_backend.models` aggregator so Alembic sees one metadata graph.

Add the workspace `tamforge-protocol` dependency to the backend project and refresh `uv.lock`.

- [ ] **Step 5: Verify the exact Plan 1 migration head before creating `_0006`**

Run: `test "$(uv run --project apps/backend alembic -c apps/backend/alembic.ini heads | cut -d' ' -f1)" = "20260825_0005_today_read_models"`

Expected: exit 0. If the actual head differs or multiple heads exist, stop and reconcile the migration plan; do not guess `down_revision`.

- [ ] **Step 6: Implement the migration with database constraints**

Add unique constraints for device token fingerprint, pairing-ticket digest, `(session_id, kind)`, `(track_id, first_sequence, last_sequence)`, and object key. Add check constraints for nonnegative sequence/sample positions, `last_sequence >= first_sequence`, supported PCM format, and nonempty checksum lists. Set `down_revision = "20260825_0005_today_read_models"` exactly after the Step 5 preflight succeeds.

- [ ] **Step 7: Run model tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_models.py -q`

Expected: PASS.

- [ ] **Step 8: Implement transactional repository methods**

Use `SELECT ... FOR UPDATE` on the track row while cataloging a batch and advancing `next_sequence`. The method accepts an already-verified immutable object reference; it never writes object storage inside the transaction.

- [ ] **Step 9: Run repository and migration integration tests only after the Docker gate is approved**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run --project apps/backend pytest apps/backend/tests/recordings/test_repository.py apps/backend/tests/integration/test_migrations.py -q -k recording_ingest
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS without skips against PostgreSQL 16; rollback tests prove no high-water movement, migration upgrades from `20260825_0005_today_read_models`, downgrades one revision, and upgrades again; final `ps` prints no running project services.

- [ ] **Step 10: Commit recording persistence**

```bash
git add apps/backend/pyproject.toml uv.lock apps/backend/alembic/versions/20260825_0006_recording_ingest.py apps/backend/src/tamforge_backend/recordings apps/backend/src/tamforge_backend/models/__init__.py apps/backend/tests/recordings/test_models.py apps/backend/tests/recordings/test_repository.py
git commit -m "feat(recording): persist sessions tracks and durable batches"
```

### Task 3: Implement backend recorder pairing and revocation

**Files:**
- Create: `apps/backend/src/tamforge_backend/recordings/pairing.py`
- Create: `apps/backend/src/tamforge_backend/recordings/routes.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Test: `apps/backend/tests/recordings/test_pairing.py`
- Test: `apps/backend/tests/recordings/test_pairing_routes.py`

- [ ] **Step 1: Write failing service tests for one-time tickets and hashed device tokens**

Test five-minute expiry, one successful redemption, replay rejection, ticket attempt limits, opaque 256-bit device token generation, SHA-256/HMAC token digest storage, scope `recording:claim recording:upload`, and immediate revocation.

- [ ] **Step 2: Run pairing service tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_pairing.py -q`

Expected: FAIL because `PairingService` is absent.

- [ ] **Step 3: Implement `PairingService` without logging raw tickets or tokens**

Return a device token once. Store only its keyed digest, short nonsecret prefix, created/last-used timestamps, scope, and revocation timestamp. Use constant-time digest comparison.

- [ ] **Step 4: Run pairing service tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_pairing.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing route tests for owner and recorder boundaries**

Cover owner-only `POST /api/v1/recorder-pairing-tickets`, public-but-rate-limited one-time `POST /api/v1/recorders/pair`, owner-only device list/revoke, CSRF on cookie-authenticated mutations, and bearer-device rejection from normal user routes.

- [ ] **Step 6: Run route tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_pairing_routes.py -q`

Expected: FAIL with 404 before router registration.

- [ ] **Step 7: Implement routes, rate limits, audits, and router registration**

Return safe actionable codes (`PAIRING_EXPIRED`, `PAIRING_ALREADY_USED`, `DEVICE_REVOKED`) and emit audit events without secrets.

- [ ] **Step 8: Run pairing tests and backend static checks**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_pairing.py apps/backend/tests/recordings/test_pairing_routes.py -q && uv run --project apps/backend ruff check apps/backend/src/tamforge_backend/recordings`

Expected: PASS and Ruff clean.

- [ ] **Step 9: Commit backend pairing**

```bash
git add apps/backend/src/tamforge_backend/recordings apps/backend/src/tamforge_backend/api.py apps/backend/tests/recordings/test_pairing.py apps/backend/tests/recordings/test_pairing_routes.py
git commit -m "feat(recording): pair and revoke scoped recorder devices"
```

### Task 4: Store recorder identity and spool encryption keys in macOS Keychain

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/recorder/pyproject.toml`
- Create: `apps/recorder/src/tamforge_recorder/__init__.py`
- Create: `apps/recorder/src/tamforge_recorder/credentials.py`
- Create: `apps/recorder/src/tamforge_recorder/pairing.py`
- Create: `apps/recorder/tests/fakes.py`
- Create: `apps/recorder/tests/test_credentials.py`
- Create: `apps/recorder/tests/test_pairing.py`

- [ ] **Step 1: Write failing Keychain-port tests**

Assert separate Keychain entries for the revocable bearer token and random 256-bit AES spool key, service name `com.tamforge.recorder`, device UUID account binding, no plaintext fallback file, rotation, and explicit deletion.

- [ ] **Step 2: Run credential tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_credentials.py -q`

Expected: FAIL because credential storage is absent.

- [ ] **Step 3: Implement a narrow `CredentialStore` around `keyring`**

Inject the backend for tests. On macOS production startup, fail visibly if the active backend is not Keychain; never silently downgrade to plaintext or an in-memory token that would break recovery.

Register `apps/recorder` in the root uv workspace. Define the recorder project with workspace `tamforge-protocol`, `sounddevice`, `websockets`, `httpx`, `keyring`, `cryptography`, `platformdirs`, and bounded test/build dependencies, then refresh `uv.lock`. Do not add a GUI framework beyond Tkinter.

- [ ] **Step 4: Run credential tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_credentials.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing pairing-client tests**

Cover ticket trimming, TLS-only base URL, token stored before success is reported, partial failure cleanup, server revocation handling, device metadata minimization, and secret-redacted exceptions.

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_pairing.py -q`

Expected: FAIL because the pairing client is absent.

- [ ] **Step 6: Implement the pairing client and typed outcomes**

The pairing UI may accept a short-lived code, but the stored device credential is the opaque 256-bit returned token. Do not persist the pairing code.

- [ ] **Step 7: Run recorder pairing tests and static checks**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_credentials.py apps/recorder/tests/test_pairing.py -q && uv run --project apps/recorder ruff check apps/recorder/src`

Expected: PASS and Ruff clean.

- [ ] **Step 8: Commit Keychain pairing support**

```bash
git add pyproject.toml uv.lock apps/recorder
git commit -m "feat(recorder): secure device pairing in macOS Keychain"
```

### Task 5: Discover, preflight, and synchronize microphone and BlackHole capture

**Files:**
- Create: `apps/recorder/src/tamforge_recorder/audio/__init__.py`
- Create: `apps/recorder/src/tamforge_recorder/audio/models.py`
- Create: `apps/recorder/src/tamforge_recorder/audio/devices.py`
- Create: `apps/recorder/src/tamforge_recorder/audio/capture.py`
- Create: `apps/recorder/src/tamforge_recorder/audio/sync.py`
- Create: `apps/recorder/tests/audio/test_devices.py`
- Create: `apps/recorder/tests/audio/test_capture.py`
- Create: `apps/recorder/tests/audio/test_sync.py`

- [ ] **Step 1: Write failing device-discovery tests with fake `sounddevice` inventory**

Cover exact and normalized `BlackHole 2ch` matching, duplicate-name ambiguity, missing mic, unsupported 44.1 kHz/PCM16, actual channel count, unstable numeric device IDs, and saved fingerprint re-resolution.

- [ ] **Step 2: Run device tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/audio/test_devices.py -q`

Expected: FAIL because discovery is absent.

- [ ] **Step 3: Implement device fingerprints and an explicit preflight result**

Fingerprint by host API, normalized name, max input channels, and default sample rate. Never auto-select an ambiguous device. Return actionable setup errors without exposing unrelated device metadata.

- [ ] **Step 4: Run device tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/audio/test_devices.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing dual-stream callback tests**

Use fake `RawInputStream` objects. Assert `dtype="int16"`, `samplerate=44100`, `blocksize=4410`, explicit per-track channels, monotonically increasing sequence/sample counters, a shared capture epoch, and callback work limited to byte copy plus `put_nowait`.

- [ ] **Step 6: Add overload tests**

When the bounded callback queue cannot accept a frame, assert capture transitions to a visible `CAPTURE_QUEUE_EXHAUSTED` stop; do not drop a frame and continue pretending the recording is complete.

Run: `uv run --project apps/recorder pytest apps/recorder/tests/audio/test_capture.py -q`

Expected: FAIL because dual-track capture is absent.

- [ ] **Step 7: Implement `DualTrackCapture` and immutable `CapturedBlock`**

Start both streams from one controller barrier, record each callback's monotonic timestamp, preserve raw track bytes unchanged, and place no hashing, encryption, network, disk, logging, or UI work in the audio callback.

- [ ] **Step 8: Run capture tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/audio/test_capture.py -q`

Expected: PASS with callback timing fake assertions and overload stop behavior.

- [ ] **Step 9: Write failing non-destructive synchronization-map tests**

Feed per-track `(sample_start, capture_monotonic_ns)` observations with known offset, callback jitter, and clock drift. Assert the fitted mapping reports initial alignment error, residual drift over 60 minutes, confidence/quality, and no mutation/resampling of either raw track. A mapping outside 100 ms initial error or 50 ms residual drift is unavailable for decision-grade response latency.

- [ ] **Step 10: Run synchronization tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/audio/test_sync.py -q`

Expected: FAIL because the synchronization mapper is absent.

- [ ] **Step 11: Implement the synchronization mapper**

Fit each track's sample clock to its monotonic observations with a robust bounded method, then map both onto the shared capture epoch. Persist coefficients, observation range, residuals, and algorithm version in track synchronization metadata.

- [ ] **Step 12: Run synchronization tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/audio/test_sync.py -q`

Expected: PASS for offset/drift fixtures and honest unavailable results for unstable clocks.

- [ ] **Step 13: Run recorder type/lint checks**

Run: `uv run --project apps/recorder ruff check apps/recorder/src/tamforge_recorder/audio apps/recorder/tests/audio && uv run --project apps/recorder mypy apps/recorder/src/tamforge_recorder/audio`

Expected: Ruff and mypy clean.

- [ ] **Step 14: Commit dual-track capture**

```bash
git add apps/recorder/src/tamforge_recorder/audio apps/recorder/tests/audio
git commit -m "feat(recorder): capture synchronized microphone and system tracks"
```

### Task 6: Build the bounded encrypted recovery spool

**Files:**
- Create: `apps/recorder/src/tamforge_recorder/spool/__init__.py`
- Create: `apps/recorder/src/tamforge_recorder/spool/crypto.py`
- Create: `apps/recorder/src/tamforge_recorder/spool/store.py`
- Create: `apps/recorder/src/tamforge_recorder/spool/worker.py`
- Create: `apps/recorder/tests/spool/test_crypto.py`
- Create: `apps/recorder/tests/spool/test_store.py`
- Create: `apps/recorder/tests/spool/test_worker.py`

- [ ] **Step 1: Write failing AES-GCM envelope tests**

Bind session ID, track ID, sequence, sample position, format, and payload checksum as authenticated additional data. Assert tampering with ciphertext or metadata fails closed and plaintext PCM never appears in the SQLite file bytes.

- [ ] **Step 2: Run crypto tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/spool/test_crypto.py -q`

Expected: FAIL because the envelope is absent.

- [ ] **Step 3: Implement versioned AES-256-GCM records with unique random nonces**

Use the Keychain-held key from Task 4. The spool database may expose nonsecret sequence metadata, but PCM and payload checksums inside the envelope remain authenticated; never reuse a nonce with the same key.

- [ ] **Step 4: Run crypto tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/spool/test_crypto.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing SQLite spool tests**

Cover atomic insert before send eligibility, ordered per-track reads, duplicate same-checksum idempotence, conflicting duplicate rejection, `delete_before(next_sequence)`, restart recovery, WAL checkpoint, a 2 GiB physical cap covering the database/WAL/journal plus the next-write estimate, a 2 GiB filesystem free-space reserve, and no unbounded query result loading.

- [ ] **Step 6: Run store tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/spool/test_store.py -q`

Expected: FAIL because `EncryptedSpool` is absent.

- [ ] **Step 7: Implement the spool with `PRAGMA synchronous=FULL` and bounded page reads**

Create one recovery database per session under `~/Library/Application Support/TAM Forge Recorder/Recovery/`, with restrictive permissions. Do not use `Library/Caches`, temporary directories, or any location macOS may purge before a durable server ACK. Track encrypted payload bytes transactionally and check actual database/WAL/journal sizes before every insert. Reject new records before the configured cap/reserve is crossed. Deleting acknowledged records makes them inaccessible immediately; after all tracks are durably sealed, close and remove that session's database/WAL/journal. Periodic checkpoint/cleanup is best effort and never blocks the audio callback.

- [ ] **Step 8: Run store tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/spool/test_store.py -q`

Expected: PASS, including restart, WAL-size, and cap exhaustion cases.

- [ ] **Step 9: Write failing spool-worker tests**

The spool worker drains the five-second-per-track callback queue promptly, persists each block before it becomes sendable, reports disk/key/database failure to the controller, and never retains recording-length payloads in Python collections.

- [ ] **Step 10: Run worker tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/spool/test_worker.py -q`

Expected: FAIL because the spool worker is absent.

- [ ] **Step 11: Implement the bounded spool worker**

Perform encryption and SQLite writes only on the spool thread. Consume one callback block at a time, release its byte object after the transaction, expose only sequence metadata to the network thread, and send typed controller events on storage/key failure or shutdown.

- [ ] **Step 12: Run all spool tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/spool -q`

Expected: PASS, including restart and cap exhaustion tests.

- [ ] **Step 13: Commit the encrypted spool**

```bash
git add apps/recorder/src/tamforge_recorder/spool apps/recorder/tests/spool
git commit -m "feat(recorder): add bounded encrypted recovery spool"
```

### Task 7: Stream spooled frames with resume, ACK deletion, and bounded reconnect

**Files:**
- Create: `apps/recorder/src/tamforge_recorder/streaming/__init__.py`
- Create: `apps/recorder/src/tamforge_recorder/streaming/state.py`
- Create: `apps/recorder/src/tamforge_recorder/streaming/client.py`
- Create: `apps/recorder/tests/streaming/fake_server.py`
- Create: `apps/recorder/tests/streaming/test_state.py`
- Create: `apps/recorder/tests/streaming/test_client.py`

- [ ] **Step 1: Write failing pure state-machine tests**

Cover `Idle -> Connecting -> Negotiating -> Streaming -> Reconnecting -> Streaming -> Sealing -> Complete`, explicit cancellation, revoked token, protocol mismatch, checksum conflict, and retry exhaustion without discarding the spool.

- [ ] **Step 2: Run state tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/streaming/test_state.py -q`

Expected: FAIL because streaming state is absent.

- [ ] **Step 3: Implement the pure streaming state reducer**

Keep retry timing outside the reducer. Terminal failures preserve enough state for an honest incomplete-session report and recovery.

- [ ] **Step 4: Run state tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/streaming/test_state.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing async client tests against an in-process fake WebSocket server**

Test `Authorization: Bearer`, subprotocol `tamforge.audio.v1`, strict `hello/ready`, one-frame-at-a-time spool reads, per-track round-robin fairness, deletion only after `durable_ack.next_sequence`, server `resend_from`, duplicate resend, ping/pong, and reconnect jitter capped by configuration.

- [ ] **Step 6: Add disconnect and stale-ACK tests**

Force disconnect after send but before ACK. Assert the same frame resends after the server high-water response. Ignore ACK regression, reject ACK beyond the highest sent sequence, and stop visibly on server checksum conflict.

- [ ] **Step 7: Run client tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/streaming/test_client.py -q`

Expected: FAIL because `StreamingClient` is absent.

- [ ] **Step 8: Implement one asyncio loop inside the networking thread**

Use the `websockets` asyncio client only in that thread. Pull encrypted rows in bounded pages, decrypt one frame, pack it with `tamforge_protocol`, send, and release bytes before loading the next. The sender may pipeline a small fixed number of frames, but the cap must be configuration-tested and independent of recording duration.

- [ ] **Step 9: Implement stop/seal semantics**

After capture stops, finish spooling callback-queue contents, send all remaining rows, issue `seal_track` for each track, wait for final durable ACK/sealed responses, and only then report remote completion. A user cancellation or deadline preserves remaining spool rows.

- [ ] **Step 10: Run streaming and resource tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/streaming -q`

Expected: PASS; fake-server counters show bounded in-flight frames and no early deletion.

- [ ] **Step 11: Commit the recorder transport**

```bash
git add apps/recorder/src/tamforge_recorder/streaming apps/recorder/tests/streaming
git commit -m "feat(recorder): resume durable audio streaming after disconnects"
```

### Task 8: Create, claim, and authorize web-selected recording sessions

**Files:**
- Modify: `apps/backend/src/tamforge_backend/recordings/routes.py`
- Create: `apps/backend/src/tamforge_backend/recordings/service.py`
- Create: `apps/backend/src/tamforge_backend/recordings/schemas.py`
- Create: `apps/backend/tests/recordings/test_session_service.py`
- Create: `apps/backend/tests/recordings/test_session_routes.py`
- Create: `apps/recorder/src/tamforge_recorder/assignments.py`
- Create: `apps/recorder/tests/test_assignments.py`

- [ ] **Step 1: Write failing backend service tests for selected-activity binding**

The owner creates one pending recording session tied to an existing attempt/activity, purpose (`practice`, `mock`, `real_interview`, or `pronunciation_diagnostic`), consent state, expected track kinds, capture format, and time limit. Assert no orphan session, no second active recorder claim, and no recording for real-interview consent `Unknown` or `Prohibited`.

- [ ] **Step 2: Run service tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_session_service.py -q`

Expected: FAIL because the session service is absent.

- [ ] **Step 3: Implement `RecordingSessionService` with idempotency keys**

The service owns state changes and emits outbox/audit events. The Mac never supplies arbitrary activity, user, consent, or purpose IDs.

- [ ] **Step 4: Run service tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_session_service.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing REST route tests**

Cover owner `POST /api/v1/recording-sessions`, device `GET /api/v1/recorders/me/assignments/next`, device `POST /api/v1/recording-sessions/{id}/claim`, owner cancellation, device scope, revoked token, session ownership, and claim replay.

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_session_routes.py -q`

Expected: FAIL because the session routes are absent.

- [ ] **Step 6: Implement schemas and routes**

The assignment returned to the recorder contains only session ID, WSS URL, expected track kinds/formats, time limit, and display-safe prompt label; it does not expose roadmap history, analyses, interviewer secrets, or object credentials.

- [ ] **Step 7: Write failing recorder assignment-client tests**

Assert Start remains disabled without an authenticated pending assignment, claim is idempotent, server cancellation clears the local assignment but not recovery spool data, and real-interview permission errors are prominent.

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_assignments.py -q`

Expected: FAIL because the assignment client is absent.

- [ ] **Step 8: Implement the bounded assignment client**

Poll only while the UI is open and idle, with a capped interval; do not create a permanent background daemon or notification loop.

- [ ] **Step 9: Run session/assignment tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_session_service.py apps/backend/tests/recordings/test_session_routes.py -q && uv run --project apps/recorder pytest apps/recorder/tests/test_assignments.py -q`

Expected: PASS.

- [ ] **Step 10: Commit web-selected session binding**

```bash
git add apps/backend/src/tamforge_backend/recordings apps/backend/tests/recordings/test_session_service.py apps/backend/tests/recordings/test_session_routes.py apps/recorder/src/tamforge_recorder/assignments.py apps/recorder/tests/test_assignments.py
git commit -m "feat(recording): bind recorder capture to selected activities"
```

### Task 9: Accept authenticated WebSocket frames without doing speech work inline

**Files:**
- Create: `apps/backend/src/tamforge_backend/recordings/websocket.py`
- Create: `apps/backend/src/tamforge_backend/recordings/ingest.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Create: `apps/backend/tests/recordings/test_websocket_auth.py`
- Create: `apps/backend/tests/recordings/test_websocket_protocol.py`

- [ ] **Step 1: Write failing WebSocket authentication tests**

Cover missing/wrong subprotocol, missing/revoked/out-of-scope bearer token, unclaimed session, wrong device/session binding, already-terminal session, and one active socket lease per claimed session.

- [ ] **Step 2: Run auth tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_websocket_auth.py -q`

Expected: FAIL because the endpoint is absent.

- [ ] **Step 3: Implement handshake authorization before accepting binary audio**

Expose `WS /api/v1/recording-sessions/{session_id}/stream`. Authenticate the header, negotiate `tamforge.audio.v1`, require `hello`, return current per-track `next_sequence`, then allow frames. Redact bearer tokens and binary payloads from access/error logs.

- [ ] **Step 4: Run auth tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_websocket_auth.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing protocol-flow tests**

Test valid binary frames, per-track next sequence, duplicate below high-water verification, future sequence `resend_from`, malformed/oversize message close code, track/format mismatch, stop then final partial batch flush, seal before complete upload rejection, and heartbeat.

- [ ] **Step 6: Add a request-path latency assertion**

Inject fake persistence. Assert the endpoint invokes validation/batching/durability only and never imports or calls Silero, faster-whisper, pronunciation, or Claude modules.

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_websocket_protocol.py -q`

Expected: FAIL because the protocol loop is absent.

- [ ] **Step 7: Implement the protocol loop with bounded per-connection state**

Reject gaps rather than buffering arbitrary future frames. Maintain at most one active five-second batch per track. On disconnect, discard only unacknowledged in-memory batch bytes; the client spool remains the recovery source.

- [ ] **Step 8: Run WebSocket protocol tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_websocket_auth.py apps/backend/tests/recordings/test_websocket_protocol.py -q`

Expected: PASS, including no-speech-import assertion.

- [ ] **Step 9: Commit authenticated ingest framing**

```bash
git add apps/backend/src/tamforge_backend/recordings/websocket.py apps/backend/src/tamforge_backend/recordings/ingest.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/recordings/test_websocket_auth.py apps/backend/tests/recordings/test_websocket_protocol.py
git commit -m "feat(recording): validate authenticated websocket audio frames"
```

### Task 10: Persist deterministic five-second batches and ACK database high-water

**Files:**
- Modify: `compose.dev.yml`
- Modify: `.env.example`
- Modify: `apps/backend/src/tamforge_backend/storage/ports.py`
- Modify: `apps/backend/src/tamforge_backend/storage/fake.py`
- Modify: `apps/backend/src/tamforge_backend/storage/s3.py`
- Create: `apps/backend/src/tamforge_backend/recordings/batcher.py`
- Create: `apps/backend/src/tamforge_backend/recordings/durability.py`
- Modify: `apps/backend/tests/unit/storage/test_contract.py`
- Modify: `apps/backend/tests/unit/storage/test_s3_adapter.py`
- Create: `apps/backend/tests/recordings/test_batcher.py`
- Create: `apps/backend/tests/recordings/test_durability.py`

- [ ] **Step 1: Write failing batcher tests**

Assert 50 approximately 100 ms frames form one batch at 44.1 kHz, Stop flushes a shorter final batch, mixed format/session/track is rejected, sequence/checksum/sample metadata stays ordered, and memory never exceeds one configured batch per track.

- [ ] **Step 2: Run batcher tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_batcher.py -q`

Expected: FAIL because the batcher is absent.

- [ ] **Step 3: Implement the pure contiguous batcher**

Compute both each frame SHA-256 and the SHA-256 of exact concatenated PCM. Return immutable batch bytes plus manifest metadata; release frame references after flush.

- [ ] **Step 4: Run batcher tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_batcher.py -q`

Expected: PASS.

- [ ] **Step 5: Extend and test the Plan 1 immutable object-store port**

Preserve Plan 1's `put_immutable`, `stat`, and `open` contracts and add only a bounded paginated `list_prefix` operation required by reconciliation. Extend the existing reusable fake/S3 contract tests for same-key/same-hash idempotence, same-key/different-metadata conflict, timeout, object-visible/database-failed orphan, missing object, pagination, and prefix isolation.

Run: `uv run --project apps/backend pytest apps/backend/tests/unit/storage/test_contract.py apps/backend/tests/unit/storage/test_s3_adapter.py -q -m "not object_store_integration"`

Expected: FAIL because bounded `list_prefix` and recording metadata verification are absent.

- [ ] **Step 6: Extend the Plan 1 S3 adapter for verified recording segments**

Reuse its private-bucket settings, boto3 client, TLS, thread offload, and bounded retry policy. Require content length and SHA-256 metadata for recording segments and never return success until `stat` confirms expected length and hash metadata. Do not log object payloads or signed URLs, and do not add a second S3 client library.

Make the existing `compose.dev.yml` MinIO contract deterministic for approval-gated tests: bind API port `59000`, use test-only access key `tamforge-test`, test-only secret `tamforge-test-only-secret`, and an idempotent `minio-init` service that creates private bucket `tamforge-test`. Mirror only variable names/placeholders in `.env.example`; production rejects these known test values.

- [ ] **Step 7: Write failing durability-order tests**

```python
async def test_ack_requires_object_then_database(durability, events):
    result = await durability.persist(batch)
    assert events == ["object.put", "object.head", "db.begin", "db.commit"]
    assert result.next_sequence == batch.last_sequence + 1
```

Also fail object PUT, HEAD verification, database commit, and high-water contention in turn. Assert no ACK on any failure.

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_durability.py -q`

Expected: FAIL because `DurableBatchWriter` is absent.

- [ ] **Step 8: Implement `DurableBatchWriter`**

Build the exact deterministic key, PUT/verify object, transactionally upsert catalog plus batch and advance contiguous `next_sequence`, then return ACK. If the object already exists with matching metadata, continue idempotently. If the range exists with any differing frame checksum, return integrity failure.

- [ ] **Step 9: Run fake-backed durability tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/unit/storage/test_contract.py apps/backend/tests/unit/storage/test_s3_adapter.py apps/backend/tests/recordings/test_batcher.py apps/backend/tests/recordings/test_durability.py -q -m "not object_store_integration"`

Expected: PASS with explicit event-order assertions.

- [ ] **Step 10: Run the S3-compatible integration contract only after Docker approval**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d minio
docker compose -f compose.dev.yml run --rm minio-init
TAMFORGE_S3_ENDPOINT_URL=http://127.0.0.1:59000 TAMFORGE_S3_BUCKET=tamforge-test TAMFORGE_S3_ACCESS_KEY=tamforge-test TAMFORGE_S3_SECRET_KEY=tamforge-test-only-secret TAMFORGE_REQUIRE_OBJECT_STORE_INTEGRATION=1 uv run --project apps/backend pytest apps/backend/tests/unit/storage/test_contract.py apps/backend/tests/unit/storage/test_s3_adapter.py -q -m object_store_integration
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS without skips against the isolated S3-compatible test service; immutable and metadata semantics match the fake; final `ps` prints no running project services.

- [ ] **Step 11: Commit durable batching and ACK**

```bash
git add compose.dev.yml .env.example apps/backend/src/tamforge_backend/storage/ports.py apps/backend/src/tamforge_backend/storage/fake.py apps/backend/src/tamforge_backend/storage/s3.py apps/backend/src/tamforge_backend/recordings/batcher.py apps/backend/src/tamforge_backend/recordings/durability.py apps/backend/tests/unit/storage/test_contract.py apps/backend/tests/unit/storage/test_s3_adapter.py apps/backend/tests/recordings/test_batcher.py apps/backend/tests/recordings/test_durability.py
git commit -m "feat(recording): acknowledge only object and database durable audio"
```

### Task 11: Reconcile object/database split-brain safely

**Files:**
- Create: `apps/backend/src/tamforge_backend/recordings/reconciliation.py`
- Create: `apps/backend/tests/recordings/test_reconciliation.py`

- [ ] **Step 1: Write failing reconciliation matrix tests**

Cover: object exists/database row missing; row exists/object missing; both match; both conflict; orphan outside a known session; object appears during scan; retry after crash; and a live recording whose newest batch must not be misclassified prematurely.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_reconciliation.py -q`

Expected: FAIL because reconciliation is absent.

- [ ] **Step 3: Implement a dry-run-first reconciliation report**

Parse only strict TAM Forge keys, verify metadata/hash, and return typed actions. Unknown or conflicting objects become `NeedsAttention`; they are never deleted or adopted automatically.

- [ ] **Step 4: Implement idempotent safe adoption of matching orphan objects**

For a known claimed track and a contiguous, manifest-valid orphan, catalog it in one transaction and advance `next_sequence`; this does not retroactively prove the client saw an ACK. Missing objects never advance high-water.

- [ ] **Step 5: Expose the reconciliation handler contract for Task 13**

Keep reconciliation callable as an idempotent application service with key `recording-reconcile:{session_id}:{scan_version}`. Task 13 registers and enqueues it through Plan 1's PostgreSQL job service. Defer scans while the session is actively capturing unless explicitly invoked after an ingest error.

- [ ] **Step 6: Run reconciliation tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_reconciliation.py -q`

Expected: PASS; conflicts remain untouched and visible.

- [ ] **Step 7: Commit reconciliation**

```bash
git add apps/backend/src/tamforge_backend/recordings/reconciliation.py apps/backend/tests/recordings/test_reconciliation.py
git commit -m "feat(recording): reconcile immutable audio objects safely"
```

### Task 12: Seal canonical manifests and stream verified WAV derivatives

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `apps/backend/src/tamforge_backend/config.py`
- Create: `apps/backend/src/tamforge_backend/recordings/manifest.py`
- Create: `apps/backend/src/tamforge_backend/recordings/manifest_keys.py`
- Create: `apps/backend/src/tamforge_backend/recordings/manifest_signing.py`
- Create: `apps/backend/src/tamforge_backend/recordings/finalize.py`
- Create: `scripts/bootstrap_manifest_signing_key.py`
- Create: `scripts/rotate_manifest_signing_key.py`
- Modify: `apps/backend/tests/unit/test_config.py`
- Create: `apps/backend/tests/recordings/test_manifest.py`
- Create: `apps/backend/tests/recordings/test_manifest_keys.py`
- Create: `apps/backend/tests/recordings/test_manifest_signing.py`
- Create: `apps/backend/tests/recordings/test_manifest_key_bootstrap.py`
- Create: `apps/backend/tests/recordings/test_manifest_key_rotation.py`
- Create: `apps/backend/tests/recordings/test_finalize.py`
- Create: `apps/backend/tests/fixtures/synthetic_audio.py`
- Create: `docs/runbooks/manifest-signing-key-rotation.md`

- [ ] **Step 1: Generate tiny synthetic PCM fixtures through the test fixture generator**

Use deterministic in-memory sine/silence construction in `synthetic_audio.py`; do not commit generated binary or personal audio. Record expected byte count, sample frames, and SHA-256 in the fixture value object.

- [ ] **Step 2: Write failing unsigned canonical-manifest tests**

Assert ordered ranges start at sequence 0 with no gaps/overlap, batch hashes and per-frame checksums resolve, sample positions are continuous, format is stable, whole-stream SHA-256 is reproducible, and an incomplete session explicitly records reason/last durable sequence. Canonical bytes use UTF-8 JSON with sorted keys, no insignificant whitespace, `ensure_ascii=False`, `allow_nan=False`, and only schema-approved integer/string/boolean/null values; no float or implementation-dependent serialization enters the signed payload.

- [ ] **Step 3: Run manifest tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_manifest.py -q`

Expected: FAIL because manifest construction is absent.

- [ ] **Step 4: Implement the immutable unsigned manifest and canonical encoder**

Build `RawRecordingManifestV1` and canonical bytes independently of signing. Preserve exact source artifact IDs, ordered segment metadata, per-frame hashes, whole-PCM hash, completion state/reason, schema version, and derivation inputs. Never rewrite raw manifest v1; identical inputs produce the same raw-manifest SHA-256.

- [ ] **Step 5: Run manifest tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_manifest.py -q`

Expected: PASS for unsigned schema, continuity, canonical bytes, and raw-manifest hash.

- [ ] **Step 6: Write failing key-version, signer, and verifier tests**

Define a strict version-1 keyring document stored outside the repository:

```json
{
  "schema_version": 1,
  "active_key_id": "manifest-2026-08-25-01",
  "keys": [
    {"key_id": "manifest-2026-08-25-01", "state": "active", "secret_base64": "<32-or-more-random-bytes>"}
  ]
}
```

Use exact settings `TAMFORGE_MANIFEST_SIGNING_CREDENTIAL_NAME=manifest-signing-keys.json` and optional local/test-only `TAMFORGE_MANIFEST_KEYRING_PATH`. In production, resolve the credential name only beneath systemd's `CREDENTIALS_DIRECTORY`; never let an environment value contain key bytes or point production directly into the Git checkout. Test an absolute, regular, nonsymlink credential file; strict JSON fields; exactly one active key; unique versioned key IDs; Base64 validation; minimum 32 decoded random bytes; and refusal of missing, group/world-readable, repository-contained, or out-of-credential-directory production files. `.env.example` contains only the nonsecret credential name and a blank/commented local path, never key material.

Signing is exactly `HMAC-SHA256(key, b"TAMFORGE-RECORDING-MANIFEST-V1\x00" + canonical_raw_manifest_bytes)`. The signed envelope stores schema version, raw payload, raw-manifest SHA-256, algorithm `hmac-sha256`, nonsecret `key_id`, and Base64 signature. Tests cover deterministic retry, domain separation, payload/hash/signature tampering, malformed Base64, unknown/disabled key ID, wrong key, and constant-time `hmac.compare_digest` verification. No verifier may try every key or fall back to the active key when `key_id` is unknown.

- [ ] **Step 7: Run signing/config tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/unit/test_config.py apps/backend/tests/recordings/test_manifest_keys.py apps/backend/tests/recordings/test_manifest_signing.py -q -k "manifest or keyring"`

Expected: FAIL because the keyring loader, signer, verifier, and manifest settings are absent.

- [ ] **Step 8: Implement fail-closed key loading, signing, and verification**

Add the credential-name and local/test path settings to `config.py`. At rest, secret bytes exist only in the root-owned `0600` source keyring; the production speech-worker unit receives it through systemd `LoadCredential=manifest-signing-keys.json:/etc/tamforge/secrets/manifest-signing-keys.json` and the app resolves the read-only runtime credential beneath `CREDENTIALS_DIRECTORY`. Tests inject an in-memory or temporary keyring. `manifest_keys.py` loads immutable key versions and returns the active signer key or an exact verification key. `manifest_signing.py` canonicalizes, hashes, signs, and verifies the envelope with `hmac.compare_digest`; exceptions/logs contain only safe error code and key ID, never raw key, keyring contents, payload, signature, audio, or transcript.

The finalization worker validates this dependency lazily. Missing/invalid keys move the job to `NeedsAttention` while canonical segment objects remain durable; they do not crash or block live ingest. Store raw-manifest SHA-256, signed-envelope SHA-256, algorithm, key ID, and signature on artifact lineage. A retry first verifies and reuses an already-persisted signed envelope, including one signed by a now verification-only key; rotation never silently re-signs or overwrites a historical manifest.

- [ ] **Step 9: Run signing/config tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/unit/test_config.py apps/backend/tests/recordings/test_manifest.py apps/backend/tests/recordings/test_manifest_keys.py apps/backend/tests/recordings/test_manifest_signing.py -q -k "manifest or keyring"`

Expected: PASS with stable raw/envelope hashes, exact key lineage, fail-closed errors, and secret-redaction assertions.

- [ ] **Step 10: Write failing initial-bootstrap and signing-key rotation tests**

Test a two-phase initial bootstrap and atomic rotation in temporary directories. Bootstrap is the only command allowed to start from a missing keyring. `--stage --new-key-id <id>` generates `secrets.token_bytes(32)` internally, creates one strict pending keyring beside the final target with root-only production ownership/`0600` mode, fsyncs the file/directory, and prints only key ID, pending-file SHA-256, and status. It refuses an existing final/pending keyring, symlink, repository path, unsafe parent permissions, caller-supplied secret, or overwrite. It never exposes the pending file through systemd.

Activation requires `--activate --backup-receipt <file>`. The strict receipt names the exact credential, pending SHA-256, verified encrypted backup snapshot/object ID, backup-manifest SHA-256, host identity, and timestamp. Bootstrap verifies the receipt and pending hash, atomically renames the pending file to the final keyring, fsyncs its directory, and refuses stale/mismatched/unverified receipts. Inject a fake receipt verifier in unit tests; the production Task 26 procedure verifies the receipt with Task 24's pinned backup tooling before activation. A crash before activation leaves only an unreferenced pending secret; a retry reports exact state and never generates a second key silently. A crash after rename yields one valid keyring. Rollback before worker use removes only the exact pending file through an allowlisted, receipt-bound command; an activated key is preserved and rotated, never deleted.

Rotation requires an existing active keyring. It creates a new `secrets.token_bytes(32)` key, promotes its caller-supplied unique key ID, demotes the prior active key to `verify_only`, retains every historical verification key, writes/fsyncs a `0600` temporary file, atomically replaces the keyring, and fsyncs its directory. It refuses symlinks, duplicate IDs, unsafe permissions/ownership, paths inside the Git worktree, and rotation without a verified encrypted-backup receipt for the pre-rotation keyring. Both commands print only key IDs/hashes/status; captured stdout/stderr and exceptions must not contain any Base64 secret.

Prove manifests signed before rotation still verify with their recorded key ID and new manifests use only the new active ID. Removing an old verification key is deliberately unsupported because historical immutable manifests still depend on it.

- [ ] **Step 11: Run rotation tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_manifest_key_bootstrap.py apps/backend/tests/recordings/test_manifest_key_rotation.py -q`

Expected: FAIL because the two-phase bootstrap, receipt verification, atomic rotation command, and policies are absent.

- [ ] **Step 12: Implement bootstrap, rotation, and the operator runbook**

Implement `scripts/bootstrap_manifest_signing_key.py` with explicit `--keyring`, `--new-key-id`, mutually exclusive `--check-only|--stage|--activate`, and `--backup-receipt` for activation. Implement `scripts/rotate_manifest_signing_key.py` with explicit `--keyring`, `--new-key-id`, `--check-only|--apply`, and `--backup-receipt`. Neither command accepts a secret on the command line or emits one. Keep receipt parsing/verifying behind a small injected boundary so Plan 2 unit tests use a deterministic fake and Plan 3 Task 24/26 binds it to the pinned encrypted-backup manifest verifier.

The runbook uses a root-owned `0700` `/etc/tamforge/secrets` directory and `0600` source/pending keyrings. For first installation it stages exactly one key, creates and independently verifies its encrypted backup, activates only against the matching receipt, verifies the speech-worker unit's `LoadCredential`, and starts the worker only after a synthetic sign/verify check. For rotation it backs up the existing keyring, verifies the receipt, rotates atomically, restarts only that worker so systemd refreshes its read-only runtime credential, then verifies an old manifest plus a new synthetic manifest. Document pre-activation pending cleanup, post-activation preservation, and rollback by atomically restoring the receipt-bound backed-up source keyring before restarting the worker. Key deletion is outside this plan and requires a separate retention/lineage decision.

Add ignore rules for `*manifest-signing-keys*.json`, temporary rotation files, and local secret directories. The secret scanner must fail if `secret_base64` key material appears outside synthetic test construction.

- [ ] **Step 13: Run rotation and secret-safety tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_manifest_keys.py apps/backend/tests/recordings/test_manifest_signing.py apps/backend/tests/recordings/test_manifest_key_bootstrap.py apps/backend/tests/recordings/test_manifest_key_rotation.py -q && ! uv run --project apps/backend python scripts/bootstrap_manifest_signing_key.py --keyring /tmp/nonexistent-parent/tamforge-manifest-keyring.json --check-only && ! uv run --project apps/backend python scripts/rotate_manifest_signing_key.py --keyring /tmp/nonexistent-tamforge-manifest-keyring.json --check-only`

Expected: overall command PASS; pytest is green, bootstrap rejects the unsafe/missing parent, rotation rejects the missing keyring, and both emit only safe typed errors with no secret value.

- [ ] **Step 14: Write failing streaming WAV tests**

Patch object reads to yield small chunks. Assert the signed envelope is verified before any source object is opened. Then assert standard-library `wave` output has correct channels, 44.1 kHz, 16-bit width, frame count, and PCM SHA; peak Python buffer stays below a fixed 2 MiB test sentinel; a signature/key failure or mid-read exception leaves no cataloged WAV artifact.

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_finalize.py -q`

Expected: FAIL because streaming finalization is absent.

- [ ] **Step 15: Implement crash-safe, signature-verifying WAV finalization**

Load the exact signed-envelope artifact, verify its raw hash/key ID/HMAC before trusting any object key or checksum, then stream source objects in manifest order through a task-scoped temporary file. Verify each object and the whole PCM stream while writing, close the WAV header, fsync, upload/HEAD-verify the deterministic derivative key, then catalog it transactionally with both raw-manifest and signed-envelope lineage. Delete only the temporary derivative on success/failure; retain all canonical source batches.

- [ ] **Step 16: Add honest incomplete-prefix finalization**

An interrupted recording may produce a WAV for its contiguous durable prefix, but its artifact metadata and UI state must say `incomplete`; never synthesize silence for unknown missing audio.

- [ ] **Step 17: Run manifest/signing/rotation/finalizer tests and static checks**

Run: `uv run --project apps/backend pytest apps/backend/tests/unit/test_config.py apps/backend/tests/recordings/test_manifest.py apps/backend/tests/recordings/test_manifest_keys.py apps/backend/tests/recordings/test_manifest_signing.py apps/backend/tests/recordings/test_manifest_key_bootstrap.py apps/backend/tests/recordings/test_manifest_key_rotation.py apps/backend/tests/recordings/test_finalize.py -q && uv run --project apps/backend ruff check apps/backend/src/tamforge_backend/recordings/manifest.py apps/backend/src/tamforge_backend/recordings/manifest_keys.py apps/backend/src/tamforge_backend/recordings/manifest_signing.py apps/backend/src/tamforge_backend/recordings/finalize.py scripts/bootstrap_manifest_signing_key.py scripts/rotate_manifest_signing_key.py && uv run --project apps/backend mypy apps/backend/src/tamforge_backend/recordings`

Expected: PASS with constant-time verification coverage, pre/post-rotation verification, verified WAV headers, secret-safe logs/output, and no leaked temporary artifact after injected failure.

- [ ] **Step 18: Commit owned manifest signing, rotation, and WAV finalization**

```bash
git add .env.example .gitignore apps/backend/src/tamforge_backend/config.py apps/backend/src/tamforge_backend/recordings/manifest.py apps/backend/src/tamforge_backend/recordings/manifest_keys.py apps/backend/src/tamforge_backend/recordings/manifest_signing.py apps/backend/src/tamforge_backend/recordings/finalize.py scripts/bootstrap_manifest_signing_key.py scripts/rotate_manifest_signing_key.py apps/backend/tests/unit/test_config.py apps/backend/tests/recordings/test_manifest.py apps/backend/tests/recordings/test_manifest_keys.py apps/backend/tests/recordings/test_manifest_signing.py apps/backend/tests/recordings/test_manifest_key_bootstrap.py apps/backend/tests/recordings/test_manifest_key_rotation.py apps/backend/tests/recordings/test_finalize.py apps/backend/tests/fixtures/synthetic_audio.py docs/runbooks/manifest-signing-key-rotation.md
git commit -m "feat(recording): sign manifests and finalize verified wav derivatives"
```

### Task 13: Add recording-priority speech jobs and a single-concurrency worker

**Files:**
- Modify: `apps/backend/src/tamforge_backend/jobs/service.py`
- Create: `apps/backend/src/tamforge_backend/jobs/scheduler.py`
- Create: `apps/backend/src/tamforge_backend/speech/__init__.py`
- Create: `apps/backend/src/tamforge_backend/speech/jobs.py`
- Create: `apps/backend/src/tamforge_backend/speech/priority.py`
- Create: `apps/backend/src/tamforge_backend/recordings/recovery.py`
- Create: `apps/backend/src/tamforge_backend/workers/__init__.py`
- Create: `apps/backend/src/tamforge_backend/workers/speech.py`
- Create: `apps/backend/tests/jobs/test_scheduler.py`
- Create: `apps/backend/tests/speech/test_job_chain.py`
- Create: `apps/backend/tests/speech/test_priority.py`
- Create: `apps/backend/tests/recordings/test_recovery.py`
- Create: `apps/backend/tests/workers/test_speech_worker.py`
- Create: `apps/backend/tests/integration/jobs/test_speech_pipeline.py`

- [ ] **Step 1: Write failing speech-handler registration and job-chain tests**

Assert `IngestSealed -> finalize_manifest -> finalize_wav -> derive_analysis_audio -> transcribe_track -> compute_metrics`, one idempotency key per source/version, no duplicate derived records on retry, typed `RetryWait`/`NeedsAttention`, and preservation of the original session after every failure.

Reuse Plan 1's durable `JobService`, repository, lease states, and shared `outbox_events`; test the smallest compatible extension required to register typed handlers. Prove output metadata, next-job enqueue, outbox event, and job completion commit or roll back together. Do not create a second job model/repository/outbox/poller.

- [ ] **Step 2: Run job-chain tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_job_chain.py -q`

Expected: FAIL because speech job contracts are incomplete.

- [ ] **Step 3: Register small handlers against the Plan 1 job service**

Extend `jobs/service.py` only with the tested handler-execution seam. Each handler accepts bounded typed IDs/version hashes, verifies its exact input artifact/version, writes a new derived version transactionally, enqueues the next job through the existing service, and writes the shared outbox row in the same unit of work. A retry must discover and reuse the existing matching output rather than duplicate it; no transcript/audio bytes enter job payloads.

- [ ] **Step 4: Run job-chain tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_job_chain.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing priority tests**

Define queues `turn_transcription` and `speech_bulk`. Assert priority turns may run during a live capture, bulk speech work does not start while any session is `Capturing`, already-running bulk work observes a cooperative yield checkpoint between bounded audio segments, and recording ingest never waits on the speech worker.

- [ ] **Step 6: Run priority tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_priority.py -q`

Expected: FAIL because `SpeechWorkPolicy` is absent.

- [ ] **Step 7: Implement `SpeechWorkPolicy`**

Use database state plus a short-lived lease, not an in-memory global flag. Limit the process to one active model job and two CPU threads. Preserve a starved bulk job's original enqueue time and do not spin while capture remains active.

- [ ] **Step 8: Run priority tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_priority.py -q`

Expected: PASS with fake database state and clock.

- [ ] **Step 9: Write failing stale-session recovery tests**

After heartbeat loss, move `Capturing` to `Interrupted/Reconnecting` and retain the device claim through a configured recovery grace period. A valid device may resume from durable high-water during that window. After grace expiry or an explicit owner action, seal only each track's contiguous durable prefix, mark the session `Incomplete` with reason, and enqueue reconciliation/manifest/WAV work. Never guess missing bytes or delete server segments/client spool.

- [ ] **Step 10: Run recovery tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_recovery.py apps/backend/tests/jobs/test_scheduler.py -q`

Expected: FAIL because stale-session recovery and database-clock scheduling are absent.

- [ ] **Step 11: Implement stale-session recovery and scheduler**

Use `jobs/scheduler.py`, Plan 1's `JobService`, and database timestamps; do not keep recovery timers only in process memory. Each scan has a stable idempotency key, uses a bounded batch, and is safe when two scheduler processes overlap.

- [ ] **Step 12: Run stale-session recovery tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_recovery.py apps/backend/tests/jobs/test_scheduler.py -q`

Expected: PASS with fake-clock reconnect/grace/finalization cases.

- [ ] **Step 13: Write failing worker crash/lease tests**

Cover process exit before output commit, lease expiry/reclaim, SIGTERM between segments, cancellation, model OOM categorization, and a second worker failing to acquire the single-concurrency advisory lease.

- [ ] **Step 14: Run worker tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/workers/test_speech_worker.py -q -m "not postgres_integration"`

Expected: FAIL because the worker entrypoint is absent.

- [ ] **Step 15: Implement the worker entrypoint**

Load heavyweight models lazily after the priority policy grants work. Set explicit CTranslate2/OpenMP thread configuration in process startup, release model/process resources after an idle timeout, and redact transcript/audio content from logs.

- [ ] **Step 16: Run all non-container job/worker tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/jobs/test_scheduler.py apps/backend/tests/speech/test_job_chain.py apps/backend/tests/speech/test_priority.py apps/backend/tests/recordings/test_recovery.py apps/backend/tests/workers/test_speech_worker.py -q -m "not postgres_integration"`

Expected: PASS with deterministic fake clock/lease behavior.

- [ ] **Step 17: Run PostgreSQL queue, outbox, scheduler, and lease tests only after Docker approval**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test TAMFORGE_REQUIRE_INTEGRATION_DB=1 uv run --project apps/backend pytest apps/backend/tests/integration/jobs/test_leases.py apps/backend/tests/integration/jobs/test_speech_pipeline.py -q -m integration
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS without skips; `SKIP LOCKED` claims are exclusive, transactional outbox rollback is proven, an expired lease is recovered once, overlapping schedulers are idempotent, and only one worker owns the speech concurrency lock. Final `ps` prints no running project services, including after a test failure via a shell cleanup trap.

- [ ] **Step 18: Commit speech job orchestration**

```bash
git add apps/backend/src/tamforge_backend/jobs/service.py apps/backend/src/tamforge_backend/jobs/scheduler.py apps/backend/src/tamforge_backend/speech apps/backend/src/tamforge_backend/workers apps/backend/src/tamforge_backend/recordings/recovery.py apps/backend/tests/jobs/test_scheduler.py apps/backend/tests/speech/test_job_chain.py apps/backend/tests/speech/test_priority.py apps/backend/tests/recordings/test_recovery.py apps/backend/tests/workers/test_speech_worker.py apps/backend/tests/integration/jobs/test_speech_pipeline.py
git commit -m "feat(speech): queue recording-aware local speech jobs"
```

### Task 14: Derive analysis audio and independent Silero speech intervals

**Files:**
- Create: `config/speech-models.yaml`
- Create: `apps/backend/src/tamforge_backend/speech/audio.py`
- Create: `apps/backend/src/tamforge_backend/speech/vad.py`
- Create: `apps/backend/src/tamforge_backend/speech/quality.py`
- Modify: `apps/backend/pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/backend/tests/speech/test_audio_derivation.py`
- Create: `apps/backend/tests/speech/test_vad.py`
- Create: `apps/backend/tests/speech/test_quality.py`

- [ ] **Step 1: Write failing audio-derivation tests**

From verified mono and stereo 44.1 kHz WAV fixtures, assert deterministic 16 kHz mono signed-PCM16 output, source artifact immutability, lineage to exact manifest/WAV, whole-derivative hash, bounded block processing, and no normalization that changes timing.

- [ ] **Step 2: Run audio tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_audio_derivation.py -q`

Expected: FAIL because the derivation port is absent.

- [ ] **Step 3: Implement streaming PyAV resampling/downmixing**

Use a fixed matrix for multi-channel-to-mono analysis while preserving the original channels separately. Record PyAV version, resampler settings, source/derived sample counts, and any duration delta.

Add pinned PyAV, NumPy, Silero VAD, and ONNX Runtime dependencies to `apps/backend/pyproject.toml`, then refresh `uv.lock`. Do not install the Torch runtime for baseline VAD.

- [ ] **Step 4: Run derivation tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_audio_derivation.py -q`

Expected: PASS with byte-stable output for the pinned dependency set.

- [ ] **Step 5: Write failing signal-quality gate tests**

Measure duration, all-silence, clipped-sample ratio, DC offset, channel energy imbalance before downmix, and discontinuity/sample-count mismatch. Assert quality failures make affected dimensions unavailable rather than silently lowering a learner score.

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_quality.py -q`

Expected: FAIL because versioned quality observations are absent.

- [ ] **Step 6: Implement versioned quality observations**

Do not claim a calibrated SNR estimator in MVP. Record observable signal conditions and thresholds with a version string; leave unsupported fields absent.

- [ ] **Step 7: Write failing VAD adapter tests**

Use a fake model to assert 16 kHz input, ordered non-overlapping speech intervals, configurable speech padding, retained raw model probabilities, pause intervals derived independently of Whisper words, and deterministic interval merging.

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_vad.py -q`

Expected: FAIL because the Silero adapter is absent.

- [ ] **Step 8: Implement the ONNX Silero adapter**

Pin the package in `uv.lock`; record the exact ONNX model source, license, file SHA-256, expected size, and compatible adapter/config version in `config/speech-models.yaml`. Run one CPU thread. Keep thresholds in versioned configuration and store them on every run.

- [ ] **Step 9: Run audio/VAD/quality tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_audio_derivation.py apps/backend/tests/speech/test_vad.py apps/backend/tests/speech/test_quality.py -q`

Expected: PASS.

- [ ] **Step 10: Run an opt-in local model smoke test**

Run: `TAMFORGE_RUN_LOCAL_MODELS=1 uv run --project apps/backend pytest apps/backend/tests/speech/test_vad.py -q -m local_model`

Expected: PASS on supported x86-64 CPU; skipped without the explicit environment marker.

- [ ] **Step 11: Commit analysis audio and VAD**

```bash
git add config/speech-models.yaml apps/backend/pyproject.toml uv.lock apps/backend/src/tamforge_backend/speech/audio.py apps/backend/src/tamforge_backend/speech/vad.py apps/backend/src/tamforge_backend/speech/quality.py apps/backend/tests/speech/test_audio_derivation.py apps/backend/tests/speech/test_vad.py apps/backend/tests/speech/test_quality.py
git commit -m "feat(speech): derive local analysis audio and vad intervals"
```

### Task 15: Persist immutable transcript lineage and run faster-whisper CPU INT8

**Files:**
- Create: `apps/backend/alembic/versions/20260825_0007_transcript_metrics.py`
- Modify: `config/speech-models.yaml`
- Create: `apps/backend/src/tamforge_backend/speech/transcription.py`
- Create: `apps/backend/src/tamforge_backend/speech/transcripts.py`
- Create: `apps/backend/src/tamforge_backend/speech/speakers.py`
- Create: `apps/backend/src/tamforge_backend/speech/processing_clock.py`
- Create: `apps/backend/src/tamforge_backend/speech/transcript_routes.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/speech/jobs.py`
- Modify: `apps/backend/pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/backend/tests/speech/test_transcription_adapter.py`
- Create: `apps/backend/tests/speech/test_transcript_repository.py`
- Create: `apps/backend/tests/speech/test_transcript_routes.py`
- Create: `apps/backend/tests/speech/test_speakers.py`
- Create: `apps/backend/tests/speech/test_processing_clock.py`

- [ ] **Step 1: Write failing migration/model tests**

Define immutable `transcripts`, `transcript_versions`, `word_tokens`, `uncertain_spans`, `speech_intervals`, and `speech_metric_sets`. Assert one raw engine version per `(track, engine, model, config_hash, source_artifact)`, ordered word times, explicit speaker/track, nullable probability, selected-for-analysis pointer by immutable version ID, and no update/delete of raw content through application repositories.

Add a shared persisted `processing_runs`/`processing_suspensions` timing ledger for Plan 3; it references and projects status into Plan 1's existing `activity_processing_statuses` rather than replacing it. A practice/mock run's eligible clock starts at the later of `IngestSealed` or `SelfReviewComplete`; a real-interview run starts at `IngestSealed`. Store wall-clock start, eligible start, `speech_ready_at`, future `feedback_ready_at`, queue delay, per-stage run time, active elapsed, suspension intervals/reasons, status, target, and exact evidence/version IDs. Only explicit `awaiting_debrief`, `awaiting_redaction`, `claude_quota`, and `claude_service_unavailable` intervals may suspend the composite clock. Quota/service exhaustion transitions to `NeedsAttention`; suspended quota time is reported separately and never counted as an on-time success.

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_transcript_repository.py apps/backend/tests/speech/test_processing_clock.py -q -m "not postgres_integration"`

Expected: FAIL because transcript models and repository contracts are absent.

- [ ] **Step 2: Verify the exact `_0006` head**

Run: `test "$(uv run --project apps/backend alembic -c apps/backend/alembic.ini heads | cut -d' ' -f1)" = "20260825_0006_recording_ingest"`

Expected: exit 0 with exactly one head. Stop and reconcile if it differs.

- [ ] **Step 3: Implement migration `20260825_0007_transcript_metrics.py`**

Set `down_revision = "20260825_0006_recording_ingest"` exactly. Keep the current selected-version pointer mutable on the parent transcript while every transcript version and token remains append-only. Add the processing-run/suspension tables and constraints in this revision, including non-overlapping closed intervals, allowed reasons, monotonic timestamps, and immutable eligibility mode. Register transcript/metric/processing model modules through `tamforge_backend.models`.

- [ ] **Step 4: Write failing transcript-engine contract tests**

Inject a fake engine and assert input is 16 kHz mono, English is fixed, word timestamps are requested, CTranslate2 config is recorded, output words are offset from each VAD chunk to track time, overlapping/regressing times become uncertainty rather than being silently rewritten, and cancellation checkpoints occur between chunks.

- [ ] **Step 5: Run adapter tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_transcription_adapter.py -q`

Expected: FAIL because the engine port is absent.

- [ ] **Step 6: Implement the transcript-engine port and faster-whisper adapter**

Baseline configuration: `small.en`, `device="cpu"`, `compute_type="int8"`, non-batched inference, `cpu_threads=2`, `num_workers=1`, `beam_size=5`, `word_timestamps=True`, `language="en"`, and `condition_on_previous_text=False`. Segment using the stored Silero intervals with fixed padding and offset results back to the original track timeline. Do not import or call stable-ts.

Add a pinned `faster-whisper` dependency and CTranslate2-compatible constraint to `apps/backend/pyproject.toml`, then refresh `uv.lock`. Model weights remain runtime artifacts outside Git and are verified against a model manifest.

- [ ] **Step 7: Run adapter tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_transcription_adapter.py -q`

Expected: PASS with fake engine; no model download occurs.

- [ ] **Step 8: Write failing repository tests for raw/corrected/selected versions**

Cover exact engine/config/source lineage, append-only user correction, uncertainty reasons, user correction attribution, selecting a version for analysis, reanalysis creating a new analysis input link, and raw-version preservation.

Add speaker tests: mic tokens are deterministically `learner`; system-track tokens are `remote_party` by default; known local TTS turns use their canonical `interviewer` label; multiple unknown remote people are never fabricated as named speakers; human speaker-label corrections append a new transcript version.

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_transcript_repository.py apps/backend/tests/speech/test_transcript_routes.py apps/backend/tests/speech/test_speakers.py apps/backend/tests/speech/test_processing_clock.py -q -m "not postgres_integration"`

Expected: FAIL because version selection, routes, speaker attribution, and processing-clock behavior are absent.

- [ ] **Step 9: Implement repository and correction/selection routes**

Expose owner-only `POST /api/v1/transcripts/{id}/versions` and `POST /api/v1/transcripts/{id}/selected-version`. Never let a recorder device token access transcript text. Emit an audit/outbox event when analysis selection changes.

Implement track-level attribution in `speakers.py`. A future diarizer may implement the same port, but no extra diarization model enters this 4 GiB baseline. Mark unresolved multi-interviewer attribution as uncertain and human-correctable.

Implement the processing clock as a database-backed service driven by recording/self-review/outbox events, using server timestamps and append-only suspension rows. It records actual wall time even when work finishes before eligibility begins. It exposes separate speech-stage and composite fields so Plan 2 cannot claim `FeedbackReady` and Plan 3 cannot hide speech queue/runtime inside one opaque duration.

- [ ] **Step 10: Run transcript unit and route tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/test_transcription_adapter.py apps/backend/tests/speech/test_transcript_repository.py apps/backend/tests/speech/test_transcript_routes.py apps/backend/tests/speech/test_speakers.py apps/backend/tests/speech/test_processing_clock.py -q`

Expected: PASS.

- [ ] **Step 11: Run migration/repository integration tests only after Docker approval**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run --project apps/backend pytest apps/backend/tests/speech/test_transcript_repository.py apps/backend/tests/integration/test_migrations.py -q -k transcript
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS without skips with append-only constraints and exact `_0006 -> _0007` migration round-trip; final `ps` prints no running project services.

- [ ] **Step 12: Run an opt-in faster-whisper smoke test**

Run: `TAMFORGE_RUN_LOCAL_MODELS=1 uv run --project apps/backend pytest apps/backend/tests/speech/test_transcription_adapter.py -q -m local_model`

Expected: PASS on the synthetic English fixture and record model/config metadata; skipped without the explicit marker.

- [ ] **Step 13: Commit transcript lineage and engine**

```bash
git add config/speech-models.yaml apps/backend/pyproject.toml uv.lock apps/backend/alembic/versions/20260825_0007_transcript_metrics.py apps/backend/src/tamforge_backend/speech/transcription.py apps/backend/src/tamforge_backend/speech/transcripts.py apps/backend/src/tamforge_backend/speech/speakers.py apps/backend/src/tamforge_backend/speech/processing_clock.py apps/backend/src/tamforge_backend/speech/transcript_routes.py apps/backend/src/tamforge_backend/speech/jobs.py apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/tests/speech/test_transcription_adapter.py apps/backend/tests/speech/test_transcript_repository.py apps/backend/tests/speech/test_transcript_routes.py apps/backend/tests/speech/test_speakers.py apps/backend/tests/speech/test_processing_clock.py
git commit -m "feat(speech): version local word-timestamped transcripts"
```

### Task 16: Compute deterministic fluency, lexical, and turn metrics with honest availability

**Files:**
- Create: `apps/backend/src/tamforge_backend/speech/metrics/__init__.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/models.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/fluency.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/lexical.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/syllables.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/turns.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/service.py`
- Create: `apps/backend/src/tamforge_backend/speech/metrics/data/fillers-v1.json`
- Modify: `apps/backend/pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/backend/tests/speech/metrics/test_fluency.py`
- Create: `apps/backend/tests/speech/metrics/test_lexical.py`
- Create: `apps/backend/tests/speech/metrics/test_turns.py`
- Create: `apps/backend/tests/speech/metrics/test_service.py`

- [ ] **Step 1: Write failing formula tests from hand-calculated timelines**

Test these version-1 definitions:

```text
response_duration = last_user_speech_end - first_user_speech_start
speech_rate_wpm = recognized_word_count / response_duration_minutes
articulation_rate_wpm = recognized_word_count / VAD_speaking_minutes
articulation_rate_syllables_per_second = syllable_count / VAD_speaking_seconds
phonation_time_ratio = VAD_speaking_seconds / response_duration
mean_length_of_run = recognized_words / number_of_pause_delimited_runs
```

Assert division-by-zero and insufficient-duration cases are `N/A`, not zero.

- [ ] **Step 2: Add pause-band and precision tests**

Use VAD gaps internal to the first/last speech interval. Version 1 bands are 250–499 ms, 500–999 ms, and at least 1000 ms. Store unrounded seconds; UI precision metadata must not imply better than the validated timestamp gate.

- [ ] **Step 3: Run fluency tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_fluency.py -q`

Expected: FAIL because calculators are absent.

- [ ] **Step 4: Implement pure fluency calculators**

No universal target WPM or automatic good/bad label belongs here. Output value, unit, availability, calculation version, exact input IDs, quality flags, and comparison cohort key (`task_family`, `mode`, duration band, rubric version).

- [ ] **Step 5: Implement deterministic syllable counting with provenance**

Use a pinned local CMU pronunciation dictionary where available and a documented vowel-group fallback. Store counts and fallback-token list so articulation rate is inspectable; do not pretend the fallback is phonetic analysis.

Add the small local dictionary dependency to `apps/backend/pyproject.toml` and refresh `uv.lock`; do not add spaCy or another heavyweight NLP model for this metric.

- [ ] **Step 6: Run fluency tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_fluency.py -q`

Expected: PASS.

- [ ] **Step 7: Write failing lexical/proxy tests**

Cover casefolded surface-token MATTR with a versioned fixed window, minimum sample length, content-token/repetition ratios, task-required-term coverage, filler/discourse-marker counts, contiguous repetition/restart candidates, and transparent proxy flags.

- [ ] **Step 8: Run lexical tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_lexical.py -q`

Expected: FAIL because lexical calculators are absent.

- [ ] **Step 9: Implement lexical metrics without a vocabulary-proficiency claim**

Plain TTR is not published. MATTR and required-term coverage compare only similar task formats. Off-the-shelf Whisper may omit disfluencies, so filler/restart counts carry `measurement_status="detected_minimum"` until their gold-set F1 gate passes.

- [ ] **Step 10: Run lexical tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_lexical.py -q`

Expected: PASS with explicit minimum-sample and proxy states.

- [ ] **Step 11: Write failing synchronized turn metric tests**

Compute response latency from system-track/local-playback end to first mic VAD speech, interruption/overlap duration from the two track timelines, clarification-response markers from canonical turn metadata, and `listening=N/A` when no scored stimulus/proposition contract exists. Do not infer listening proficiency from a monologue.

- [ ] **Step 12: Run turn tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_turns.py -q`

Expected: FAIL because synchronized turn calculators are absent.

- [ ] **Step 13: Implement synchronized turn metrics**

Consume only timelines whose clock mapping and precision status are compatible. Persist the chosen timing source and uncertainty; emit `N/A` instead of silently mixing browser, server, and audio clocks.

- [ ] **Step 14: Run turn tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_turns.py -q`

Expected: PASS for synchronized audio, playback-event fallback, and honest unavailable cases.

- [ ] **Step 15: Write failing metric-set service tests**

The service consumes exact transcript/VAD/quality/turn versions, persists one immutable metric set by input/config hash, normalizes no English rubric weights itself, and emits `metrics_ready`. Reprocessing after transcript correction creates a new metric set. When every required local speech output is durable, it atomically records `speech_ready_at`, stage queue/run durations, and the speech sub-budget result; it never writes `FeedbackReady`.

- [ ] **Step 16: Run service tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics/test_service.py -q`

Expected: FAIL because metric-set orchestration is absent.

- [ ] **Step 17: Implement immutable metric-set orchestration**

Resolve all input versions before calculation, persist values and availability/proxy metadata in one transaction, use a deterministic input/config idempotency hash, and enqueue the existing `metrics_ready` outbox event only after the metric set is durable. Update the shared processing run in that transaction. Version-1 monitored speech budgets are active elapsed at most 10 minutes for a 10-minute practice and at most 45 minutes for a 60-minute mock/real interview; report queue and execution time separately. A miss blocks the composite SLO claim but preserves every output.

- [ ] **Step 18: Run all deterministic metric tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/metrics -q`

Expected: PASS with exact hand-calculated values and explicit N/A/proxy states.

- [ ] **Step 19: Commit deterministic metrics**

```bash
git add apps/backend/pyproject.toml uv.lock apps/backend/src/tamforge_backend/speech/metrics apps/backend/tests/speech/metrics
git commit -m "feat(speech): calculate versioned evidence-based speech metrics"
```

### Task 17: Spike and gate the controlled pronunciation diagnostic

**Files:**
- Create: `apps/backend/alembic/versions/20260825_0008_pronunciation_diagnostics.py`
- Modify: `config/speech-models.yaml`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/__init__.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/models.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/adapter.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/mfa_adapter.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/kaldi_gop_adapter.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/calibration.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/scripts/tam-intelligibility-v1.yaml`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`
- Create: `apps/backend/tests/speech/pronunciation/test_adapter_contract.py`
- Create: `apps/backend/tests/speech/pronunciation/test_calibration.py`
- Create: `scripts/pronunciation_benchmark.py`
- Create: `evaluation/speech/schemas/pronunciation-annotation.schema.json`
- Create: `evaluation/speech/schemas/pronunciation-benchmark.schema.json`
- Create: `docs/decisions/0003-pronunciation-adapter.md`

- [ ] **Step 1: Write the known-script and annotation schemas**

The versioned script must be short, role-relevant, phonetically varied, and contain no employer/customer data. Annotation records audio quality, comprehensibility, segmental clarity, word stress, prosodic control, candidate target correctness, adjudicator, and timestamped notes. Keep actual annotations/audio private.

- [ ] **Step 2: Write failing adapter-contract tests**

Every candidate accepts clean 16 kHz mono audio plus exact known text and returns word/phone alignments, candidate evidence, quality warnings, engine/model/config versions, runtime, and peak-memory telemetry. It must not return accent, nationality, native-likeness, or an uncalibrated 0–4 score.

- [ ] **Step 3: Run adapter tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation/test_adapter_contract.py -q`

Expected: FAIL because pronunciation ports are absent.

- [ ] **Step 4: Implement the replaceable adapter port and unavailable baseline**

The default adapter returns `Pronunciation not yet measured` plus quality/availability reasons. This safe baseline is production-valid but does not satisfy full MVP pronunciation acceptance.

- [ ] **Step 5: Implement the MFA alignment candidate behind the port**

Use MFA's current supported single-file known-text alignment interface and a pinned English model/dictionary manifest. MFA alignment supplies timing/evidence only; it is never relabeled as a pronunciation score.

- [ ] **Step 6: Implement the official Kaldi GOP candidate behind the port**

Follow the official `gop_speechocean762` recipe with exact model/data/license provenance. Isolate subprocess arguments, use per-job temporary directories, never interpolate shell text, and classify OOV/alignment/model failure. Do not ship downloaded model artifacts in Git.

- [ ] **Step 7: Write failing calibration tests**

Test the approved gates: at least 85% of diagnostic rubric scores within one point of adjudicated human intelligibility scores, weighted agreement at least 0.60, false-target rate at most 10% after quality filtering, no accent field, and the same numeric CX23 host/resource/ingest gates defined in Task 21. Use at least two blinded human raters plus adjudication; a single self-rating cannot establish calibration. A missing gate yields disabled numeric scoring.

- [ ] **Step 8: Run calibration tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation/test_calibration.py -q`

Expected: FAIL because gate calculation and redacted aggregation are absent.

- [ ] **Step 9: Implement calibration and redacted benchmark aggregation**

The harness reads a private manifest of object IDs/local authorized paths, never copies audio into the repository, and writes per-run private results plus a commit-safe aggregate without transcripts or filenames.

- [ ] **Step 10: Run synthetic adapter/calibration tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation -q`

Expected: PASS with fake adapters; the unavailable baseline remains the selected default.

- [ ] **Step 11: Verify the exact `_0007` head**

Run: `test "$(uv run --project apps/backend alembic -c apps/backend/alembic.ini heads | cut -d' ' -f1)" = "20260825_0007_transcript_metrics"`

Expected: exit 0 with exactly one head. Stop and reconcile if it differs.

- [ ] **Step 12: Create migration `_0008_pronunciation_diagnostics` and register its models**

Set `down_revision = "20260825_0007_transcript_metrics"` exactly. Persist known-script version, source artifact, adapter/model/config, alignments/evidence artifact, human corrections, quality state, calibration-report ID, availability, and optional calibrated 0–4 intelligibility rubric result. Append new diagnostic versions; never overwrite raw data or human corrections. Import the pronunciation model module through the canonical `tamforge_backend.models` aggregator.

- [ ] **Step 13: Run candidate benchmark on the private pronunciation subset**

Run: `TAMFORGE_PRIVATE_EVAL=1 uv run --project apps/backend python scripts/pronunciation_benchmark.py --manifest evaluation/private/speech/pronunciation-manifest.json --output evaluation/private/results/pronunciation-0001.json`

Expected: a schema-valid private result containing agreement, false-target, runtime, per-process/cgroup and whole-host memory/CPU/PSI/swap telemetry, concurrent-ingest ACK latency, failure categories, and no accent/native-likeness measure. Run one candidate at a time in an isolated optional environment under the Task 21 CX23 quotas; do not install/load it into the baseline worker until it passes. This command may require large local candidate dependencies but may not use paid/external compute without a new explicit decision.

- [ ] **Step 14: Record the evidence-backed ADR**

Choose an adapter only if every calibration, quality, privacy, license, Task 21 whole-host resource/ingest, and speech SLO gate passes under the worst approved concurrency. Otherwise record `No candidate approved`, retain the safe unavailable adapter, mark full-MVP pronunciation acceptance blocked, and request a critical architecture decision rather than weakening the gate.

- [ ] **Step 15: Enable only the approved adapter through configuration**

Never infer success from model startup. Numeric pronunciation stays feature-flagged off until the database references the passing calibration report and exact adapter/model/config hash.

- [ ] **Step 16: Run migration integration tests only after Docker approval**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test uv run --project apps/backend pytest apps/backend/tests/integration/test_migrations.py apps/backend/tests/speech/pronunciation -q -k pronunciation
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS without skips for exact `_0007 -> _0008`, append-only history, and calibration-gated numeric availability; final `ps` prints no running project services.

- [ ] **Step 17: Commit the pronunciation spike and gate**

```bash
git add config/speech-models.yaml apps/backend/alembic/versions/20260825_0008_pronunciation_diagnostics.py apps/backend/src/tamforge_backend/speech/pronunciation apps/backend/src/tamforge_backend/models/__init__.py apps/backend/tests/speech/pronunciation scripts/pronunciation_benchmark.py evaluation/speech/schemas docs/decisions/0003-pronunciation-adapter.md
git commit -m "feat(speech): gate controlled pronunciation diagnostics by calibration"
```

### Task 18: Expose the controlled diagnostic and human-correction workflow

**Files:**
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/service.py`
- Create: `apps/backend/src/tamforge_backend/speech/pronunciation/routes.py`
- Modify: `apps/backend/src/tamforge_backend/speech/jobs.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Create: `apps/backend/tests/speech/pronunciation/test_service.py`
- Create: `apps/backend/tests/speech/pronunciation/test_routes.py`
- Create: `apps/web/src/features/pronunciation/PronunciationDiagnostic.tsx`
- Create: `apps/web/src/features/pronunciation/pronunciationApi.ts`
- Create: `apps/web/src/features/pronunciation/__tests__/PronunciationDiagnostic.test.tsx`

- [ ] **Step 1: Write failing service tests for the diagnostic lifecycle**

Cover script selection/version, clean-microphone-only recording session, quality rejection, adapter job idempotency, candidate targets, human accept/reject/correct actions, append-only correction history, recalculation after correction, and numeric score availability only with the exact passing calibration report.

- [ ] **Step 2: Run service tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation/test_service.py -q`

Expected: FAIL because `PronunciationDiagnosticService` is absent.

- [ ] **Step 3: Implement lifecycle service and job handler**

Free-speech recordings cannot call this scoring path. A diagnostic with bad quality or unapproved adapter remains `not_measured` and retains its audio/alignment evidence for later reanalysis.

- [ ] **Step 4: Run service tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation/test_service.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing owner-route tests**

Add routes to create/read a diagnostic, read the known script, read quality/alignment/candidate evidence through authorized signed artifact access, submit human corrections, and request reanalysis. Reject recorder-device credentials, cross-purpose recordings, mutation of old versions, and accent/native-likeness fields.

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation/test_routes.py -q`

Expected: FAIL because diagnostic routes are absent.

- [ ] **Step 6: Implement strict schemas/routes and audit events**

Return the exact human-facing unavailable message `Pronunciation not yet measured` when calibration is missing/failed. Do not expose raw acoustic posterior matrices in ordinary UI payloads; keep them as private derived artifacts.

- [ ] **Step 7: Write failing web component tests**

Test script display, microphone-only instruction, quality warning, timestamped target playback, human accept/reject/edit, calibration badge, no accent UI, and unavailable-state honesty.

Run: `pnpm --dir apps/web test -- PronunciationDiagnostic.test.tsx --run`

Expected: FAIL because the diagnostic component is absent.

- [ ] **Step 8: Implement the minimal diagnostic component**

Use the universal activity/recording controls from the foundation plan. Do not add a second browser recorder. The Mac assignment identifies purpose `pronunciation_diagnostic` and expects only the mic track.

- [ ] **Step 9: Run backend and web tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/speech/pronunciation/test_service.py apps/backend/tests/speech/pronunciation/test_routes.py -q && pnpm --dir apps/web test -- PronunciationDiagnostic.test.tsx --run`

Expected: PASS; no accent/native-likeness text or field exists.

- [ ] **Step 10: Commit the controlled diagnostic workflow**

```bash
git add apps/backend/src/tamforge_backend/speech/pronunciation apps/backend/src/tamforge_backend/speech/jobs.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/speech/pronunciation apps/web/src/features/pronunciation
git commit -m "feat(speech): review calibrated pronunciation evidence"
```

### Task 19: Define local TTS timing and priority-turn transcription interfaces

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/turns.py`
- Create: `packages/protocol/tests/test_turn_protocol.py`
- Create: `apps/backend/src/tamforge_backend/interviewer/__init__.py`
- Create: `apps/backend/src/tamforge_backend/interviewer/turn_audio.py`
- Create: `apps/backend/src/tamforge_backend/interviewer/turn_routes.py`
- Modify: `apps/backend/src/tamforge_backend/speech/jobs.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Create: `apps/backend/tests/interviewer/test_turn_audio.py`
- Create: `apps/backend/tests/interviewer/test_turn_routes.py`
- Create: `apps/web/src/features/interviewer/audio/LocalQuestionPlayer.ts`
- Create: `apps/web/src/features/interviewer/audio/__tests__/LocalQuestionPlayer.test.ts`

- [ ] **Step 1: Write failing shared turn-contract tests**

Define strict contracts for `QuestionReady`, `PlaybackStarted`, `PlaybackEnded`, `AnswerCapturing`, `AnswerSealed`, `PriorityTranscriptRequested`, `PriorityTranscriptReady`, `FollowupDecisionRequested`, timeout, and session seal. Include attempt/session/turn IDs, canonical question text hash, client monotonic timing, server receipt timing, and optional synchronized system-track sample positions.

- [ ] **Step 2: Run protocol tests and confirm failure**

Run: `uv run --project packages/protocol pytest packages/protocol/tests/test_turn_protocol.py -q`

Expected: FAIL because turn contracts are absent.

- [ ] **Step 3: Implement strict turn models and serialization**

Generated TTS audio is neither a Claude input nor a persisted artifact. Store question text/version and timing events only; system-track source audio remains governed by the recording pipeline.

- [ ] **Step 4: Run protocol tests**

Run: `uv run --project packages/protocol pytest packages/protocol/tests/test_turn_protocol.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing browser-local TTS tests**

Mock `window.speechSynthesis`. Assert playback is generated from approved question text, `PlaybackStarted/Ended` callbacks are emitted once, cancel/error is explicit, no audio blob is uploaded, and Answer capture cannot begin until playback ends or is explicitly aborted.

Run: `pnpm --dir apps/web test -- LocalQuestionPlayer.test.ts --run`

Expected: FAIL because `LocalQuestionPlayer` is absent.

- [ ] **Step 6: Implement `LocalQuestionPlayer` as a narrow port**

Use browser SpeechSynthesis where available and return an unsupported result otherwise; do not introduce cloud TTS. Voice/rate choices are local presentation settings, not model prompt context.

- [ ] **Step 7: Write failing backend priority-turn tests**

For an answer no longer than five minutes, server receipt of `AnswerSealed` creates one highest-priority transcript job over the exact mic sequence/sample range. Persist the boundary through the transaction that commits `PriorityTranscriptReady`, including queue delay, model runtime, cold/warm state, source range, and timing version. Assert it can preempt queued bulk work, does not access hidden reviewer/coach context, exposes only the current allowed turn history, enforces at most two routine follow-ups in application state, and times out at the configured deadline.

Run: `uv run --project apps/backend pytest apps/backend/tests/interviewer/test_turn_audio.py apps/backend/tests/interviewer/test_turn_routes.py -q`

Expected: FAIL because turn audio orchestration and routes are absent.

- [ ] **Step 8: Implement `TurnAudioService` and routes**

Routes accept playback events from the authenticated web session and answer-seal from the session owner/state machine. The priority job returns a transcript-version ID and timing/quality metadata through an outbox event; the Interviewer/Claude layer consumes that interface in its own plan.

This plan gates only `AnswerSealed` server receipt to durable `PriorityTranscriptReady` at p95 <=90 seconds. Plan 3 owns and must separately demonstrate the approved composite `AnswerSealed -> Claude follow-up -> local playback` p95 <=120 seconds; Plan 2 never labels transcript readiness as local playback readiness.

- [ ] **Step 9: Add response-latency selection logic**

Prefer synchronized system-track VAD/sample timing when available; otherwise use recorded playback events with explicit lower precision. Never combine mismatched local clocks as though they share an epoch.

- [ ] **Step 10: Run turn protocol/backend/web tests**

Run: `uv run --project packages/protocol pytest packages/protocol/tests/test_turn_protocol.py -q && uv run --project apps/backend pytest apps/backend/tests/interviewer/test_turn_audio.py apps/backend/tests/interviewer/test_turn_routes.py -q && pnpm --dir apps/web test -- LocalQuestionPlayer.test.ts --run`

Expected: PASS with two-follow-up hard limit and no persisted/generated TTS audio.

- [ ] **Step 11: Commit turn audio interfaces**

```bash
git add packages/protocol/src/tamforge_protocol/turns.py packages/protocol/tests/test_turn_protocol.py apps/backend/src/tamforge_backend/interviewer apps/backend/src/tamforge_backend/speech/jobs.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/interviewer apps/web/src/features/interviewer/audio
git commit -m "feat(interviewer): prioritize sealed turns with local tts timing"
```

### Task 20: Assemble the minimal always-on-top recorder controller and GUI

**Files:**
- Create: `apps/recorder/src/tamforge_recorder/controller.py`
- Create: `apps/recorder/src/tamforge_recorder/app.py`
- Create: `apps/recorder/src/tamforge_recorder/__main__.py`
- Create: `apps/recorder/tests/test_controller.py`
- Create: `apps/recorder/tests/test_app.py`

- [ ] **Step 1: Write failing controller state tests**

Cover startup credential check, pairing needed, assignment ready, device preflight, Start, dual-stream/spool/network startup order, Stop, remote seal, reconnect, spool recovery on relaunch, cap/queue failure, permission failure, revoked token, and safe shutdown.

- [ ] **Step 2: Assert startup/shutdown ordering explicitly**

Start order is credentials -> assignment claim -> device preflight -> spool worker -> network negotiation -> capture streams. Stop order is capture stop -> callback queue drain -> spool drain -> network upload -> track seal -> remote session seal -> eligible spool deletion. Any partial failure unwinds only resources already started.

- [ ] **Step 3: Run controller tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_controller.py -q`

Expected: FAIL because the controller is absent.

- [ ] **Step 4: Implement controller with injected ports and thread-safe UI events**

Tkinter owns the main thread. Audio callbacks, spool writer, and networking thread communicate through bounded queues/events. Only `root.after(...)` updates widgets. Never block the GUI while connecting, stopping, sealing, or recovering.

- [ ] **Step 5: Run controller tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_controller.py -q`

Expected: PASS.

- [ ] **Step 6: Write failing minimal-GUI tests**

Assert `-topmost=True`, one Start/Stop button, status label, concise actionable error/recovery text, pairing dialog only when needed, Start disabled without assignment/preflight, Stop available within one second while capture is active, and no waveform/transcript/history view.

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_app.py -q`

Expected: FAIL because the Tkinter app is absent.

- [ ] **Step 7: Implement the Tkinter app and entrypoint**

The status differentiates `Ready`, `Recording`, `Reconnecting`, `Stopping`, `Uploading recovery audio`, `Complete`, and `Needs attention`. Closing during active/recoverable capture asks whether to stop safely; it never silently deletes spool data.

- [ ] **Step 8: Run recorder unit/UI tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/test_controller.py apps/recorder/tests/test_app.py -q`

Expected: PASS under the headless Tk fixture with all worker threads joined.

- [ ] **Step 9: Run recorder quality checks**

Run: `uv run --project apps/recorder ruff check apps/recorder && uv run --project apps/recorder mypy apps/recorder/src`

Expected: Ruff and mypy clean.

- [ ] **Step 10: Commit the recorder shell**

```bash
git add apps/recorder/src/tamforge_recorder/controller.py apps/recorder/src/tamforge_recorder/app.py apps/recorder/src/tamforge_recorder/__main__.py apps/recorder/tests/test_controller.py apps/recorder/tests/test_app.py
git commit -m "feat(recorder): add minimal resilient mac recording app"
```

### Task 21: Build reproducible failure-injection and performance evaluation harnesses

**Files:**
- Create: `scripts/recording_failure_harness.py`
- Create: `scripts/speech_benchmark.py`
- Create: `scripts/cx23_speech_benchmark.py`
- Create: `apps/recorder/scripts/hardware_soak.py`
- Create: `evaluation/speech/README.md`
- Create: `evaluation/speech/cx23-profile.yaml`
- Create: `evaluation/speech/schemas/gold-manifest.schema.json`
- Create: `evaluation/speech/schemas/transcript-annotation.schema.json`
- Create: `evaluation/speech/schemas/benchmark-result.schema.json`
- Create: `evaluation/speech/schemas/cx23-benchmark.schema.json`
- Create: `evaluation/speech/schemas/recorder-hardware-soak.schema.json`
- Create: `apps/backend/tests/evaluation/test_speech_benchmark.py`
- Create: `apps/backend/tests/evaluation/test_cx23_benchmark.py`
- Create: `apps/recorder/tests/soak/test_recorder_soak.py`
- Create: `apps/recorder/tests/soak/test_hardware_report.py`
- Create: `apps/backend/tests/recordings/test_failure_injection.py`
- Create: `docs/runbooks/recording-recovery.md`
- Create: `docs/runbooks/speech-worker.md`

- [ ] **Step 1: Write schemas and private-evaluation instructions first**

The private gold manifest references authorized artifact IDs/paths and contains manual verbatim transcript, critical TAM terms, word/pause timestamps, track identity, task mode, and human ratings. The CX23 and hardware schemas require run/fixture IDs, code commit, model/config hashes, wall/eligible clocks, host/device profile, thresholds, raw aggregate counters, and pass/fail reasons. Commit schemas/instructions only; add `evaluation/private/` to `.gitignore` in the foundation plan or this task if absent.

- [ ] **Step 2: Write failing recorder soak assertions**

Use generated PCM and fake callbacks/network. Assert in-memory audio at most five seconds per track, peak RSS at most 100 MiB, RSS growth after warm-up at most 10 MiB over a 60-minute simulated/accelerated run, configured 2 GiB spool cap/reserve behavior, and Start/Stop/status responsiveness within one second.

- [ ] **Step 3: Run recorder soak test and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/soak/test_recorder_soak.py -q`

Expected: FAIL because resource instrumentation and the soak driver are absent.

- [ ] **Step 4: Implement recorder resource instrumentation and soak harness**

Read RSS through `psutil`; emit a schema-valid result. Implement both the accelerated fake driver and a hardware driver that uses the saved device fingerprints and an owner-created `benchmark` assignment without retaining source audio on the Mac. Do not weaken limits for CI—use accelerated duration for routine CI and reserve the true 60-minute hardware run for release evidence.

- [ ] **Step 5: Run recorder soak test**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/soak/test_recorder_soak.py -q`

Expected: PASS for the accelerated deterministic run; the true 60-minute hardware evidence remains a release checkpoint.

- [ ] **Step 6: Run the true 3,600-second Mac hardware soak at the release checkpoint**

Create a dedicated remote `benchmark` assignment first, feed deterministic live system audio through BlackHole, keep the microphone open, then run:

```bash
TAMFORGE_HARDWARE_SOAK=1 uv run --project apps/recorder python apps/recorder/scripts/hardware_soak.py --duration-seconds 3600 --system-device "BlackHole 2ch" --output evaluation/private/results/recorder-hardware-soak-release-0001.json
```

Expected: schema-valid private result with actual callback/device evidence; peak recorder RSS <=100 MiB, post-warm-up RSS growth <=10 MiB, callback-queue high-water <=5 seconds per track, Start/Stop/status response <=1 second, no silent callback drop, valid reconnect/seal hashes, and no recoverable spool after remote seal. Any failure blocks recorder release; accelerated CI is not accepted as substitute.

- [ ] **Step 7: Write failing transport failure matrix**

Inject duplicate, delayed, reordered, future, and conflicting frames; disconnect before/after object PUT and before/after DB commit; object timeout; DB rollback; server process kill; nearly full disk; client kill; finalizer kill; and retry. Assert exact acknowledged-byte reconstruction, bounded memory/spool, no false completion, and preserved recoverability.

- [ ] **Step 8: Run transport failure tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_failure_injection.py -q -m "not container_integration"`

Expected: FAIL because seeded kill points and failure controls are absent.

- [ ] **Step 9: Implement deterministic failure harness controls**

Use seeded schedules and explicit kill points. The default target is fakes/local child processes, never production. A real test bucket/server requires an explicit environment marker and isolated prefix.

- [ ] **Step 10: Run non-container transport failure tests**

Run: `uv run --project apps/backend pytest apps/backend/tests/recordings/test_failure_injection.py -q -m "not container_integration"`

Expected: PASS with exact reconstructed hashes and explicit incomplete outcomes at every kill point.

- [ ] **Step 11: Write failing speech, processing-clock, priority, and host-budget calculations**

Calculate median and p90 WER, critical-term recall, pause F1, pause-boundary MAE, deterministic-metric error, runtime, real-time factor, speech queue/runtime/active-clock budgets, and priority-turn latency distribution. For the host report calculate minimum `/proc/meminfo` `MemAvailable`, per-process and systemd-cgroup peaks, swap-in/out deltas, memory PSI, CPU/MemoryMax quotas, ingest frame-to-ACK and batch-ready-to-ACK p95. Do not include transcript/audio content in the redacted report.

- [ ] **Step 12: Run benchmark tests and confirm failure**

Run: `uv run --project apps/backend pytest apps/backend/tests/evaluation/test_speech_benchmark.py apps/backend/tests/evaluation/test_cx23_benchmark.py -q`

Expected: FAIL because benchmark calculations, host telemetry decisions, and schema output are absent.

- [ ] **Step 13: Implement the benchmark harnesses and explicit decisions**

Decision-grade gate: median WER <=15%, p90 WER <=25%, critical-term recall >=90%, pause F1 >=0.90 and boundary MAE <=150 ms for pauses >=500 ms, and deterministic numeric metrics within 5% of hand-calculated gold values. Exact filler/restart counts remain disabled unless their event-level F1 is at least 0.80. Failure leaves transcripts visible but marks affected speech observations non-decision-grade or proxy-only.

Speech-stage gates are `speech_ready_at` active elapsed <=10 minutes for a 10-minute practice and <=45 minutes for a 60-minute mock/real interview. This plan does not test or claim `FeedbackReady`. Priority transcription uses at least 20 cold and 20 warm trials, across at least five representative answers up to five minutes, while bulk work is queued and dual-track ingest is live; both populations must meet p95 `AnswerSealed` server receipt -> durable `PriorityTranscriptReady` <=90 seconds. Plan 3 separately owns the composite local-follow-up-playback p95 <=120 seconds.

The whole-host CX23 gate, sampled throughout the worst approved concurrency (dual-track ingest + one speech job + one Claude compatibility job, with embeddings paused/yielding), requires: `MemAvailable >=1 GiB`; no OOM; zero swap-in/out increase; zero memory-PSI `full` stall delta; maximum memory-PSI `some avg10 <1.0%`; batch-ready -> durable ACK p95 <=2 seconds and frame-receipt -> ACK p95 <=7 seconds. Record total host plus Caddy, API, PostgreSQL, speech-worker, and Claude-worker process/cgroup peaks. Record exact deployed systemd `MemoryMax` and `CPUQuota` for each; a missing/unlimited app-worker quota fails the gate. `evaluation/speech/cx23-profile.yaml` versions these thresholds, required service names, fixture counts, and telemetry sampling interval.

- [ ] **Step 14: Run all fake/synthetic harness tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/soak/test_recorder_soak.py apps/recorder/tests/soak/test_hardware_report.py -q && uv run --project apps/backend pytest apps/backend/tests/recordings/test_failure_injection.py apps/backend/tests/evaluation/test_speech_benchmark.py apps/backend/tests/evaluation/test_cx23_benchmark.py -q`

Expected: PASS with schema-valid synthetic reports and exact checksum reconstruction.

- [ ] **Step 15: Run container-backed fault integration only after Docker approval**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d postgres minio
docker compose -f compose.dev.yml run --rm minio-init
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test TAMFORGE_S3_ENDPOINT_URL=http://127.0.0.1:59000 TAMFORGE_S3_BUCKET=tamforge-test TAMFORGE_S3_ACCESS_KEY=tamforge-test TAMFORGE_S3_SECRET_KEY=tamforge-test-only-secret TAMFORGE_REQUIRE_INTEGRATION_DB=1 TAMFORGE_REQUIRE_OBJECT_STORE_INTEGRATION=1 uv run --project apps/backend pytest apps/backend/tests/recordings/test_failure_injection.py -q -m container_integration
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS without skips against isolated PostgreSQL/S3-compatible services; final `ps` prints no running project services, including after a failure via the cleanup trap.

- [ ] **Step 16: Run the private 20–30 recording gold set**

Run: `TAMFORGE_PRIVATE_EVAL=1 uv run --project apps/backend python scripts/speech_benchmark.py --manifest evaluation/private/speech/gold-manifest.json --output evaluation/private/results/speech-0001.json`

Expected: a private schema-valid result and redacted aggregate. If any decision-grade gate fails, affected metrics remain experimental/unavailable and a bounded improvement issue is created; do not silently change thresholds.

- [ ] **Step 17: Run the reproducible CX23 benchmark only after Plan 3 deployment compatibility**

This release checkpoint runs after the Plan 3 Claude worker, deployment units, and synthetic Claude compatibility job exist; it does not block earlier unit implementation. On `tam-forge-prod`, through the deployment runbook, run:

```bash
cd /opt/tamforge/current
sudo -u tamforge env TAMFORGE_PRODUCTION_BENCHMARK=1 uv run --project apps/backend python scripts/cx23_speech_benchmark.py --profile evaluation/speech/cx23-profile.yaml --manifest /var/lib/tamforge/private-eval/cx23-manifest.json --output /var/lib/tamforge/private-eval/results/cx23-release-0001.json --practice-trials 5 --mock-trials 3 --priority-cold-trials 20 --priority-warm-trials 20 --require-live-ingest --require-claude-compatibility-load
```

The private manifest contains exact approved fixture/artifact IDs; the driver refuses arbitrary object paths, production customer/interview data, missing service quotas, a dirty/mismatched commit, or an unpaused embedding worker. It emits a schema-validated decision with code commit, OS/host profile, exact systemd quota values, model/config/file hashes, trial IDs/counts, per-stage clocks, host/cgroup telemetry, ACK distributions, and every threshold input.

Expected: PASS for the Task 21 speech/priority/host/ingest gates. `FeedbackReady` 15/60-minute and `AnswerSealed -> local follow-up playback` 120-second composite evidence is explicitly absent here and must be appended by Plan 3. Failure first runs the already-approved `base.en` INT8 comparison against the same fixtures; then stop for a critical decision before external compute, paid services, another server, or more monthly cost.

- [ ] **Step 18: Write recovery and worker runbooks from tested behavior**

Document status interpretation, safe spool recovery, incomplete finalization, reconciliation dry run, retry/attention categories, model cache, resource limits, gold-set revalidation, and the Docker approval rule.

- [ ] **Step 19: Commit harnesses and runbooks**

```bash
git add scripts/recording_failure_harness.py scripts/speech_benchmark.py scripts/cx23_speech_benchmark.py apps/recorder/scripts/hardware_soak.py evaluation/speech apps/backend/tests/evaluation apps/backend/tests/recordings/test_failure_injection.py apps/recorder/tests/soak docs/runbooks/recording-recovery.md docs/runbooks/speech-worker.md .gitignore
git commit -m "test(speech): verify recording durability and speech quality gates"
```

### Task 22: Package and verify the standalone macOS `.app`

**Files:**
- Create: `apps/recorder/TAMForgeRecorder.spec`
- Create: `apps/recorder/assets/Info.plist`
- Create: `apps/recorder/scripts/build_app.sh`
- Create: `apps/recorder/tests/packaging/test_bundle_metadata.py`
- Create: `apps/recorder/tests/packaging/test_imports.py`
- Create: `apps/recorder/tests/packaging/scan_bundle.py`
- Create: `docs/runbooks/mac-recorder-install.md`

- [ ] **Step 1: Write failing packaging metadata/import tests**

Assert bundle name `TAM Forge Recorder`, identifier `com.frank.tamforge.recorder`, `NSMicrophoneUsageDescription`, no console window, native architecture, protocol package inclusion, `sounddevice`/PortAudio binaries, Keychain backend, cryptography backend, CA bundle, and no `.env`, token, spool database, test fixture, model, or private evaluation file.

- [ ] **Step 2: Run packaging tests and confirm failure**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/packaging -q`

Expected: FAIL because the spec/bundle metadata is absent.

- [ ] **Step 3: Create the PyInstaller spec and build script**

Use a native-architecture Python environment, windowed mode, explicit hidden imports only where hooks require them, a sanitized resource list, and reproducible clean output. The build script must execute:

```bash
uv run --project apps/recorder pyinstaller --noconfirm --clean apps/recorder/TAMForgeRecorder.spec
```

Expected artifact: `dist/TAM Forge Recorder.app`.

After PyInstaller completes, the script applies an ad-hoc signature with `codesign --force --deep --sign -` for the private local bundle; Developer ID signing and notarization remain deferred.

- [ ] **Step 4: Run packaging tests**

Run: `uv run --project apps/recorder pytest apps/recorder/tests/packaging -q`

Expected: PASS before building.

- [ ] **Step 5: Build the `.app` on macOS**

Run: `bash apps/recorder/scripts/build_app.sh`

Expected: clean PyInstaller exit and `dist/TAM Forge Recorder.app` present.

- [ ] **Step 6: Verify bundle structure and signature integrity**

Run: `plutil -lint "dist/TAM Forge Recorder.app/Contents/Info.plist" && codesign --verify --deep --strict --verbose=2 "dist/TAM Forge Recorder.app"`

Expected: plist OK and signature valid. Use an ad-hoc signature for personal local testing unless a Developer ID/notarization decision is explicitly made later.

- [ ] **Step 7: Scan the bundle for forbidden secret/private files**

Run: `uv run --project apps/recorder python apps/recorder/tests/packaging/scan_bundle.py "dist/TAM Forge Recorder.app"`

Expected: PASS; no secret, spool, `.env`, private audio/evaluation, or backend credential material found.

- [ ] **Step 8: Perform the real-Mac smoke checklist**

Launch through Finder; approve microphone permission; resolve mic and BlackHole; pair; claim a synthetic practice assignment; capture both tracks; disconnect/reconnect Wi-Fi; Stop; verify remote seal; relaunch and verify no recoverable spool remains. Record app RSS, sync, drift, status responsiveness, and server hashes.

Expected: all release budgets pass, or release remains blocked with the failing evidence attached.

- [ ] **Step 9: Write the install/re-pair/recovery runbook**

Include BlackHole setup, microphone permission recovery, Keychain item names, device revocation/re-pair, log location with redaction, safe spool status, and exact build command. Do not document secret values.

- [ ] **Step 10: Commit packaging sources and docs, never `dist/`**

```bash
git add apps/recorder/TAMForgeRecorder.spec apps/recorder/assets/Info.plist apps/recorder/scripts/build_app.sh apps/recorder/tests/packaging docs/runbooks/mac-recorder-install.md .gitignore
git commit -m "build(recorder): package verified macos app bundle"
```

### Task 23: Verify the complete recording-to-metrics slice and freeze interfaces

**Files:**
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Create: `apps/backend/tests/e2e/test_recording_to_metrics.py`
- Create: `apps/backend/tests/e2e/test_interrupted_recording.py`
- Create: `apps/backend/tests/e2e/test_priority_turn.py`
- Create: `docs/contracts/recording-speech-v1.md`
- Modify: `docs/runbooks/recording-recovery.md`
- Modify: `docs/runbooks/speech-worker.md`

- [ ] **Step 1: Write the end-to-end happy-path test**

Pair a fake device, create/claim a selected practice session, send two tracks with duplicate/reconnect behavior, seal, finalize manifests/WAVs, run fake VAD/transcriber then deterministic metrics, correct/select a transcript version, and assert immutable lineage from activity to every artifact/result.

- [ ] **Step 2: Write the interrupted-path test**

Kill the client/server at each durability boundary, resume from high-water where possible, finalize the contiguous prefix otherwise, and assert every acknowledged frame reconstructs byte-for-byte while state remains honestly `Incomplete` when required.

- [ ] **Step 3: Write the priority-turn path test**

Play a local question event, seal a bounded answer, create the turn-priority job while a bulk job waits, return a transcript version/event, calculate response latency with explicit timing precision, and assert no reviewer/coach context or generated TTS audio enters the result.

- [ ] **Step 4: Extend non-Docker Make and CI checks for the recorder slice**

Add `test-recorder` and `check-recorder` Make targets and a macOS CI job for recorder unit/static/packaging-metadata tests. Extend existing backend/protocol CI paths for this slice. No default `test`/`check` target may start Docker, download local speech models, access private evaluation data, build the `.app`, or require recording hardware.

Run: `make check-recorder`

Expected: PASS locally on macOS without Docker, model downloads, network calls, or hardware capture.

- [ ] **Step 5: Run all non-container unit/contract/E2E tests**

Run: `uv run --project packages/protocol pytest packages/protocol/tests -q && uv run --project apps/recorder pytest apps/recorder/tests -q -m "not hardware" && uv run --project apps/backend pytest apps/backend/tests/recordings apps/backend/tests/speech apps/backend/tests/interviewer apps/backend/tests/e2e -q -m "not postgres_integration and not object_store_integration and not container_integration and not local_model"`

Expected: PASS without starting Docker, downloading models, or contacting external services.

- [ ] **Step 6: Run the complete integration set only after Docker approval**

`[REQUIRES EXPLICIT DOCKER APPROVAL]` Run:

```bash
set -e
trap 'docker compose -f compose.dev.yml down' EXIT
docker compose -f compose.dev.yml up -d postgres minio
docker compose -f compose.dev.yml run --rm minio-init
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test TAMFORGE_S3_ENDPOINT_URL=http://127.0.0.1:59000 TAMFORGE_S3_BUCKET=tamforge-test TAMFORGE_S3_ACCESS_KEY=tamforge-test TAMFORGE_S3_SECRET_KEY=tamforge-test-only-secret TAMFORGE_REQUIRE_INTEGRATION_DB=1 TAMFORGE_REQUIRE_OBJECT_STORE_INTEGRATION=1 uv run --project apps/backend pytest apps/backend/tests/recordings apps/backend/tests/speech apps/backend/tests/interviewer apps/backend/tests/e2e -q -m "postgres_integration or object_store_integration or container_integration"
docker compose -f compose.dev.yml down
trap - EXIT
docker compose -f compose.dev.yml ps --status running
```

Expected: PASS with no skips against the isolated PostgreSQL/MinIO services; final `ps` prints no running project services, including after a test failure via the cleanup trap.

- [ ] **Step 7: Run formatting, lint, types, and web tests**

Run: `uv run --project packages/protocol ruff check packages/protocol && uv run --project packages/protocol mypy packages/protocol/src && uv run --project apps/recorder ruff check apps/recorder && uv run --project apps/recorder mypy apps/recorder/src && uv run --project apps/backend ruff check apps/backend && uv run --project apps/backend mypy apps/backend/src && pnpm --dir apps/web test -- LocalQuestionPlayer.test.ts PronunciationDiagnostic.test.tsx --run`

Expected: all checks PASS.

- [ ] **Step 8: Perform privacy/immutability assertions**

Search structured model-request fixtures, logs, and bundle contents to prove original audio is never a Claude input; recorder devices cannot read transcripts; raw audio/transcript/analysis versions are append-only; object URLs are private/short-lived; and real-interview text remains outside this plan's automatic processing path.

- [ ] **Step 9: Freeze and document v1 contracts**

Write `docs/contracts/recording-speech-v1.md` with the exact frame/control schema, ACK semantics, object keys, state transitions, metric formulas/availability, model configuration, pronunciation gate, error codes, and compatibility policy. Link the tested runbooks and avoid duplicating secrets/config values.

- [ ] **Step 10: Review acceptance evidence against the approved specification**

Require: bounded recorder budgets; sync/drift gate; no acknowledged loss under injected failures; 10/60-minute SLO; priority turn p95; speech gold-set gate; transcript lineage; deterministic metric accuracy; pronunciation calibration or explicit full-MVP blocker; no accent scoring; and no paid fallback.

- [ ] **Step 11: Commit final E2E contracts**

```bash
git add Makefile .github/workflows/ci.yml apps/backend/tests/e2e docs/contracts/recording-speech-v1.md docs/runbooks/recording-recovery.md docs/runbooks/speech-worker.md
git commit -m "test(speech): verify recording to metrics contract"
```

- [ ] **Step 12: Push and open the exact stacked draft PR**

```bash
test "$(git branch --show-current)" = "feat/recording-speech"
git status --short
git push -u origin feat/recording-speech
gh pr create --repo fgomensoro/tam-forge \
  --draft \
  --base feat/foundation-learning-workspace \
  --head feat/recording-speech \
  --title "Recording: durable audio and speech evidence" \
  --body-file .github/pull_request_body.md
```

Expected: the worktree is clean, the PR is draft, its base/head are exact, and its body records the Plan 1 prerequisite SHA plus linked issue keys. Verify the final head, required CI, review, and three-dot file diff. Stop for explicit merge approval; do not merge, force-push, or delete either branch.

## Execution stop/decision points

Implementation proceeds autonomously task-by-task except at these material boundaries:

1. **Docker/Testcontainers/Compose:** wait for explicit approval before each marked local command group.
2. **Real Hetzner/production credentials or deployment:** follow the infrastructure/deployment plan and its secret-handling/rollback gate; this plan's fakes do not authorize production mutation.
3. **Pronunciation calibration fails:** keep numeric pronunciation disabled and ask for a critical architecture decision; do not substitute Whisper probability or accent scoring.
4. **CX23 benchmark fails quality/resource/SLO:** compare `base.en` INT8 against the same gold set, then stop for approval before external compute, paid services, another server, or additional monthly cost.
5. **Developer ID signing/notarization:** personal ad-hoc packaging is sufficient for the initial private app; paid Apple distribution credentials require a separate decision.
6. **Any source-audio deletion or compaction:** source segments remain retained; deletion/compaction is outside this plan and requires verified reconstruction plus explicit retention authorization.

## Completion evidence

The child plan is complete only when the commit-bound v1 protocol and state contracts are implemented; unit/static checks pass; explicitly approved integration tests pass; macOS hardware soak and network recovery pass; dedicated-server and speech-gold-set reports meet their gates; transcript/metric history is immutable and inspectable; controlled pronunciation is calibrated or formally blocks full MVP; and the standalone `.app` records a selected activity without unbounded RAM or local permanent audio.
