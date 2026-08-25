# TAM Forge Agents, Interviews, Memory, and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver TAM Forge's subscription-only Claude roles, evidence-backed persistent memory, correction and interview workflows, later study workspaces, analytics, portability, and production-safety foundation without weakening the approved learning, privacy, cost, or destructive-action constraints.

**Architecture:** FastAPI remains the sole command/state boundary and PostgreSQL remains canonical for prompts, rubrics, model runs, evidence, memory, interviews, opportunities, reports, and exports. A constrained Python Claude Agent SDK worker consumes prepared text/metrics through versioned structured contracts and typed in-process MCP tools; local embeddings plus relational filters provide role-safe retrieval, while object storage contains immutable large artifacts and verified exports. Operations use idempotent PostgreSQL jobs/outbox events, least-privilege services, encrypted off-host backups, and explicit gates before any real Claude submission, Docker-backed local test, paid service, or Gastos destruction.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, pgvector, PostgreSQL full-text search, Claude Agent SDK for Python, FastEmbed for local ONNX embedding inference, React 19 + TypeScript + Vite, TanStack Query, Vitest/Testing Library, pytest/pytest-asyncio/Hypothesis, Ruff, mypy, GitHub Actions, Caddy, systemd, private Hetzner Object Storage.

---

## Scope and prerequisites

This is child plan **03**. Execute it only after the foundation and recording/speech plans have supplied these stable interfaces:

- authenticated single-user FastAPI application and GitHub-owner identity check;
- PostgreSQL session/transaction helpers, durable job queue, transactional outbox, audit events, object catalog, signed-object access, the approved versioned application signer/verifier, and the Plan 2 `processing_runs`/`processing_suspensions` clock ledger;
- roadmap/task/activity, immutable attempt, self-review, evidence, transcript/version, word-token, deterministic speech-metric, and artifact models;
- `SelfReviewComplete`, `IngestSealed`, and transcript/metrics readiness events;
- web application shell, Today screen, universal activity workspace, and server-sent job-status channel;
- canonical monorepo layout: `apps/backend/src/tamforge_backend/`, `apps/web/`, `apps/recorder/src/tamforge_recorder/`, `packages/protocol/src/tamforge_protocol/`, and `apps/backend/alembic/versions/`.

This plan must not reimplement recording, ASR, VAD, pronunciation measurement, roadmap import, authentication, or base job infrastructure. It consumes those components through their approved interfaces.

## Non-negotiable gates

| Gate | Trigger | Required action |
|---|---|---|
| **PRIVACY** | First real transcript/metric submission to Claude | Confirm and record that Claude data-model-improvement is disabled; show the current Anthropic policy and retention acknowledgement. No real-interview text may pass without a separate approved redaction version. |
| **AUTH/POLICY** | Enabling the Claude worker in production | Run the current official subscription-compatibility check. The system must remain single-user/self-operated, use a manually provisioned `CLAUDE_CODE_OAUTH_TOKEN`, and contain no paid/API credential or in-app Claude login flow. |
| **PAID** | Any API key, usage credit, hosted model, paid GPU, extra server, or other new spend | Stop and obtain explicit approval. Never auto-fallback. |
| **DOCKER** | Any local command that can start Docker, Compose, Testcontainers, or a database container | Warn in one line and wait for explicit approval. Until approved, run only unit/contract tests that cannot touch Docker. CI may use its isolated PostgreSQL service. |
| **DESTRUCTIVE** | Stopping/removing Gastos, deleting volumes, repurposing/renaming its server, physically purging learner/object data, deleting backups, or changing production DNS | Present exact targets plus verified archive/restore/recovery evidence and obtain explicit approval immediately before the action. Archive, recoverable tombstone, and read-only inventory do not authorize physical removal. |
| **MERGE/DEPLOY** | Merging or production activation | Follow repository policy and require the user's explicit final merge/deploy decision when applicable; bind review and CI evidence to the exact final head. |

The subscription integration is an external compatibility dependency, not a permanent product guarantee. As of the approved specification date, official Anthropic guidance permits personal Claude-plan use through a setup token and applies ordinary subscription limits; Anthropic has paused the separately claimed monthly Agent SDK credit proposal. Because authentication, eligible plans, models, usage limits, and data-use terms may change, the production gate must re-verify them and leave Claude disabled on any mismatch—never substitute an API key or paid credit.

## Canonical invariants implemented by this plan

- No AI-generated Attempt A and no feedback before committed self-review.
- Original audio and object-store audio URLs never enter Claude input.
- Real-interview text is withheld until consent is `UserAttestedPermitted`, the private debrief is committed, and a redacted transcript version is explicitly approved.
- Reviewer output has exactly two demonstrated strengths and exactly two corrections; invalid output is not published.
- Feedback publication, `processing_runs.feedback_ready_at`, processing projection, and notification outbox commit atomically; active composite targets are 15 minutes for practice and 60 minutes for mock/real, with every suspension and miss visible.
- There is no Attempt C. Attempt B updates comparison/correction state but does not independently raise competency level.
- Interviewer receives no hidden coaching, reviewer judgment, active correction answer, or broader sensitive memory for the current attempt.
- Coach may read approved durable memory but current Coach Mode messages/audio/transcript/score/analysis are not persisted.
- PostgreSQL evidence and memory revisions are canonical; vectors and SDK sessions are derived conveniences.
- Complete TAM Forge exports support validated dry-run and conflict-safe transactional restore; optional OKF remains an export projection only.
- Archive is reversible, deletion is recoverable before a disclosed deadline, and physical purge is never an automatic/default action.
- Claude jobs use subscription allowance only, one concurrent job initially, with no silent model/provider fallback or credit purchase.
- Every material model claim resolves to immutable evidence/timestamp IDs, and every run records prompt, rubric, schema, SDK, resolved model, and context-manifest versions.

## File and component map

### Shared protocol

- `packages/protocol/src/tamforge_protocol/agents.py`: role, prompt, rubric, model-run, tool-call, and structured-output wire contracts.
- `packages/protocol/src/tamforge_protocol/memory.py`: memory revision, proposal, retrieval reason, and context-manifest contracts.
- `packages/protocol/src/tamforge_protocol/corrections.py`: correction lifecycle, Attempt B, and A/B comparison contracts.
- `packages/protocol/src/tamforge_protocol/interviews.py`: consent, redaction, debrief, session/follow-up, and outcome contracts layered on the existing turn protocol.
- `packages/protocol/src/tamforge_protocol/opportunities.py`: opportunity/stage/context contracts.
- `packages/protocol/src/tamforge_protocol/reports.py`: daily, weekly, readiness, and inspectable calculation contracts.
- `packages/protocol/src/tamforge_protocol/exports.py`: export manifest, checksums, schema versions, and optional OKF contracts.

### Backend AI and role runtime

- `apps/backend/src/tamforge_backend/agents/settings.py`: fail-closed subscription-only settings and concurrency limits.
- `apps/backend/src/tamforge_backend/agents/compatibility.py`: SDK/CLI/token/model/tool/schema compatibility probe.
- `apps/backend/src/tamforge_backend/agents/runtime.py`: Claude Agent SDK adapter and fakeable runner boundary.
- `apps/backend/src/tamforge_backend/agents/model_runs.py`: transactional model-run lifecycle and publication policy.
- `apps/backend/src/tamforge_backend/analysis/{models,repository,service,routes}.py`: immutable analysis, observations, feedback reads, and links to foundation rubric evaluations.
- `apps/backend/src/tamforge_backend/agents/prompt_registry.py`: immutable prompt/rubric loading and hashes.
- `config/prompts/*.md`: versioned base and six role prompts loaded explicitly by the application.
- `apps/backend/src/tamforge_backend/agents/tools/*.py`: typed in-process MCP tool registry and constrained handlers.
- `apps/backend/src/tamforge_backend/agents/roles/*.py`: Planner, Tutor, Coach, Interviewer, Reviewer, and Analyst services.
- `apps/backend/src/tamforge_backend/agents/routes.py`: role chat, compatibility, and run-status endpoints.
- `apps/backend/src/tamforge_backend/workers/general.py`: non-speech/non-Claude durable-job entrypoint, including the credential-bearing export build/sign handler.
- `apps/backend/src/tamforge_backend/workers/claude.py`: one-concurrent-job Claude worker entrypoint.
- `apps/backend/src/tamforge_backend/integrity/`: production Ed25519 export-manifest signer, public trust-bundle verifier, and fail-closed credential loaders. Recording-manifest HMAC remains the separate Plan 2 domain.

### Memory and corrections

- `apps/backend/src/tamforge_backend/memory/models.py`: SQLAlchemy memory/conversation/context/embedding models.
- `apps/backend/src/tamforge_backend/memory/repository.py`: version-safe persistence and scoped queries.
- `apps/backend/src/tamforge_backend/memory/policy.py`: automatic, hypothesis, approval, contradiction, expiry, and no-write rules.
- `apps/backend/src/tamforge_backend/memory/embeddings.py`: local pinned embedding adapter and reindex jobs.
- `apps/backend/src/tamforge_backend/memory/retrieval.py`: relational-first hybrid retrieval and deterministic ranking.
- `apps/backend/src/tamforge_backend/memory/context.py`: role-specific context packet assembly and manifest recording.
- `apps/backend/src/tamforge_backend/memory/routes.py`: inspect, approve, correct, supersede, archive, and search endpoints.
- `apps/backend/src/tamforge_backend/corrections/repository.py`: extension repository over the foundation correction records and Attempt B comparisons.
- `apps/backend/src/tamforge_backend/corrections/service.py`: two-correction selection, scheduling, and Attempt B comparison.
- `apps/backend/src/tamforge_backend/corrections/routes.py`: correction/Attempt B reads and idempotent commands.

### Interviews, opportunities, reports, and exports

- `apps/backend/src/tamforge_backend/interviews/{models,policy,redaction,service,routes}.py`: separate real-interview lifecycle.
- `apps/backend/src/tamforge_backend/opportunities/{models,service,routes}.py`: personal opportunity pipeline and scoped context.
- `apps/backend/src/tamforge_backend/workspaces/{reading,sql,sql_runner,cases,portfolio,writing,career}.py`: later specialized workspace policies over the universal activity model.
- `apps/backend/src/tamforge_backend/reports/{calculator,service,routes}.py`: deterministic daily/weekly/readiness reports.
- `apps/backend/src/tamforge_backend/exports/{builder,validator,importer,okf,service,routes}.py`: complete portable export, dry-run/transactional restore, and optional OKF projection.
- `apps/backend/src/tamforge_backend/retention/{models,repository,policy,service,routes}.py`: versioned retention, reversible archive, recoverable deletion, and gated purge records.
- `apps/backend/src/tamforge_backend/observability/{logging,metrics,health}.py`: content-safe events, metrics, and health/readiness checks.

### Web

- `apps/web/src/features/agents/`: active-role UI, compatibility status, persistent text threads, and memory provenance.
- `apps/web/src/features/corrections/`: exactly-two correction view, Attempt B launch, and comparison.
- `apps/web/src/features/interviews/`: consent, redaction, debrief, processing, and outcome screens.
- `apps/web/src/features/opportunities/`: opportunity list/detail/stage/next-action UI.
- `apps/web/src/features/workspaces/`: later SQL, case, writing, and career workspace components.
- `apps/web/src/features/reports/`: daily, weekly, readiness, and calculation-inspection UI.
- `apps/web/src/features/exports/`: export request/download plus upload, dry-run, conflict review, and restore UI.
- `apps/web/src/features/privacy/`: retention disclosure, archive, deletion preview, quarantine, and recovery UI.

### Operations and documentation

- `infra/systemd/`: API, general worker, speech worker, Claude worker, embedding worker, backup service/timer, and restore-check service/timer units.
- `infra/caddy/Caddyfile`: private app proxy, WSS/SSE, headers, and protected operational endpoints.
- `infra/scripts/gastos/`: inventory, encrypted archive, verification, isolated restore, and gated decommission scripts.
- `infra/scripts/backup/`: database/configuration backup, manifest verification, restore, and drill recording scripts.
- `infra/scripts/bootstrap/`: idempotent post-Gastos Ubuntu 24.04 host verification/provisioning, PostgreSQL 16 + pgvector, service layout, firewall, verification, and bounded rollback.
- `scripts/run-plan-03-integration.sh` and `tamforge_backend/testing/plan03_integration_gate.py`: explicit-database, required-marker, zero-skip integration runner used by every Plan 3 PostgreSQL command.
- `infra/tests/`: Bats/pytest tests using fixtures and temporary directories only.
- `.github/workflows/ci.yml`: unit, web, contract, PostgreSQL integration, security, and AI eval jobs.
- `docs/runbooks/`: Claude subscription, privacy/redaction, backup/restore, Gastos retirement, security incident, quota outage, and production release procedures.

## Test command policy

Safe local commands used below:

```bash
uv run pytest apps/backend/tests/unit packages/protocol/tests -q
uv run ruff check apps/backend packages/protocol
uv run mypy apps/backend/src packages/protocol/src
pnpm --dir apps/web exec vitest run
pnpm --dir apps/web exec tsc --noEmit
```

Commands marked `[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]` must not run locally until the user approves. Every Plan 3 PostgreSQL integration test carries the `postgres_integration` marker and must run through the checked-in gate below; invoking pytest directly is not acceptable evidence:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration
```

The runner exits before collection when `TEST_DATABASE_URL` is absent, loads the Plan 3 pytest gate, requires at least one collected `postgres_integration` test, and converts every skip into failure. Its final summary must say `collected > 0, skipped = 0`; a skipped or uncollected command is never green. CI may invoke the same runner against a GitHub Actions PostgreSQL 16 + pgvector service without starting Docker on the user's Mac. Local commands still require the Docker approval even if a database happens to be running.

## Initial stacked branch and pull-request contract

Plan 2's exact remote head is the immutable prerequisite for this slice. Before Task 1, require a clean worktree, fetch without deleting any prerequisite branch, record the prerequisite SHA, and create Plan 3's branch from that exact remote commit:

```bash
git status --short
git fetch origin --prune
git rev-parse --verify origin/feat/recording-speech
git switch --detach origin/feat/recording-speech
git switch -c feat/agents-interviews-operations
git rev-parse HEAD | tee /tmp/tamforge-plan-03-prerequisite-sha.txt
git status --short --branch
```

Expected: the initial `feat/agents-interviews-operations` HEAD equals `origin/feat/recording-speech`, the worktree is clean, and the recorded SHA is copied into every Plan 3 PR body. If either local branch already exists, the worktree is dirty, or the remote prerequisite cannot be resolved, stop and reconcile rather than reset, overwrite, or invent a base. All Plan 3 commits remain on `feat/agents-interviews-operations`; dependency-coherent PRs may be cut from this branch only when their exact prerequisite head is declared.

The initial Plan 3 draft PR targets `feat/recording-speech`. Do not merge it before the Plan 2 PR. After an explicitly approved Plan 2 merge, perform this exact no-rewrite transition:

```bash
git switch feat/agents-interviews-operations
git status --short
git fetch origin --prune
git merge --no-edit origin/main
git push origin feat/agents-interviews-operations
gh pr edit --repo fgomensoro/tam-forge --base main
gh pr view --repo fgomensoro/tam-forge --json baseRefName,headRefName,headRefOid,isDraft
git diff --name-status origin/main...HEAD
```

Expected: the current branch remains `feat/agents-interviews-operations`, push is non-force, the PR is still draft with base `main`, and the three-dot diff contains only Plan 3 work. Stop on a dirty tree, conflict, unexpected base/head, or prerequisite content in the diff. Never delete the Plan 2 branch until this check passes.

---

### Task 1: Freeze shared role, model-run, review, and tool contracts

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/agents.py`
- Create: `packages/protocol/tests/test_agents.py`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`

- [ ] **Step 1: Write failing protocol tests**

Cover the six explicit roles; assessed/unavailable dimension states; evidence references; exactly-two strength/correction bounds; prompt/rubric/schema/model identifiers; tool-call audit data; measured/user-stated/inferred/unknown attribution; and rejection of audio/object URLs.

```python
def test_review_requires_exactly_two_strengths_and_corrections() -> None:
    payload = valid_review_payload()
    payload["corrections"] = payload["corrections"][:1]
    with pytest.raises(ValidationError):
        ReviewOutput.model_validate(payload)


def test_model_input_rejects_audio_artifacts() -> None:
    with pytest.raises(ValidationError, match="audio is prohibited"):
        ModelInputArtifact(kind="audio", evidence_id=uuid4())
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_agents.py -q`

Expected: FAIL during import because `tamforge_protocol.agents` does not exist.

- [ ] **Step 3: Implement the protocol models minimally**

Use string enums for `AgentRole`, `AttributionKind`, `DimensionAvailability`, and `ModelRunStatus`; Pydantic models with `ConfigDict(extra="forbid")`; `Field(min_length=2, max_length=2)` for strengths/corrections; UUID evidence IDs; non-negative timestamp ranges; and a validator that permits only prepared text, metric, rubric, roadmap, and memory-summary artifacts.

- [ ] **Step 4: Add round-trip and schema-snapshot tests**

Serialize each contract to JSON, validate it again, and snapshot `ReviewOutput.model_json_schema()` so accidental schema drift requires an explicit version bump.

- [ ] **Step 5: Run protocol verification and verify GREEN**

Run: `uv run pytest packages/protocol/tests/test_agents.py -q`

Expected: PASS; schema snapshot includes `minItems: 2` and `maxItems: 2` for both arrays.

- [ ] **Step 6: Run static checks**

Run: `uv run ruff check packages/protocol && uv run mypy packages/protocol/src`

Expected: both exit 0.

- [ ] **Step 7: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/agents.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_agents.py
git commit -m "feat(protocol): define agent and review contracts"
```

### Task 2: Persist immutable prompts, rubrics, schemas, model runs, and tool calls

**Files:**
- Create: `apps/backend/alembic/versions/20260825_0009_agent_runtime.py`
- Create: `apps/backend/src/tamforge_backend/testing/__init__.py`
- Create: `apps/backend/src/tamforge_backend/testing/plan03_integration_gate.py`
- Create: `apps/backend/src/tamforge_backend/agents/models.py`
- Create: `apps/backend/src/tamforge_backend/analysis/models.py`
- Create: `apps/backend/src/tamforge_backend/agents/prompt_registry.py`
- Create: `apps/backend/src/tamforge_backend/agents/model_runs.py`
- Create: `apps/backend/tests/unit/agents/test_prompt_registry.py`
- Create: `apps/backend/tests/unit/agents/test_model_runs.py`
- Create: `apps/backend/tests/unit/testing/test_plan03_integration_gate.py`
- Create: `apps/backend/tests/integration/agents/test_agent_runtime_migration.py`
- Create: `scripts/run-plan-03-integration.sh`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`

- [ ] **Step 1: Write failing registry, lifecycle, and integration-gate tests**

Test SHA-256 content identity, immutable duplicate handling, refusal to mutate a published version, context-manifest item ordering, legal transitions (`queued -> running -> succeeded|retry_wait|needs_attention|failed`), and tool-call audit persistence with redacted inputs.

For the integration gate, fake the pytest process and environment. Assert the runner refuses missing/blank `TEST_DATABASE_URL`, always selects the `postgres_integration` marker, fails when collection is empty or any test skips, preserves pytest's nonzero exit, prints no credential, and reports `collected > 0, skipped = 0` only on a real zero-skip pass. Unit tests must not open a database or start Docker.

```python
async def test_published_prompt_cannot_be_replaced(prompt_registry) -> None:
    first = await prompt_registry.publish("reviewer", "1.0.0", "prompt A")
    with pytest.raises(ImmutableVersionConflict):
        await prompt_registry.publish("reviewer", "1.0.0", "prompt B")
    assert first.content_hash == sha256(b"prompt A").hexdigest()
```

- [ ] **Step 2: Run unit tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/test_prompt_registry.py apps/backend/tests/unit/agents/test_model_runs.py apps/backend/tests/unit/testing/test_plan03_integration_gate.py -q`

Expected: FAIL because persistence services, models, and the required integration runner/plugin are absent.

- [ ] **Step 3: Implement the fail-closed Plan 3 integration runner**

`scripts/run-plan-03-integration.sh` must require an explicit non-production `TEST_DATABASE_URL`, invoke pytest with `--strict-markers -m postgres_integration` and the `tamforge_backend.testing.plan03_integration_gate` plugin, forward only explicit test paths, and refuse an empty path list. The plugin counts collection and reports; it forces a failing exit when zero marked tests run or any report is skipped. Register every Plan 3 database integration test with `@pytest.mark.postgres_integration`. CI supplies its isolated service URL; the script contains no default URL and never invokes Docker, Compose, or Testcontainers.

