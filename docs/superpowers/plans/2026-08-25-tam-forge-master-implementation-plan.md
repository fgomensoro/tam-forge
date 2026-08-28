# TAM Forge Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete private single-user TAM Forge application in verified increments, beginning with a usable closed spoken-practice loop and ending with the full approved curriculum workspace, durable professional agent memory, real-interview support, and verified portability.

## Authoritative native architecture override

The locked [Native macOS Redesign](../specs/2026-08-28-tam-forge-native-macos-redesign.md) and [Native macOS Batch 01 Plan](./2026-08-28-tam-forge-native-macos-batch-01.md) are authoritative for all current and future work. They replace any conflicting React/Vite, Python-recorder, BlackHole, WSS, faster-whisper, or browser-only verification language in historical child plans.

**Architecture:** Build a native SwiftUI macOS application that talks directly to the remote FastAPI backend through generated OpenAPI types and `URLSession`. Capture microphone and macOS-shareable system audio as separate synchronized tracks with ScreenCaptureKit/Core Audio, retain a bounded encrypted recovery spool until durable server audio plus accepted local transcript lineage are confirmed, and run one local `whisper.cpp` job at a time only after recording. Keep PostgreSQL, permanent object storage, pronunciation/alignment, and other heavy services on the Hetzner host. React/Vite and the Python recorder remain migration-only surfaces until E10-I10 proves parity and removes them.

**Tech Stack:** Swift 6, SwiftUI, ScreenCaptureKit, Core Audio, URLSession, Swift OpenAPI Generator, Keychain Services, whisper.cpp with Metal and optional Core ML; Python 3.12, uv, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, pgvector, Claude Agent SDK with subscription authentication only, Caddy, systemd, GitHub Actions, and Hetzner Object Storage.

---

## 1. Plan set and execution order

The original product plan is split into three independently testable child plans:

1. [Foundation and Learning Workspace](./2026-08-25-tam-forge-01-foundation-learning.md)
2. [Durable Recording and Speech](./2026-08-25-tam-forge-02-recording-speech.md)
3. [Agents, Interviews, and Operations](./2026-08-25-tam-forge-03-agents-interviews-operations.md)

Their backend and domain tasks remain valid where the issue catalog still references them. The native redesign supersedes their client, recorder, local-transcription, and pronunciation architecture.

Plan 1 establishes the repository, identity, storage, curriculum, activity, and evidence foundations used by Plans 2 and 3. Plan 2 completes durable audio plus local speech evidence. Plan 3 closes the AI feedback/memory loop, completes interview and opportunity behavior, adds the remaining specialized workspaces, and hardens operations/export.

Implementation proceeds in this order unless a documented dependency change is reviewed. Each task ends with focused verification and a commit. GitHub epics organize issues; they do not force a one-PR-per-epic shape. The child plans use an explicit stacked-branch chain so implementation can continue while every merge remains an explicit user decision:

```text
main
└── feat/foundation-learning-workspace       PR base: main
    └── feat/recording-speech                PR base: feat/foundation-learning-workspace
        └── feat/agents-interviews-operations PR base: feat/recording-speech
```

Each child plan contains the exact branch creation and draft-PR commands. A child branch must start from the recorded exact remote head of its prerequisite and its PR must target that prerequisite branch while the prerequisite PR is open. Never merge a child before its prerequisite. After an explicitly approved prerequisite merge, fetch `origin/main`, merge—not rebase—the new `origin/main` into the child branch, push without force, retarget the child PR to `main`, and verify that `git diff --name-status origin/main...HEAD` contains only the child slice before treating the transition as valid. Keep prerequisite branches until every dependent PR has been safely retargeted. Every PR lists its exact issue keys and prerequisite SHA, remains draft until its exact final head has passed required checks/review, and never mixes work whose prerequisite head is unavailable. No force-push, branch deletion, or merge is automatic.

## 2. Migration repository layout

