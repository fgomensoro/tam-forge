# Model provenance implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete issue53 with immutable hash-addressed registries and exact invocation/evidence history.
**Architecture:** One cohesive persistence aggregate: content registries, existing rubric hash binding, frozen run+context header, append-only lifecycle/tool events. Existing activity, attempt and job systems remain authoritative.
**Tech Stack:** Python/Pydantic/SQLAlchemy/Alembic/PostgreSQL16/pytest.
**Spec:** docs/superpowers/specs/2026-09-04-model-provenance.md

## Global Constraints

- No model execution, scoring publication, new rubric weights, recording/audio/auth/recovery/native UI changes, or production operations.
- Initial context profile is committed-attempt-text-v1 only; verify exact immutable committed learner text, never task prompts or external artifacts.
- Prompt/schema max1MiB, manifest max256KiB and1..64contexts, audit max16KiB, event/run max256KiB, SHA25632bytes.
- No local DB/Docker/Compose/Xcode/hardware/provider calls. Actual persistence validation is isolated CI only.
- Reuse existing ORM metadata, rubric definitions, owner IDs, activity/attempt FKs and BackgroundJob.
- All7exactheadCIchecks and independent review before authorized merge.

### Task 1: Persist and verify the provenance aggregate

**Files:**
Create agents/__init__.py, agents/contracts.py, agents/hashing.py, agents/models.py, agents/prompt_registry.py, agents/model_runs.py under apps/backend/src/tamforge_backend; create testing/plan03_integration_gate.py and testing/__init__.py; create apps/backend/alembic/versions/20260905_0015_model_provenance.py; register agents.models in models/__init__.py. Create unit/agents/test_prompt_registry.py, test_model_runs.py, unit/testing/test_plan03_integration_gate.py and integration/agents/test_agent_runtime_migration.py (plus necessary __init__.py). Create scripts/run-plan-03-integration.sh. Update pyproject.toml marker and .github/workflows/ci.yml backend integration step; update unit/roadmaps/test_curriculum_schema.py current head. Create docs/runbooks/model-provenance.md. Tests may be split into focused test modules in same owned directories if readability requires.

**Interfaces:** PromptRegistry(session) publishes/looks up owner-scoped exact prompt/schema content and binds existing rubrics; ModelRunRepository(session) registers idempotent invocation+context, appends expected-state/sequence lifecycle and tool records, reads owner/hash-addressed complete records. Closed typed errors, no raw diagnostics/content leakage. Contracts and precise method signatures live in these owned files; no external consumer is changed by this ticket.

- [ ] Write focused failing contracts/canonicalization/registry/lifecycle/gate tests using real validators and external session/process doubles only where needed. Test original request replay/conflict, exact UTF8 identity, finite canonical JSON, safe field allowlists, range/pointer/source mismatch, terminal-state/tool ordering. No tests that only check mocked calls.

```python
async def test_published_prompt_cannot_be_replaced(prompt_registry):
    first = await prompt_registry.publish_prompt(owner_id=1, key="reviewer", version="v1", content="prompt A")
    with pytest.raises(ImmutableVersionConflict):
        await prompt_registry.publish_prompt(owner_id=1, key="reviewer", version="v1", content="prompt B")
    assert first.content_hash == sha256(b"prompt A").digest()
```

- [ ] Run focused unit command with PYTHONPATH=apps/backend/src:packages/protocol/src and uv run python -m pytest; observe absent implementation failing.
- [ ] Implement smallest complete registry/run/context/event/tool aggregate with explicit canonical envelopes and source checks from spec. Use real transactions and same owner/activity locking boundary. Add SQL digest/reference checks and append-only UPDATE/DELETE/TRUNCATE guards, including directSQL attempts and deferred context sealing. Hash-bind existing rubric definitions after validating release parity; no seeded fake production rubric.
- [ ] Implement Plan03 script/plugin. Explicit test_database_url boundary, strict selection and counts. Tests simulate pytest collection/report/exit and process boundary, never start local services. CI invocation uses existing service and both integration markers.
- [ ] Add actual PG integration cases: valid publish/register/read/replay, committed learner pointer/range/hash identity, owner/attempt/rubric/config mismatch, raw SQL forged hashes and refs, UPDATE/DELETE/TRUNCATE, added context, concurrent duplicate invocation/event conflicts, tool pending/success/failure, terminal state refusal, migration downgrade/upgrade isolation. Seed activity/attempt using existing lawful lifecycle fixtures; use established isolated DROP/CREATEpublic teardown when evolved evidence prevents historical downgrade. Do not weaken production guards.
- [ ] Run focused/local fullunit once, Ruff/mypy, OpenAPI unchanged, Alembichead/metadata, gate unit tests and integration collection without DB. Commit only owned files; report full commands/output and pendingCI truthfully.
- [ ] Single task review followed by final branch review per SDD; no intermediate CI pushes. After approved code, root pushes once and runs required realCI, fixes concrete failures only, then merges/validatesissueclosed.