- [ ] **Step 4: Define the migration**

Create append-only tables for `prompt_versions`, `output_schema_versions`, `model_runs`, `model_run_context_items`, `agent_tool_calls`, `analysis_versions`, `analysis_observations`, and `attempt_comparisons`; extend the foundation's existing `corrections` table only with the source-analysis/comparison fields needed by this plan. Reuse the foundation's immutable `rubric_versions`, `rubric_evaluations`, `rubric_dimension_scores`, and evidence ledger rather than creating parallel tables. Make the two-correction invariant concurrency-safe in PostgreSQL: active/due corrections must use priority slot 1 or 2, and a partial unique index on `(owner_id, priority)` for active/due states prevents two rows from occupying a slot and therefore prevents a third active correction. Add foreign keys to transcript/evidence/activity/rubric/correction records, status checks, one-Attempt-B uniqueness, JSONB only for versioned structured metadata, and indexes for job/status/time queries. Never store the OAuth token or raw audio metadata in these tables.

- [ ] **Step 5: Implement repository-backed registries and model-run transitions**

Require expected-current status on transitions, retain every error category/attempt, record exact resolved model and SDK/CLI versions, and store context IDs/reasons rather than duplicating complete learner history.

- [ ] **Step 6: Run unit tests and verify GREEN**

Run: `uv run pytest apps/backend/tests/unit/agents/test_prompt_registry.py apps/backend/tests/unit/agents/test_model_runs.py apps/backend/tests/unit/testing/test_plan03_integration_gate.py -q`

Expected: PASS.

- [ ] **Step 7: Verify migration locally only after the Docker gate**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/agents/test_agent_runtime_migration.py
```

Expected: PASS; upgrade creates constraints and downgrade removes only revision `20260825_0009` objects. The test opens concurrent transactions attempting three active/due corrections and proves that at most priority slots 1 and 2 commit. During implementation, inspect the actual Plan 2 head and set `down_revision` to that exact revision rather than assuming a filename is the graph parent.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/alembic/versions/20260825_0009_agent_runtime.py apps/backend/src/tamforge_backend/testing apps/backend/src/tamforge_backend/agents apps/backend/src/tamforge_backend/analysis/models.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/tests/unit/agents apps/backend/tests/unit/testing/test_plan03_integration_gate.py apps/backend/tests/integration/agents/test_agent_runtime_migration.py scripts/run-plan-03-integration.sh
git commit -m "feat(agents): persist versioned model run contracts"
```

### Task 3: Build the subscription-only Claude compatibility gate

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/settings.py`
- Create: `apps/backend/src/tamforge_backend/agents/compatibility.py`
- Create: `apps/backend/src/tamforge_backend/agents/errors.py`
- Create: `apps/backend/src/tamforge_backend/agents/routes.py`
- Create: `apps/backend/tests/unit/agents/test_settings.py`
- Create: `apps/backend/tests/unit/agents/test_compatibility.py`
- Create: `docs/runbooks/claude-subscription.md`
- Modify: `apps/backend/src/tamforge_backend/config.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing fail-closed worker settings tests**