```text
tam-forge/
├── .github/
│   ├── CODEOWNERS
│   ├── ISSUE_TEMPLATE/
│   ├── pull_request_template.md
│   └── workflows/
│       ├── backend.yml
│       ├── macos.yml
│       ├── recorder.yml           # legacy until E10-I10
│       ├── web.yml                # legacy until E10-I10
│       ├── integration.yml
│       └── security.yml
├── apps/
│   ├── backend/
│   │   ├── alembic/
│   │   ├── src/tamforge_backend/
│   │   │   ├── agents/
│   │   │   ├── analysis/
│   │   │   ├── artifacts/
│   │   │   ├── auth/
│   │   │   ├── core/
│   │   │   ├── db/
│   │   │   ├── evidence/
│   │   │   ├── interviews/
│   │   │   ├── learning/
│   │   │   ├── memory/
│   │   │   ├── notifications/
│   │   │   ├── opportunities/
│   │   │   ├── recordings/
│   │   │   ├── roadmaps/
│   │   │   ├── speech/
│   │   │   ├── storage/
│   │   │   ├── today/
│   │   │   ├── workers/
│   │   │   ├── models/
│   │   │   ├── api.py
│   │   │   ├── config.py
│   │   │   └── main.py
│   │   └── tests/
│   ├── macos/
│   │   ├── TAMForge.xcodeproj/
│   │   ├── TAMForge/
│   │   ├── TAMForgeTests/
│   │   └── TAMForgeUITests/
│   ├── recorder/                  # legacy until E10-I10
│   │   ├── src/tamforge_recorder/
│   │   ├── tests/
│   │   └── tam-forge-recorder.spec
│   └── web/                       # legacy until E10-I10
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── features/
│       │   └── styles/
│       └── tests/
├── packages/
│   └── protocol/
│       ├── src/tamforge_protocol/
│       └── tests/
├── config/
│   ├── exercise-mappings/
│   ├── prompts/
│   ├── roadmaps/
│   └── rubrics/
├── docs/
│   ├── architecture.md
│   ├── operations/
│   ├── project/
│   └── superpowers/
├── evaluation/
│   ├── fixtures/
│   ├── manifests/
│   └── reports/
├── infra/
│   ├── caddy/
│   ├── systemd/
│   └── scripts/
├── scripts/
│   └── github/
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-lock.yaml
└── pnpm-workspace.yaml
```

Boundaries:

- `apps/backend` is one deployable codebase with separate API, general-worker, speech-worker, and Claude-worker process entrypoints. This avoids duplicated domain logic while allowing resource isolation.
- `apps/macos` is the only target native client. It consumes generated OpenAPI types, uses `URLSession`, owns capture and local transcription, and never imports backend internals.
- `apps/recorder`, `apps/web`, and their workflows are legacy migration surfaces only; no open ticket may add new product behavior there unless E10-I10's later Ultra plan explicitly requires a parity fixture.
- `packages/protocol` is historical Python-recorder protocol code. The native recording contract is the versioned HTTPS manifest/part API defined by the native redesign.
- `config` contains versioned application-owned data, not secrets.
- Infrastructure code never contains production credentials or the Gastos archive.

## 3. Delivery milestones

| Milestone | Exit condition |
|---|---|
| M0 — Safe Foundation | Private repo, CI, auth, Postgres/object abstractions, backup rehearsal, roadmap import, universal activity workspace, evidence ledger |
| M1 — Closed Spoken Loop | Durable dual-track Attempt A, self-review lock, local transcript/metrics/pronunciation diagnostic, evidence-backed review, exactly two corrections, Attempt B |
| M2 — Persistent Agents and Interviews | Subscription-only Agent SDK, role tools/memory, turn interviewer, opportunities, consent/redaction real-interview workflow |
| M3 — Complete Month 1 Workspace | Specialized SQL, reading, cases, writing, career, portfolio, reports, weekly/month transition behavior |
| M4 — Production and Portability | Dedicated hardened server, restore-tested backups, complete export, optional OKF, failure/security/evaluation gates, release runbook |

## 4. GitHub labels

Create these labels idempotently through the issue manifest synchronizer:

| Label | Purpose |
|---|---|
| `type/epic` | Parent tracking issue |
| `type/feature` | User-visible behavior |
| `type/infrastructure` | Deployment/storage/operations |
| `type/security` | Authentication/privacy/hardening |
| `type/evaluation` | Quality or reliability measurement |
| `area/backend` | FastAPI/domain/worker work |
| `area/web` | Historical React client work retained on closed issues until cutover |
| `area/macos` | SwiftUI macOS client work |
| `area/recorder` | Historical legacy recorder work retained on closed issues only |
| `area/speech` | Audio/transcript/metrics work |
| `area/agents` | Agent SDK/prompts/tools/memory work |
| `area/curriculum` | Roadmap/study/evidence work |
| `area/operations` | Production/backup/export work |
| `gate/destructive` | Requires explicit destructive approval |
| `gate/privacy` | Requires privacy contract verification |
| `gate/spend` | Requires approval before new cost |
| `gate/docker-local` | Requires explicit approval before local Docker/Testcontainers |
| `status/blocked` | Cannot progress without a named gate/input |

## 5. GitHub epic and issue catalog

The sync manifest stores stable local keys so repeated runs update existing issues rather than create duplicates. Each child issue includes acceptance criteria, dependencies, plan path/task, test evidence, and privacy/cost/destructive gates.

### Epic E1 — Repository and infrastructure safety

1. `E1-I01` Bootstrap uv/pnpm monorepo and repository conventions.
2. `E1-I02` Add deterministic lint, unit-test, typecheck, and build workflows.
3. `E1-I03` Implement typed configuration and fail-closed secret validation.
4. `E1-I04` Implement PostgreSQL session, migration, and health foundations.
5. `E1-I05` Implement private S3 artifact abstraction and content-addressed manifests.
6. `E1-I06` Inventory Gastos/n8n/NocoDB/PostgreSQL/Caddy state read-only.
7. `E1-I07` Create encrypted Gastos archive, checksums, recovery inventory, and restore instructions.
8. `E1-I08` Prove isolated Gastos restore and record evidence.
9. `E1-I09` Gate destructive Gastos removal and dedicated TAM Forge host rebuild.
10. `E1-I10` Harden Caddy/systemd/firewall/resource limits/log rotation.
11. `E1-I11` Configure daily encrypted backups, versioning, retention, and restore drills.

### Epic E2 — Learning foundation

1. `E2-I01` Implement immutable curriculum and roadmap-version schema.
2. `E2-I02` Implement manual folder/ZIP roadmap manifest and validation.
3. `E2-I03` Implement immutable snapshot storage and private GitHub mirror status.
4. `E2-I04` Implement semantic roadmap diff, preview, approval, and activation guards.
5. `E2-I05` Implement GitHub OAuth restricted to immutable owner ID `102269369`.
6. `E2-I06` Implement resumable StudyDay/Activity state machine and timers.
7. `E2-I07` Implement universal source/hide/Markdown/SQL/artifact activity workspace.
8. `E2-I08` Enforce self-review, assessment, Sunday, hard-stop, and missed-work rules.
9. `E2-I09` Seed canonical competencies, rubrics, exercise mappings, and Portfolio Judgment.
10. `E2-I10` Implement inspectable versioned evidence ledger and skill estimator.
11. `E2-I11` Implement Today screen and primary Continue selection.
12. `E2-I12` Implement allowed notification/status stream.

### Epic E3 — Durable native macOS recording

1. `E3-I01` Specify the versioned recording manifest and resumable HTTPS upload contract.
2. `E3-I02` Implement recording permissions, all-Mac coverage prototype, preflight, and audio diagnostics.
3. `E3-I03` Capture separate synchronized 48 kHz microphone and all shareable Mac audio tracks.
4. `E3-I04` Implement callback-safe conversion, bounded buffering, and timeline accounting.
5. `E3-I05` Implement the encrypted crash-recoverable bounded local spool.
6. `E3-I06` Implement resumable URLSession upload and local recovery coordination.
7. `E3-I07` Implement authenticated recording session, track, part, and seal endpoints.
8. `E3-I08` Persist verified immutable recording parts and transactional high-water state.
9. `E3-I09` Seal manifests, reconcile orphans, and finalize canonical server originals.
10. `E3-I10` Run all-app coverage, route, interruption, crash, disk, duplicate, reorder, corruption, and permission tests.
11. `E3-I11` Benchmark PCM format plus 10/60/120-minute resource and spool behavior.
12. `E3-I12` Build the stable-signed app/DMG and prove permission persistence.

### Epic E4 — Local transcription and English measurement