Test that the API still starts with Claude explicitly disabled and no host credential, so independent study remains available. Test that starting/enabling the Claude worker rejects `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock/Vertex/Foundry switches, missing `CLAUDE_CODE_OAUTH_TOKEN`, an unapproved privacy attestation, more than one concurrent job, and an implicit paid fallback. Test that token values never appear in `repr`, validation errors, route responses, or logs.

```python
def test_api_key_is_a_hard_worker_configuration_error(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    with pytest.raises(PaidCredentialForbidden):
        ClaudeSubscriptionSettings.for_worker()
```

- [ ] **Step 2: Run settings tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/test_settings.py -q`

Expected: FAIL because subscription settings do not exist.

- [ ] **Step 3: Implement subscription-only worker settings and degraded API state**

Keep base application configuration valid with `CLAUDE_ENABLED=false`; the owner API then reports Claude as disabled while every non-Claude study path works. Only the Claude worker loads its manually provisioned one-year token through a host-secret path/injected process value. Expose only a `SecretStr`, force `setting_sources=[]`, set concurrency to one, set bounded turn/wall-time limits, and set nonessential traffic/error/feedback telemetry opt-outs. Do not offer an endpoint that accepts or returns a Claude token.

- [ ] **Step 4: Write failing compatibility-probe tests with a fake CLI/SDK adapter**

Probe token authentication method, SDK and bundled CLI versions, selected model availability, resolved model identifier, structured-output validation, one harmless typed tool round-trip, and quota/auth/policy error classification. Assert the probe never reads application evidence.

- [ ] **Step 5: Run probe tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/test_compatibility.py -q`

Expected: FAIL because `ClaudeCompatibilityProbe` is absent.

- [ ] **Step 6: Implement the compatibility probe and owner-only status route**

Return `disabled`, `blocked`, `ready`, or `needs_attention` with nonsecret remediation. Resolve the install-time model against what the subscription and installed SDK actually support; do not assume a marketing alias is permanent. Persist the exact resolved model identifier and policy-check timestamp. A quota failure is not retried in a tight loop. Compatibility failure prevents the Claude worker from claiming jobs; it does not make the API unready.

- [ ] **Step 7: Document the manual activation procedure**

The runbook must state: run `claude setup-token` locally through Anthropic's browser flow; never paste the token into chat/GitHub/TAM Forge UI; install it as a root-owned service credential; record the one-year rotation date; confirm data-model-improvement is off; verify current official subscription/Agent SDK policy; and stop if the product ceases to be personal/single-user. Pin these official check locations in the runbook: `https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan`, `https://code.claude.com/docs/en/authentication`, `https://code.claude.com/docs/en/agent-sdk/overview`, and `https://code.claude.com/docs/en/data-usage`.

- [ ] **Step 8: Run safe verification**

Run: `uv run pytest apps/backend/tests/unit/agents/test_settings.py apps/backend/tests/unit/agents/test_compatibility.py -q`

Expected: PASS using fakes and no network/model request.

- [ ] **Step 9: Cross-check current official policy before production activation**

`[AUTH/POLICY + PRIVACY GATE]` Re-read Anthropic's current setup-token, Agent SDK subscription, legal/authentication, and data-usage pages. Record the URLs, check time, account plan class, model-improvement attestation, and decision in the deployment evidence. If subscription use is no longer permitted for this self-operated case, leave Claude disabled; do not add an API key.

- [ ] **Step 10: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents apps/backend/tests/unit/agents docs/runbooks/claude-subscription.md apps/backend/src/tamforge_backend/config.py apps/backend/src/tamforge_backend/api.py
git commit -m "feat(agents): add subscription compatibility gate"
```

### Task 4: Implement the fakeable Claude Agent SDK runtime and bounded worker

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/runtime.py`
- Create: `apps/backend/src/tamforge_backend/workers/claude.py`
- Create: `apps/backend/tests/unit/agents/test_runtime.py`
- Create: `apps/backend/tests/unit/workers/test_claude_worker.py`
- Create: `apps/backend/src/tamforge_backend/jobs/registry.py`
- Modify: `apps/backend/pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Write failing runtime tests**

Use a fake SDK stream to test custom system-prompt file use, `setting_sources=[]`, explicit allowed-tool list, structured JSON schema, exact model capture, timeout/max-turn handling, token/quota/auth classification, no session-resume dependency, and local prompt-history suppression for one-shot analysis jobs.

- [ ] **Step 2: Run runtime tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/test_runtime.py -q`

Expected: FAIL because the runtime boundary is absent.

- [ ] **Step 3: Add and lock the Claude Agent SDK dependency**

Run: `uv add --project apps/backend claude-agent-sdk && uv lock --check`

Expected: `apps/backend/pyproject.toml` declares `claude-agent-sdk`, `uv.lock` pins one concrete resolved SDK/dependency graph, and the command exits 0. Do not add the usage-billed Anthropic client as an application integration or configure any API credential.

Run: `uv run --project apps/backend python -c "import claude_agent_sdk"`

Expected: exit 0. The compatibility probe—not a hardcoded plan value—records the exact installed SDK and bundled CLI versions because supported subscription releases can change.

- [ ] **Step 4: Implement `ClaudeRuntime` behind a protocol**

Expose one method accepting `PreparedAgentRun` and returning `ValidatedAgentResult`. Construct `ClaudeAgentOptions` only inside the adapter. Pass a custom prompt, a versioned JSON schema, the resolved model, bounded turns, the in-process MCP server, no built-in tools, and no user/project setting sources. Sanitize SDK exceptions into typed internal errors without transcript/token content.

- [ ] **Step 5: Write failing worker lease/idempotency tests**

Test one active Claude lease, duplicate job idempotency, stale lease recovery, `NeedsAttention` on quota/auth, bounded retry on transient service errors, transactional publication, and deterministic metrics remaining visible on every Claude failure.

- [ ] **Step 6: Implement the worker handler minimally**

Register `claude.review`, `claude.analyze`, `claude.plan`, and `claude.followup` job types. The worker must fetch prepared context by IDs, create a `ModelRun`, invoke the runtime once, validate output, publish an outbox event transactionally, and release the single concurrency lease.

- [ ] **Step 7: Run focused verification**

Run: `uv run pytest apps/backend/tests/unit/agents/test_runtime.py apps/backend/tests/unit/workers/test_claude_worker.py -q`

Expected: PASS with no live Claude call.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/pyproject.toml uv.lock apps/backend/src/tamforge_backend/agents/runtime.py apps/backend/src/tamforge_backend/workers/claude.py apps/backend/src/tamforge_backend/jobs/registry.py apps/backend/tests/unit/agents/test_runtime.py apps/backend/tests/unit/workers/test_claude_worker.py
git commit -m "feat(agents): run bounded subscription agent jobs"
```

### Task 5: Expose only constrained, audited in-process tools

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/tools/registry.py`
- Create: `apps/backend/src/tamforge_backend/agents/tools/evidence.py`
- Create: `apps/backend/src/tamforge_backend/agents/tools/memory.py`
- Create: `apps/backend/src/tamforge_backend/agents/tools/actions.py`
- Create: `apps/backend/src/tamforge_backend/agents/tools/exercises.py`
- Create: `apps/backend/src/tamforge_backend/agents/tools/opportunities.py`
- Create: `apps/backend/src/tamforge_backend/agents/tools/__init__.py`
- Create: `apps/backend/tests/unit/agents/tools/test_registry.py`
- Create: `apps/backend/tests/unit/agents/tools/test_injection_and_scope.py`

- [ ] **Step 1: Write failing tool-registry permission tests**

Define the exact role/tool matrix. Verify that raw SQL, arbitrary paths/URLs, shell/network/filesystem tools, original audio, another opportunity's restricted context, hidden current-attempt feedback, and unbounded limits are rejected before handler execution.

```python
@pytest.mark.parametrize(
    ("role", "tool"),
    [(AgentRole.INTERVIEWER, "search_broad_history"),
     (AgentRole.COACH, "propose_memory_candidate")],
)
async def test_forbidden_role_tool_pair_is_blocked(role, tool, registry) -> None:
    with pytest.raises(ToolNotAuthorized):
        await registry.call(role, tool, {})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/tools -q`

Expected: FAIL because the registry is absent.

- [ ] **Step 3: Implement read-only tools**

Implement typed handlers for `get_current_assignment`, `get_roadmap_task`, `get_active_corrections(limit<=2)`, `search_evidence(limit<=10)`, `get_evidence(ids<=10)`, `get_related_attempts(limit<=3)`, `get_opportunity_context`, and `fetch_curated_exercises`. Return bounded structured content with evidence IDs and sensitivity labels.

- [ ] **Step 4: Implement proposal-only mutation tools**

Implement `propose_memory_candidate`, `create_practice_checklist`, and `propose_adaptive_change`. Enforce idempotency keys, application validation, draft/proposal state, source model-run ID, evidence IDs, role permission, and audit event. Tools never directly activate a plan, promote sensitive memory, or edit a roadmap.

- [ ] **Step 5: Build the in-process MCP server**

Wrap only these handlers with `create_sdk_mcp_server`; construct an explicit allowed-tool list per role. Do not register Claude Code built-ins.

- [ ] **Step 6: Add prompt/tool-injection cases**

Use malicious transcript/source strings requesting secret exfiltration, role changes, hidden-feedback reads, external HTTP, and raw database access. Assert they remain plain untrusted content and produce no unauthorized handler call.

- [ ] **Step 7: Run tool verification**

Run: `uv run pytest apps/backend/tests/unit/agents/tools -q`

Expected: PASS, including zero unauthorized tool invocations.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/tools apps/backend/tests/unit/agents/tools
git commit -m "feat(agents): constrain and audit role tools"
```

### Task 6: Version the base and six role prompt contracts

**Files:**
- Create: `config/prompts/base-v1.md`
- Create: `config/prompts/planner-v1.md`
- Create: `config/prompts/tutor-v1.md`
- Create: `config/prompts/coach-v1.md`
- Create: `config/prompts/interviewer-v1.md`
- Create: `config/prompts/reviewer-v1.md`
- Create: `config/prompts/analyst-v1.md`
- Create: `apps/backend/src/tamforge_backend/agents/roles/contracts.py`
- Create: `apps/backend/tests/unit/agents/test_role_prompts.py`

- [ ] **Step 1: Write failing prompt-contract tests**

Parse prompt metadata and assert every role declares purpose, allowed inputs, prohibited behavior, tools, output schema, uncertainty/attribution rules, English-only behavior, independent-attempt protection, and evidence citation requirements. Assert role-specific invariants: Planner cannot change spine/time; Tutor follows the hint ladder; Coach does not persist; Interviewer cannot coach or read hidden feedback; Reviewer waits for self-review and returns exactly two corrections; Analyst cannot invent longitudinal patterns.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/test_role_prompts.py -q`

Expected: FAIL because prompt files are absent.

- [ ] **Step 3: Write the shared base prompt**

Label prepared transcript/source text as untrusted evidence, distinguish `measured`, `user_stated`, `ai_inference`, and `unknown`, require permanent evidence IDs/timestamps, prohibit audio access and fabricated experience, and require explicit limitations. Specify that structured JSON—not Markdown prose—is canonical; the UI renders professional Markdown.

- [ ] **Step 4: Write focused role overlays**

Keep each overlay short and non-overlapping. Embed only role rules; load task, roadmap, rubric, memory, and opportunity context through the prepared run/context builder.

- [ ] **Step 5: Register immutable versions and hashes**

Use `PromptRegistry` to publish the seven files and role contract metadata. A content change requires `v2`; it cannot replace `v1`.

- [ ] **Step 6: Run prompt verification**

Run: `uv run pytest apps/backend/tests/unit/agents/test_role_prompts.py -q`

Expected: PASS for all six roles and the shared prompt.

- [ ] **Step 7: Commit**

```bash
git add config/prompts apps/backend/src/tamforge_backend/agents/roles/contracts.py apps/backend/tests/unit/agents/test_role_prompts.py
git commit -m "feat(agents): version role prompt contracts"
```

### Task 7: Publish Reviewer results only after self-review and evidence validation

**Files:**
- Modify: `packages/protocol/src/tamforge_protocol/agents.py`
- Modify: `packages/protocol/tests/test_agents.py`
- Create: `apps/backend/src/tamforge_backend/agents/roles/reviewer.py`
- Create: `apps/backend/src/tamforge_backend/agents/review_validation.py`
- Create: `apps/backend/src/tamforge_backend/agents/rendering.py`
- Create: `apps/backend/src/tamforge_backend/analysis/repository.py`
- Create: `apps/backend/src/tamforge_backend/analysis/service.py`
- Create: `apps/backend/src/tamforge_backend/analysis/routes.py`
- Create: `apps/backend/tests/unit/agents/roles/test_reviewer.py`
- Create: `apps/backend/tests/unit/agents/test_review_validation.py`
- Create: `apps/backend/tests/unit/agents/test_rendering.py`
- Create: `apps/backend/tests/unit/analysis/test_feedback_routes.py`
- Create: `apps/backend/tests/integration/agents/test_feedback_ready_clock.py`
- Create: `apps/web/src/features/feedback/api.ts`
- Create: `apps/web/src/features/feedback/FeedbackPanel.tsx`
- Create: `apps/web/src/features/feedback/FeedbackPanel.test.tsx`
- Modify: `apps/backend/src/tamforge_backend/workers/claude.py`
- Modify: `apps/backend/src/tamforge_backend/speech/processing_clock.py`
- Modify: `apps/backend/tests/speech/test_processing_clock.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing eligibility and feedback-read contract tests**

Test that review preparation requires an immutable Attempt A/output, committed self-review, selected transcript version, applicable prompt/rubric/schema versions, and evidence packet. Test rejection when a self-review is draft, original audio is included, transcript uncertainty is silently treated as learner error, or a real interview lacks approved redaction. Define a versioned `FeedbackRead` response with `processing|needs_attention|ready`, immutable analysis/version IDs, verdict, exactly two strengths, exactly two corrections, evidence/timestamp links, separate TAM and six English-dimension results, uncertainty, rendered Markdown, Attempt B instructions, prompt/rubric/schema/model versions, and timing/SLO fields. Audio/object URLs are forbidden.

- [ ] **Step 2: Run eligibility tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_agents.py apps/backend/tests/unit/agents/roles/test_reviewer.py apps/backend/tests/unit/analysis/test_feedback_routes.py -q`

Expected: FAIL because `ReviewerService`, feedback-read contracts, and routes do not exist.

- [ ] **Step 3: Implement the prepared reviewer input**

Include separate TAM and English sections, deterministic speech metrics with metric-version/uncertainty, transcript text plus word/timestamp IDs, the learner's self-review/self-score, rubric criteria, task facts, and only the approved context manifest. Keep all six English dimensions distinct: fluency from timing/pace/pause/restart evidence; accuracy and vocabulary from the selected transcript with uncertainty; pronunciation only from the controlled calibrated diagnostic; listening only from synchronized question-response relevance, clarification, and instruction-retention evidence; and communication effectiveness from audience/task outcome evidence. Represent listening/pronunciation as `not_assessed` when evidence is unavailable and never map ASR probability to pronunciation quality.

- [ ] **Step 4: Write failing publication, processing-clock, and SLO tests**

Reject fewer/more than two strengths or corrections, invalid timestamps, evidence IDs outside the context manifest, a complete answer to memorize when the rubric forbids it, unsupported material claims, combined TAM/English scores, or an output schema/model/prompt version mismatch. Extend Plan 2's `processing_runs` tests with frozen server clocks: practice passes at active elapsed `00:15:00` and misses at `00:15:00.001`; mock/real passes at `01:00:00` and misses at `01:00:00.001`. Assert practice/mock eligibility starts at `max(IngestSealed, SelfReviewComplete)`, real-interview eligibility at `IngestSealed`, required speech-stage misses block a composite pass, duplicate publication is idempotent, and `feedback_ready_at` is monotonic/write-once.

Test all four allowed suspension reasons. `awaiting_debrief` and `awaiting_redaction` are reported and excluded from active elapsed. `claude_quota` and `claude_service_unavailable` create explicit `processing_suspensions`, move the run to `NeedsAttention`, report wall/active/suspended durations separately, and can never yield an on-time success even if later recovery publishes feedback. No other reason may pause the clock.

- [ ] **Step 5: Implement bounded repair, atomic publication, and FeedbackReady accounting**

Validate with Pydantic first, then cross-check evidence/timestamp resolution. Permit at most one structured repair call with the validation errors and no new evidence. On another failure, retain the `ModelRun`, mark the analysis and shared processing run `NeedsAttention`, and publish no feedback. On success, use Plan 2's database-backed processing-clock service to create the immutable `AnalysisVersion`, set `processing_runs.feedback_ready_at` once, compute the active 15/60-minute result, project `FeedbackReady` into the foundation processing status, and enqueue both feedback-ready and allowed-notification outbox events in one transaction. `FeedbackReady` means selected transcript, deterministic speech outputs, self-review, and published analysis are all durable; it is not inferred from worker success.

On Claude quota or service unavailability, open/close only the corresponding append-only suspension through `processing_clock.py`, record queue/runtime separately, and preserve retry idempotency. Never hide speech time, wall time, or suspended time; never count a speech-stage miss or quota/service-suspended run as an on-time composite success.

- [ ] **Step 6: Implement exact owner-only feedback read APIs**

Add `GET /api/v1/attempts/{attempt_id}/feedback` for the current selected published analysis/status and `GET /api/v1/analyses/{analysis_version_id}` for an immutable historical version. Both resolve only owner-scoped records, return the canonical structured response (not reparsed Markdown), expose `processing`/`NeedsAttention` without leaking failed model text, and include timing/SLO/suspension reason codes without transcript content in operational fields. A draft analysis or pre-self-review request returns no feedback body.

- [ ] **Step 7: Render structured output to Markdown**

Build a deterministic renderer producing a professional report with verdict, two strengths, two corrections, evidence links/timestamps, compact structure, Attempt B instructions, scores, uncertainty, and versions. Never treat generated Markdown as canonical data.

- [ ] **Step 8: Write the feedback UI test and verify RED**

Run: `pnpm --dir apps/web exec vitest run src/features/feedback/FeedbackPanel.test.tsx`

Expected: FAIL because the feedback client/panel do not exist. The test requires reload-safe API fetching; visible processing/NeedsAttention states; verdict; exactly two strengths/corrections; timestamp/evidence navigation; distinct TAM/English dimensions with `not_assessed`; uncertainty and version provenance; and the server-supplied Attempt B instruction. Failed/raw model output and original-audio URLs never render.

- [ ] **Step 9: Implement the feedback client and panel**

Fetch the exact attempt feedback route with TanStack Query, invalidate it from the existing SSE `feedback_ready` event, and render canonical fields accessibly. A browser refresh must reconstruct the same result from PostgreSQL. Keep the panel read-only; launching Attempt B belongs to Task 8.

- [ ] **Step 10: Run reviewer and web verification**

Run: `uv run pytest packages/protocol/tests/test_agents.py apps/backend/tests/unit/agents/roles/test_reviewer.py apps/backend/tests/unit/agents/test_review_validation.py apps/backend/tests/unit/agents/test_rendering.py apps/backend/tests/unit/analysis/test_feedback_routes.py apps/backend/tests/speech/test_processing_clock.py -q -m "not postgres_integration" && pnpm --dir apps/web exec vitest run src/features/feedback/FeedbackPanel.test.tsx`

Expected: PASS; invariant cases pass at 100%, clock boundaries are exact, and the UI reloads canonical feedback.

- [ ] **Step 11: Prove atomic FeedbackReady persistence after the database gate**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/agents/test_feedback_ready_clock.py
```

Expected: PASS with marked tests collected and zero skips. Concurrent/retried publication creates one analysis, one `feedback_ready_at`, one notification, legal suspension rows, correct active/wall durations, and exact 15/60-minute boundary results.

- [ ] **Step 12: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/agents.py packages/protocol/tests/test_agents.py apps/backend/src/tamforge_backend/agents/roles/reviewer.py apps/backend/src/tamforge_backend/agents/review_validation.py apps/backend/src/tamforge_backend/agents/rendering.py apps/backend/src/tamforge_backend/analysis apps/backend/src/tamforge_backend/workers/claude.py apps/backend/src/tamforge_backend/speech/processing_clock.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/agents apps/backend/tests/unit/analysis apps/backend/tests/speech/test_processing_clock.py apps/backend/tests/integration/agents/test_feedback_ready_clock.py apps/web/src/features/feedback
git commit -m "feat(review): publish evidence-backed structured feedback"
```

### Task 8: Implement exactly-two corrections and the Attempt B lifecycle

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/corrections.py`
- Create: `packages/protocol/tests/test_corrections.py`
- Create: `apps/backend/src/tamforge_backend/corrections/repository.py`
- Create: `apps/backend/src/tamforge_backend/corrections/service.py`
- Create: `apps/backend/src/tamforge_backend/corrections/routes.py`
- Create: `apps/backend/tests/unit/corrections/test_service.py`
- Create: `apps/backend/tests/unit/corrections/test_routes.py`
- Create: `apps/backend/tests/integration/corrections/test_attempt_b_flow.py`
- Create: `apps/web/src/features/corrections/api.ts`
- Create: `apps/web/src/features/corrections/CorrectionsPanel.tsx`
- Create: `apps/web/src/features/corrections/AttemptBPanel.tsx`
- Create: `apps/web/src/features/corrections/AttemptComparison.tsx`
- Create: `apps/web/src/features/corrections/CorrectionsPanel.test.tsx`
- Create: `apps/web/src/features/corrections/AttemptBPanel.test.tsx`
- Modify: `apps/backend/src/tamforge_backend/today/models.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing correction-state and read-API tests**

Cover `Proposed -> Active -> Due -> AttemptBCommitted -> Improved|PartiallyImproved|NotImproved -> Resolved|RetrievalQueued`, maximum two active corrections, exactly one correction warm-up choice, Attempt B at the next lesson, maximum ten minutes, same core prompt, no Attempt C, and unresolved transfer through a different future scenario. Freeze response contracts for `GET /api/v1/corrections?state=active,due`, `GET /api/v1/analyses/{analysis_version_id}/corrections`, and `GET /api/v1/attempts/{attempt_b_id}/comparison`; each returns owner-scoped canonical IDs, source evidence, due state, priority rationale, instruction, warm-up type, Attempt B eligibility/ID, comparison/version, and retrieval link without hidden reviewer/model text.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_corrections.py apps/backend/tests/unit/corrections/test_service.py apps/backend/tests/unit/corrections/test_routes.py -q`

Expected: FAIL because correction contracts/services are absent.

- [ ] **Step 3: Implement correction contracts and persistence**

Extend the foundation correction model/repository rather than mapping a second `corrections` table. Store source analysis/evidence, priority rationale, target skill, concrete instruction, due activity/date, state, chosen warm-up type, Attempt B ID, comparison version, and later retrieval link. Allocate priority slots while locking the single owner row with `SELECT ... FOR UPDATE`; on a uniqueness race, reload and return the existing two rather than retrying unboundedly. The revision `20260825_0009` partial unique index/check constraint is the final guard against a third active/due correction, and the Attempt B uniqueness constraint blocks a second Attempt B for the same correction set.

- [ ] **Step 4: Implement deterministic scheduling**

At daily close, activate at most two published corrections. At next lesson, instantiate one correction warm-up—not spoken, written, and SQL together. Never add minutes beyond the approved roadmap allocation; reschedule required work only through the existing unfinished-work policy.

- [ ] **Step 5: Implement A/B comparison preparation and publication**

Require comparable task/prompt conditions; provide both immutable outputs and evidence to a versioned comparator; return only `Improved`, `PartiallyImproved`, or `NotImproved` plus evidence. Attempt B must not create qualifying competency evidence; transfer later requires a new independent Attempt A.

- [ ] **Step 6: Implement exact read routes and idempotent Attempt B commands**

Implement the three GET routes above plus `POST /api/v1/analyses/{analysis_version_id}/attempt-b` to create/return the single due Attempt B activity and `POST /api/v1/attempts/{attempt_b_id}/commit` to seal it once. Repeated launch returns the existing Attempt B; a second commit or any Attempt C is rejected. All mutations use the foundation session/CSRF/version checks. The current two corrections and comparison remain readable after reload and historical analyses remain immutable.

- [ ] **Step 7: Write corrections/Attempt B UI tests and verify RED**

Run: `pnpm --dir apps/web exec vitest run src/features/corrections/CorrectionsPanel.test.tsx src/features/corrections/AttemptBPanel.test.tsx`

Expected: FAIL because the client and components do not exist. Tests require exactly two ordered cards, due/active state and evidence, one enabled warm-up, a ten-minute same-core-prompt Attempt B launch, uninterrupted commit, no Attempt C control, persisted A/B comparison, later-retrieval state, SSE/query refresh, and full browser-reload recovery.

- [ ] **Step 8: Implement the corrections and Attempt B UI**

Use the read/command routes rather than client-derived state. `CorrectionsPanel` shows the two highest-impact corrections and provenance; `AttemptBPanel` launches the one allowed next-lesson activity and reuses the universal saved-attempt recorder/workspace; `AttemptComparison` renders only the three allowed outcomes plus cited evidence. Disable coaching during saved Attempt B and never expose a model answer to memorize.

- [ ] **Step 9: Run safe unit and web tests**

Run: `uv run pytest packages/protocol/tests/test_corrections.py apps/backend/tests/unit/corrections/test_service.py apps/backend/tests/unit/corrections/test_routes.py -q && pnpm --dir apps/web exec vitest run src/features/corrections/CorrectionsPanel.test.tsx src/features/corrections/AttemptBPanel.test.tsx && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS.

- [ ] **Step 10: Run state integration test after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/corrections/test_attempt_b_flow.py
```

Expected: PASS; concurrent commands cannot create a third correction or Attempt C.

- [ ] **Step 11: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/corrections.py packages/protocol/tests/test_corrections.py apps/backend/src/tamforge_backend/corrections apps/backend/src/tamforge_backend/today/models.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/corrections apps/backend/tests/integration/corrections apps/web/src/features/corrections
git commit -m "feat(corrections): enforce Attempt B learning loop"
```

### Task 9: Add canonical versioned memory and conversation storage

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/memory.py`
- Create: `packages/protocol/tests/test_memory.py`
- Create: `apps/backend/alembic/versions/20260825_0010_memory.py`
- Create: `apps/backend/src/tamforge_backend/memory/models.py`
- Create: `apps/backend/src/tamforge_backend/memory/repository.py`
- Create: `apps/backend/tests/unit/memory/test_repository_contract.py`
- Create: `apps/backend/tests/integration/memory/test_memory_migration.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`

- [ ] **Step 1: Write failing memory contract tests**

Cover episodic, semantic, hypothesis, procedural, and working types; global/role/roadmap/activity/case/opportunity/interview scopes; role visibility; sensitivity; confidence; provenance; valid-from/to; expiry; contradiction; supersession; and approval status. Require permanent revision IDs and prohibit in-place claim mutation.

- [ ] **Step 2: Run protocol tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_memory.py -q`

Expected: FAIL because memory protocol is absent.

- [ ] **Step 3: Define the memory migration**

Enable `vector`; create `conversations`, `conversation_messages`, `memory_records`, `memory_revisions`, `memory_evidence_links`, and `memory_embeddings`, then add the memory foreign keys needed by the existing `model_run_context_items` table from revision `20260825_0009`. Add unique revision ordering, lifecycle checks, scope/sensitivity indexes, a GIN index over an explicit English `tsvector`, and a vector column with embedding model/version. Do not create HNSW yet; exact search is sufficient for one user's initial corpus and avoids unnecessary RAM/recall trade-offs.

- [ ] **Step 4: Write failing repository tests**

Test append-only revisions, optimistic expected-revision checks, explicit contradiction links, expiry visibility, role/scope filtering before retrieval, conversation archive without evidence deletion, and Coach Mode refusing message persistence.

- [ ] **Step 5: Implement repository operations**

Expose `append_revision`, `supersede`, `contradict`, `approve`, `expire`, `archive_conversation`, and scoped candidate queries. Every mutation emits an audit event and preserves the prior revision.

- [ ] **Step 6: Run safe tests**

Run: `uv run pytest packages/protocol/tests/test_memory.py apps/backend/tests/unit/memory/test_repository_contract.py -q`

Expected: PASS using repository fakes.

- [ ] **Step 7: Verify PostgreSQL behavior after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/memory/test_memory_migration.py
```

Expected: PASS for vector extension, GIN search, constraints, revision races, and downgrade. Set `down_revision` by inspecting revision `20260825_0009` in the checked-out migration graph.

- [ ] **Step 8: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/memory.py packages/protocol/tests/test_memory.py apps/backend/alembic/versions/20260825_0010_memory.py apps/backend/src/tamforge_backend/memory apps/backend/tests/unit/memory apps/backend/tests/integration/memory/test_memory_migration.py apps/backend/src/tamforge_backend/models/__init__.py
git commit -m "feat(memory): persist versioned learner memory"
```

### Task 10: Generate local embeddings and implement relational-first hybrid retrieval

**Files:**
- Create: `apps/backend/src/tamforge_backend/memory/embeddings.py`
- Create: `apps/backend/src/tamforge_backend/memory/retrieval.py`
- Create: `apps/backend/src/tamforge_backend/workers/embeddings.py`
- Create: `apps/backend/tests/unit/memory/test_embeddings.py`
- Create: `apps/backend/tests/unit/memory/test_retrieval.py`
- Create: `apps/backend/tests/integration/memory/test_pgvector_retrieval.py`
- Create: `apps/backend/tests/fixtures/memory_retrieval_cases.json`
- Create: `config/embeddings/local-model-v1.yaml`
- Modify: `apps/backend/src/tamforge_backend/jobs/registry.py`
- Modify: `apps/backend/pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Write failing embedding-adapter tests**

Use a deterministic fake to verify normalization, dimension/model/version storage, content-hash deduplication, re-embedding on model-version change, local-only execution, batching, and no embedding for disallowed sensitive/ephemeral content.

- [ ] **Step 2: Run embedding tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/memory/test_embeddings.py -q`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Add and lock the local inference dependency**

Run: `uv add --project apps/backend fastembed && uv lock --check`

Expected: `apps/backend/pyproject.toml` declares FastEmbed, `uv.lock` pins one concrete local ONNX inference graph, and no hosted embedding client/provider is configured.

Run: `uv run --project apps/backend python -c "import fastembed"`

Expected: exit 0 without making an inference request.

- [ ] **Step 4: Implement a replaceable local embedding boundary**

Select a small English retrieval model only after a CPU/RAM spike confirms it fits the CX23 budget, then pin its model name/revision, artifact checksum, dimensions, pooling/normalization, cache location, and generated-at contract in `config/embeddings/local-model-v1.yaml`. Startup must verify the checksum and fail only the embedding worker if the model is absent/mismatched. The worker has no external inference endpoint and processes only approved revisions/evidence summaries.

- [ ] **Step 5: Write failing retrieval tests**

Seed required and forbidden memories. Assert hard relational filters for role, scope, company/opportunity, interview, sensitivity, lifecycle, competency, evidence type, and version run before full-text/vector ranking. Test deterministic inclusion of active assignment/rubric/two corrections, source diversity, reason codes, token budget, and zero Interviewer leakage.

- [ ] **Step 6: Implement hybrid ranking minimally**

Retrieve exact required context first, then candidate text matches and exact cosine neighbors. Rerank using semantic relevance, exact task/competency relation, evidence strength, freshness, and role affinity; cap repeated sources. Return IDs, revisions, excerpts, reason, score components, and sensitivity—never a provenance-free text blob.

- [ ] **Step 7: Run safe retrieval tests**

Run: `uv run pytest apps/backend/tests/unit/memory/test_embeddings.py apps/backend/tests/unit/memory/test_retrieval.py -q`

Expected: PASS with deterministic fakes.

- [ ] **Step 8: Run PostgreSQL retrieval tests after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/memory/test_pgvector_retrieval.py
```

Expected: PASS; filtered exact vector/FTS results match the fixture and forbidden rows never appear.

- [ ] **Step 9: Benchmark before adding ANN**

Run a production-like local/server benchmark with 10,000 synthetic/fixture memory summaries and record p50/p95 latency plus PostgreSQL RSS. If exact search meets the request budget, do not add HNSW. Any future ANN index requires retrieval-recall comparison and a new migration.

- [ ] **Step 10: Commit**

```bash
git add apps/backend/src/tamforge_backend/memory apps/backend/src/tamforge_backend/workers/embeddings.py apps/backend/src/tamforge_backend/jobs/registry.py apps/backend/tests/unit/memory apps/backend/tests/integration/memory/test_pgvector_retrieval.py apps/backend/tests/fixtures/memory_retrieval_cases.json config/embeddings/local-model-v1.yaml apps/backend/pyproject.toml uv.lock
git commit -m "feat(memory): add local hybrid retrieval"
```

### Task 11: Enforce evidence-backed memory promotion, revision, expiry, and approval

**Files:**
- Create: `apps/backend/src/tamforge_backend/memory/policy.py`
- Create: `apps/backend/src/tamforge_backend/memory/service.py`
- Create: `apps/backend/src/tamforge_backend/memory/routes.py`
- Create: `apps/backend/tests/unit/memory/test_policy.py`
- Create: `apps/backend/tests/unit/memory/test_service.py`
- Create: `apps/backend/tests/security/test_memory_authorization.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write a table-driven failing policy suite**

Cases must include: verified system/evidence facts auto-write; explicit user preferences auto-write with source quote; agent pattern becomes hypothesis only; one event cannot create an identity trait; sensitive/personal inference needs approval; contradictions append revisions; temporary detail expires; unsupported/unprovenanced claim is rejected; Coach Mode current content is rejected; transcript instructions are not memory commands.

- [ ] **Step 2: Run policy tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/memory/test_policy.py -q`

Expected: FAIL because `MemoryWritePolicy` is absent.

- [ ] **Step 3: Implement deterministic policy decisions**

Return `AUTO_ACCEPT`, `STORE_HYPOTHESIS`, `REQUIRE_USER_APPROVAL`, or `REJECT`, plus reason code, retention/expiry, allowed visibility, and required evidence count. Never let model prose choose its own policy result.

- [ ] **Step 4: Implement proposal and review commands**

Accept proposals only from a recorded model run and allowed role/tool. Validate cited evidence, sensitivity, scope, confidence, and idempotency. Add owner-only endpoints to inspect provenance, approve, correct, supersede, expire, archive, or reject. Corrections create a new revision rather than edit history.

- [ ] **Step 5: Add authorization and cross-scope tests**

Verify the GitHub owner can review, device tokens cannot access memory, an Interviewer cannot search global reviewer/coach memories, and opportunity/interview scoped records cannot leak into another company context.

- [ ] **Step 6: Run verification**

Run: `uv run pytest apps/backend/tests/unit/memory/test_policy.py apps/backend/tests/unit/memory/test_service.py apps/backend/tests/security/test_memory_authorization.py -q`

Expected: PASS with zero forbidden reads/writes.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/tamforge_backend/memory/policy.py apps/backend/src/tamforge_backend/memory/service.py apps/backend/src/tamforge_backend/memory/routes.py apps/backend/tests/unit/memory apps/backend/tests/security/test_memory_authorization.py apps/backend/src/tamforge_backend/api.py
git commit -m "feat(memory): govern evidence-backed memory changes"
```

### Task 12: Assemble minimal role-safe context packets and manifests

**Files:**
- Create: `apps/backend/src/tamforge_backend/memory/context.py`
- Create: `apps/backend/src/tamforge_backend/agents/roles/context_policies.py`
- Create: `apps/backend/tests/unit/memory/test_context_builder.py`
- Create: `apps/backend/tests/security/test_role_context_isolation.py`
- Create: `apps/backend/tests/fixtures/role_context_cases.json`

- [ ] **Step 1: Write failing hierarchy tests**

Assert the approved order: current roadmap assignment; current prompt/source/case/interview; prompt/rubric contracts; active two corrections; related attempts/evidence; active company/role; verified role memory; broader history only when needed. Test stable ordering and explicit exclusion reasons under a fixed token budget.

- [ ] **Step 2: Write failing role-isolation tests**

Seed hidden current-attempt corrections, reviewer judgments, Coach notes, a second opportunity, a sensitive real interview, expired hypotheses, and superseded facts. Assert Planner/Tutor/Coach/Reviewer/Analyst visibility rules and complete Interviewer exclusion.

- [ ] **Step 3: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/memory/test_context_builder.py apps/backend/tests/security/test_role_context_isolation.py -q`

Expected: FAIL because context policies are absent.

- [ ] **Step 4: Implement context packet assembly**

Build typed sections with source/revision/evidence IDs, sensitivity, attribution, reason, and truncation status. Never concatenate untrusted evidence into the system prompt; place it in clearly delimited task evidence. Hash the resulting packet and persist a manifest referencing exact revisions.

- [ ] **Step 5: Add interviewer allowlist enforcement outside prompts**

The Interviewer packet may contain canonical scenario facts, audience/difficulty, visible question-answer turns, permitted response-level timing, and follow-up count only. Application code—not prompt obedience—must reject every hidden feedback/memory class.

- [ ] **Step 6: Run verification**

Run: `uv run pytest apps/backend/tests/unit/memory/test_context_builder.py apps/backend/tests/security/test_role_context_isolation.py -q`

Expected: PASS; forbidden-context leakage count is zero.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/tamforge_backend/memory/context.py apps/backend/src/tamforge_backend/agents/roles/context_policies.py apps/backend/tests/unit/memory/test_context_builder.py apps/backend/tests/security/test_role_context_isolation.py apps/backend/tests/fixtures/role_context_cases.json
git commit -m "feat(memory): build role-isolated context packets"
```

### Task 13: Implement Planner, Tutor, and unsaved Coach role services

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/roles/planner.py`
- Create: `apps/backend/src/tamforge_backend/agents/roles/tutor.py`
- Create: `apps/backend/src/tamforge_backend/agents/roles/coach.py`
- Create: `apps/backend/src/tamforge_backend/agents/conversations.py`
- Create: `apps/backend/tests/unit/agents/roles/test_planner.py`
- Create: `apps/backend/tests/unit/agents/roles/test_tutor.py`
- Create: `apps/backend/tests/unit/agents/roles/test_coach.py`
- Create: `apps/backend/tests/unit/agents/test_conversations.py`
- Create: `apps/web/src/features/agents/RoleBadge.tsx`
- Create: `apps/web/src/features/agents/AgentThread.tsx`
- Create: `apps/web/src/features/agents/CoachMode.tsx`
- Create: `apps/web/src/features/agents/AgentThread.test.tsx`
- Modify: `apps/backend/src/tamforge_backend/agents/routes.py`

- [ ] **Step 1: Write failing Planner tests**

Reject any adaptive change that modifies required time/coverage/resource/Saturday/Sunday/exit criteria. Require what changed, why, evidence, roadmap objective, coverage impact, and time impact. Ensure a proposal remains pending until application validation accepts it.

- [ ] **Step 2: Write failing Tutor tests**

Lock Tutor before independent recall/attempt, enforce the ordered SQL/learning hint ladder, allow solution reveal only after committed attempt or expiry, and record which hint level was used without converting assisted work into qualifying evidence.

- [ ] **Step 3: Write failing Coach tests**

Allow reads from durable speaking/correction memory, enforce 10–15 minute maximum, prohibit assessment use, and assert zero conversation/message/model-output/memory persistence for current Coach Mode. Only generic operational audit metadata such as start/stop/failure may persist without content.

- [ ] **Step 4: Run role tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_planner.py apps/backend/tests/unit/agents/roles/test_tutor.py apps/backend/tests/unit/agents/roles/test_coach.py -q`

Expected: FAIL because role services are absent.

- [ ] **Step 5: Implement role services and routes**

Use common runtime/context boundaries but role-specific eligibility, tools, persistence, and output schema. Implement `AgentConversationService` to append/load/archive role-scoped messages with optimistic ordering and exact model-run/context-manifest links. Planner/Tutor text threads persist through that application-owned service; Coach Mode calls bypass it, set no SDK session store/history, and discard content after streaming to the browser.

- [ ] **Step 6: Write and run UI role tests**

Test an always-visible role badge, lock reasons, durable Planner/Tutor history, Coach unsaved warning/timer, and no saved-history affordance in Coach Mode.

Run: `pnpm --dir apps/web exec vitest run src/features/agents/AgentThread.test.tsx`

Expected before implementation: FAIL; after implementing the three components: PASS.

- [ ] **Step 7: Run backend and type verification**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_planner.py apps/backend/tests/unit/agents/roles/test_tutor.py apps/backend/tests/unit/agents/roles/test_coach.py apps/backend/tests/unit/agents/test_conversations.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/roles apps/backend/src/tamforge_backend/agents/conversations.py apps/backend/src/tamforge_backend/agents/routes.py apps/backend/tests/unit/agents/roles apps/backend/tests/unit/agents/test_conversations.py apps/web/src/features/agents
git commit -m "feat(agents): add planner tutor and unsaved coach"
```

### Task 14: Implement the evidence-bounded longitudinal Analyst

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/roles/analyst.py`
- Create: `apps/backend/src/tamforge_backend/agents/roles/longitudinal.py`
- Create: `apps/backend/tests/unit/agents/roles/test_analyst.py`
- Create: `apps/backend/tests/unit/agents/roles/test_analyst_conversation.py`
- Create: `apps/backend/tests/fixtures/analyst_longitudinal_cases.json`
- Create: `apps/web/src/features/agents/AnalystThread.tsx`
- Create: `apps/web/src/features/agents/AnalystThread.test.tsx`
- Create: `apps/web/src/features/agents/MemoryProvenance.tsx`
- Create: `apps/web/src/features/agents/MemoryProvenance.test.tsx`
- Modify: `apps/backend/src/tamforge_backend/agents/conversations.py`
- Modify: `apps/backend/src/tamforge_backend/agents/routes.py`

- [ ] **Step 1: Write failing longitudinal-input tests**

Test that only versioned evidence is eligible; Attempt B, guided work, expired/superseded memory, and vanity metrics cannot create a demonstrated trend. Require source diversity, explicit date windows, separate self/AI scores, and at least three relevant independent contexts before describing a recurring learner pattern as more than a hypothesis.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_analyst.py -q`

Expected: FAIL because the Analyst services are absent.

- [ ] **Step 3: Implement deterministic evidence preparation**

Build bounded competency/date-window summaries from the evidence ledger. Include included and excluded event IDs, assistance/mode, confidence, score formula version, correction history, real-interview provenance category, and missing-data flags. Calculate counts, weighted values, and date comparisons in Python; Claude may explain them but may not recalculate or overwrite them.

- [ ] **Step 4: Implement structured Analyst output and validation**

Return evidence summaries, supported patterns, counterevidence, uncertainty, retrieval candidates, and memory proposals. Every pattern must cite at least two evidence IDs; identity-level claims remain hypotheses and pass through `MemoryWritePolicy`; causal claims and invented experiences are rejected. Do not allow Analyst output to change readiness directly.

- [ ] **Step 5: Write failing persistent Analyst-thread tests**

Create an Analyst conversation, append user/assistant turns across two simulated browser sessions, reload them in stable ordinal order, and assert each assistant turn resolves to its model run/context manifest. Assert role isolation, optimistic concurrency, archive behavior, and that retrieved historical snippets are manifest references—not an opaque resumed SDK session.

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_analyst_conversation.py -q`

Expected: FAIL until the Analyst is registered with `AgentConversationService` and its route supports list/create/append/archive.

- [ ] **Step 6: Implement Analyst conversation persistence and UI**

Register the Analyst as a durable role, reuse `AgentThread` for application-owned history, and add `AnalystThread` with a visible active-role badge, source/provenance expansion, archive/new-thread controls, loading/error states, and no implied full-history preload.

Run before UI implementation: `pnpm --dir apps/web exec vitest run src/features/agents/AnalystThread.test.tsx`

Expected: FAIL because the component is absent.

Run after implementation: `uv run pytest apps/backend/tests/unit/agents/roles/test_analyst_conversation.py -q && pnpm --dir apps/web exec vitest run src/features/agents/AnalystThread.test.tsx`

Expected: PASS across the simulated session boundary.

- [ ] **Step 7: Add provenance UI tests and implementation**

Test that the user can expand a pattern into contributing/excluded evidence, see `measured`, `user_stated`, `ai_inference`, or `unknown`, inspect memory proposal status, and correct a claim through a new revision.

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/agents/MemoryProvenance.test.tsx`

Expected: FAIL because the component is absent.

Run after implementation: `pnpm --dir apps/web exec vitest run src/features/agents/MemoryProvenance.test.tsx`

Expected: PASS.

- [ ] **Step 8: Run role verification**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_analyst.py apps/backend/tests/unit/agents/roles/test_analyst_conversation.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS; no fixture creates a durable unsupported claim.

- [ ] **Step 9: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/roles/analyst.py apps/backend/src/tamforge_backend/agents/roles/longitudinal.py apps/backend/src/tamforge_backend/agents/conversations.py apps/backend/src/tamforge_backend/agents/routes.py apps/backend/tests/unit/agents/roles/test_analyst.py apps/backend/tests/unit/agents/roles/test_analyst_conversation.py apps/backend/tests/fixtures/analyst_longitudinal_cases.json apps/web/src/features/agents/AnalystThread.tsx apps/web/src/features/agents/AnalystThread.test.tsx apps/web/src/features/agents/MemoryProvenance.tsx apps/web/src/features/agents/MemoryProvenance.test.tsx
git commit -m "feat(agents): add evidence-bounded analyst"
```

### Task 15: Define and persist practice interviews, real interviews, consent, and opportunities

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/interviews.py`
- Create: `packages/protocol/src/tamforge_protocol/opportunities.py`
- Create: `packages/protocol/tests/test_interviews.py`
- Create: `packages/protocol/tests/test_opportunities.py`
- Create: `apps/backend/alembic/versions/20260825_0011_interviews_opportunities.py`
- Create: `apps/backend/src/tamforge_backend/interviews/models.py`
- Create: `apps/backend/src/tamforge_backend/opportunities/models.py`
- Create: `apps/backend/tests/integration/interviews/test_interview_opportunity_migration.py`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`

- [ ] **Step 1: Write failing state and contract tests**

Cover session-level compatibility with the recording/speech plan's existing `tamforge_protocol.turns` state machine, maximum two routine follow-ups, separate `RealInterview` identity, consent states `Unknown`, `UserAttestedPermitted`, and `Prohibited`, append-only permission records, redaction approval, five-minute debrief, attribution categories, opportunity stages/outcomes, immutable job-description snapshots, and permanent links to evidence.

```python
def test_permission_never_defaults_to_recordable() -> None:
    interview = RealInterviewCreate.model_validate(minimal_interview())
    assert interview.permission_state is RecordingPermission.UNKNOWN
    assert interview.can_record is False
```

- [ ] **Step 2: Run protocol tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_interviews.py packages/protocol/tests/test_opportunities.py -q`

Expected: FAIL because the contracts do not exist.

- [ ] **Step 3: Implement strict protocol models**

Import the existing strict turn-event contracts instead of defining a second question/audio/transcript state machine; add only session/follow-up decisions and real-interview contracts in `interviews.py`. Model real-interview provenance as `explicit_interview_content`, `learner_recollection`, `ai_inference`, or `unknown`; never collapse these fields into prose. Model outcomes as `Advanced`, `Rejected`, `Withdrew`, `Offer`, `NoResponse`, or an open stage event without inferring one from interviewer tone.

- [ ] **Step 4: Define the database migration**

Create `practice_interview_sessions`, `practice_interview_turns`, `interview_permission_records`, `interview_debriefs`, `interview_redaction_versions`, `interview_question_segments`, `interview_outcome_events`, `opportunities`, `opportunity_job_description_versions`, `opportunity_stage_events`, and `opportunity_evidence_links`; extend the foundation's existing forward-compatible `interviews` table into the canonical real-interview record instead of creating a parallel table. Add uniqueness for turn ordinals and redaction versions; check constraints for state, permission, outcome, and attribution; indexes for scheduled date, active stage, and company scope; and foreign keys to activities, attempts, transcripts, artifacts, and evidence.

- [ ] **Step 5: Make permission/history append-only**

Use new permission records for every attestation or revocation. `UserAttestedPermitted -> Prohibited` affects future capture only; it never deletes source evidence. A later permitted state requires a new dated attestation record. Preserve source job-description snapshots and stage history rather than updating them in place.

- [ ] **Step 6: Run safe protocol verification**

Run: `uv run pytest packages/protocol/tests/test_interviews.py packages/protocol/tests/test_opportunities.py -q`

Expected: PASS.

- [ ] **Step 7: Verify the migration only after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

During implementation, inspect the checked-out Alembic graph and set `down_revision` to the exact `20260825_0010_memory` revision.

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/interviews/test_interview_opportunity_migration.py
```

Expected: PASS for upgrades, constraints, append-only history, and a downgrade limited to revision `20260825_0011` objects.

- [ ] **Step 8: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/interviews.py packages/protocol/src/tamforge_protocol/opportunities.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_interviews.py packages/protocol/tests/test_opportunities.py apps/backend/alembic/versions/20260825_0011_interviews_opportunities.py apps/backend/src/tamforge_backend/interviews/models.py apps/backend/src/tamforge_backend/opportunities/models.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/tests/integration/interviews/test_interview_opportunity_migration.py
git commit -m "feat(interviews): persist consent turns and opportunities"
```

### Task 16: Implement the isolated turn-based practice Interviewer

**Files:**
- Create: `apps/backend/src/tamforge_backend/agents/roles/interviewer.py`
- Create: `apps/backend/src/tamforge_backend/interviews/practice.py`
- Create: `apps/backend/src/tamforge_backend/interviews/routes.py`
- Create: `apps/backend/tests/unit/agents/roles/test_interviewer.py`
- Create: `apps/backend/tests/unit/interviews/test_practice_service.py`
- Create: `apps/backend/tests/security/test_interviewer_isolation.py`
- Create: `apps/web/src/features/interviews/PracticeInterviewer.tsx`
- Create: `apps/web/src/features/interviews/PracticeInterviewer.test.tsx`
- Modify: `apps/backend/src/tamforge_backend/interviewer/turn_audio.py`
- Modify: `apps/backend/src/tamforge_backend/interviewer/turn_routes.py`
- Modify: `apps/web/src/features/interviewer/audio/LocalQuestionPlayer.ts`
- Modify: `apps/web/src/features/interviewer/audio/__tests__/LocalQuestionPlayer.test.ts`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Modify: `apps/backend/src/tamforge_backend/workers/claude.py`

- [ ] **Step 1: Write failing application-state tests**

Test legal turn transitions, uninterrupted answers, pre-generated/local-TTS questions, maximum two routine follow-ups, no third follow-up even if Claude asks, retry idempotency, and timeout behavior that either seals the session or requires an explicit retry without coaching the completed answer.

- [ ] **Step 2: Write failing isolation tests**

Seed current corrections, Coach/Tutor messages, reviewer judgments, broad learner memory, a second opportunity, and private real-interview content. Assert the prepared Interviewer packet contains only canonical scenario facts, audience/difficulty, current priority transcript, visible prior question/answer turns, allowed scenario state, and follow-up count.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_interviewer.py apps/backend/tests/unit/interviews/test_practice_service.py apps/backend/tests/security/test_interviewer_isolation.py -q`

Expected: FAIL because the practice service and Interviewer are absent.

- [ ] **Step 4: Implement priority-turn orchestration**

Consume the speech plan's bounded `PriorityTranscriptReady` event only after `AnswerSealed`; bulk transcription must yield while capture is active. Store visible turns in application state, call the Interviewer for a structured `ask_followup|seal_session` decision, and persist the exact input manifest/output. Never resume an opaque SDK session as canonical history.

- [ ] **Step 5: Implement local TTS and failure behavior in the web UI**

Extend the recording/speech plan's tested `LocalQuestionPlayer`; do not create a second TTS implementation. Use browser/macOS local speech synthesis, do not send generated question audio to Claude, and do not persist that audio as evidence. Keep recording controls separate from follow-up generation, show the active Interviewer role, and never interrupt capture. On the configured deadline, show `Seal session` and `Retry follow-up`; do not offer coaching.

- [ ] **Step 6: Gate production activation on measured latency**

Keep follow-up generation disabled by default behind `INTERVIEWER_FOLLOWUPS_ENABLED=false`. On the target server, benchmark representative answers up to five minutes and require p95 `AnswerSealed -> LocalTTSPlaying` at or below 120 seconds with zero isolation/follow-up-limit failures. Missing the gate leaves the session usable as a no-follow-up saved attempt; no paid compute fallback is allowed.

- [ ] **Step 7: Run backend and UI verification**

Run: `uv run pytest apps/backend/tests/unit/agents/roles/test_interviewer.py apps/backend/tests/unit/interviews/test_practice_service.py apps/backend/tests/security/test_interviewer_isolation.py -q && pnpm --dir apps/web exec vitest run src/features/interviews/PracticeInterviewer.test.tsx && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS; every routine case has at most two follow-ups and zero forbidden context.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/tamforge_backend/agents/roles/interviewer.py apps/backend/src/tamforge_backend/interviews/practice.py apps/backend/src/tamforge_backend/interviews/routes.py apps/backend/src/tamforge_backend/interviewer/turn_audio.py apps/backend/src/tamforge_backend/interviewer/turn_routes.py apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/workers/claude.py apps/backend/tests/unit/agents/roles/test_interviewer.py apps/backend/tests/unit/interviews/test_practice_service.py apps/backend/tests/security/test_interviewer_isolation.py apps/web/src/features/interviews apps/web/src/features/interviewer/audio
git commit -m "feat(interviews): add isolated turn-based interviewer"
```

### Task 17: Enforce the real-interview consent, debrief, redaction, and analysis path

**Files:**
- Create: `apps/backend/src/tamforge_backend/interviews/policy.py`
- Create: `apps/backend/src/tamforge_backend/interviews/redaction.py`
- Create: `apps/backend/src/tamforge_backend/interviews/service.py`
- Create: `apps/backend/tests/unit/interviews/test_policy.py`
- Create: `apps/backend/tests/unit/interviews/test_redaction.py`
- Create: `apps/backend/tests/integration/interviews/test_real_interview_flow.py`
- Create: `apps/backend/tests/security/test_real_interview_privacy.py`
- Create: `apps/web/src/features/interviews/RealInterviewSetup.tsx`
- Create: `apps/web/src/features/interviews/InterviewDebrief.tsx`
- Create: `apps/web/src/features/interviews/RedactionApproval.tsx`
- Create: `apps/web/src/features/interviews/RealInterviewFlow.test.tsx`
- Create: `docs/runbooks/real-interview-privacy.md`
- Modify: `apps/backend/src/tamforge_backend/interviews/routes.py`

- [ ] **Step 1: Write failing permission and capture-policy tests**

Assert capture controls are disabled in `Unknown` and `Prohibited`; TAM Forge records a user attestation plus jurisdiction/context/policy version but never makes a legal conclusion; revocation blocks new capture; and no live Claude/AI assistance job can be queued for an interview in progress.

- [ ] **Step 2: Write failing processing-eligibility tests**

Require `IngestSealed`, a committed private five-minute debrief, selected transcript/speaker versions, explicit approval of a redacted submission bundle, and the global Claude privacy attestation. Ensure the bundle previews and versions every text field sent to Claude, including transcript, debrief, job description excerpts, and remembered questions.

- [ ] **Step 3: Run unit/security tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/interviews/test_policy.py apps/backend/tests/unit/interviews/test_redaction.py apps/backend/tests/security/test_real_interview_privacy.py -q`

Expected: FAIL because policy/redaction services are absent.

- [ ] **Step 4: Implement redaction as an append-only approval artifact**

Generate deterministic local suggestions for obvious names, emails, domains, customer/account identifiers, secrets, and numbers; never auto-approve them. Save original transcript/debrief unchanged, save redaction spans and replacement labels in a new version, render an exact before/after preview, and require explicit owner approval tied to content hash. Editing invalidates prior approval and creates another version.

- [ ] **Step 5: Implement real-interview processing and attribution**

Queue speaker separation, question segmentation, timeline, competency mapping, and Reviewer analysis only after the eligibility policy passes. Store explicit interview content, learner recollection, AI inference, and unknown information separately. Produce exactly two corrections, avoid pass/fail prediction from tone, schedule one corrected replay for the next lesson, and later test transfer in a different scenario.

- [ ] **Step 6: Implement setup, debrief, approval, and outcome UI**

Capture company, role, stage, date, expected duration, known interviewers, job-description snapshot, competencies, research, questions, permission metadata, and expected next step. Warn against new/exhausting material in the final 60–90 minutes. Keep debrief private until a separate redacted submission is approved. Allow outcome/stage events without changing the original interview record.

- [ ] **Step 7: Document the privacy gate**

The runbook must state that the user—not TAM Forge—determines recording permission; real-interview audio stays private; no text is sent to Claude without the per-interview approved hash; anonymization must cover confidential employer/customer information; and a consent/policy change stops new processing without deleting history.

- [ ] **Step 8: Run safe verification**

Run: `uv run pytest apps/backend/tests/unit/interviews/test_policy.py apps/backend/tests/unit/interviews/test_redaction.py apps/backend/tests/security/test_real_interview_privacy.py -q && pnpm --dir apps/web exec vitest run src/features/interviews/RealInterviewFlow.test.tsx`

Expected: PASS; the Claude fake sees only the exact approved redacted bytes.

- [ ] **Step 9: Run the transactional flow only after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/interviews/test_real_interview_flow.py
```

Expected: PASS for permission, recording link, debrief, redaction invalidation/reapproval, processing, correction, replay, and outcome history.

- [ ] **Step 10: Pass the first-use privacy gate**

`[PRIVACY GATE]` Before any production real-interview submission, the user reviews the exact redacted bundle and approves its hash. A generic prior consent is insufficient.

- [ ] **Step 11: Commit**

```bash
git add apps/backend/src/tamforge_backend/interviews apps/backend/tests/unit/interviews apps/backend/tests/integration/interviews/test_real_interview_flow.py apps/backend/tests/security/test_real_interview_privacy.py apps/web/src/features/interviews docs/runbooks/real-interview-privacy.md
git commit -m "feat(interviews): enforce private real interview lifecycle"
```

### Task 18: Add opportunity tracking and opportunity-scoped practice context

**Files:**
- Create: `apps/backend/src/tamforge_backend/opportunities/service.py`
- Create: `apps/backend/src/tamforge_backend/opportunities/routes.py`
- Create: `apps/backend/tests/unit/opportunities/test_service.py`
- Create: `apps/backend/tests/security/test_opportunity_isolation.py`
- Create: `apps/web/src/features/opportunities/OpportunityList.tsx`
- Create: `apps/web/src/features/opportunities/OpportunityDetail.tsx`
- Create: `apps/web/src/features/opportunities/OpportunityFlow.test.tsx`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Modify: `apps/backend/src/tamforge_backend/memory/context.py`

- [ ] **Step 1: Write failing opportunity lifecycle tests**

Test immutable job-description snapshots; current stage and append-only history; saved pipeline action/artifact; next action; competencies, stories, known gaps, and related interviews; outcomes and time between stages; and idempotent updates. Require a concrete saved action or artifact to complete a 30-minute pipeline block.

- [ ] **Step 2: Write failing context-boundary tests**

Assert an active opportunity may influence adaptive prompt/company/audience selection but cannot rewrite roadmap coverage, required resources, time, Saturday assessment, Sunday, or exit criteria. Assert confidential/company-scoped content never enters another opportunity's context.

- [ ] **Step 3: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/opportunities/test_service.py apps/backend/tests/security/test_opportunity_isolation.py -q`

Expected: FAIL because the service is absent.

- [ ] **Step 4: Implement commands and owner-only routes**

Provide create, snapshot job description, append stage/outcome, link interview/evidence/story, record pipeline action, and set next action commands. Derive stage duration from events; never infer conversion or a rejection/offer. Keep deletion as archive-only in the normal UI.

- [ ] **Step 5: Connect opportunity context to Planner and interview preparation**

Return a bounded, sensitivity-labeled context packet with company/product facts, target competencies, approved stories/evidence, gaps, next action, and relevant interview stage. Every inclusion receives a reason and source ID. Do not put entire job descriptions or unrelated company history in routine model calls.

- [ ] **Step 6: Implement and test the web flow**

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/opportunities/OpportunityFlow.test.tsx`

Expected: FAIL because the feature is absent.

Implement list/detail/stage timeline, snapshots, next action, related interviews, privacy labels, and archive. Then rerun the command.

Expected after implementation: PASS.

- [ ] **Step 7: Run verification**

Run: `uv run pytest apps/backend/tests/unit/opportunities/test_service.py apps/backend/tests/security/test_opportunity_isolation.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS with zero cross-company fixture leakage.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/tamforge_backend/opportunities apps/backend/src/tamforge_backend/api.py apps/backend/src/tamforge_backend/memory/context.py apps/backend/tests/unit/opportunities apps/backend/tests/security/test_opportunity_isolation.py apps/web/src/features/opportunities
git commit -m "feat(opportunities): track pipeline and scoped context"
```

### Task 19: Add specialized technical-reading and SQL workspaces after the universal MVP

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/workspaces.py`
- Create: `packages/protocol/tests/test_workspaces.py`
- Create: `apps/backend/src/tamforge_backend/workspaces/reading.py`
- Create: `apps/backend/src/tamforge_backend/workspaces/sql.py`
- Create: `apps/backend/src/tamforge_backend/workspaces/sql_runner.py`
- Create: `apps/backend/src/tamforge_backend/workspaces/routes.py`
- Create: `apps/backend/tests/unit/workspaces/test_reading.py`
- Create: `apps/backend/tests/unit/workspaces/test_sql.py`
- Create: `apps/backend/tests/integration/workspaces/test_sql_runner.py`
- Create: `infra/sql/tamforge_learning_role.sql`
- Create: `apps/web/src/features/workspaces/ReadingWorkspace.tsx`
- Create: `apps/web/src/features/workspaces/SqlWorkspace.tsx`
- Create: `apps/web/src/features/workspaces/SqlWorkspace.test.tsx`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing workspace-contract tests**

Define phase/timer, source-visibility, immutable committed output, assistance, hint level, evidence requirement, and result-validation contracts. Require the reading recall note's three key ideas, one boundary/failure mode, one TAM/customer example, and one unresolved question. Require SQL query, result, explanation/business meaning, timing, assistance, self-review, and mistake categories.

- [ ] **Step 2: Run protocol tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_workspaces.py -q`

Expected: FAIL because workspace contracts are absent.

- [ ] **Step 3: Implement technical-reading behavior over the universal activity model**

Enforce preview 2 minutes, focused assigned reading about 20, hidden-source recall about 8, application about 10, and teach-back about 5. The source becomes inaccessible in the recall phase; Tutor unlocks only after the learner commits the note. AI evaluates the note but never replaces it with an AI summary.

- [ ] **Step 4: Write failing SQL lock and hint-ladder tests**

Test 5-minute retrieval, 30-minute primary work, 5-minute validation/explanation, 5-minute self-review/save; AI lock until commit or expiry; ordered hint levels; solution reveal only after saved attempt; Saturday no-AI; and assisted work excluded from qualifying evidence.

- [ ] **Step 5: Implement SQL evidence capture first**

Deliver the specialized editor/result/explanation/self-review flow using existing activity/evidence tables even when the browser executor is disabled. This satisfies the MVP's committed SQL text/results requirement without making full in-browser execution a launch dependency.

- [ ] **Step 6: Implement the post-MVP isolated SQL runner**

Use a dedicated `tamforge_learning_runner` database role and a per-exercise allowlisted schema/DSN. The database—not query-string parsing—is the security boundary: no application schema grants, no network/server file capabilities, `default_transaction_read_only=on`, bounded `statement_timeout`, `lock_timeout`, row count, result bytes, and concurrent executions. Roll back the execution transaction and store a canonicalized result artifact plus validation metadata. This service is not exposed as a Claude tool.

- [ ] **Step 7: Test the UI lock and evidence flow**

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/workspaces/SqlWorkspace.test.tsx`

Expected: FAIL because the component is absent.

Implement timers, source/schema view, editor, bounded results, explanation, commit, hint ladder, AI-lock reason, mistake classification, and resume. Then rerun the command.

Expected after implementation: PASS.

- [ ] **Step 8: Run safe unit verification**

Run: `uv run pytest packages/protocol/tests/test_workspaces.py apps/backend/tests/unit/workspaces/test_reading.py apps/backend/tests/unit/workspaces/test_sql.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS.

- [ ] **Step 9: Verify database isolation only after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/workspaces/test_sql_runner.py
```

Expected: PASS for valid curriculum queries and denial of application-table access, filesystem/server functions, runaway queries, oversized results, and cross-exercise schemas.

- [ ] **Step 10: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/workspaces.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_workspaces.py apps/backend/src/tamforge_backend/workspaces apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/workspaces apps/backend/tests/integration/workspaces/test_sql_runner.py infra/sql/tamforge_learning_role.sql apps/web/src/features/workspaces
git commit -m "feat(workspaces): specialize reading and SQL practice"
```

### Task 20: Add case, cumulative-history, and portfolio-judgment workspaces

**Files:**
- Create: `apps/backend/src/tamforge_backend/workspaces/cases.py`
- Create: `apps/backend/src/tamforge_backend/workspaces/portfolio.py`
- Create: `apps/backend/tests/unit/workspaces/test_cases.py`
- Create: `apps/backend/tests/unit/workspaces/test_portfolio.py`
- Create: `apps/backend/tests/fixtures/northstar_history.json`
- Create: `apps/web/src/features/workspaces/CaseWorkspace.tsx`
- Create: `apps/web/src/features/workspaces/PortfolioBoard.tsx`
- Create: `apps/web/src/features/workspaces/CaseWorkspace.test.tsx`
- Modify: `packages/protocol/src/tamforge_protocol/workspaces.py`
- Modify: `apps/backend/src/tamforge_backend/workspaces/routes.py`

- [ ] **Step 1: Write failing 60-minute case-state tests**

Enforce Understand 5, Discovery 10, Structure 5, Solve/Produce 25, Present/Defend 10, and Self-review 5; canonical prompt/facts; questions; explicit assumptions; working notes; final artifact; presentation recording/transcript; at most two routine follow-ups; decisions/risks/unknowns; and mandatory self-review.

- [ ] **Step 2: Write failing cumulative-history tests**

Seed the Northstar fixture and assert canonical facts, injections, decisions, reversals, risks, and unresolved questions append with provenance/version. Neither AI nor a new activity may silently rewrite a past fact or decision. A changed fact must be an explicit scenario event linked to what it supersedes.

- [ ] **Step 3: Write failing portfolio tests**

Require explicit priority, delegation, escalation, customer communication, protected proactive work, and reprioritization. Capture impact, financial/data/security/compliance risk, severity/blast radius, time sensitivity, deterioration risk, workaround quality, deadline, strategic context, capacity, and diagnostic confidence. Verify the loudest/largest customer is not automatically priority one.

- [ ] **Step 4: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/workspaces/test_cases.py apps/backend/tests/unit/workspaces/test_portfolio.py -q`

Expected: FAIL because case services are absent.

- [ ] **Step 5: Implement case and portfolio services on immutable artifacts/events**

Reuse universal activities, artifact lineage, attempts, evidence, and outbox events. Do not add a second case database. Preserve the Month 1 progression: two competing incidents in Week 2, five-account reactive/proactive planning in Week 3, and five-account triage followed by single-customer depth in Week 4.

- [ ] **Step 6: Prevent full-case repetition for one weakness**

Convert the highest-value weak segment into one of tomorrow's maximum two corrections or a later retrieval scenario. The service must reject scheduling the same full 60-minute case as an automatic correction.

- [ ] **Step 7: Implement and test case UI**

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/workspaces/CaseWorkspace.test.tsx`

Expected: FAIL because the components are absent.

Implement phase timer, facts/assumptions separation, discovery questions, artifact editor, decision/risk timeline, portfolio board, presentation launch, self-review, and immutable history view. Rerun the test.

Expected after implementation: PASS.

- [ ] **Step 8: Run verification**

Run: `uv run pytest apps/backend/tests/unit/workspaces/test_cases.py apps/backend/tests/unit/workspaces/test_portfolio.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS; fixture history hashes remain stable.

- [ ] **Step 9: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/workspaces.py apps/backend/src/tamforge_backend/workspaces/cases.py apps/backend/src/tamforge_backend/workspaces/portfolio.py apps/backend/src/tamforge_backend/workspaces/routes.py apps/backend/tests/unit/workspaces/test_cases.py apps/backend/tests/unit/workspaces/test_portfolio.py apps/backend/tests/fixtures/northstar_history.json apps/web/src/features/workspaces
git commit -m "feat(workspaces): add cases and portfolio judgment"
```

### Task 21: Add written-communication and career-pipeline workspaces

**Files:**
- Create: `apps/backend/src/tamforge_backend/workspaces/writing.py`
- Create: `apps/backend/src/tamforge_backend/workspaces/career.py`
- Create: `apps/backend/tests/unit/workspaces/test_writing.py`
- Create: `apps/backend/tests/unit/workspaces/test_career.py`
- Create: `apps/web/src/features/workspaces/WritingWorkspace.tsx`
- Create: `apps/web/src/features/workspaces/CareerWorkspace.tsx`
- Create: `apps/web/src/features/workspaces/WritingCareerWorkspace.test.tsx`
- Modify: `packages/protocol/src/tamforge_protocol/workspaces.py`
- Modify: `apps/backend/src/tamforge_backend/workspaces/routes.py`

- [ ] **Step 1: Write failing writing-lifecycle tests**

Cover audience, requested action, facts, unknowns, tone, and limit; independent Attempt A; one self-edit; immutable committed draft; asynchronous analysis after self-review; exactly two corrections; future 10-minute Attempt B; and no further revision. Reject AI-invented experience, metrics, decisions, or technical evidence.

- [ ] **Step 2: Write failing artifact-type tests**

Exercise customer incident update, executive summary, discovery follow-up, engineering escalation, implementation update, launch recommendation, postmortem, account plan, QBR narrative, behavioral story, application/outreach, and interview thank-you note with type-specific required metadata but a shared writing state machine.

- [ ] **Step 3: Write failing career-block tests**

Enforce Select 5, Produce 20, Record 5; company/role; job-description snapshot; completed action; current stage; next action; relevant stories/competencies; gaps; related interviews; and a concrete saved artifact/action before completion. Active opportunities may shape practice but never rewrite the roadmap spine.

- [ ] **Step 4: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/workspaces/test_writing.py apps/backend/tests/unit/workspaces/test_career.py -q`

Expected: FAIL because services are absent.

- [ ] **Step 5: Implement shared workspace policies**

Persist every draft/version as an artifact/evidence link, reuse the self-review/Reviewer/correction services, and allow exactly one Attempt B. Career actions link to an opportunity when applicable; absence of an opportunity does not prevent general pipeline work.

- [ ] **Step 6: Implement and test the UI**

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/workspaces/WritingCareerWorkspace.test.tsx`

Expected: FAIL because components are absent.

Implement writing constraints, version comparison, self-edit lock, career action selector, artifact upload/editor, opportunity linkage, next action, timers, and resume. Then rerun the command.

Expected after implementation: PASS.

- [ ] **Step 7: Run verification**

Run: `uv run pytest apps/backend/tests/unit/workspaces/test_writing.py apps/backend/tests/unit/workspaces/test_career.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/workspaces.py apps/backend/src/tamforge_backend/workspaces/writing.py apps/backend/src/tamforge_backend/workspaces/career.py apps/backend/src/tamforge_backend/workspaces/routes.py apps/backend/tests/unit/workspaces/test_writing.py apps/backend/tests/unit/workspaces/test_career.py apps/web/src/features/workspaces
git commit -m "feat(workspaces): add writing and career flows"
```

### Task 22: Build analytics, interview-family readiness, and reports over the foundation evidence ledger

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/reports.py`
- Create: `packages/protocol/tests/test_reports.py`
- Create: `apps/backend/alembic/versions/20260825_0012_reports_exports.py`
- Create: `config/interview-families/interview-families-v1.yaml`
- Create: `apps/backend/src/tamforge_backend/reports/models.py`
- Create: `apps/backend/src/tamforge_backend/reports/repository.py`
- Create: `apps/backend/src/tamforge_backend/reports/calculator.py`
- Create: `apps/backend/src/tamforge_backend/reports/service.py`
- Create: `apps/backend/src/tamforge_backend/reports/routes.py`
- Create: `apps/backend/src/tamforge_backend/exports/models.py`
- Create: `apps/backend/src/tamforge_backend/exports/repository.py`
- Create: `apps/backend/src/tamforge_backend/retention/models.py`
- Create: `apps/backend/src/tamforge_backend/retention/repository.py`
- Create: `apps/backend/tests/unit/reports/test_repository.py`
- Create: `apps/backend/tests/unit/reports/test_calculator.py`
- Create: `apps/backend/tests/unit/reports/test_service.py`
- Create: `apps/backend/tests/unit/exports/test_repository.py`
- Create: `apps/backend/tests/unit/retention/test_repository.py`
- Create: `apps/backend/tests/integration/reports/test_reports_migration.py`
- Create: `apps/web/src/features/reports/DailySummary.tsx`
- Create: `apps/web/src/features/reports/WeeklyReport.tsx`
- Create: `apps/web/src/features/reports/ReadinessView.tsx`
- Create: `apps/web/src/features/reports/Reports.test.tsx`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`
- Modify: `apps/web/src/features/evidence/FormulaBreakdown.tsx`

- [ ] **Step 1: Write failing report and readiness contracts**

Require report/config version, covered roadmap nodes, pass-criterion results, strongest evidence, weakness, corrections, unfinished requirement, self/AI calibration, A/B comparison, real-interview evidence, priorities, risk, and exact source IDs. A readiness item references the foundation's immutable calculation trace and exposes contributing/excluded evidence, estimate/confidence/trend/recency, target gap, and readiness-state rationale. Daily/weekly reports are immutable versions, not mutable dashboard blobs.

- [ ] **Step 2: Run protocol tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_reports.py -q`

Expected: FAIL because report contracts are absent.

- [ ] **Step 3: Write failing persistence contract tests**

Test append-only report versions, report/evidence ordering and uniqueness, readiness snapshot source manifests, export/import state transitions, export/import artifact uniqueness, immutable import preview hashes/idempotency keys, optimistic expected-state updates, idempotent job publication, and refusal to mark an export/import verified when a referenced source/hash is missing. Also test append-only retention-policy versions, archive events, deletion-request/item closure, immutable preview hashes, legal recoverable-deletion states, and owner/target uniqueness; Tasks 23–24 will own command behavior over this schema.

Run: `uv run pytest apps/backend/tests/unit/reports/test_repository.py apps/backend/tests/unit/exports/test_repository.py apps/backend/tests/unit/retention/test_repository.py -q`

Expected: FAIL because SQLAlchemy models and repositories are absent.

- [ ] **Step 4: Define and implement report/export persistence**

Create `report_config_versions`, `interview_family_readiness_snapshots`, `report_versions`, `report_evidence_links`, `exports`, `export_artifact_links`, `imports`, `import_artifact_links`, `retention_policy_versions`, `archive_events`, `deletion_requests`, and `deletion_items`, with matching focused SQLAlchemy models and repositories imported by `models/__init__.py`. Reuse the foundation's existing `config_seed_versions`, `skill_evidence_events`, `skill_snapshots`, rubric records, qualification rules, correction foundations, audit ledger, and object catalog; do not duplicate or fork those calculators. Keep report/readiness snapshots rebuildable from their exact source IDs and versions. Add unique report/export/config versions, evidence foreign keys, import preview/idempotency uniqueness, immutable preview hashes, legal import/deletion-state checks, target/item uniqueness, and indexes for family/date/report/import/retention queries. Set `down_revision` by inspecting the actual `20260825_0011_interviews_opportunities` revision. Reserved import/retention records remain inert until Tasks 23–24 implement owner commands; no automatic import, lifecycle, or purge is enabled by this migration.

- [ ] **Step 5: Write failing evidence-adapter and readiness tests**

Seed the foundation evidence service with qualifying and nonqualifying events. Verify reports consume its stored calculation trace without recalculating weights. Attempt B, exposure, reading, applications, unsaved Coach, unscored completion, and guided work may appear in preparation/history sections but cannot raise skill or interview-family readiness. Verify Interviewer-only AI remains independent evidence when every other qualifying condition holds.

- [ ] **Step 6: Define and test the seventeen interview-family mappings**

Version the approved seventeen families and six states: Not attempted, Coach-assisted, Independent pass, Pressure-tested, Demonstrated in mock, and Demonstrated in real interview. Require explicit exercise/family/condition mappings; do not infer coverage from a title or transcript. Assert evidence strength/state monotonicity, condition diversity, and the difference between family readiness and underlying competency level.

- [ ] **Step 7: Implement deterministic report aggregation**

Read roadmap completion/pass criteria, the foundation skill-estimate traces, corrections, Attempt comparisons, real-interview provenance, and opportunity outcomes through typed ports. Compute family state, coverage, self-versus-AI calibration, measurable changes, repeated mistakes, and report selections in Python with explicit inclusion/exclusion reasons. Keep self score separate and never allow a report or Claude summary to mutate evidence.

- [ ] **Step 8: Implement daily, weekly, and readiness reports**

Daily output is strongest evidence, most important weakness, exactly two corrections, and unfinished requirement. Weekly output has the approved ten ordered sections. Track all seventeen interview families and their six readiness states. Opportunity stage conversion appears only after a configured minimum evidence count and never substitutes for skill evidence. Exclude recording count, transcript word count, raw app time, and streaks as success measures.

At month close, require the final assessment before producing an exit report; compare immutable evidence with versioned exit criteria, review interview outcomes, classify competencies as advanced/stable/weak, and then wait for a separately supplied, staged, and explicitly activated roadmap version. Reports must never invent Month 2 or activate a staged roadmap.

- [ ] **Step 9: Implement inspectable report UI**

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/reports/Reports.test.tsx`

Expected: FAIL because report components are absent.

Implement daily/weekly/readiness views and extend the foundation `FormulaBreakdown` to show the report's contributing/excluded events, formula/config versions, weights, confidence/trend/recency basis, family-state rationale, and gaps. Then rerun the command.

Expected after implementation: PASS.

- [ ] **Step 10: Run safe verification**

Run: `uv run pytest packages/protocol/tests/test_reports.py apps/backend/tests/unit/reports apps/backend/tests/unit/exports/test_repository.py apps/backend/tests/unit/retention/test_repository.py -q && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS; every displayed estimate references and round-trips to the same foundation calculation trace.

- [ ] **Step 11: Verify the migration only after Docker approval**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/reports/test_reports_migration.py
```

Expected: PASS for report/export/import/retention constraints, append-only records, import/deletion closure and state checks, readiness/report rebuild parity, reuse of foundation ledger IDs, inert-by-default import/retention records, and downgrade limited to `20260825_0012` objects.

- [ ] **Step 12: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/reports.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_reports.py config/interview-families/interview-families-v1.yaml apps/backend/alembic/versions/20260825_0012_reports_exports.py apps/backend/src/tamforge_backend/reports apps/backend/src/tamforge_backend/exports/models.py apps/backend/src/tamforge_backend/exports/repository.py apps/backend/src/tamforge_backend/retention/models.py apps/backend/src/tamforge_backend/retention/repository.py apps/backend/src/tamforge_backend/models/__init__.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/reports apps/backend/tests/unit/exports/test_repository.py apps/backend/tests/unit/retention/test_repository.py apps/backend/tests/integration/reports/test_reports_migration.py apps/web/src/features/reports apps/web/src/features/evidence/FormulaBreakdown.tsx
git commit -m "feat(reports): add reproducible readiness analytics"
```

### Task 23: Build complete verified export plus dry-run/transactional import and optional OKF 0.2 projection

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/exports.py`
- Create: `packages/protocol/tests/test_exports.py`
- Create: `apps/backend/src/tamforge_backend/exports/builder.py`
- Create: `apps/backend/src/tamforge_backend/exports/validator.py`
- Create: `apps/backend/src/tamforge_backend/exports/importer.py`
- Create: `apps/backend/src/tamforge_backend/exports/okf.py`
- Create: `apps/backend/src/tamforge_backend/exports/service.py`
- Create: `apps/backend/src/tamforge_backend/exports/routes.py`
- Create: `apps/backend/src/tamforge_backend/workers/general.py`
- Modify: `apps/backend/src/tamforge_backend/jobs/registry.py`
- Create: `apps/backend/src/tamforge_backend/integrity/__init__.py`
- Create: `apps/backend/src/tamforge_backend/integrity/export_keys.py`
- Create: `apps/backend/src/tamforge_backend/integrity/export_signing.py`
- Modify: `apps/backend/src/tamforge_backend/exports/models.py`
- Modify: `apps/backend/src/tamforge_backend/exports/repository.py`
- Modify: `apps/backend/src/tamforge_backend/config.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `scripts/bootstrap_export_signing_key.py`
- Create: `scripts/rotate_export_signing_key.py`
- Create: `apps/backend/tests/unit/exports/test_builder.py`
- Create: `apps/backend/tests/unit/exports/test_validator.py`
- Create: `apps/backend/tests/unit/exports/test_importer.py`
- Create: `apps/backend/tests/unit/exports/test_okf.py`
- Create: `apps/backend/tests/unit/exports/test_job_handler.py`
- Create: `apps/backend/tests/unit/workers/test_general_worker.py`
- Create: `apps/backend/tests/unit/integrity/test_export_keys.py`
- Create: `apps/backend/tests/unit/integrity/test_export_signing.py`
- Create: `apps/backend/tests/unit/integrity/test_export_key_rotation.py`
- Create: `apps/backend/tests/integration/exports/test_export_import_restore.py`
- Create: `apps/web/src/features/exports/ExportPanel.tsx`
- Create: `apps/web/src/features/exports/ImportRestorePanel.tsx`
- Create: `apps/web/src/features/exports/ExportPanel.test.tsx`
- Create: `apps/web/src/features/exports/ImportRestorePanel.test.tsx`
- Create: `docs/runbooks/export-and-portability.md`
- Create: `docs/runbooks/export-signing-keys.md`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing export/import manifest, signing, and state contracts**

Require export ID, generated-at, application/schema version, roadmap versions, database snapshot reference, logical-record inventories, object paths, byte lengths, MIME types, SHA-256 hashes, lineage/relationship files, missing-item reasons, and an `ExportSignatureEnvelopeV1` containing algorithm `ed25519`, domain/schema version, exact unsigned-manifest SHA-256, nonsecret key ID, public-key fingerprint, and Base64 signature. Add `ImportDryRunRequest|Result`, typed validation findings, `ImportConflict`, exact source-to-target plan, `ImportCommitRequest|Result`, idempotency key, preview hash, and `uploaded -> validating -> preview_ready -> committing -> restored|needs_attention` states. Reject a verified export/import when any required source, trusted signature, relationship, or checksum is missing.

Define two strict versioned files stored outside Git: a root-only private signing document with exactly one active Ed25519 private key, and a public trust bundle containing every current/retired verification key plus its SHA-256 fingerprint. Exact nonsecret settings are `TAMFORGE_EXPORT_SIGNING_CREDENTIAL_NAME=export-signing-private.json` and `TAMFORGE_EXPORT_TRUST_CREDENTIAL_NAME=export-signing-public.json`; optional direct paths are test/development-only and fail closed in production. Tests must reject unknown/disabled IDs, duplicate IDs, wrong algorithms, malformed keys/signatures, unsafe permissions, symlinks, repository-contained secrets, signature/key substitution, and attempts to trust a public key supplied only by the archive.

- [ ] **Step 2: Run protocol and importer tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_exports.py apps/backend/tests/unit/exports/test_validator.py apps/backend/tests/unit/exports/test_importer.py apps/backend/tests/unit/exports/test_job_handler.py apps/backend/tests/unit/integrity/test_export_keys.py apps/backend/tests/unit/integrity/test_export_signing.py apps/backend/tests/unit/integrity/test_export_key_rotation.py apps/backend/tests/unit/workers/test_general_worker.py -q`

Expected: FAIL because export/import contracts, production key loading/signing/verification, rotation, the general-worker export handler, archive validation, and importer are absent.

- [ ] **Step 3: Implement bounded streaming export assembly and the durable general-worker handler**

Stream rows and object-store artifacts through a temporary bounded-disk workspace; never accumulate audio or the whole archive in RAM. Include original audio and integrity manifests; every transcript/analysis version; notes, SQL, written artifacts; scores, rubrics, prompts, model-run/context manifests; every roadmap/source snapshot; interview/opportunity history; memory revisions; audit-safe relationships and metadata; plus JSON/CSV human-readable indexes. Preserve original filenames, permanent IDs, and immutable source bytes.

`POST /api/v1/exports` validates owner scope/idempotency and enqueues exactly one `export.build.v1` job through Plan 1's durable job service; it never assembles/signs the archive in the API process. `GET /api/v1/exports/{export_id}` reads durable state. Register `export.build.v1` in the shared `jobs/registry.py` with a typed handler that calls the export service, heartbeats during bounded streaming, publishes success only after immutable upload/HEAD verification and catalog commit, and marks retry/`NeedsAttention` without advertising a partial archive.

Create `tamforge_backend.workers.general` as the executable module for the general worker. It builds an allowlisted registry of non-speech, non-Claude, non-embedding job types, claims through Plan 1's lease service, dispatches one bounded job at a time initially, heartbeats, and shuts down without abandoning a claimed lease. It explicitly excludes recording/speech, Claude, and embedding job types owned by their dedicated workers. The export handler lazily loads the private signer credential only after claiming an export job; missing/invalid signing material marks that export `NeedsAttention` and leaves unrelated general jobs claimable. Tests prove handler registration, producer-to-lease-to-signed-publication flow, duplicate idempotency, crash/reclaim, disallowed type refusal, and no signing key in API/queue payload/logs.

- [ ] **Step 4: Verify and sign before export publication**

Re-read every staged file, compare size/hash with its canonical catalog record, and validate foreign-key/relationship references in the exported logical graph. Canonicalize the unsigned manifest as strict UTF-8 JSON with sorted keys, no insignificant whitespace or non-finite numbers. Sign exactly `b"TAMFORGE-EXPORT-MANIFEST-V1\x00" + SHA256(canonical_unsigned_manifest_bytes)` using the active Ed25519 private key and persist the envelope without changing the unsigned bytes. Verification selects exactly the envelope's key ID from the independently provisioned public trust bundle and never tries every key, trusts an archive-supplied key, falls back to the active key, or re-signs history. Upload only the verified archive to a private object key and issue a short-lived owner-only download. Incomplete exports remain `NeedsAttention` and are never advertised as complete.

Implement `bootstrap_export_signing_key.py` and `rotate_export_signing_key.py` as check-first, secret-safe, atomic commands. Initial bootstrap is two-phase: `--stage --new-key-id <id>` generates the Ed25519 pair internally into root-only pending private/public documents and prints only their hashes/fingerprint; `--activate --backup-receipt <file>` verifies Task 24's independently generated encrypted-backup receipt for the exact pending private document before atomically installing the private source credential and retained public trust bundle. No unit sees the pending private file. It refuses existing/pending targets, symlinks, unsafe parents, Git paths, stale/mismatched receipts, and caller-supplied secret bytes. Crash/retry tests prove exactly one keypair and no silent overwrite.

Rotation likewise requires a verified encrypted recovery receipt, generates key bytes internally, writes/fsyncs root-owned source files through `0600` temporaries, and retains old public verification keys indefinitely. Both commands print only key IDs/hashes/fingerprints, never accept secret bytes on the command line, and never delete an old trust key. Missing/invalid signing credentials disable export publication only; missing/invalid trust credentials disable import verification only; neither may crash study, ingest, or unrelated workers.

- [ ] **Step 5: Implement archive-safe validation and a mutation-free dry run**

Stream the uploaded archive into a bounded quarantine directory. Verify its signature against the already provisioned trust bundle before trusting declared paths or relationships. Reject bad/unknown signer or key version, unsupported schema/application version, path traversal, absolute paths, symlinks/devices, duplicate logical/object IDs, decompression bombs/file-count or byte-limit breaches, MIME/size/hash mismatch, missing parents, broken lineage, owner mismatch, and undeclared content. `POST /api/v1/imports/dry-run` performs no canonical database/object-catalog mutation and returns exact insert/reuse/conflict counts, object bytes, required space, version compatibility, sensitive-real-interview scope, and an expiring exact preview hash persisted with the dry-run record. Commit compares that server-stored hash; it is not a bearer credential and needs no second signing key.

For a clean-install restore, the operator must first retrieve the historical public trust bundle from the encrypted off-host recovery repository, verify its independently recorded SHA-256 fingerprint/recovery manifest, and provision it through the API service's read-only systemd credential. An archive's embedded key ID/fingerprint is identification only and can never establish trust. The old private key is not required to verify/import; generating a new post-restore signing key is a separate operation that adds its public key to the retained trust bundle. No trust-on-first-use path exists.

- [ ] **Step 6: Implement explicit conflict policy and transactional restore**

Classify absent IDs as `insert`, and an existing immutable ID with the identical content hash as idempotent `reuse`. Treat the same permanent ID with different content, a changed roadmap/source snapshot, owner mismatch, or mutable-current-pointer disagreement as a hard conflict; never overwrite or silently remap it. Default commit aborts on any conflict. `POST /api/v1/imports/{import_id}/commit` requires owner session, CSRF, idempotency key, unexpired exact preview hash, and explicit sensitive-scope confirmation. Verify and place content-addressed object bytes first, then acquire one owner-scoped advisory lock and insert all logical rows, links, current pointers, object-catalog entries, and audit/outbox records in one serializable transaction. On failure, roll back every database row and inventory safe orphaned staged objects for cleanup; never delete a pre-existing object. Repeating the exact commit returns the prior result.

Add `GET /api/v1/imports/{import_id}` for durable status. Prove both a clean empty-install restore and an additive idempotent restore; no import operation deletes records absent from the archive.

- [ ] **Step 7: Add optional OKF 0.2 projection tests**

Map only verified, user-approved memory and roadmap knowledge to a pinned, human-readable OKF 0.2 Markdown/YAML projection. Test provenance links, stable IDs, relationships, escaping, deterministic order, and omission of hypotheses/sensitive records outside the chosen scope.

- [ ] **Step 8: Implement OKF as export-only**

Generate an `optional-okf/` directory inside the full export with its own version/readme and mapping manifest. PostgreSQL remains canonical; pgvector remains derived; Obsidian remains unchanged. The complete TAM Forge archive is importable through the importer above; the optional OKF projection itself is not an import/runtime/synchronization format.

- [ ] **Step 9: Write owner export/import UI tests and verify RED**

Run: `pnpm --dir apps/web exec vitest run src/features/exports/ExportPanel.test.tsx src/features/exports/ImportRestorePanel.test.tsx`

Expected: FAIL because the panels are absent. Test export scope/size/sensitive confirmation/OKF/progress/download plus import upload, dry-run-only first step, validation details, exact conflicts, preview expiry, explicit commit confirmation, durable status, idempotent retry, and success/failure recovery after reload.

- [ ] **Step 10: Implement the owner export/import UI and safe unit verification**

Implement the two-step UI without a one-click overwrite path. Never enable Commit while conflicts, signature failure, missing space, owner mismatch, or an expired preview exists. Show that import is additive and that optional OKF is not imported.

Run: `uv run pytest packages/protocol/tests/test_exports.py apps/backend/tests/unit/exports/test_builder.py apps/backend/tests/unit/exports/test_validator.py apps/backend/tests/unit/exports/test_importer.py apps/backend/tests/unit/exports/test_okf.py apps/backend/tests/unit/exports/test_job_handler.py apps/backend/tests/unit/integrity/test_export_keys.py apps/backend/tests/unit/integrity/test_export_signing.py apps/backend/tests/unit/integrity/test_export_key_rotation.py apps/backend/tests/unit/workers/test_general_worker.py -q && pnpm --dir apps/web exec vitest run src/features/exports/ExportPanel.test.tsx src/features/exports/ImportRestorePanel.test.tsx && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS using temporary credential files, deterministic test-only Ed25519 keys, and fake object storage; production credential policy, signature substitution, historical verification after rotation, and clean-restore trust refusal are covered without network/database access.

- [ ] **Step 11: Prove complete export and transactional import only after the database gate**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/exports/test_export_import_restore.py
```

Expected: PASS with marked tests collected and zero skips. An independently rehashed export restores every fixture artifact/version/relation into an empty database, exact replay is idempotent, a conflicting replay changes zero canonical rows, injected mid-commit failure leaves zero partial rows, and all restored relationships/hashes equal the source.

- [ ] **Step 12: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/exports.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_exports.py apps/backend/src/tamforge_backend/exports apps/backend/src/tamforge_backend/integrity apps/backend/src/tamforge_backend/workers/general.py apps/backend/src/tamforge_backend/jobs/registry.py apps/backend/src/tamforge_backend/config.py apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/exports apps/backend/tests/unit/integrity apps/backend/tests/unit/workers/test_general_worker.py apps/backend/tests/integration/exports/test_export_import_restore.py apps/web/src/features/exports scripts/bootstrap_export_signing_key.py scripts/rotate_export_signing_key.py docs/runbooks/export-and-portability.md docs/runbooks/export-signing-keys.md .env.example .gitignore
git commit -m "feat(exports): add verified export and transactional restore"
```

### Task 24: Implement retention, archive, recoverable deletion, and encrypted off-host recovery

**Files:**
- Create: `packages/protocol/src/tamforge_protocol/retention.py`
- Create: `packages/protocol/tests/test_retention.py`
- Create: `apps/backend/src/tamforge_backend/retention/policy.py`
- Create: `apps/backend/src/tamforge_backend/retention/service.py`
- Create: `apps/backend/src/tamforge_backend/retention/routes.py`
- Modify: `apps/backend/src/tamforge_backend/retention/models.py`
- Modify: `apps/backend/src/tamforge_backend/retention/repository.py`
- Create: `apps/backend/tests/unit/retention/test_policy.py`
- Create: `apps/backend/tests/unit/retention/test_service.py`
- Create: `apps/backend/tests/unit/retention/test_routes.py`
- Create: `apps/backend/tests/integration/retention/test_recoverable_deletion.py`
- Create: `apps/web/src/features/privacy/RetentionArchivePage.tsx`
- Create: `apps/web/src/features/privacy/DeletionPreviewDialog.tsx`
- Create: `apps/web/src/features/privacy/RetentionArchivePage.test.tsx`
- Create: `infra/toolchain.lock`
- Create: `infra/scripts/bootstrap/install-toolchain.sh`
- Create: `infra/scripts/backup/backup-database.sh`
- Create: `infra/scripts/backup/backup-config.sh`
- Create: `infra/scripts/backup/build-manifest.py`
- Create: `infra/scripts/backup/verify-manifest.py`
- Create: `infra/scripts/backup/restore-sample.sh`
- Create: `infra/scripts/backup/prune.sh`
- Create: `infra/systemd/tamforge-backup.service`
- Create: `infra/systemd/tamforge-backup.timer`
- Create: `infra/systemd/tamforge-restore-check.service`
- Create: `infra/systemd/tamforge-restore-check.timer`
- Create: `infra/tests/test_backup_scripts.py`
- Create: `docs/runbooks/data-retention-and-deletion.md`
- Create: `docs/runbooks/backup-restore.md`
- Modify: `packages/protocol/src/tamforge_protocol/__init__.py`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing retention/archive/deletion contracts and policy tests**

Define versioned retention policy, target scope/closure, preview hash, archive event, deletion request/item, recovery deadline, audit reason, and `Active -> Archived -> PendingDeletion -> Quarantined -> Restored|PurgeEligible -> Purged` contracts. Test reversible archive, exact dependency closure, no partial deletion of originals versus derivatives, real-interview separation, legal-hold/active-job refusal, duplicate/idempotent commands, stale preview refusal, and default preservation of original audio. The conservative v1 policy has no automatic application-data deletion, keeps archive reversible, and provides at least a 30-day recovery window after explicit deletion confirmation.

- [ ] **Step 2: Run retention tests and verify RED**

Run: `uv run pytest packages/protocol/tests/test_retention.py apps/backend/tests/unit/retention -q`

Expected: FAIL because retention contracts, policy, service, and routes are absent.

- [ ] **Step 3: Implement reversible archive and exact owner read/command APIs**

Add `GET /api/v1/retention/policy`, `GET /api/v1/archive`, `POST /api/v1/archive/preview`, `POST /api/v1/archive/commit`, and `POST /api/v1/archive/{archive_id}/restore`. Archive changes visibility only; it never deletes PostgreSQL rows or object versions. Preview returns the exact target/dependency closure and hash. Commit requires owner session, CSRF, optimistic version, unexpired matching preview, and audit reason. Restore reactivates the same permanent IDs and records another append-only event.

- [ ] **Step 4: Implement recoverable deletion before any purge**

Add `POST /api/v1/deletions/preview`, `POST /api/v1/deletions/{request_id}/confirm`, `GET /api/v1/deletions/{request_id}`, and `POST /api/v1/deletions/{request_id}/restore`. Confirmation transactionally tombstones the exact relational closure and marks catalogued object versions under a dedicated quarantine state/prefix; it does not physically erase bytes. Restore before the policy deadline reverses every tombstone/link and reuses the same IDs. Display that encrypted backups may retain data until their separate rotation expires. Final purge is disabled by default, operates only on the immutable request allowlist after the recovery deadline, and remains the separate destructive gate in Step 16.

- [ ] **Step 5: Write and implement the retention/archive UI RED then GREEN**

Run before implementation: `pnpm --dir apps/web exec vitest run src/features/privacy/RetentionArchivePage.test.tsx`

Expected: FAIL because the page/dialog do not exist. Implement policy disclosure, active/archived/quarantined lists, exact dependency/byte preview, real-interview warning, typed confirmation, recovery deadline, restore action, backup-retention disclosure, durable reload, and no ordinary Purge button. Rerun the command; expected PASS.

- [ ] **Step 6: Write failing backup-script tests using only fakes and temporary directories**

Fake `pg_dump`, `pg_restore`, `restic`, and clock commands through an injected test `PATH`. Test exact tool-version/checksum enforcement, fail-fast handling, restrictive permissions, atomic temporary/final names, checksum mismatch, partial upload, secret redaction, manifest inventory, backup-pruning boundaries, and refusal to call any real endpoint. Keep backup rotation tests distinct from application retention/deletion tests.

- [ ] **Step 7: Run backup tests and verify RED**

Run: `uv run pytest infra/tests/test_backup_scripts.py -q`

Expected: FAIL because the scripts do not exist. This command uses fakes only and must not touch Docker or the network.

- [ ] **Step 8: Pin the recovery toolchain and implement daily encrypted backup**

Use PostgreSQL 16 `pg_dump`/`pg_restore` plus one exact restic release. Record official artifact/version/SHA-256 data in `infra/toolchain.lock`; verify it idempotently before use. Create a consistent custom-format database dump, nonsecret configuration inventory, schema/Alembic version, object-catalog/version inventory, recovery metadata, sizes, hashes, tool versions, and the nonsecret export public trust bundle plus its independently rehashed fingerprint. Encrypt to the private off-host repository and publish the signed/hash manifest last. The private export signing key and recording-manifest HMAC keyring may be included only in the encrypted root-credential backup class with an independently held recovery key and an explicit restore procedure; neither enters a human-readable manifest.

`verify-manifest.py --emit-credential-receipt` may emit a strict, nonsecret receipt only after restoring and byte-hashing the named encrypted credential object. The receipt binds credential name, exact source SHA-256, restic repository/snapshot/object identity, backup-manifest SHA-256, host identity, tool version, and verification timestamp. It never embeds secret bytes. Plan 2's manifest bootstrap/rotation and Task 23's export-key bootstrap/rotation accept only this receipt schema through their verifier boundary and reject any unverified, stale, mismatched, or differently targeted receipt. Never print or embed Claude, database, object-store, session, recovery, or signing secrets.

- [ ] **Step 9: Configure backup rotation separately from learner-data retention**

Keep 7 daily, 5 weekly, and 12 monthly verified backup restore points. Enable object versioning for immutable source artifacts and backup manifests. Backup prune operates only on the fully resolved dedicated backup prefix and retains the newest valid restore point on malformed metadata. Application archive/deletion never invokes backup prune, and backup expiry never mutates canonical learner rows.

- [ ] **Step 10: Implement monthly sample and quarterly full restore procedures**

The timer may run a non-destructive monthly sample restore in an isolated database/temporary object prefix; verify schema, representative relationships, original audio hash, transcript/analysis lineage, memory revisions, retention/tombstone state, export/import manifest, and verification of a historical export using only the independently restored public trust bundle. The quarterly clean-environment drill records start/end, RPO/RTO, manifest, checks, deviations, and sign-off.

- [ ] **Step 11: Add systemd hardening, failure reporting, and offline-key procedure**

Run backup services under a dedicated least-privilege user with root-owned credentials, `UMask=0077`, `NoNewPrivileges`, `PrivateTmp`, restricted writable paths, bounded runtime, and the allowed processing-failure notification. A failed backup never deletes prior restore points. Keep at least one verified offline recovery-key copy and one export public-trust fingerprint outside the server/object account; document signing/trust rotation, clean-install trust provisioning, lost-key consequence, 24-hour database/configuration RPO, 24-hour whole-service RTO, and acknowledged-audio durability.

- [ ] **Step 12: Run safe unit, UI, and infrastructure verification**

Run: `uv run pytest packages/protocol/tests/test_retention.py apps/backend/tests/unit/retention infra/tests/test_backup_scripts.py -q && pnpm --dir apps/web exec vitest run src/features/privacy/RetentionArchivePage.test.tsx && pnpm --dir apps/web exec tsc --noEmit`

Expected: PASS with fakes only; no network, Docker, database, production data, or physical deletion.

- [ ] **Step 13: Prove transactional recoverability after the database gate**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration/retention/test_recoverable_deletion.py
```

Expected: PASS with marked tests collected and zero skips. Archive/restore and confirm/recover preserve exact IDs/hashes/relations; injected failures leave no partial tombstones; active processing/legal hold blocks deletion; cross-real-interview closure cannot leak; no physical purge occurs.

- [ ] **Step 14: Approve storage cost before provisioning**

`[PAID GATE]` Before creating/enabling a private backup bucket, object versioning, quarantine storage, or retained capacity, present the current monthly estimate and verify it stays within the approved cost boundary. Do not provision or raise a budget without explicit approval.

- [ ] **Step 15: Verify a production-like restore before relying on backups**

`[PRODUCTION-SAFE-WRITE + POSSIBLE DOCKER APPROVAL GATE]` Use an isolated target only, never the live database or live object prefix. Obtain explicit Docker approval first if the selected restore environment can start Docker/Compose/Testcontainers locally. A clean representative restore must pass all hashes/relationships and record RPO/RTO before backup status becomes `Verified`.

- [ ] **Step 16: Keep final physical purge behind a fresh destructive approval**

`[DESTRUCTIVE GATE]` After the recovery deadline, present the immutable deletion request/preview hash, exact database tombstones and object version IDs, dependency-closure proof, latest verified backup implications, and rollback limits. Require a fresh approval artifact tied to that exact allowlist immediately before purge. No wildcard, discovery-at-execution, expired approval, current original under retention, legal hold, or default timer may physically delete data.

- [ ] **Step 17: Commit**

```bash
git add packages/protocol/src/tamforge_protocol/retention.py packages/protocol/src/tamforge_protocol/__init__.py packages/protocol/tests/test_retention.py apps/backend/src/tamforge_backend/retention apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/retention apps/backend/tests/integration/retention apps/web/src/features/privacy infra/toolchain.lock infra/scripts/bootstrap/install-toolchain.sh infra/scripts/backup infra/systemd/tamforge-backup.service infra/systemd/tamforge-backup.timer infra/systemd/tamforge-restore-check.service infra/systemd/tamforge-restore-check.timer infra/tests/test_backup_scripts.py docs/runbooks/data-retention-and-deletion.md docs/runbooks/backup-restore.md
git commit -m "feat(portability): add recoverable deletion and verified backups"
```

### Task 25: Archive, restore-test, and explicitly gate retirement of Gastos

**Files:**
- Create: `infra/scripts/gastos/inventory.sh`
- Create: `infra/scripts/gastos/archive.sh`
- Create: `infra/scripts/gastos/verify-archive.py`
- Create: `infra/scripts/gastos/restore-isolated.sh`
- Create: `infra/scripts/gastos/decommission.sh`
- Create: `infra/tests/fixtures/gastos-inventory/`
- Create: `infra/tests/test_gastos_scripts.py`
- Create: `docs/runbooks/gastos-retirement.md`

- [ ] **Step 1: Write failing fixture-only safety tests**

Test exact-target allowlisting, required inventory sections, archive encryption/hash, partial archive rejection, isolated restore path validation, default dry-run, missing manifest/hash rejection, stale approval rejection, and unconditional exclusion of `lamas-prod`. Assert no fixture test can resolve `/`, a home directory, workspace root, live service path, or a wildcard as a destructive target.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest infra/tests/test_gastos_scripts.py -q`

Expected: FAIL because scripts are absent. Tests use fixtures/temporary directories only.

- [ ] **Step 3: Implement read-only inventory first**

Inventory the exact Gastos host and record OS/packages, running services, containers if present, named volumes, n8n, NocoDB, PostgreSQL databases/roles/extensions, Caddy configuration, cron/systemd schedules, application files, object/external dependencies, ports/DNS, sizes, and nonsecret environment-key names. Hash and timestamp the inventory; do not stop or mutate anything. Reject any resolved host/asset that belongs to Lamas.

- [ ] **Step 4: Implement encrypted archive creation and verification**

Archive Gastos application/configuration files, Caddy configuration, n8n/NocoDB state, PostgreSQL 16-compatible custom dumps, named-volume/file manifests, and required recovery metadata through the exact `infra/toolchain.lock` restic repository format. Exclude live secret values from human-readable manifests but preserve necessary encrypted recovery material. Finalize the tagged snapshot only after local hash verification, `restic check`, re-restore/sample verification, and independent retention of the archive manifest.

- [ ] **Step 5: Implement isolated restore proof**

Restore into a newly created isolated directory/database namespace with no production DNS and no outbound integrations. Verify database schema/row-count samples, n8n workflow inventory, NocoDB metadata, referenced files, Caddy syntax as text, and representative application startup/health without contacting customers. Record the exact archive hash and restore evidence.

- [ ] **Step 6: Make decommission default to a non-mutating plan**

`decommission.sh` must emit the exact services/containers/volumes/files/DNS entries it would touch and exit without mutation by default. Execution requires all of: matching host identity, matching verified archive manifest hash, successful isolated restore record, an unexpired separately supplied approval artifact tied to that hash/target list, and an explicit `--execute`. It must never accept globs or discover extra destructive targets at execution time.

- [ ] **Step 7: Run fixture verification**

Run: `uv run pytest infra/tests/test_gastos_scripts.py -q`

Expected: PASS; every destructive-path test fails closed and `lamas-prod` is untouched.

- [ ] **Step 8: Perform production inventory/archive/restore in gated phases**

The read-only inventory and encrypted archive phases may proceed only through the approved production-access procedure. If Docker/Compose is required on the Mac for the isolated restore, stop for the Docker gate. Do not repurpose or rename the server until the restore evidence is complete.

- [ ] **Step 9: Stop for the final destructive decision**

`[DESTRUCTIVE GATE]` Present the exact Gastos host identity, target allowlist, archive location/hash, verification results, isolated restore evidence, rollback procedure, and expected outage/data effect. Obtain explicit approval immediately before stopping/removing Gastos or changing its DNS/name. Prior approval to build TAM Forge is not approval for this final command.

- [ ] **Step 10: Commit**

```bash
git add infra/scripts/gastos infra/tests/fixtures/gastos-inventory infra/tests/test_gastos_scripts.py docs/runbooks/gastos-retirement.md
git commit -m "feat(ops): gate Gastos archival and retirement"
```

### Task 26: Provision and harden the post-Gastos Ubuntu 24.04 TAM Forge host

**Files:**
- Create: `infra/config/host-layout.env`
- Create: `infra/scripts/bootstrap/verify-target-host.sh`
- Create: `infra/scripts/bootstrap/provision-ubuntu-24.04.sh`
- Create: `infra/scripts/bootstrap/install-postgresql16-pgvector.sh`
- Create: `infra/scripts/bootstrap/create-service-layout.sh`
- Create: `infra/scripts/bootstrap/configure-firewall.sh`
- Create: `infra/scripts/bootstrap/verify-host.sh`
- Create: `infra/scripts/bootstrap/rollback-host-provision.sh`
- Create: `infra/systemd/tamforge-api.service`
- Create: `infra/systemd/tamforge-worker.service`
- Create: `infra/systemd/tamforge-speech-worker.service`
- Create: `infra/systemd/tamforge-claude-worker.service`
- Create: `infra/systemd/tamforge-embedding-worker.service`
- Create: `infra/caddy/Caddyfile`
- Create: `infra/scripts/deploy/preflight.sh`
- Create: `infra/scripts/deploy/install-release.sh`
- Create: `infra/scripts/deploy/verify-release.sh`
- Create: `infra/scripts/deploy/rollback-release.sh`
- Create: `infra/tests/fixtures/ubuntu-24.04-host/`
- Create: `infra/tests/test_host_provisioning.py`
- Create: `infra/tests/test_systemd_units.py`
- Create: `infra/tests/test_deploy_scripts.py`
- Create: `docs/runbooks/host-provisioning.md`
- Create: `docs/runbooks/production-release.md`
- Create: `docs/runbooks/security-incident.md`

- [ ] **Step 1: Write failing fixture-only host-provisioning tests**

With an injected fixture root and fake `PATH`, assert refusal unless `/etc/os-release` is exactly Ubuntu `24.04`, architecture is the approved x86_64 target, host ID/IP match the separately approved Gastos manifest, Gastos archive/isolated-restore/decommission evidence hashes match, and no resolved asset belongs to `lamas-prod`. Test `--check` versus `--apply`, package/version pins, repository-key fingerprints, PostgreSQL/pgvector/Caddy verification, service users/groups, exact directory modes, local-only database listening, firewall ordering, SSH preservation, no secret output, repeat-run idempotence, interrupted-step resume, and rollback from every checkpoint. Cover absent manifest/export keys through stage -> encrypted fake backup -> restored-hash receipt -> activation, crash before/after activation, preservation of existing keys, and refusal to enable a unit for pending/unbacked/mismatched credentials. No fixture test may call apt, systemctl, ufw, PostgreSQL, Caddy, network, Docker, or a real host.

- [ ] **Step 2: Write failing service/deployment tests**

Assert root-owned immutable release code, per-service credentials, no shared writable code directory, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, explicit writable state/cache/runtime paths, zero unnecessary capabilities, resource limits, bounded restart policy, log identifiers, and dependency ordering that leaves ingest/study available when Claude or transcription is degraded. Prove the general worker unit executes `tamforge_backend.workers.general`, that entrypoint registers `export.build.v1`, the general worker alone receives the export private signing credential, the API and general worker receive the public export trust bundle, the speech worker alone receives the recording-manifest HMAC keyring, and no other service can read those credentials. Test exact artifact checksums, Alembic single-head preflight, migration/health rollback, and refusal unless environment/host/release IDs match.

- [ ] **Step 3: Run tests and verify RED**

Run: `uv run pytest infra/tests/test_host_provisioning.py infra/tests/test_systemd_units.py infra/tests/test_deploy_scripts.py -q`

Expected: FAIL because the checked-in host contract, scripts, units, and deployment flow are absent.

- [ ] **Step 4: Freeze the exact post-Gastos target and idempotent execution contract**

`host-layout.env` contains no secrets; it records expected Ubuntu release/architecture, approved host ID/name/IP, public application hostname, approved SSH source CIDR, package/version constraints, Unix identities, ports, paths, and per-service CPU/RAM/open-file/task budgets derived from the Task 25 observed host inventory. Tests require the aggregate reservation to leave an explicit PostgreSQL/Caddy/OS safety reserve. Every bootstrap script supports `--check` (default, read-only) and `--apply`; writes a root-only checkpoint/rollback manifest; uses an exact allowlist; performs atomic config replacement after syntax validation; and is safe to rerun. It must refuse a host still running any Gastos workload, any host/name/IP mismatch, and every Lamas host. Production uses native systemd services, not Docker.

- [ ] **Step 5: Provision Ubuntu 24.04 packages, PostgreSQL 16 + pgvector, and Caddy explicitly**

Verify signed official Ubuntu/PostgreSQL/Caddy repository metadata and pinned supported package versions before installation; record resolved versions in the provisioning manifest. Install only the required runtime/administration packages, PostgreSQL 16 server/client, the matching pgvector extension package, Caddy, UFW, and the pinned TAM Forge toolchain. Initialize one PostgreSQL 16 cluster, create database `tamforge`, enable `vector`, and create separate non-superuser roles `tamforge_app`, `tamforge_migrator`, and `tamforge_backup` with least privilege; require SCRAM credentials from root-owned files and bind PostgreSQL only to loopback/local socket. Validate `server_version`, extension version, `pg_hba.conf`, each role's positive/negative privileges, and a least-privilege connection; never expose port 5432.

- [ ] **Step 6: Create exact service users, groups, directories, and permissions**

Create locked no-login/no-home users `tamforge-api`, `tamforge-worker`, `tamforge-speech`, `tamforge-claude`, `tamforge-embedding`, and `tamforge-backup` plus the narrow `tamforge` shared-data group. Create `/opt/tamforge/releases` and root-owned `/opt/tamforge/current` (`root:tamforge`, `0750`); `/etc/tamforge` (`root:tamforge`, `0750`) with private environment/credential files `root:<owning-service>`, `0640`, root source secrets under `/etc/tamforge/secrets` (`0700`/`0600`), and the nonsecret public export trust bundle under `/etc/tamforge/trust` (`0755`/`0644`) with its recorded fingerprint; per-service state under `/var/lib/tamforge/{api,worker,speech,claude,embedding}` (`0750`); shared non-code data `/var/lib/tamforge/shared` (`root:tamforge`, setgid `2770`); `/var/lib/tamforge/backup` (`tamforge-backup`, `0700`); `/var/lib/tamforge/quarantine` (`tamforge-api`, `0700`); and model caches `/var/cache/tamforge/{speech,embeddings}` (`0750`). Runtime directories come from systemd `RuntimeDirectory` with `0750`. No service can read the Claude token except `tamforge-claude`; only `tamforge-worker` receives the export private key; only `tamforge-speech` receives the recording-manifest HMAC keyring; and no service can modify release code, another service's credentials, or backup keys.

- [ ] **Step 7: Configure Caddy, firewall, and external boundary without losing SSH**

Render and validate Caddy before reload; terminate TLS; proxy owner-authenticated HTTP, WSS, and SSE to loopback; preserve streaming timeouts; apply secure headers and bounded upload/path limits; redact sensitive headers/query values; and protect operational routes. Snapshot current UFW state, add verified allow rules for only approved SSH plus TCP 80/443, explicitly deny database/application loopback ports externally, verify the current SSH path remains allowed, then enable/reload atomically. Record a manual Hetzner-firewall verification checklist; scripts must not assume the provider firewall already matches.

- [ ] **Step 8: Install hardened systemd units and resource budgets**

Run API, general, speech, Claude, and embedding workers separately with the exact identities/paths above. The general worker's `ExecStart` invokes the tested `python -m tamforge_backend.workers.general` entrypoint from the immutable current release; unit tests prove that this process registers and claims `export.build.v1`. Allow at most one general export build, one transcription, and one Claude job; prioritize ingest; set explicit memory/CPU/open-file/task limits appropriate to the CX23; keep credentials per service; and use hardening directives verified by tests.

Before any credential-bearing unit is enabled, freeze unique initial manifest/export key IDs in the approved nonsecret host manifest. If the recording-manifest source keyring is absent, run Plan 2's bootstrap `--stage`, back up and restore-verify the exact pending keyring with Task 24's pinned tooling, emit the bound credential receipt, then run `--activate --backup-receipt`; existing final/pending state causes a stop, never a second key. If the export signing source/trust files are absent, perform the same stage, encrypted backup/restore verification, receipt-bound activation, and public-fingerprint check with Task 23's bootstrap. Existing keys are verified and preserved; provisioning never rotates them implicitly. Run one synthetic recording-manifest sign/verify and one synthetic export sign/verify before unit activation, and retain only content-safe key IDs/fingerprints/receipt hashes as evidence.

The general worker unit maps `LoadCredential=export-signing-private.json:/etc/tamforge/secrets/export-signing-private.json` and `LoadCredential=export-signing-public.json:/etc/tamforge/trust/export-signing-public.json`; the API maps only the public trust credential; the speech worker maps only Plan 2's recording-manifest keyring. The application resolves every production credential only beneath `CREDENTIALS_DIRECTORY` and fails the affected capability closed. A clean-install import is unavailable until the independently fingerprint-verified historical public trust bundle is provisioned; it never trusts a key from an uploaded archive. `daemon-reload` and enablement happen only after all units pass `systemd-analyze verify`; application services remain stopped/disabled until a release is installed and the activation gate passes.

- [ ] **Step 9: Implement immutable release, migration, verification, and bounded rollback**

Preflight verifies host manifest/checkpoint, disk/RAM, PostgreSQL/pgvector, object access, backup freshness, Alembic graph, config schema, owner, firewall/Caddy, directory permissions, and service versions. Install a checksum-verified artifact to `/opt/tamforge/releases/<release-id>`, migrate once under a lock with the migration role, atomically switch `current`, start in dependency order, and verify owner/auth/ingest/job endpoints. Release rollback switches to the prior compatible artifact but never downgrades the database automatically. Host-provision rollback restores captured config/firewall/unit state and disables TAM Forge services; it never deletes PostgreSQL data, uninstall packages blindly, remove the Gastos archive, or touch Lamas.

- [ ] **Step 10: Run static/idempotency verification**

Run: `uv run pytest infra/tests/test_host_provisioning.py infra/tests/test_systemd_units.py infra/tests/test_deploy_scripts.py -q`

Expected: PASS with fake commands/filesystems only. A second apply reports zero changes; each injected interruption resumes or rolls back to the recorded checkpoint; no network or production write occurs.

- [ ] **Step 11: Obtain the final host-repurpose approval immediately before provisioning**

`[DESTRUCTIVE GATE]` Present the exact Gastos host ID/name/IP, completed archive hash, independent restore evidence, completed Gastos decommission result, Ubuntu 24.04/x86_64 check, planned users/packages/ports/directories/firewall changes, checkpoint/rollback location, expected outage, and explicit statement that `lamas-prod` is excluded. Obtain a fresh approval artifact bound to that manifest immediately before the first `--apply`. Earlier approval to design TAM Forge or retire Gastos is not approval to provision the host.

- [ ] **Step 12: Provision in gated checkpoints and verify before application activation**

Run `verify-target-host.sh --check`, then each `--apply` bootstrap stage and `verify-host.sh` only through the approved production-access procedure. Stop on any drift; do not guess an existing package, database, firewall, user, directory, or permission. Capture before/after manifests and prove PostgreSQL+pgvector, Caddy config, firewall, service identities, filesystem permissions, and rollback procedure before installing an application release.

- [ ] **Step 13: Pass application activation gates**

`[AUTH/POLICY + PRIVACY + PAID + MERGE/DEPLOY GATES]` Require exact-head CI/review, current subscription compatibility, disabled Claude model-improvement attestation, approved object/quarantine/backup cost, fresh verified backup, host verification, and explicit production activation. Use synthetic smoke evidence, confirm real recording WSS durability, keep Claude disabled until its own policy/privacy checks pass, and capture commit, migration head, installed package/extension versions, units, firewall, and observed health. A successful merge or provision is not deployment evidence.

- [ ] **Step 14: Commit**

```bash
git add infra/config/host-layout.env infra/scripts/bootstrap infra/systemd/tamforge-api.service infra/systemd/tamforge-worker.service infra/systemd/tamforge-speech-worker.service infra/systemd/tamforge-claude-worker.service infra/systemd/tamforge-embedding-worker.service infra/caddy/Caddyfile infra/scripts/deploy infra/tests/fixtures/ubuntu-24.04-host infra/tests/test_host_provisioning.py infra/tests/test_systemd_units.py infra/tests/test_deploy_scripts.py docs/runbooks/host-provisioning.md docs/runbooks/production-release.md docs/runbooks/security-incident.md
git commit -m "feat(ops): provision hardened Ubuntu TAM Forge host"
```

### Task 27: Add content-safe observability, health, and actionable notifications

**Files:**
- Create: `apps/backend/src/tamforge_backend/observability/logging.py`
- Create: `apps/backend/src/tamforge_backend/observability/metrics.py`
- Create: `apps/backend/src/tamforge_backend/observability/health.py`
- Create: `apps/backend/src/tamforge_backend/observability/routes.py`
- Modify: `apps/backend/src/tamforge_backend/notifications/policy.py`
- Create: `apps/backend/tests/unit/observability/test_logging.py`
- Create: `apps/backend/tests/unit/observability/test_metrics.py`
- Create: `apps/backend/tests/unit/observability/test_health.py`
- Modify: `apps/backend/tests/unit/notifications/test_policy.py`
- Create: `apps/backend/tests/security/test_log_redaction.py`
- Create: `docs/runbooks/quota-and-worker-outages.md`
- Modify: `apps/backend/src/tamforge_backend/api.py`

- [ ] **Step 1: Write failing log-redaction tests**

Inject OAuth tokens, API-key-shaped values, cookies, transcript phrases, real-interview names, signed URLs, model payloads, SQL text, and object keys into exceptions/requests. Assert structured logs retain only request/job/evidence IDs, state, category, duration, sizes, versions, and redacted error codes.

- [ ] **Step 2: Write failing metrics and health tests**

Cover ingest ACK latency/failure, queue depth/age, job duration/status/error category, speech and FeedbackReady deadlines, 15/60-minute active composite outcomes, separate wall/active/suspension durations and reason codes, overdue unresolved runs, Claude quota/auth state, backup age/verification, disk/RAM, export/import integrity, recoverable-deletion state, interviewer follow-up latency, and allowed notification counts. A quota/service suspension and speech-stage miss must remain failure/NeedsAttention signals rather than an on-time sample. No metric label may contain user text, company, prompt, transcript, object key, or unbounded ID cardinality.

- [ ] **Step 3: Run tests and verify RED**

Run: `uv run pytest apps/backend/tests/unit/observability apps/backend/tests/unit/notifications apps/backend/tests/security/test_log_redaction.py -q`

Expected: FAIL because observability policies are absent.

- [ ] **Step 4: Implement safe event/log construction**

Use allowlisted structured fields rather than post-hoc regex alone. Correlate by opaque IDs, hash only where operationally necessary, bound error text, and keep detailed sensitive diagnostics in audited application records with owner authorization—not journal or metrics.

- [ ] **Step 5: Implement component-aware health**

Separate liveness from readiness/degradation. Database or ingest-durability failure may make the service unready; Claude quota/auth or transcription failure marks only that capability `degraded/NeedsAttention` while independent study remains ready. Surface backup staleness and disk pressure before data loss. Do not restart-loop on quota exhaustion.

- [ ] **Step 6: Enforce notification allowlist**

Permit only AI feedback ready, correction due, upcoming real interview, Saturday assessment, and processing failure requiring action. Suppress duplicates, streak/engagement prompts, and every Sunday study reminder. Background Sunday processing may run without study prompts.

- [ ] **Step 7: Run verification**

Run: `uv run pytest apps/backend/tests/unit/observability apps/backend/tests/unit/notifications apps/backend/tests/security/test_log_redaction.py -q`

Expected: PASS; secret/content leakage count is zero.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/tamforge_backend/observability apps/backend/src/tamforge_backend/notifications apps/backend/src/tamforge_backend/api.py apps/backend/tests/unit/observability apps/backend/tests/unit/notifications apps/backend/tests/security/test_log_redaction.py docs/runbooks/quota-and-worker-outages.md
git commit -m "feat(ops): add private operational observability"
```

### Task 28: Build deterministic CI and the AI/memory evaluation harness

**Files:**
- Create: `apps/backend/src/tamforge_backend/evals/cases.py`
- Create: `apps/backend/src/tamforge_backend/evals/runner.py`
- Create: `apps/backend/src/tamforge_backend/evals/scoring.py`
- Create: `apps/backend/src/tamforge_backend/evals/feedback_slo.py`
- Create: `apps/backend/tests/evals/test_role_invariants.py`
- Create: `apps/backend/tests/evals/test_rubric_agreement.py`
- Create: `apps/backend/tests/evals/test_memory_retrieval.py`
- Create: `apps/backend/tests/evals/test_prompt_injection.py`
- Create: `apps/backend/tests/evals/test_feedback_ready_slo.py`
- Create: `apps/backend/tests/fixtures/evals/synthetic-agent-cases.json`
- Create: `apps/backend/tests/fixtures/evals/memory-cases.json`
- Create: `apps/backend/tests/fixtures/evals/feedback-ready-runs.json`
- Create: `scripts/benchmark-feedback-ready.py`
- Create: `scripts/verify-plan-03.sh`
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/evals.yml`
- Create: `docs/runbooks/ai-evaluation.md`

- [ ] **Step 1: Write failing threshold tests**

Require 100% exactly-two strength/correction and prohibited-answer invariants; 100% valid material evidence/timestamps; zero high-severity unsupported claims; at least 85% rubric dimensions within one point of adjudicated human scores; weighted agreement at least 0.60; required memory recall at least 95%; top-k relevance at least 90%; and zero Interviewer/sensitive leakage across the complete seeded set. Add deterministic FeedbackReady cases at, below, and above the 15-minute practice and 60-minute mock/real boundaries; speech-stage failure; unresolved overdue work; every allowed suspension; quota/service recovery; duplicate completion; and invalid/missing clock data.

- [ ] **Step 2: Run eval tests and verify RED**

Run: `uv run pytest apps/backend/tests/evals -q`

Expected: FAIL because the eval runner/scorers and FeedbackReady benchmark are absent.

- [ ] **Step 3: Implement versioned, reproducible eval inputs**

Use synthetic/anonymized text fixtures in Git. Store fixture hash, evaluator version, prompt/rubric/model/schema versions, selected evidence, and raw structured result. The private 20–30 item speech/TAM/ESL gold set remains outside Git in protected storage; Git contains only its encrypted-object manifest/reference and loaders that fail closed when unavailable.

- [ ] **Step 4: Implement deterministic and adjudicated scoring**

Keep code-enforced invariants separate from subjective agreement. Report per-role failures, unsupported claim severity, citation validity, agreement/confusion, retrieval inclusion/exclusion, sensitivity leakage, and regression against the last accepted baseline. A newer model/prompt/rubric is not promoted merely because average prose quality appears better.

- [ ] **Step 5: Implement an executable, content-safe FeedbackReady benchmark**

`feedback_slo.py` accepts normalized rows from either the versioned fixture or a read-only query of Plan 2's `processing_runs`/`processing_suspensions` joined to the published analysis ID. `scripts/benchmark-feedback-ready.py` validates eligibility mode, `speech_ready_at`, `feedback_ready_at`, active/wall/suspended arithmetic, speech sub-budget, publication linkage, target, and suspension outcome; it emits schema-versioned JSON containing only opaque run IDs, mode, durations, reason codes, sample counts, threshold, result, commit/migration/config hashes, and input hash. It exits nonzero on malformed/missing rows, zero qualifying samples, any active practice over 900 seconds, any active mock/real run over 3,600 seconds, any overdue unresolved run, any speech-stage miss labeled pass, or any quota/service-suspended run labeled on-time. Awaiting-debrief/redaction exclusion remains visible. It never outputs transcript, prompt, company, or user text.

- [ ] **Step 6: Create a safe root verification script**

Run protocol/backend unit, security, eval, Ruff, mypy, web Vitest/typecheck/build, and static infrastructure tests. The script must exclude every Docker/Testcontainers/integration selector by default and print the separate `TEST_DATABASE_URL=... bash scripts/run-plan-03-integration.sh apps/backend/tests/integration` gated command rather than invoking it. It must report integration as `NOT RUN`, never PASS, when no zero-skip runner artifact is supplied.

- [ ] **Step 7: Configure CI with isolated PostgreSQL/pgvector**

Pin every third-party GitHub Action to a reviewed commit SHA. Split fast Python/web/static jobs from PostgreSQL integration and eval jobs. CI's integration job must set its isolated `TEST_DATABASE_URL` and call `scripts/run-plan-03-integration.sh`; direct pytest integration invocation or a skipped test fails the job. CI may use an isolated PostgreSQL 16 + pgvector service; it must not contain the Claude OAuth token, make live Claude calls, upload private transcripts/audio, deploy, or mutate production. Store test/eval/FeedbackReady JSON artifacts with bounded retention and no sensitive payloads.

- [ ] **Step 8: Keep full private/live evals out of automatic CI**

Run full private gold-set evaluation on the protected host through a manual, audited procedure. Live Claude compatibility/model checks run only on the host with its secret and current policy/privacy gates. Do not add that secret to GitHub Actions. If private-repo Actions billing is unavailable, report `ci_missing`; never enable paid minutes/budget without approval.

- [ ] **Step 9: Run safe verification and the synthetic FeedbackReady benchmark**

Run:

```bash
uv run pytest apps/backend/tests/evals -q
uv run python scripts/benchmark-feedback-ready.py \
  --fixture apps/backend/tests/fixtures/evals/feedback-ready-runs.json \
  --output build/plan-03-feedback-ready-synthetic.json
bash scripts/verify-plan-03.sh
```

Expected: PASS without Docker, network, live models, or private evidence. The benchmark artifact proves exact 900/3,600-second arithmetic and fail-closed suspension/malformed-data behavior over the complete synthetic fixture; it is labeled synthetic, not observed production evidence.

- [ ] **Step 10: Run full integration only after Docker approval when local**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]`

Run after approval:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  bash scripts/run-plan-03-integration.sh apps/backend/tests/integration
```

Expected: PASS against PostgreSQL/pgvector/object-store fakes with `collected > 0, skipped = 0`. Prefer CI's isolated service if local RAM is constrained.

- [ ] **Step 11: Commit**

```bash
git add apps/backend/src/tamforge_backend/evals apps/backend/tests/evals apps/backend/tests/fixtures/evals scripts/benchmark-feedback-ready.py scripts/verify-plan-03.sh .github/workflows/ci.yml .github/workflows/evals.yml docs/runbooks/ai-evaluation.md
git commit -m "test: add agent memory and privacy quality gates"
```

### Task 29: Prove the integrated learning, privacy, portability, and recovery journey

**Files:**
- Create: `apps/web/e2e/agents-memory.spec.ts`
- Create: `apps/web/e2e/attempt-correction.spec.ts`
- Create: `apps/web/e2e/interviewer.spec.ts`
- Create: `apps/web/e2e/real-interview.spec.ts`
- Create: `apps/web/e2e/opportunity-reports-export.spec.ts`
- Create: `apps/web/e2e/portability-retention.spec.ts`
- Create: `apps/backend/tests/acceptance/test_plan_03_acceptance.py`
- Create: `scripts/collect-plan-03-release-evidence.sh`
- Create: `docs/release-evidence/plan-03-template.md`
- Modify: `docs/runbooks/production-release.md`

- [ ] **Step 1: Write failing browser journeys against fakes**

Cover persistent Planner/Tutor/Analyst threads and provenance; unsaved Coach content; locked Attempt A; mandatory self-review; feedback `processing -> ready` and full-page reload through the exact read API; exactly two visible corrections with evidence; next-lesson Attempt B launch/commit/comparison and no Attempt C; isolated two-follow-up Interviewer; real-interview permission/debrief/redaction; opportunity context; and inspectable readiness. Prove complete verified export, download/upload, mutation-free import dry run, explicit conflict handling, transactional/idempotent restore status, reversible archive, exact deletion preview, recoverable deletion/restore after reload, absence of an ordinary purge control, and quota failure that leaves independent study available.

- [ ] **Step 2: Write failing backend acceptance invariants**

Assert no original audio/model input edge, no feedback before self-review, no real-interview model run without the exact approved redaction hash, no forbidden memory context, no nonqualifying readiness change, no unverified export/import/backup success, no partial import/deletion transaction, no physical purge without an exact approval artifact, and no paid-provider fallback configuration. Assert published feedback and `processing_runs.feedback_ready_at` commit atomically; clock start/mode and allowed suspensions match Plan 2; 15/60-minute boundaries are exact; speech/quota/service misses cannot be labeled on-time; and the feedback-ready notification is idempotent.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `uv run pytest apps/backend/tests/acceptance/test_plan_03_acceptance.py -q`

Expected: FAIL until all prior tasks are integrated.

- [ ] **Step 4: Wire routes, outbox handlers, UI navigation, and fake services minimally**

Connect only the public contracts produced by Plans 1–3, including feedback/correction read routes, Attempt B commands, import status, and retention/archive routes. Keep fake Claude/local speech/object storage deterministic for browser acceptance; do not introduce environment-specific branches into domain services.

- [ ] **Step 5: Run safe backend acceptance**

Run: `uv run pytest apps/backend/tests/acceptance/test_plan_03_acceptance.py -q`

Expected: PASS with fakes and no Docker/network/private data.

- [ ] **Step 6: Run browser acceptance only after its local service gate**

If the selected E2E harness starts Docker, Testcontainers, or Compose, `[DOCKER APPROVAL REQUIRED LOCALLY]`; otherwise document that the command uses only already-running test processes.

Run after the applicable approval/preconditions: `pnpm --dir apps/web exec playwright test e2e/agents-memory.spec.ts e2e/attempt-correction.spec.ts e2e/interviewer.spec.ts e2e/real-interview.spec.ts e2e/opportunity-reports-export.spec.ts e2e/portability-retention.spec.ts`

Expected: PASS using synthetic fixtures and fake Claude. Refreshes reconstruct feedback, corrections, comparison, import, archive, and deletion state from backend reads; no real interview/audio/token is loaded and no purge occurs.

- [ ] **Step 7: Execute and retain database-backed FeedbackReady benchmark evidence**

`[DOCKER APPROVAL REQUIRED LOCALLY; CI POSTGRESQL SERVICE ALLOWED]` Populate the approved synthetic production-like timing fixture through the integration setup, then query the shared ledger read-only:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  uv run python scripts/benchmark-feedback-ready.py \
    --database-url-env TEST_DATABASE_URL \
    --fixture-label production-like \
    --output build/plan-03-feedback-ready-database.json
```

Expected: exit 0 with at least one passing boundary/near-boundary sample for practice, mock, and real modes; explicit failing control cases rejected; every row resolves to durable speech/analysis/version IDs; and no private content appears. Hash and retain the JSON with exact-head evidence. Later observed production runs are reported in a separate artifact and never relabeled as benchmark fixtures.

- [ ] **Step 8: Collect exact-head release evidence**

Record commit SHA, migration head, unit/integration zero-skip summary, eval/E2E results, security checks, subscription compatibility timestamp/model, privacy attestations, synthetic and database-backed FeedbackReady benchmark hashes/results/sample modes, any separate observed 15/60-minute result, Interviewer p95, memory recall/relevance/leakage, report reproducibility, export-to-import restore proof, retention/archive/recoverable-deletion proof, latest backup hash/date, monthly restore evidence, Gastos archive/restore/decommission and post-Gastos host-provision manifests, rollback verification, deployed service versions, and every disabled/experimental feature. The script gathers evidence; a human/agent must review it rather than treating script exit 0 as proof of production behavior.

- [ ] **Step 9: Stop on every unresolved acceptance gate**

Do not label decision-grade any metric whose eval gate failed. Leave pronunciation, Interviewer follow-ups, or Claude processing explicitly unavailable/experimental when their applicable production gates fail. Do not hide late, overdue, speech-stage, quota, service, or suspended runs from timing reports. A skipped integration, fixture-only timing artifact, untested import conflict, missing recovery proof, or unverified host checkpoint cannot be called production-ready. Do not buy external compute or change privacy architecture automatically.

- [ ] **Step 10: Run final safe verification**

Run: `bash scripts/verify-plan-03.sh`

Expected: PASS; the script reports integration/E2E/production drills separately when they were not run.

- [ ] **Step 11: Commit**

```bash
git add apps/web/e2e apps/backend/tests/acceptance/test_plan_03_acceptance.py scripts/collect-plan-03-release-evidence.sh docs/release-evidence/plan-03-template.md docs/runbooks/production-release.md
git commit -m "test: prove integrated learning and recovery journeys"
```

- [ ] **Step 12: Push and open the exact stacked draft PR**

```bash
test "$(git branch --show-current)" = "feat/agents-interviews-operations"
git status --short
git push -u origin feat/agents-interviews-operations
gh pr create --repo fgomensoro/tam-forge \
  --draft \
  --base feat/recording-speech \
  --head feat/agents-interviews-operations \
  --title "Agents: memory, interviews, portability, and operations" \
  --body-file .github/pull_request_body.md
```

Expected: the worktree is clean, the PR is draft, its base/head are exact, and its body records the Plan 2 prerequisite SHA plus linked issue keys. Verify the final head, required CI, review, and three-dot file diff. Stop for explicit merge approval; do not merge, force-push, or delete either branch.

## Execution order and release checkpoints

1. **Agent/runtime foundation:** Tasks 1–7. Keep Claude disabled until the current subscription/auth and privacy gates pass; all tests use fakes.
2. **Closed learning loop and memory:** Tasks 8–14. Do not promote memory or readiness until evidence, retrieval, isolation, and correction invariants pass.
3. **Interviews and opportunities:** Tasks 15–18. Practice Interviewer and real-interview processing remain separately gated.
4. **Post-MVP specialized workspaces:** Tasks 19–21. The universal workspace remains the fallback and launch path; specialized SQL execution is not an MVP blocker.
5. **Analytics and portability:** Tasks 22–23. Calculations and exports must be reproducible and independently verifiable.
6. **Operations:** Tasks 24–27. Finish backup/archive/restore evidence before any Gastos destruction or TAM Forge production cutover.
7. **Quality and release proof:** Tasks 28–29. Bind review, CI, eval, deployment, and observed production results to the exact final commit.

At every checkpoint, preserve partial work and truthfully mark unavailable/degraded states. Proceed autonomously through safe implementation and verification, but stop for the explicit privacy, auth/policy, paid, Docker, destructive, merge, and deployment decisions listed above.