1. `E4-I01` Integrate speech-analysis jobs and workers with the existing durable queue and outbox.
2. `E4-I02` Implement versioned 16 kHz mono derivation and audio-quality lineage.
3. `E4-I03` Integrate pinned whisper.cpp, built-in VAD, Metal, and optional Core ML.
4. `E4-I04` Benchmark and select quantized Base.en versus Small.en on Francisco's voice.
5. `E4-I05` Implement transcript, word, uncertainty, correction, and model lineage.
6. `E4-I06` Implement deterministic pace, pause, filler, restart, and latency metrics.
7. `E4-I07` Build M2/8 GB 10/60-minute speech performance and cleanup harness.
8. `E4-I08` Build the private voice gold-set manifest and adjudication tooling.
9. `E4-I09` Benchmark dedicated server-side pronunciation/alignment candidates on original audio.
10. `E4-I10` Implement the calibrated server-side pronunciation pipeline and SwiftUI diagnostic.
11. `E4-I11` Enforce decision-grade transcription, timing, pause, and pronunciation gates.
12. `E4-I12` Implement one-at-a-time local speech scheduling and memory-pressure recovery.

### Epic E5 — Closed evidence and correction loop

1. `E5-I01` Implement immutable prompt, rubric, schema, and model-run versions.
2. `E5-I02` Implement separate English and TAM analysis contracts.
3. `E5-I03` Implement mandatory self-review release gate.
4. `E5-I04` Implement evidence-linked observations and confidence/uncertainty.
5. `E5-I05` Enforce exactly two strengths and exactly two corrections.
6. `E5-I06` Implement compact structure and Attempt B instruction contract.
7. `E5-I07` Implement correction scheduling and no-Attempt-C invariant.
8. `E5-I08` Implement A/B comparison and transfer-only later evidence.
9. `E5-I09` Update competency/readiness only from qualifying evidence.
10. `E5-I10` Implement daily and weekly evidence reports.
11. `E5-I11` Prove 15/60-minute end-to-end FeedbackReady SLOs.

### Epic E6 — Persistent role agents

1. `E6-I01` Add Claude Agent SDK installation/auth/model compatibility probe.
2. `E6-I02` Reject API credentials and enforce subscription-only/no-paid-fallback policy.
3. `E6-I03` Implement bounded Claude job runner and structured-output repair.
4. `E6-I04` Implement role-authorized typed in-process tools.
5. `E6-I05` Implement Planner, Tutor, Coach, Reviewer, and Analyst prompt contracts.
6. `E6-I06` Implement isolated Interviewer contract and native SwiftUI/TTS turn orchestration.
7. `E6-I07` Implement versioned episodic/semantic/hypothesis/procedural memory schema.
8. `E6-I08` Implement server-side embeddings, relational filtering, and pgvector retrieval.
9. `E6-I09` Implement memory proposal, promotion, conflict, expiry, and supersession.
10. `E6-I10` Implement role overlays and minimal context manifests.
11. `E6-I11` Evaluate recall/relevance/provenance and zero forbidden leakage.
12. `E6-I12` Implement quota/expiry monitoring and NeedsAttention behavior.

### Epic E7 — Real interviews and opportunities

1. `E7-I01` Implement opportunity/company/job-description/stage model and workspace.
2. `E7-I02` Implement scheduled interview preparation and final 60–90 minute protection.
3. `E7-I03` Implement permission attestation state machine and recording lock.
4. `E7-I04` Implement practice versus real-interview storage/retrieval isolation.
5. `E7-I05` Implement mandatory immediate debrief before feedback.
6. `E7-I06` Implement transcript redaction preview and explicit Claude-release approval.
7. `E7-I07` Implement question segmentation, synchronized two-track timeline, and user/remote attribution.
8. `E7-I08` Implement two-correction real-interview recovery flow.
9. `E7-I09` Track outcomes/stage timing without tone-based predictions.
10. `E7-I10` Use active opportunity evidence to vary adaptive practice without changing the roadmap.

### Epic E8 — Complete study workspace

1. `E8-I01` Implement specialized SQL execution and validation sandbox.
2. `E8-I02` Implement ordered SQL hint ladder and mistake taxonomy.
3. `E8-I03` Implement technical reading preview/hide/recall/application/teach-back flow.
4. `E8-I04` Implement TAM case stages, artifacts, defense, and follow-ups.
5. `E8-I05` Implement cumulative Northstar fact/decision history.
6. `E8-I06` Implement written Attempt A/self-edit/feedback/Attempt B flow.
7. `E8-I07` Implement career-pipeline actions and artifact completion.
8. `E8-I08` Implement portfolio triage, 0–20 composite, and reprioritization.
9. `E8-I09` Implement Saturday no-AI assessments and evidence scoring.
10. `E8-I10` Implement weekly cadence, daily close, and missed-day replacement rules.
11. `E8-I11` Implement month exit review and next-roadmap activation.
12. `E8-I12` Implement interview-family readiness and variation coverage.
13. `E8-I13` Implement evidence-first analytics and self-versus-AI calibration views.

### Epic E9 — Privacy, portability, and production quality

1. `E9-I01` Implement data classification, sensitivity scopes, and model-submission audit.
2. `E9-I02` Implement data-model-improvement attestation gate.
3. `E9-I03` Implement complete versioned export with hashes and relationship manifest.
4. `E9-I04` Implement verified import/restore of a TAM Forge export.
5. `E9-I05` Implement optional generated OKF 0.2 export adapter.
6. `E9-I06` Implement retention, archive, and recoverable deletion controls.
7. `E9-I07` Add structured logs, health/readiness, metrics, and actionable alerts.
8. `E9-I08` Run authorization, prompt/tool injection, secret, and context-leak tests.
9. `E9-I09` Run full recording/job/storage failure-injection suite.
10. `E9-I10` Run speech, agent, memory, and rubric evaluation suite.
11. `E9-I11` Prove backup RPO/RTO with a clean-environment restore drill.
12. `E9-I12` Complete production checklist, user runbook, and versioned release.

### Epic E10 — Native macOS application and web parity

1. `E10-I01` Add execution routing and native macOS taxonomy to the issue catalog.
2. `E10-I02` Bootstrap the Swift 6 macOS 15 app, tests, and CI.
3. `E10-I03` Generate the typed Swift OpenAPI client and URLSession transport.
4. `E10-I04` Implement native GitHub OAuth exchange, token rotation, and Keychain storage.
5. `E10-I05` Implement the SwiftUI shell, navigation, session states, and status stream.
6. `E10-I06` Migrate Today and notifications to SwiftUI.
7. `E10-I07` Migrate roadmap import, validation, diff, approval, and activation to SwiftUI.
8. `E10-I08` Migrate activity workspace, timers, artifacts, commit, and self-review to SwiftUI.
9. `E10-I09` Migrate the evidence ledger and confidence/portfolio explanations to SwiftUI.
10. `E10-I10` Prove native parity and remove React/Vite/Node from runtime and CI.

## 6. Approval gates

The agent may execute ordinary reversible development, verification, commits, pushes, draft PRs, and issue updates after plan approval. It must stop at these gates:

- **Destructive:** removing Gastos/n8n/NocoDB/PostgreSQL/Caddy data or rebuilding the Gastos server requires final explicit approval after archive checks and restore proof.
- **Local Docker:** any command or test that may start Docker Desktop, Testcontainers, or Compose requires explicit approval immediately before execution.
- **Spend:** any new server, GPU, paid transcription, pay-per-token model, or expected non-Claude monthly cost above the approved boundary requires approval.
- **Privacy:** weakening audio/transcript isolation, sending original audio to a model, or changing real-interview release rules requires approval.
- **External identity:** the production domain and GitHub OAuth callback are configured when known; no alternate public exposure is inferred.
- **Merge:** implementation may create and update pull requests autonomously, but merge remains explicit.

## 7. Cross-plan verification matrix

| Invariant | Primary plan | Required evidence |
|---|---|---|
| Roadmap cannot silently change time/coverage | Plan 1 | state/property tests and semantic-diff fixture |
| No feedback before self-review | Plans 1 and 3 | API/state-machine integration test |
| Only qualifying Attempt A/assessment/mock/real evidence advances | Plan 1 | formula golden cases and inspectable ledger |
| Exactly two strengths/corrections; no Attempt C | Plan 3 | schema/property tests at 100% |
| No acknowledged audio segment is lost | Native E3 | crash/reconnect/hash reconstruction tests |
| Native app RAM/spool remain bounded | Native E3/E4 | 10/60/120-minute M2/8 GB reports |
| Audio never enters Claude | Native E3/E4 and Plan 3 | request-capture and security tests |
| Interviewer cannot see reviewer/coach context | Plan 3 | seeded forbidden-context suite at 0 leakage |
| Real-interview text requires redaction approval | Plan 3 | consent/redaction state tests |
| Claude uses subscription only | Plan 3 | startup rejection of API credentials and compatibility smoke test |
| Sunday creates no work/reminders | Plan 1 | calendar/property tests |
| History and original artifacts are append-only | All | migration constraints, lineage, and export verification |
| End-to-end analysis SLOs | Native E4 and Plan 3 | production-like benchmark report |
| Pronunciation is measured only when calibrated | Native E4 | controlled gold-set agreement report |
| Full export/restore preserves relationships | Plan 3 | clean restore and hash comparison |

## 8. Master execution tasks

### Task 1: Freeze the approved plan set

**Files:**

- Modify: `docs/superpowers/specs/2026-08-25-tam-forge-product-architecture-design.md`
- Create: `docs/superpowers/plans/2026-08-25-tam-forge-master-implementation-plan.md`
- Create: `docs/superpowers/plans/2026-08-25-tam-forge-01-foundation-learning.md`
- Create: `docs/superpowers/plans/2026-08-25-tam-forge-02-recording-speech.md`
- Create: `docs/superpowers/plans/2026-08-25-tam-forge-03-agents-interviews-operations.md`

- [ ] **Step 1: Validate Markdown and cross-document links**

Run:

```bash
git diff --check
rg -n "FIXME|XXX|\[fill-me\]" docs/superpowers/specs docs/superpowers/plans
```

Expected: no whitespace errors; no unresolved design placeholders.

- [ ] **Step 2: Confirm the reviewed specification remains the authority**

Run:

```bash
rg -n "^\*\*Status:\*\* Approved" docs/superpowers/specs/2026-08-28-tam-forge-native-macos-redesign.md
rg -n "Authoritative native architecture override" docs/superpowers/plans/2026-08-25-tam-forge-master-implementation-plan.md
```

Expected: both commands resolve exactly one authoritative design relationship.

- [ ] **Step 3: Commit the approved plan set**

```bash
git add docs/superpowers/specs docs/superpowers/plans
git commit -m "docs: add TAM Forge implementation plan"
```

Expected: one documentation-only commit and a clean worktree.

### Task 2: Maintain the GitHub planning catalog

**Files:** See `scripts/github/sync_issues.py`, `scripts/github/tests/test_sync_issues.py`, `docs/project/github-issues.yml`, and the current ticket-specific Sol/ultra batch plan.

The current native catalog and its locked batch plan are authoritative. Historical Plan 1 describes the original bootstrap only and must not replace the current counts, routing, or native taxonomy.

- [ ] **Step 1: Run the focused synchronizer tests and validate every child route before client access**
- [ ] **Step 2: Verify `gh api user --jq .id` equals immutable personal owner ID `102269369` and the target repository is private and personally owned**
- [ ] **Step 3: Run and review a live read-only dry-run; stop on missing historical issues, ambiguous markers, unexpected state, or stale keys**
- [ ] **Step 4: Synchronize exactly 5 milestones, 18 labels, 10 epics, and 115 children only from a reviewed exact head**
- [ ] **Step 5: Re-run the synchronizer dry-run and verify zero duplicate or planned writes**

Expected: GitHub planning objects are reproducible and idempotent; 17 closed historical children are never recreated, reopened, or rewritten; manual/status labels survive while structural labels match the catalog exactly.

### Task 3: Execute Plan 1 Tasks 3–26 — Foundation and learning workspace

**Files:** See Tasks 3–26 in `docs/superpowers/plans/2026-08-25-tam-forge-01-foundation-learning.md`.

- [ ] **Step 1: Execute the remaining Plan 1 tasks in order with TDD**
- [ ] **Step 2: Run Plan 1 unit/type/build checks**
- [ ] **Step 3: Run container-backed integration tests only after explicit local-Docker approval, or rely on the required exact-head GitHub Actions jobs**
- [ ] **Step 4: Bind review and CI to the final exact head and record every skipped check honestly**
- [ ] **Step 5: Update linked issues and prepare the foundation plan's dependency-coherent draft PR for explicit merge approval**

Expected: M0 application foundation plus the evidence-driven universal Month 1 workspace are usable without audio or Claude.

### Task 4: Execute native E3/E4 — Durable recording and English measurement

**Files:** See the locked [Native macOS Redesign](../specs/2026-08-28-tam-forge-native-macos-redesign.md), the routed E3/E4 issues, and the ticket-specific Sol/ultra batch plan required by each issue's dispatch gate. The older Plan 2 is historical context only.

- [ ] **Step 1: Execute E3 and E4 in dependency order from locked ticket-specific plans with TDD**
- [ ] **Step 2: Prove separate synchronized microphone/system tracks, HTTPS durability, bounded encrypted recovery, and reconstruction invariants**
- [ ] **Step 3: Run 10/60/120-minute recording and speech benchmarks on the M2/8 GB Mac without lowering accuracy automatically**
- [ ] **Step 4: Pass Base-versus-Small, PCM16-versus-PCM24, transcript, timing, pause, and server-side pronunciation gates**
- [ ] **Step 5: Update linked issues and prepare dependency-coherent draft PRs for explicit merge approval**

Expected: an independently verifiable native capture/transcription/measurement pipeline whose acknowledged source audio cannot be lost under tested failures and whose local model memory is released after each job.

### Task 5: Execute Plan 3 — Agents, interviews, complete workspace, and operations

**Files:** See `docs/superpowers/plans/2026-08-25-tam-forge-03-agents-interviews-operations.md`.

For every user-facing step, the native issue acceptance and Swift verification supersede historical browser implementation commands.

- [ ] **Step 1: Execute the closed feedback loop and subscription-only Agent SDK tasks**
- [ ] **Step 2: Execute professional memory and role-isolation tasks**
- [ ] **Step 3: Execute opportunities, real interviews, and specialized workspace tasks**
- [ ] **Step 4: Execute privacy, export, backup, evaluation, and production-hardening tasks**
- [ ] **Step 5: Stop at every named destructive/privacy/spend/local-Docker gate**
- [ ] **Step 6: Update linked issues and prepare dependency-coherent Plan 3 draft PRs with explicit prerequisite heads for merge approval**

Expected: the complete approved product operates privately and passes the cross-plan verification matrix.

### Task 6: Perform final release qualification

**Files:**

- Create: `docs/operations/release-checklist.md`
- Create: `docs/operations/user-runbook.md`
- Create: `evaluation/reports/mvp-release.json`
- Create: `evaluation/reports/mvp-release.md`

- [ ] **Step 1: Verify the exact release candidate head**

Run:

```bash
git status --short
git rev-parse HEAD
gh pr checks --required
```

Expected: clean tree; recorded head SHA; all required checks present and passing.

- [ ] **Step 2: Run non-container release checks locally**

Run:

```bash
uv run pytest -m "not integration and not postgres_integration and not object_store_integration and not container_integration and not local_model and not hardware and not soak" -q
uv run mypy apps/backend/src packages/protocol/src scripts/github
uv run python scripts/ci/check_openapi.py
xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build
xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' test
```

Expected: all commands pass. Plan 3 PostgreSQL tests run only through its zero-skip runner; integration, object-store, container, model, hardware, and soak evidence comes from the exact CI/manual procedures. A skip is not green.

- [ ] **Step 3: Confirm CI integration/evaluation/soak evidence**

Run:

```bash
gh run list --branch "$(git branch --show-current)" --limit 10
```

Expected: integration, security, speech/agent evaluation, and required soak workflows pass on the exact head.

- [ ] **Step 4: Verify production restore and observable smoke test**

Run the versioned release checklist. Expected: health/readiness, native authentication and Today flow, synchronized two-track recording, local transcription cleanup, one complete Attempt A/self-review/feedback/Attempt B cycle, export verification, and clean restore evidence all pass.

- [ ] **Step 5: Request explicit merge/release approval**

No merge or destructive production cutover occurs before the user approves the exact reviewed head and release evidence.
