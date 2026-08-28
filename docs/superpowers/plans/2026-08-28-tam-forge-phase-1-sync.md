# TAM Forge Phase 1 Six-Week Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import, activate, and run the approved six-week Phase 1 roadmap in TAM Forge without changing historical Month 1 configuration, evidence, or the fourteen numerical competency targets.

**Architecture:** Treat the six-week plan as a roadmap-only schema-v2 release layered over the unchanged `seed-v1` fourteen-competency scoring release. Normalize Phase 1 metadata, lineage, coverage ownership, per-question interview state, calendar budgets, the six English dimensions, the multi-action pipeline contract, and Week 7 into immutable roadmap payloads; pin every staged import to the exact roadmap release that validated it; and consume the canonical Obsidian `phase-1-transition-v1` JSON and sidecar byte-for-byte without a second envelope, redaction pass, or hand-authored translation. Persist one owner-scoped phase run plus append-only progress, pipeline-stage, and English-dimension records; update coverage, queue position, and weekly publications through one transaction-scoped progress service. Scheduling, Today, evidence labels, and activation behavior derive from the active roadmap version rather than global Month 1 constants. Keep the existing database/API field names `month`, `month_number`, `month_one_target`, and `month_one_target_gap` as compatibility fields.

**Tech Stack:** Python 3.12, Pydantic 2, JSON Schema Draft 2020-12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pytest/Hypothesis, React 19, TypeScript, TanStack Query, Vitest/Playwright, OpenAPI TypeScript, YAML, Obsidian Markdown roadmap packages.

---

## Preconditions and immutable boundaries

- This plan starts only after `docs/superpowers/plans/2026-08-28-tam-phase-1-obsidian-roadmap.md` has been implemented and its vault validation has passed. The validated Obsidian `Roadmap/` folder is the package source; do not reconstruct curriculum prose in TAM Forge.
- The prerequisite Obsidian implementation also produces a live, machine-readable transition export at vault-root `Exports/phase-1-transition-v1.json`, its producer schema `Exports/phase-1-transition-v1.schema.json`, and its sidecar `Exports/phase-1-transition-v1.json.sha256`. They sit **outside** `Roadmap/`: the roadmap ZIP remains Markdown/SQL-only and must exclude `Exports/`.
- TAM Forge consumes that raw producer contract exactly. The root keys are `$schema`, `schema_version`, `export_version`, `roadmap_version`, `mapping_version`, `activation_cutoff`, `schema_sha256`, `source_hashes`, `transition`, `coverage`, `interview_queue`, `weekday_sessions`, `saturday_sessions`, `resources`, `exit_criteria`, and `next_phase_priorities`. The JSON Schema has `additionalProperties: false`; the consumer must reject a missing, extra, renamed, or transformed root field. Never create a second transition envelope, normalize it into another JSON shape, redact and rehash a parallel copy, or hand-maintain a TAM Forge translation.
- Pin the approved v1 producer schema byte-for-byte as a TAM Forge runtime resource. Every live import or refresh must compare the supplied schema bytes and SHA-256 with that pinned resource before payload validation. A changed schema under `export_version: phase-1-transition-v1` is rejected even when the supplied JSON's `schema_sha256` matches the changed file.
- Use the approved design at `docs/superpowers/specs/2026-08-28-tam-study-phase-1-six-week-redesign.md` as the behavioral source.
- Preserve these checked-in legacy files byte-for-byte:

  | File | Required SHA-256 |
  |---|---|
  | `config/tam-skills.yaml` | `6008a4b157272d3cb62685b647f1cf3dfd889dd79014a40cc9cd86083ea4fecf` |
  | `config/tam-exercise-types.yaml` | `e0275f1c546f5899954f5e9b66f2f05db5a15d24465ed367acd6f36af8ba0e78` |
  | `config/tam-rubrics.yaml` | `32767e6393475a6e1c9dda52aa5f638940a38dc7a0881657baeb4b3baba43a00` |
  | `config/tam-roadmap-task-map.yaml` | `44206a242e9c6b9219b2de7cf27ff709e96e5f553ba4c378d3a83092d03fc814` |

- Create `config/releases/phase-1-six-week-v1/`; its three scoring YAML files must be byte-identical copies of the root scoring files. Only its `tam-roadmap-task-map.yaml` uses schema v2.
- Do not rename or change `month_one_target` storage/API fields in this batch. The human label becomes `Phase 1 target — six weeks`; all fourteen target values remain unchanged.
- Do not call `seed-config --apply` with the Phase 1 release directory. It is a roadmap-only release and must reuse the already-persisted `seed-v1` scoring lineage.
- The six English dimensions are additive Phase 1 evidence metadata, not new competencies and not a second scoring seed. They must never change the fourteen skill rows or their baseline, Phase 1, or final targets.
- Keep imported roadmap versions, curriculum nodes, task definitions, study days, attempts, and evidence immutable. Activating Phase 1 may supersede the old roadmap version; it must not rewrite its records.
- A later Phase 1 activation changes the former current `PhaseRun` to `superseded`, with a pointer to its successor. Completed, completed-with-gap, and superseded runs remain queryable as historical runs and can never become active again by mutating their status.
- The Phase 1 task map uses only the existing block codes `communication_spoken`, `career_pipeline`, `technical_learning`, `daily_close`, and `saturday_assessment`. A due correction is an optional first ten-minute procedure inside the 75-minute roadmap activity; do not add a fifth weekday block or restore the legacy standalone `correction_warmup` task.
- Focused unit tests, type checks, lint, and OpenAPI generation below do not require Docker. Any Alembic or integration command that touches PostgreSQL is a separate approval gate. Announce it and wait for explicit approval before starting Docker, Testcontainers, or Compose; afterward stop only services started for this work, verify no project containers remain, and close Docker Desktop.

## Locked schema-v2 release contract

Use this top-level shape in `config/releases/phase-1-six-week-v1/tam-roadmap-task-map.yaml`. Field names are part of the implementation contract; do not replace them with another Month abstraction.

```yaml
schema_version: 2
roadmap_version: phase-1-six-week-v1
mapping_version: seed-v1
month: 1                         # compatibility only
default_required: true

program:
  program_key: tam_phase_1
  display_name: TAM Study Phase 1
  target_label: Phase 1 target — six weeks
  nominal_weeks: 6

lineage:
  predecessor_roadmap_version: month-1-v2
  legacy_task_map_sha256: 44206a242e9c6b9219b2de7cf27ff709e96e5f553ba4c378d3a83092d03fc814
  compatibility_month: 1

calendar:
  anchor_date: 2026-08-24
  nominal_end_date: 2026-10-03
  weekday_minutes: 180
  saturday_minutes: 120
  sunday_minutes: 0
  ordinary_interview_minutes: 60
  pipeline_minutes: 30
  roadmap_minutes: 75
  close_minutes: 15

week7:
  available: true
  starts_on: 2026-10-05
  ends_on: 2026-10-10
  completion_only: true
  variance_trigger_percent: 15
  provisional_trigger_codes:
    - actual_variance_above_threshold
  activation_trigger_codes:
    - coverage_incomplete
    - exit_not_assessed
    - exit_assessed_not_demonstrated

interview_queue:
  - {ordinal: 1, segment: 1, question_key: tell_me_about_yourself, selection_mode: ordered, prompt: Tell me about yourself.}
  # ...all thirty approved prompts, in design order...
  - {ordinal: 30, segment: 6, question_key: sealed_final_mock, selection_mode: fixed_event, fixed_local_date: 2026-10-02, prompt: Run the sealed Phase 1 final mock.}

english_dimensions:
  policy_version: phase-1-english-v1
  aggregate_skill_slug: tam_english
  scale_min: 0
  scale_max: 4
  unavailable_state: not_assessed
  accent_scored: false
  dimensions:
    - {dimension_key: communication_effectiveness, weight: 0.30, modalities: [written, spoken]}
    - {dimension_key: fluency, weight: 0.25, modalities: [spoken_audio]}
    - {dimension_key: accuracy, weight: 0.15, modalities: [written, spoken]}
    - {dimension_key: vocabulary, weight: 0.10, modalities: [written, spoken]}
    - {dimension_key: pronunciation_intelligibility, weight: 0.10, modalities: [spoken_audio]}
    - {dimension_key: listening, weight: 0.10, modalities: [interactive_spoken]}

coverage:
  requirements:
    - requirement_key: task:m1-w1-d01-sql
      kind: task
      legacy_stable_id: m1-w1-d01-sql
      source_path: Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md
      source_heading: Day 1 — Baseline and HTTP
    # Include every legacy task, canonical assessment, required resource assignment,
    # and Phase 1 exit criterion exactly once.
  assignments:
    - requirement_key: task:m1-w1-d01-sql
      phase_task_ids: [p1-w01-d01-roadmap]
      completion_owner_task_id: p1-w01-d01-roadmap
      treatment: transition_import
      reconciliation_note: Preserve verified Day 1 evidence; do not schedule it again.

contracts:
  interview_cycle:
    kind: ordinary_interview
    total_minutes: 60
    steps:
      - {step_key: frame, minutes: 5, assistance: none}
      - {step_key: independent_attempt_a, minutes: 15, assistance: none}
      - {step_key: self_review, minutes: 5, assistance: none}
      - {step_key: codex_coaching, minutes: 20, assistance: coach_after_attempt_a, fresh_codex_task: true}
      - {step_key: separate_attempt_b, minutes: 5, assistance: none, after_coach_handoff: true}
      - {step_key: save_handoff_and_notes, minutes: 10, assistance: analyst}
    attempt_b:
      separate_from_coach_task: true
      same_question_as_attempt_a: true
      qualifying_for_level: false
    coach_handoff:
      required_before_attempt_b: true
      coach_must_not_claim_attempt_b: true
  sealed_final_mock:
    kind: sealed_final_mock
    total_minutes: 60
    queue_ordinal: 30
    fixed_local_date: 2026-10-02
    steps:
      - {step_key: setup, minutes: 5, assistance: none}
      - {step_key: sealed_mock, minutes: 45, assistance: none}
      - {step_key: save_and_self_review, minutes: 10, assistance: none}
    coaching_allowed: false
    attempt_b_allowed: false
  pipeline:
    kind: multi_action_pipeline
    output_contract_version: 2
    weekly_quality_target: 10
    default_weekday_actions: 2
    daily_pass_fail: false
    action_types: [application, recruiter_reply]
    required_fields:
      - company
      - role
      - context_snapshot_ref
      - relevance
      - known_gap
      - resume_or_story_version
      - completed_action
      - completed_on
      - current_stage
      - next_action
    nonqualifying_reasons:
      - simple_acknowledgement
      - research_without_required_artifact
    conversion_stages:
      - applied
      - recruiter_contact
      - recruiter_screen
      - hiring_manager_interview
      - next_round
      - offer
      - rejected
      - no_response
      - withdrawn
reconciliations: []
days:
  - week: 1
    day: 1
    source_path: Phase 1 - Week 1 - Transition, foundations, and baseline.md
    source_heading: Day 1 — Historical transition record
    tasks:
      - stable_id: p1-w01-d01-interview
        block: communication_spoken
        order: 1
        exercise_type: tell_me_about_yourself
        timebox_minutes: 60
        contract: interview_cycle
        allowed_ai_role: interviewer
      - stable_id: p1-w01-d01-pipeline
        block: career_pipeline
        order: 2
        exercise_type: application_or_outreach
        timebox_minutes: 30
        contract: pipeline
        allowed_ai_role: planner
      - stable_id: p1-w01-d01-roadmap
        block: technical_learning
        order: 3
        exercise_type: sql_guided_lesson
        timebox_minutes: 75
        contract: roadmap_unit
        allowed_ai_role: tutor
      - stable_id: p1-w01-d01-close
        block: daily_close
        order: 4
        exercise_type: official_reading
        timebox_minutes: 15
        contract: close
        allowed_ai_role: analyst
```

The completed file must satisfy these exact invariants:

- Thirty nominal weekdays each total `60 + 30 + 75 + 15 = 180` minutes. Twenty-nine use the ordinary interview contract `5 + 15 + 5 + 20 + 5 + 10`; the fixed October 2 Week 6 event uses `5 + 45 + 10`, with no pre/during coaching and no Attempt B. The ordinary contract's coach handoff ends before the separate uninterrupted Attempt B, and the coach task cannot claim that Attempt B was recorded or analyzed.
- Nominal Week 1 weekday definitions remain in the immutable package for a complete six-week source, but Francisco's transition import marks August 24–28 elapsed/reserved. They are never materialized, backfilled, treated as failed, or allowed to advance the interview queue; the first governed ordinary session is August 31.
- Six Saturdays total exactly 120 minutes each and preserve the approved structures in order: `35/45/20/10/10`, `30/50/25/15`, `30/35/20/20/15`, `35/45/20/10/10`, `30/35/20/20/15`, and `30/55/20/15`.
- Sundays have no task entries.
- Task IDs match `^p1-w(0[1-7])-d(0[1-9]|[1-3][0-9]|4[0-2])-[a-z0-9-]+$`; nominal tasks use weeks 01–06 and days 01–36. Week 7 is runtime-selected completion work, not forty-two prefilled tasks.
- The interview queue contains exactly 30 unique ordinals and keys. Ordinals 1–10 are the two core question sets from the design. Items 1–29 are `ordered`; Q30 alone is the fixed October 2 mock. Queue advancement begins at the first post-transition operating session rather than calendar Day 1. Completing Q30 out of order updates Q30 only: it never skips or marks Q1–Q29 complete, and the cursor remains the lowest incomplete ordered item.
- The English policy contains exactly the six approved dimensions, exact weights summing to `1.00`, modality-specific availability, and `accent_scored: false`. Unavailable evidence is persisted and returned as `not_assessed`/`N/A`, never numeric zero. The weighted TAM English contribution renormalizes over only the dimensions valid for that modality and remains an event for the existing `tam_english` competency; it does not create another competency or target.
- The pipeline contract accepts one or more atomic actions from one 30-minute block, distinguishes applications from substantive recruiter replies, requires every approved quality field, and counts only records without a nonqualifying reason. Its weekly target is ten across the first full operating week and later weeks; two per weekday is a planning default, not a daily gate.
- Each coverage requirement has one assignment, one nonempty `phase_task_ids` list or an explicit `transition_import`, and exactly one `completion_owner_task_id`. A phase task may support several requirements, but a requirement cannot have two completion owners.
- The v2 roadmap retains `mapping_version: seed-v1`; every non-pipeline/non-reading exercise resolves to the unchanged scoring release.
- Active Phase 1 text and task contracts say Codex, never Claude.
- Coverage contains exactly four requirements marked `kind: canonical_assessment` and one marked `kind: next_phase_priorities`; these are closure gates, not informational links.

## Task 1: Freeze the legacy release and establish the roadmap-only release boundary

**Files:**

- Create: `apps/backend/tests/unit/evidence/test_phase1_config_loader.py`
- Create: `config/releases/phase-1-six-week-v1/tam-skills.yaml`
- Create: `config/releases/phase-1-six-week-v1/tam-exercise-types.yaml`
- Create: `config/releases/phase-1-six-week-v1/tam-rubrics.yaml`
- Create later in Task 3: `config/releases/phase-1-six-week-v1/tam-roadmap-task-map.yaml`
- Modify later in Task 2: `apps/backend/src/tamforge_backend/evidence/config_models.py`
- Modify later in Task 2: `apps/backend/src/tamforge_backend/evidence/config_loader.py`

- [ ] Add a failing regression test that hashes all four root YAML files and asserts the four SHA-256 values in the preconditions table.
- [ ] In the same test, assert that the three scoring files in `config/releases/phase-1-six-week-v1/` exist and have exactly the same bytes and hashes as their root counterparts.
- [ ] Run `uv run pytest apps/backend/tests/unit/evidence/test_phase1_config_loader.py -q`; expect failure because the release files do not exist.
- [ ] Add the three scoring copies with `apply_patch`. Do not edit the root files and do not normalize line endings or YAML formatting.
- [ ] Re-run the focused test; expect the byte-freeze assertions to pass while schema-v2 loading tests added in Task 2 remain pending.
- [ ] Commit only the freeze test and scoring copies:

```bash
git add apps/backend/tests/unit/evidence/test_phase1_config_loader.py config/releases/phase-1-six-week-v1
git commit -m "test: freeze legacy TAM scoring release"
```

## Task 2: Add schema-aware v1/v2 roadmap configuration without changing scoring models

**Files:**

- Modify: `apps/backend/src/tamforge_backend/evidence/config_models.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/config_loader.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/seed.py`
- Modify: `apps/backend/src/tamforge_backend/cli.py`
- Modify: `apps/backend/src/tamforge_backend/config.py`
- Modify: `apps/backend/tests/unit/evidence/test_config_loader.py`
- Modify: `apps/backend/tests/unit/evidence/test_seed_config.py`
- Modify: `apps/backend/tests/unit/evidence/test_phase1_config_loader.py`
- Modify: `apps/backend/tests/unit/test_config.py`

- [ ] Add red tests proving all of the following:

  - the existing root bundle still parses as roadmap schema v1 and retains 158 tasks/24 study days;
  - a v2 release may use roadmap schema 2 while skills, exercises, and rubrics remain schema 1;
  - the loader rejects an unknown roadmap schema rather than falling back to v1;
  - `program`, `lineage`, `calendar`, `week7`, `interview_queue`, and `coverage` reject unknown fields, duplicate keys, incoherent dates, changed minute constants, missing trigger codes, variance as an activation trigger, and duplicate completion owners;
  - `contracts.interview_cycle` accepts only the ordered `5/15/5/20/5/10` procedure, requires a fresh Codex coaching task followed by a separate Attempt B and save/handoff step, and rejects a coach-owned Attempt B, coaching before Attempt A, or any other total;
  - `contracts.sealed_final_mock` accepts only `5/45/10`, queue ordinal 30, October 2, no coaching, and no Attempt B;
  - `english_dimensions` accepts exactly the six approved keys and weights, rejects accent as a scored field, rejects an unknown modality or numeric score for unavailable evidence, and cannot add a fifteenth skill or change `tam_english` targets;
  - `contracts.pipeline` requires the ten-action weekly target, both action types, every quality field, the closed conversion-stage set, and the rule that the two-action weekday default is not a daily gate;
  - queue selection modes contain exactly Q1–Q29 as `ordered` and Q30 as the single `fixed_event` item;
  - the `month` and scoring `month_one_target` compatibility fields are preserved;
  - `seed_config(..., apply=True)` rejects a roadmap-only v2 bundle with `"roadmap-only release cannot seed scoring"` before opening a database transaction;
  - `Settings` resolves `config` as the legacy scoring directory and `config/releases` as the roadmap-release registry by default.

- [ ] Run:

```bash
uv run pytest \
  apps/backend/tests/unit/evidence/test_config_loader.py \
  apps/backend/tests/unit/evidence/test_phase1_config_loader.py \
  apps/backend/tests/unit/evidence/test_seed_config.py \
  apps/backend/tests/unit/test_config.py -q
```

  Expect failures for missing v2 models and the coupled schema-version check.

- [ ] Split the current model explicitly instead of weakening it:

  - retain the current `RoadmapTaskConfig`, `RoadmapReconciliationConfig`, and `RoadmapTaskMapFile` behavior as v1 compatibility models;
  - add strict `RoadmapProgramConfig`, `RoadmapLineageConfig`, `RoadmapCalendarConfig`, `Week7PolicyConfig`, `InterviewQueueItemConfig`, `InterviewProcedureStepConfig`, `OrdinaryInterviewContractConfig`, `SealedFinalMockContractConfig`, `EnglishDimensionConfig`, `EnglishDimensionPolicyConfig`, `PipelineContractConfig`, `RoadmapContractsConfig`, `CoverageRequirementConfig`, `CoverageAssignmentConfig`, `CoverageConfig`, `RoadmapTaskV2Config`, and `RoadmapTaskMapV2File` models;
  - parse the roadmap file by its own `schema_version` discriminator;
  - keep `ConfigBundle.schema_version` as the scoring schema version and add `roadmap_schema_version`, `program`, `lineage`, `calendar`, `week7`, `interview_queue`, `english_dimensions`, `contracts`, and `coverage` fields;
  - provide legacy defaults only for v1 (`Month 1`, 240/120/0, four weeks, no Week 7) so old canonical payloads reconstruct unchanged;
  - never reinterpret a v2 file as a new scoring release.

- [ ] Replace `_build_bundle`'s single set-equality check with two checks: all three scoring schemas must match; roadmap schema may be 1 or 2. Keep the existing version-link checks for `seed-v1` exercise/rubric mappings.
- [ ] Add a `RoadmapReleaseRegistry` loader that indexes the root v1 bundle plus each direct child of `settings.roadmap_releases_dir` by a validated release key, rejects duplicate roadmap versions/content hashes, and returns a bundle only by exact key and content hash. Do not recursively scan arbitrary directories.
- [ ] Add `tamforge validate-roadmap-release --release-dir PATH --legacy-config-dir config`. Its JSON output must include `roadmap_schema_version`, `roadmap_version`, `program_key`, `study_days`, `weekday_days`, `saturdays`, `nominal_minutes`, `interview_questions`, `coverage_requirements`, and `coverage_assignments`. Keep `validate-roadmap-map` unchanged for v1.
- [ ] Make `seed-config` fail closed when handed a v2 roadmap-only release; its dry-run and apply paths must not create a second `ConfigSeedVersion` merely because roadmap content changed.
- [ ] Re-run the focused tests; expect all green.
- [ ] Commit:

```bash
git add apps/backend/src/tamforge_backend/evidence apps/backend/src/tamforge_backend/cli.py \
  apps/backend/src/tamforge_backend/config.py apps/backend/tests/unit/evidence \
  apps/backend/tests/unit/test_config.py
git commit -m "feat: load versioned Phase 1 roadmap releases"
```

## Task 3: Materialize the six-week release and canonical package fixture

**Files:**

- Modify: `apps/backend/pyproject.toml`
- Create: `config/releases/phase-1-six-week-v1/tam-roadmap-task-map.yaml`
- Create: `apps/backend/tests/fixtures/roadmaps/phase-1-six-week-v1.zip`
- Create: `apps/backend/tests/fixtures/roadmaps/expected-phase-1-six-week-v1.json`
- Create mechanically from the producer output: `apps/backend/tests/fixtures/roadmaps/phase-1-transition-v1.schema.json`
- Create mechanically from the producer output: `apps/backend/tests/fixtures/roadmaps/phase-1-transition-v1.json`
- Create mechanically from the producer output: `apps/backend/tests/fixtures/roadmaps/phase-1-transition-v1.json.sha256`
- Create mechanically from the producer output: `apps/backend/src/tamforge_backend/roadmaps/schemas/phase-1-transition-v1.schema.json`
- Modify: `apps/backend/tests/unit/evidence/test_phase1_config_loader.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_parser.py`

- [ ] From the already-validated Obsidian implementation, package the active `Roadmap/` directory into the fixture ZIP using the existing deterministic package conventions. Include only `.md` and `.sql`; do not include vault-root `Exports/`, either `Roadmap.backup-*` folder, or files outside active Phase 1. Add a package test that fails if a `.json` entry appears in the ZIP.
- [ ] Add a red loader test for the locked release invariants: 36 nominal study days, 30 weekdays, 6 Saturdays, `5,400 + 720 = 6,120` nominal minutes, 30 queue items, 29 ordinary interview contracts, one fixed Q30 final mock in segment 6, exact `5/15/5/20/5/10` and `5/45/10` internal procedures, exact weekday/Saturday shapes, the six English dimensions and exact weights/modality rules, the multi-action ten-per-week pipeline contract, unchanged `seed-v1` scoring links, exactly four canonical-assessment gates, one next-phase-priorities gate, and exact legacy coverage.
- [ ] Add a red parser summary fixture test. `expected-phase-1-six-week-v1.json` must record the normalized schema/version/program/calendar, task count, all six Saturday shapes, queue count, coverage counts, resource keys, exit criteria, and normalized hash.
- [ ] Build the v2 task map from the Obsidian coverage ledger. Preserve the exact source path and heading for every task and coverage requirement. Use the four weekday task IDs `interview`, `pipeline`, `roadmap`, and `close`; use ordered `saturday_assessment` component IDs on Saturdays.
- [ ] Encode the first ten interview prompts verbatim in the approved order, then the remaining twenty segments. Q1–Q29 use `selection_mode: ordered`; Q30 uses `selection_mode: fixed_event` on October 2. The fixed mock fulfills Q30 itself but does not consume, delete, or implicitly complete an earlier queue item.
- [ ] Encode all four canonical Saturday assessments with their original no-coaching constraints and the two diagnostic Saturdays with fresh-transfer constraints.
- [ ] Encode the correction window in the `roadmap_unit` contract as `maximum_items: 1`, `maximum_minutes: 10`, `source: due_corrections`, `no_attempt_c: true`, and `skill_level_effect: none`. Its remaining 65 minutes are the minimum primary roadmap work; when no correction is due, all 75 minutes remain available to that roadmap unit.
- [ ] Verify the prerequisite producer artifacts before copying any fixture bytes: run the Obsidian exporter in `--check` mode, run `shasum -a 256 -c '.../Exports/phase-1-transition-v1.json.sha256'`, hash `phase-1-transition-v1.schema.json` and compare it with the JSON's `schema_sha256`, and independently rehash every vault-relative path in `source_hashes`. The raw JSON must contain exactly the root contract below and the producer schema must reject additional properties at every object boundary.
- [ ] Copy the producer schema, JSON, and sidecar byte-for-byte into the three fixture paths, and copy the exact same schema bytes into the runtime schema resource. Do not redact, rename fields, extract a subset, add `export_sha256`, replace `source_hashes` with `source_pins`, or build a second envelope. Prove both schema copies with `cmp` against the producer, then run the tracked secret/audio policy check before committing; the canonical export contains bounded metadata and vault-relative references, never note bodies, transcripts, audio, credentials, or absolute paths.
- [ ] Include the runtime schema as package data in `apps/backend/pyproject.toml`. Add a loader test that resolves it with `importlib.resources`, reads the exact bytes in both an editable checkout and a built wheel, and compares its SHA-256 with the copied fixture and producer schema. A missing packaged resource fails closed.
- [ ] The fixture and live import use this exact raw producer-owned root shape; all nested contracts come from the copied JSON Schema rather than a TAM Forge reinterpretation:

```json
{
  "$schema": "phase-1-transition-v1.schema.json",
  "schema_version": 1,
  "export_version": "phase-1-transition-v1",
  "roadmap_version": "phase-1-six-week-v1",
  "mapping_version": "phase-1-transition-v1",
  "activation_cutoff": "2026-08-28",
  "schema_sha256": "<raw producer-schema SHA-256>",
  "source_hashes": {"<vault-relative authoritative Markdown path>": "<raw UTF-8 SHA-256>"},
  "transition": {},
  "coverage": [],
  "interview_queue": [],
  "weekday_sessions": [],
  "saturday_sessions": [],
  "resources": [],
  "exit_criteria": [],
  "next_phase_priorities": {}
}
```

  The exact nested shapes, counts, enums, cutoff, transition capacity, 158 coverage rows, 30 queue rows, 25 future weekday rows, six Saturday rows, 50 resource rows, ten exit criteria, and next-phase-priorities gate are producer-owned. TAM Forge first requires the supplied schema to equal the pinned runtime schema byte-for-byte, then validates the raw JSON and performs cross-reference and semantic checks; it never rewrites the JSON. The captured regression fixture remains immutable. Every non-test activation or gate refresh uses a freshly generated raw export and sidecar.

- [ ] Run:

```bash
uv run pytest \
  apps/backend/tests/unit/evidence/test_phase1_config_loader.py \
  apps/backend/tests/unit/roadmaps/test_parser.py -q
uv run tamforge validate-roadmap-release \
  --release-dir config/releases/phase-1-six-week-v1 \
  --legacy-config-dir config
uv run python scripts/ci/check_repository_policy.py
```

  Expected CLI fields include `"roadmap_schema_version": 2`, `"study_days": 36`, `"weekday_days": 30`, `"saturdays": 6`, `"nominal_minutes": 6120`, and `"interview_questions": 30`.

- [ ] Re-run the SHA freeze test to prove all four root files remain byte-identical.
- [ ] Commit:

```bash
git add apps/backend/pyproject.toml config/releases/phase-1-six-week-v1 apps/backend/tests/fixtures/roadmaps \
  apps/backend/src/tamforge_backend/roadmaps/schemas/phase-1-transition-v1.schema.json \
  apps/backend/tests/unit/evidence/test_phase1_config_loader.py \
  apps/backend/tests/unit/roadmaps/test_parser.py
git commit -m "data: add six-week Phase 1 roadmap release"
```

## Task 4: Normalize Phase 1 metadata, lineage, coverage, and Week 7

**Files:**

- Modify: `apps/backend/src/tamforge_backend/roadmaps/contracts.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/parser.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/diff.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/service.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_parser.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_diff.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_service.py`

- [ ] Add red parser tests that reject: 35 or 37 nominal days; a weekday not totaling 180; any Saturday not totaling 120; reordered/missing core interview questions; Q30 outside segment 6; any ordinary interview procedure other than `5/15/5/20/5/10`; a coach task that owns or claims Attempt B; Attempt B before the coach handoff; a final mock other than `5/45/10` or with coaching/Attempt B; more than one fixed queue event; a coached canonical assessment; an English policy with missing/extra/reweighted dimensions, a scored accent field, or invalid modality; a pipeline contract without both action types, all quality fields, target ten, or the conversion-stage set; fewer or more than four canonical-assessment gates; a missing next-phase-priorities gate; a Phase 1 task with an `m1-` ID; a missing legacy requirement; two completion owners; an assignment to a nonexistent Phase 1 task; a reset of known completed Day 1–3 work; and a Week 7 policy that permits new material.
- [ ] Add red tests proving v1 continues to require `Month 1 exit criteria` while v2 requires `Phase 1 exit criteria`; neither parser should accept the other heading by accident.
- [ ] Extend `ParsedRoadmap` with immutable normalized `program`, `lineage`, `calendar`, `week7`, `interview_queue`, `english_dimensions`, `contracts`, `coverage_requirements`, and `coverage_assignments`. Include them in `payload_dict()` and the normalized hash. `_parsed_from_payload` must reconstruct both schema 1 historical payloads and schema 2 payloads.
- [ ] Make `_validate_tasks` dispatch by roadmap schema. Preserve the v1 implementation exactly; add a v2 validator for the locked invariants. Do not loosen v1 ID, week, day, or time rules.
- [ ] Add semantic-diff sections for program/calendar/Week 7 metadata, English-dimension policy, pipeline contract, and coverage. A Month 1 → Phase 1 diff must visibly report the program change and coverage lineage; it must not present the old 158 tasks as silently deleted with no mapping.
- [ ] Include the exact config pin and normalized coverage summary in successful validation reports:

```json
{
  "config_pin": {
    "release_key": "phase-1-six-week-v1",
    "roadmap_schema_version": 2,
    "roadmap_version": "phase-1-six-week-v1",
    "bundle_content_hash": "<64 lowercase hex>"
  },
  "coverage": {"requirements": 0, "assigned": 0, "orphaned": 0, "duplicate_owners": 0}
}
```

  Replace the zeros with deterministic counts from the release. Approval must compare all four pin fields before reparsing.

- [ ] Run the focused parser/diff/service tests and expect green:

```bash
uv run pytest \
  apps/backend/tests/unit/roadmaps/test_parser.py \
  apps/backend/tests/unit/roadmaps/test_diff.py \
  apps/backend/tests/unit/roadmaps/test_service.py -q
```

- [ ] Commit:

```bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/tests/unit/roadmaps
git commit -m "feat: normalize Phase 1 roadmap lineage"
```

## Task 5: Pin staged imports to the exact roadmap release

**Files:**

- Modify: `apps/backend/src/tamforge_backend/roadmaps/ports.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/routes.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/service.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/repository.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_routes.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_service.py`

- [ ] Add red service and route tests for a required `roadmap_release_key` form field on new imports, exact release lookup, a missing release, duplicate package replay under the same pin, and approval after an application restart.
- [ ] Add a red test where the configured default release changes after staging. Approval must use the persisted `config_pin` and succeed only if the exact pinned bundle remains registered; it must return 409 if the pin is missing or its content hash differs. It must never revalidate with whichever release is currently newest.
- [ ] Change `RoadmapService` to receive a `RoadmapReleaseRegistry`, not one mutable `ConfigBundle`. Resolve the caller-selected release once during stage, write its pin into `validation_report`, and resolve by exact key/hash during approval.
- [ ] Return `release_key`, `roadmap_schema_version`, and `roadmap_version` in `RoadmapImportResponse`. Keep package idempotency behavior and private object keys unchanged.
- [ ] Do not place absolute local config paths in the response, audit event, manifest, or stored normalized payload.
- [ ] Run:

```bash
uv run pytest \
  apps/backend/tests/unit/roadmaps/test_routes.py \
  apps/backend/tests/unit/roadmaps/test_service.py -q
```

- [ ] Commit:

```bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/tests/unit/roadmaps
git commit -m "fix: pin roadmap imports to validation release"
```

## Task 6: Add Phase 1 runtime and coverage persistence

**Files:**

- Create: `apps/backend/alembic/versions/20260828_0012_phase1_runtime.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/models.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/models.py`
- Modify: `apps/backend/src/tamforge_backend/models/__init__.py`
- Create: `apps/backend/tests/unit/roadmaps/test_phase1_runtime_models.py`
- Create: `apps/backend/tests/integration/roadmaps/test_phase1_runtime_migration.py`
- Modify: `apps/backend/tests/integration/test_migrations.py`

- [ ] Write red model-contract tests before the migration. The migration creates these eleven owner-scoped tables and adds nullable `phase_weekly_publication_id`, `self_score`, and `reviewer_score` fields to Phase 1 `skill_snapshots` while leaving historical snapshots valid:

  | Table | Required identity and state |
  |---|---|
  | `phase_runs` | owner, immutable roadmap version and scoring seed, program/display/target label snapshots, anchor/nominal/Week 7 dates, version-bound minute policy, raw transition export/schema versions and hashes, complete producer `source_hashes`, lowest-incomplete ordered interview cursor, run status, Week 7 state, superseded-by pointer, timestamps |
  | `phase_interview_items` | owner, phase run, immutable ordinal/segment/question/selection mode/fixed date, workflow state, Attempt A/self-review/coach-handoff/Attempt B or sealed-mock refs, note/transcript/analysis refs, qualification, timestamps |
  | `roadmap_coverage_requirements` | owner, roadmap version, requirement key/kind, legacy stable ID when applicable, source path/heading, immutable obligation JSON |
  | `roadmap_coverage_assignments` | owner, roadmap version, requirement, Phase 1 task definition when scheduled, treatment, completion-owner flag, reconciliation note |
  | `roadmap_coverage_progress` | owner, phase run, requirement, coverage status, exit outcome, planned/attributed actual minutes, actual-time state, checkpoint, note/evidence refs, valid assessment/retest counts, qualification state, optimistic version, timestamps |
  | `phase_progress_events` | owner, phase run, immutable source kind/source id/source version/payload hash, unique activity seconds, coverage effects, note/evidence refs, checkpoint, created timestamp |
  | `phase_transition_refreshes` | owner, phase run, prior refresh when any, exact raw schema/export versions and SHA-256 hashes, complete live source hashes, activation cutoff, canonical next-phase-priorities object/hash, idempotency identity/payload hash, imported timestamp |
  | `phase_weekly_publications` | owner, phase run, period key (`week_1` through `week_6` or `week_7_completion`), evidence cutoff/watermark, weekly-review ref, nullable validated transition-refresh link, immutable publication status/hash, timestamps |
  | `phase_english_dimension_scores` | owner, phase run, evaluation/publication lineage, exact policy version/dimension key, modality, assessor kind, availability, nullable 0–4 score, reason, bounded evidence refs, timestamps |
  | `phase_pipeline_actions` | owner, phase run, source activity/idempotency identity, action type, company/role, context snapshot ref, relevance, known gap, resume/story version, completed action/date, quality result/reason, current stage/next action, optimistic version, timestamps |
  | `phase_pipeline_stage_events` | owner, phase action, immutable from/to stage, exact next action, source identity/payload hash, occurred timestamp |

- [ ] Use these closed state sets:

  - phase run: `staged`, `active`, `superseded`, `completed`, `completed_with_gap`;
  - Week 7: `available`, `provisional`, `active`, `closed`;
  - interview item: `pending`, `attempt_a_committed`, `self_review_complete`, `coaching_handoff_received`, `attempt_b_committed`, `mock_committed`, `completed`, `not_assessed`;
  - coverage status: `pending`, `in_progress`, `completed`, `not_assessed`;
  - exit outcome: `not_applicable`, `not_assessed`, `assessed_not_demonstrated`, `demonstrated`;
  - actual-time state: `not_historical`, `unknown`, `verified`;
  - qualification: `not_applicable`, `nonqualifying`, `qualifying`.
  - English assessor: `self`, `reviewer`; availability: `scored`, `not_assessed`; modality: `written`, `spoken`, `spoken_audio`, `interactive_spoken`;
  - pipeline action: `application`, `recruiter_reply`; quality: `qualifying`, `simple_acknowledgement`, `research_without_required_artifact`; pipeline stage: the exact closed set in the v2 contract.

- [ ] Add composite owner/version foreign keys, unique `(phase_run_id, requirement_id)` progress, unique `(roadmap_version_id, requirement_key)` requirement, unique `(phase_run_id, ordinal)` and `(phase_run_id, question_key)` interview items, unique `(phase_run_id, period_key)` weekly publications, unique `(phase_run_id, raw_export_sha256)` transition refreshes, unique English `(evaluation_id, dimension_key, assessor_kind)`, unique pipeline source identities, unique stage-event source identities, unique progress-event source identity, and a partial unique index allowing exactly one `completion_owner = true` per requirement. A weekly publication may link only to a refresh for the same owner/run.
- [ ] Add database/model constraints that Q1–Q29 are `ordered`, Q30 alone is segment 6 and `fixed_event` on October 2, and an ordinary item can reach `completed` only with Attempt A, self-review, coach handoff, separate Attempt B, and save/note refs. Q30 can reach `completed` only through `mock_committed` plus a valid rubric evaluation and must have no coach-handoff or Attempt B refs.
- [ ] Make configuration/provenance columns immutable after insert. Allow only monotonic run/interview/progress transitions; never permit `completed` to return to pending or verified minutes to become unknown. Transition refreshes are append-only: `pending → completed` is allowed, and a Week 7 completed refresh may supersede the Week 6 completed refresh only through an explicit predecessor link and later review date; no row is edited in place. A completed Q30 must leave incomplete Q1–Q29 untouched. Store only bounded vault-relative note/transcript/analysis refs and numeric evidence IDs, never transcript bodies or absolute vault paths.
- [ ] Treat `phase_progress_events.actual_seconds` as the de-duplicated time source. Coverage rows may attribute the event to several requirements for traceability, but capacity/variance aggregation counts each source activity once and never sums duplicated requirement attribution.
- [ ] Link Phase 1 `SkillSnapshot` rows to exactly one `phase_weekly_publication`; raw daily evidence events have no snapshot. Persist the weekly self score separately from the server-derived reviewer score; neither may overwrite `estimated_level`. Preserve all pre-Phase-1 snapshots with null Phase 1 publication/self/reviewer fields.
- [ ] Enforce English availability coherently: `not_assessed` requires null score and a reason; `scored` requires a 0–4 score and evidence valid for the dimension's modality. Accent is not a dimension. Listening requires an interactive prompt/follow-up artifact; a monologue cannot score it.
- [ ] Enforce one or more independently addressable pipeline actions per Phase 1 pipeline activity. Only qualifying actions count toward ten; acknowledgements and research without the required concrete artifact remain stored but excluded. Stage changes append an immutable event and atomically update the current projection.
- [ ] `phase_runs.scoring_config_seed_version_id` is the authoritative scoring pin. This is how later scoring releases avoid the current “highest database ID wins” behavior.
- [ ] A new same-program activation changes the former current run from `active` to `superseded` and sets `superseded_at`/`superseded_by_phase_run_id` atomically. `superseded`, `completed`, and `completed_with_gap` are historical terminal states; rollback creates/activates another approved run rather than reviving one.
- [ ] The migration downgrade must refuse to run when any Phase 1 row exists; it must not cascade-delete study history.
- [ ] Import all new Phase 1 models through `models/__init__.py` so Alembic metadata sees all eleven tables and the snapshot/refresh relationships.
- [ ] Run only the model tests now:

```bash
uv run pytest apps/backend/tests/unit/roadmaps/test_phase1_runtime_models.py -q
```

  Expected: green without a database.

- [ ] Do **not** run the migration/integration test yet. Record it for the explicit Docker/PostgreSQL gate in Task 13.
- [ ] Commit:

```bash
git add apps/backend/alembic/versions/20260828_0012_phase1_runtime.py \
  apps/backend/src/tamforge_backend/roadmaps/models.py \
  apps/backend/src/tamforge_backend/evidence/models.py \
  apps/backend/src/tamforge_backend/models/__init__.py \
  apps/backend/tests/unit/roadmaps/test_phase1_runtime_models.py \
  apps/backend/tests/integration/roadmaps/test_phase1_runtime_migration.py \
  apps/backend/tests/integration/test_migrations.py
git commit -m "feat: persist Phase 1 coverage runtime"
```

## Task 7: Persist normalized coverage, import the Day 1–3 transition, and activate safely

**Files:**

- Modify: `apps/backend/pyproject.toml`
- Regenerate mechanically: `uv.lock`
- Create: `apps/backend/src/tamforge_backend/roadmaps/transition.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/ports.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/repository.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/service.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/routes.py`
- Modify: `apps/backend/src/tamforge_backend/cli.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_service.py`
- Create: `apps/backend/tests/unit/roadmaps/test_transition.py`
- Modify: `apps/backend/tests/unit/roadmaps/test_routes.py`
- Create: `apps/backend/tests/integration/roadmaps/test_phase1_transition.py`

- [ ] Add `jsonschema>=4.23,<5` to the backend runtime dependencies and refresh `uv.lock`; TAM Forge must validate Draft 2020-12 with `Draft202012Validator.check_schema(...)` rather than approximating the producer contract with a parallel Pydantic envelope.
- [ ] Add red pure tests that first require the supplied schema bytes and SHA-256 to equal `roadmaps/schemas/phase-1-transition-v1.schema.json`, then validate the **raw JSON bytes** against that pinned schema, and only then apply TAM Forge semantics. Require the exact root-key set, `$schema = phase-1-transition-v1.schema.json`, `schema_version = 1`, exact export/roadmap/mapping versions, matching pinned schema SHA-256, full-file sidecar SHA-256, every current `source_hashes` entry, the producer-owned transition/coverage/queue/session/resource/exit/next-priority shapes and counts, numeric queue segments `1`–`6` in five-item bands with Q30 in segment `6`, Monday anchor, ordered elapsed slots, verified minutes only for `verified`, unknown minutes preserved as null, known Day 3 SQL complete, idempotency in progress, all 30 unique queue records, derived cursor 1, no retroactive interview or pipeline failure, and future-only capacity through October 3. Reject an extra/transformed root field, any supplied-schema byte drift under v1 even when its self-hash is internally consistent, stale source hash, edited JSON, mismatched sidecar, unknown version, missing queue/resource/exit/next-priority record, categorical/wrong segment, or non-lowest cursor.
- [ ] Keep the two mapping namespaces explicit: raw transition `mapping_version = phase-1-transition-v1` identifies the producer/export contract, while roadmap/scoring `mapping_version = seed-v1` identifies exercise-to-skill mappings. Validate both exact values and never compare them as if they should be equal.
- [ ] Add a red service test proving approval persists every normalized coverage requirement and assignment with exactly one owner while preserving predecessor lineage.
- [ ] Add red activation tests proving:

  - a v2 Phase 1 version remains `approved` until its transition ledger is imported;
  - importing transition data creates a `staged` phase run pinned to the existing `seed-v1` `ConfigSeedVersion` and is idempotent by owner + roadmap version + transition-file hash;
  - import materializes all 30 per-run interview item rows without synthesizing historical attempts;
  - activation may supersede an active Month 1 version even though both retain `month_number = 1`;
  - old study days/activities/evidence remain attached to the old roadmap version and unchanged;
  - no elapsed calendar date is backfilled with a new Phase 1 `StudyDay`;
  - activation sets the new roadmap and phase run active atomically; if a prior Phase 1 run exists, it becomes `superseded` with successor lineage in the same transaction;
  - a second active phase run per owner is rejected.

- [ ] Add red refresh tests using producer-shaped pending, Week 6 completed, and Week 7 completed fixtures. Prove that the initial import creates a pending append-only transition-refresh provenance row; a valid completed raw export creates exactly one successor refresh for the active owner/run; replay of the same idempotency key and bytes returns the stored result; and a Week 7 refresh may supersede the Week 6 refresh only after retest evidence and with a later review date. Reject a bare note ref, pending or schema-invalid gate, missing priority field, wrong gate/owner, stale live source hash, unpinned schema, different roadmap/mapping version, reverse lifecycle/date, changed immutable requirement/queue/session/resource/exit definitions, any backward status/evidence change relative to runtime, or the same idempotency key with different bytes.

- [ ] Implement `tamforge import-phase-transition` with required `--owner-id`, `--roadmap-version-key`, `--transition-file`, `--transition-schema-file`, `--transition-sha256-file`, and mutually exclusive `--dry-run`/`--apply`. `--apply` additionally requires `--vault-root` so every producer `source_hashes` path can be rehashed immediately before the transaction. Dry-run is the default and prints:

```json
{
  "status": "validated",
  "program_key": "tam_phase_1",
  "roadmap_version": "phase-1-six-week-v1",
  "export_version": "phase-1-transition-v1",
  "transition_sha256": "<64 lowercase hex>",
  "schema_matches_pinned_v1": true,
  "source_hashes_current": true,
  "elapsed_weekday_slots": 0,
  "elapsed_saturday_slots": 0,
  "verified_historical_minutes": 0,
  "unknown_historical_slots": 0,
  "future_schedulable_minutes": 0,
  "completed_requirements": 0,
  "in_progress_requirements": 0,
  "pending_requirements": 0,
  "interview_queue_cursor": 1,
  "next_phase_priorities_state": "pending"
}
```

  Values come directly from the raw producer arrays and `transition` object at `activation_cutoff`, not from nominal 6,120 minutes and not from the wall clock on the day the command happens to run. The captured fixture must report five elapsed weekday slots and `5,220` future schedulable minutes. `source_hashes_current` may be true only after hashing every supplied live-vault source; fixture-only schema validation is never sufficient for apply.

- [ ] Before every non-test dry-run/apply, run the prerequisite producer's `--write` and `--check` commands against the canonical vault, review the raw diff, and verify the schema and sidecar. Never edit the schema, JSON, or sidecar directly. The captured fixture remains an immutable regression input and must never be applied when a newer live export exists.
- [ ] On initial apply, lock owner + target roadmap; re-read and hash the raw schema and JSON after live-source validation; verify the exact pinned schema, roadmap release, and scoring pin; persist the export/schema versions and hashes plus the complete `source_hashes`; import `transition`, `coverage`, `interview_queue`, `weekday_sessions`, `saturday_sessions`, `resources`, `exit_criteria`, and the pending `next_phase_priorities` object directly; and create the first append-only transition-refresh provenance row in one transaction. Emit one outbox event with counts only. Abort if either file changes between validation and insert. Do not store absolute vault paths, note bodies, transcript text, or secrets.
- [ ] Implement `tamforge refresh-phase-transition` with required `--owner-id`, `--phase-run-id`, `--transition-file`, `--transition-schema-file`, `--transition-sha256-file`, `--vault-root`, `--idempotency-key`, and mutually exclusive `--dry-run`/`--apply`. It reruns the identical pinned-schema, sidecar, semantic, and all-live-source checks; requires the active run's exact roadmap/export lineage; compares immutable identities and runtime progress monotonically; and imports the canonical `next_phase_priorities` object as an append-only successor without overwriting study progress. `--dry-run` writes nothing and reports gate state/hash plus every refusal reason. `--apply` locks the run and latest refresh, re-reads all bytes, inserts exactly one refresh row, and returns its ID/hash. The weekly publication endpoint accepts that persisted refresh ID—not a client-supplied bare priorities reference. Week 6 requires a completed refresh; `week_7_completion` requires a newer completed refresh whose review follows the retest.
- [ ] Add read-only `GET /api/v1/roadmaps/phase-runs/{phase_run_id}/transition-refreshes/latest` so the weekly-review UI can show `pending`, `completed_for_week_6`, or `completed_after_week_7_retest`, the validated review ref/date, and the raw export hash. It never accepts or edits priority content; mutation remains the fail-closed CLI import of canonical producer bytes. Route tests must prove owner isolation and that a pending/stale refresh cannot be represented as closure-ready.
- [ ] Extend same-month activation to recognize v2 program lineage. Retain the existing previous-month exit gate for actual Month 2+ versions.
- [ ] Run non-database tests:

```bash
uv run pytest \
  apps/backend/tests/unit/roadmaps/test_transition.py \
  apps/backend/tests/unit/roadmaps/test_service.py \
  apps/backend/tests/unit/roadmaps/test_routes.py -q
shasum -a 256 -c \
  '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.json.sha256'
uv run tamforge import-phase-transition \
  --owner-id 1 \
  --roadmap-version-key phase-1-six-week-v1 \
  --transition-file '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.json' \
  --transition-schema-file '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.schema.json' \
  --transition-sha256-file '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.json.sha256' \
  --vault-root '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice' \
  --dry-run
```

  The CLI must validate the raw producer schema, file semantics, full-file sidecar, and all live source hashes without contacting PostgreSQL in dry-run mode.

- [ ] Defer `apps/backend/tests/integration/roadmaps/test_phase1_transition.py` to Task 13.
- [ ] Commit:

```bash
git add apps/backend/pyproject.toml uv.lock apps/backend/src/tamforge_backend/roadmaps apps/backend/src/tamforge_backend/cli.py \
  apps/backend/tests/unit/roadmaps apps/backend/tests/integration/roadmaps
git commit -m "feat: migrate active study into Phase 1"
```

## Task 8: Make budgets, scheduling, timers, and Today version-bound

**Files:**

- Modify: `apps/backend/src/tamforge_backend/learning/time_policy.py`
- Modify: `apps/backend/src/tamforge_backend/learning/timers.py`
- Modify: `apps/backend/src/tamforge_backend/learning/scheduling.py`
- Modify: `apps/backend/src/tamforge_backend/learning/repository.py`
- Modify: `apps/backend/src/tamforge_backend/learning/models.py`
- Modify: `apps/backend/src/tamforge_backend/learning/service.py`
- Modify: `apps/backend/src/tamforge_backend/today/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/today/service.py`
- Modify: `apps/backend/src/tamforge_backend/today/repository.py`
- Modify: `apps/backend/tests/unit/learning/test_time_policy.py`
- Modify: `apps/backend/tests/unit/learning/test_timers.py`
- Modify: `apps/backend/tests/unit/learning/test_scheduling.py`
- Modify: `apps/backend/tests/unit/today/test_today_service.py`
- Modify: `apps/backend/tests/unit/today/test_continue_priority.py`
- Modify: `apps/backend/tests/unit/today/test_today_routes.py`
- Create: `apps/backend/tests/integration/learning/test_phase1_study_day_creation.py`

- [ ] Add red tests for two immutable policies:

  - legacy v1 remains weekday target/minimum/hard stop `240/225/255`, Saturday `120`, Sunday `0`;
  - Phase 1 v2 is `180/180/180`, Saturday `120/120/120`, Sunday `0/0/0`.

- [ ] Replace the global `budget_for(date)` and `DAY_HARD_STOP_SECONDS` dependency with an immutable version-bound `StudyTimePolicy` snapshot supplied by the active `PhaseRun`. Keep an explicit `LEGACY_MONTH_ONE_POLICY` fallback only for historical v1 days.
- [ ] Pass `day_hard_stop_seconds=policy.hard_stop_minutes * 60` into timer heartbeat accumulation. An activity attached to a legacy day keeps the legacy snapshot even after Phase 1 activates.
- [ ] Add scheduling/runtime-contract tests for the exact ordinary Phase 1 shape and final-mock exception. The ordinary activity exposes and enforces `frame 5 → independent Attempt A 15 → self-review 5 → fresh Codex coaching 20 → coach handoff → separate uninterrupted Attempt B 5 → save/handoff/notes 10`; Attempt B cannot be recorded before the handoff or by the coach task. The fixed Q30 mock exposes and enforces `setup 5 → sealed mock 45 → save/self-review 10`, and rejects coaching or Attempt B. An interview booked within 72 hours makes the 60-minute slot company/role-specific. A real weekday interview replaces only that slot and never removes the 75-minute roadmap floor; excess time is explicit displaced minutes for reforecast, with no live-AI assistance.
- [ ] Delete the phase-v2 path through `_replace_for_interviews` that removes `tam_case`, `technical_learning`, pipeline, or close blocks. Keep legacy behavior behind the legacy policy until historical days finish.
- [ ] Treat Phase 1 corrections as metadata inside the 75-minute roadmap task: expose at most one due correction and its ten-minute cap, but keep the activity's total timebox 75 and never create a fifth weekday task.
- [ ] Enforce at most one unfinished roadmap carryover. Any incomplete required roadmap activity must save one nonblank exact observable checkpoint; a second unfinished roadmap unit stays unscheduled until weekly reforecast rather than becoming hidden debt. Early completion never creates filler work, and no carryover may select Sunday.
- [ ] Add a pure, exhaustively table-tested `evaluate_week7` state machine with these exact rules:

  - every run starts Week 7 as `available`;
  - before/at Week 6 close, absolute planned-versus-actual variance strictly greater than 15% changes `available → provisional`; exactly 15% does not; variance alone can never make Week 7 `active`;
  - only after Week 6 closes, incomplete required coverage, any `not_assessed` exit, or any `assessed_not_demonstrated` exit changes `available|provisional → active`;
  - Phase 1 cannot close until all required coverage is complete, all four canonical assessments have valid independent/no-coaching rubric results, and a schema-valid completed next-phase-priorities raw export has been imported as the required transition refresh and linked to the closing publication;
  - `not_assessed` blocks both `completed` and `completed_with_gap` until a valid assessment/retest exists;
  - `assessed_not_demonstrated` requires at least one valid Week 7 retest. A demonstrated retest permits `completed`; a valid still-not-demonstrated retest permits only `completed_with_gap`, with the gap carried to Phase 2. Without a valid retest the run stays active;
  - closure changes Week 7 to `closed`; no terminal run can re-enter Week 7.
- [ ] For October 5–10, select completion work only from pending coverage, missing canonical-assessment/next-priority gates, or required retests. Do not clone a new resource or create work unrelated to an existing requirement. Sunday October 11 remains off.
- [ ] Make `StudyDayService` read the active phase run and its immutable policy. Never create Phase 1 days for elapsed dates; never return an old-version day as if it belonged to the new active version. Existing same-date historical rows remain read-only history.
- [ ] Add `program_key`, `display_name`, `target_label`, nullable `nominal_week` (1–6 only), `interview_queue_ordinal`, `week7_status`, and `displaced_minutes` to the Today read model while retaining `month` as compatibility output. Week 7 has `nominal_week = null` and its explicit Week 7 state; it is never serialized as nominal week 7.
- [ ] Change Today validation to use the version-bound policy, not a global 225-minute minimum. The read response for an ordinary Phase 1 weekday must report target/hard stop 180 and four required blocks totaling 180.
- [ ] Run:

```bash
uv run pytest \
  apps/backend/tests/unit/learning/test_time_policy.py \
  apps/backend/tests/unit/learning/test_timers.py \
  apps/backend/tests/unit/learning/test_scheduling.py \
  apps/backend/tests/unit/today/test_today_service.py \
  apps/backend/tests/unit/today/test_continue_priority.py \
  apps/backend/tests/unit/today/test_today_routes.py -q
```

- [ ] Defer the new database-backed study-day test to Task 13.
- [ ] Commit:

```bash
git add apps/backend/src/tamforge_backend/learning apps/backend/src/tamforge_backend/today \
  apps/backend/tests/unit/learning apps/backend/tests/unit/today \
  apps/backend/tests/integration/learning/test_phase1_study_day_creation.py
git commit -m "feat: enforce Phase 1 study-time policy"
```

## Task 9: Update coverage and interview progress atomically from runtime work

**Files:**

- Create: `apps/backend/src/tamforge_backend/roadmaps/progress.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/ports.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/repository.py`
- Modify: `apps/backend/src/tamforge_backend/learning/contracts.py`
- Modify: `apps/backend/src/tamforge_backend/learning/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/learning/routes.py`
- Modify: `apps/backend/src/tamforge_backend/learning/service.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/repository.py`
- Create: `apps/backend/tests/unit/roadmaps/test_phase1_progress.py`
- Create: `apps/backend/tests/unit/learning/test_phase1_interview_workflow.py`
- Create: `apps/backend/tests/unit/learning/test_phase1_pipeline.py`
- Modify: `apps/backend/tests/unit/learning/test_output_commit.py`
- Modify: `apps/backend/tests/unit/evidence/test_evidence_service.py`
- Create: `apps/backend/tests/integration/roadmaps/test_phase1_progress_atomicity.py`
- Create: `apps/backend/tests/integration/learning/test_phase1_pipeline.py`

- [ ] Add red pure/service tests for a transaction-scoped `PhaseProgressService`. It receives the same `AsyncSession` already used by `ActivityService` or `SqlAlchemyEvidenceRepository`; it never opens a second transaction and never relies on an eventual worker to make authoritative progress current.
- [ ] Define bounded `PhaseProgressInput` on Phase 1 completion commands: vault-relative `note_refs`, a checkpoint that is optional only for completed work and mandatory/nonblank for every incomplete item, and the current interview/assessment step. Coverage requirement keys come from immutable assignments rather than client input. Actual seconds come from persisted timers, planned minutes from the pinned task definition, and evidence IDs from the committed evaluation; the client cannot supply any of those values.
- [ ] Wire these atomic hooks and test rollback of **both** source and progress changes when either side fails:

  | Source command/event | Progress effect in the same transaction |
  |---|---|
  | Phase 1 activity output commit | append one de-duplicated progress event; set assigned coverage `pending → in_progress`; capture timer seconds once, note refs, and checkpoint; for an interview, set its item to `attempt_a_committed` |
  | Phase 1 self-review submit | set the same interview item to `self_review_complete`; do not advance the cursor |
  | `record-interview-coach-handoff` | require the fresh-Codex handoff after self-review; store only its bounded vault-relative handoff ref; set `coaching_handoff_received`; do not accept or claim Attempt B |
  | `complete-interview-session` | require a distinct Attempt B artifact/ref created after the handoff plus transcript/analysis/note refs; set `attempt_b_committed → completed`, close the parent timer, preserve Attempt B as nonqualifying, and then recompute the ordered cursor |
  | Phase 1 pipeline output commit | accept a contract-v2 array of one or more atomic actions; insert each action idempotently, preserve excluded quality reasons, count unique qualifying actions once, and complete the activity without treating ten as a daily gate |
  | pipeline stage update | append one immutable stage event, update current stage/next action, and make conversion reporting current in the same transaction |
  | activity incomplete classification | preserve actual seconds and note refs, set coverage to `in_progress` or `not_assessed` as the classification requires, and save one exact next checkpoint |
  | evidence evaluation commit | append evidence IDs/qualification atomically; complete only requirements whose pinned completion predicate now passes; update canonical-assessment initial/retest counts and exit outcome |
  | sealed Q30 mock save/evaluation | use `pending → mock_committed → completed`, require no coaching/Attempt B, attach the qualifying/nonqualifying evaluation, and leave every earlier item unchanged |

- [ ] Make generic `commit-output` recognize `contract: interview_cycle`: commit independent Attempt A but keep its timer open through the remaining procedure. `submit-self-review` also keeps that timer open. Add `POST /api/v1/activities/{activity_id}/interview-coach-handoff` and `POST /api/v1/activities/{activity_id}/complete-interview-session`; the latter ends the timer and moves the activity from `self_review_complete` to `ai_processing`. Reject either endpoint for legacy/non-interview activities.
- [ ] Enforce the ordinary sequence exactly: `frame 5 → independent Attempt A 15 → self-review 5 → Codex coaching 20 → received coach handoff → separate uninterrupted Attempt B 5 → save/handoff/notes 10`. Tests must reject missing/out-of-order steps, a coach-owned Attempt B, a reused Attempt A artifact as B, a B timestamp before/equal to the handoff, missing transcript/analysis/note refs, and a procedure whose planned step minutes do not total 60.
- [ ] Enforce the fixed mock sequence exactly: `setup 5 → sealed mock 45 → save/self-review 10`. It has no coach endpoints and no Attempt B. Its rubric evaluation may complete Q30 out of order; the persisted cursor is recomputed as the minimum ordinal whose `selection_mode = ordered` and state is not `completed`, so Q30 can never move it past Q1–Q29.
- [ ] Add `PipelineOutputV2` without changing legacy `PipelineOutput`: `contract_version: 2` plus `actions` containing every locked quality field. Require `context_snapshot_ref` to be a bounded vault-relative job-description snapshot for applications or recruiter-context note for replies. Reject a simple acknowledgement as qualifying, and reject research as qualifying unless it links the concrete legacy artifact. Add `POST /api/v1/pipeline-actions/{action_id}/stage-events` with optimistic version and idempotency key.
- [ ] Add weekly pipeline queries grouped by the Phase 1 operating-week calendar. Return qualifying total/target/gap; separate application and recruiter-reply counts; stage funnel counts for recruiter screen, hiring-manager interview, next round, rejection/no response, and offer; excluded-action reasons; and exact next actions. The transition week reports actual imported actions only and has no target failure.
- [ ] Store/replay every hook through unique `phase_progress_events`. An idempotent command replay returns its saved result without adding seconds, refs, assessment counts, or cursor movements twice. A conflicting source version/payload hash returns 409.
- [ ] Attribute actual minutes to the completion-owner coverage row while linking the same source event to all supporting requirements. Weekly/capacity totals query unique progress events, not summed requirement rows. Preserve unknown historical minutes as null; never convert planned minutes into actual minutes.
- [ ] Add a coverage completion matrix test for output-only, self-review-required, evidence-required, canonical-assessment, and next-phase-priorities requirements. A note link alone never demonstrates a skill; an evidence event alone never completes an unrelated coverage owner; and the priorities owner completes only from a closing weekly publication linked to the correct validated completed transition refresh.
- [ ] Run the focused non-database tests:

```bash
uv run pytest \
  apps/backend/tests/unit/roadmaps/test_phase1_progress.py \
  apps/backend/tests/unit/learning/test_phase1_interview_workflow.py \
  apps/backend/tests/unit/learning/test_phase1_pipeline.py \
  apps/backend/tests/unit/learning/test_output_commit.py \
  apps/backend/tests/unit/evidence/test_evidence_service.py -q
```

- [ ] Defer `apps/backend/tests/integration/roadmaps/test_phase1_progress_atomicity.py` and `apps/backend/tests/integration/learning/test_phase1_pipeline.py` to the approval-gated database task.
- [ ] Commit:

```bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/src/tamforge_backend/learning \
  apps/backend/src/tamforge_backend/evidence/repository.py apps/backend/tests/unit \
  apps/backend/tests/integration/roadmaps/test_phase1_progress_atomicity.py \
  apps/backend/tests/integration/learning/test_phase1_pipeline.py
git commit -m "feat: synchronize Phase 1 runtime progress"
```

## Task 10: Bind evidence views to the active scoring lineage and publish estimates weekly

**Files:**

- Modify: `apps/backend/src/tamforge_backend/evidence/qualification.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/repository.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/service.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/routes.py`
- Modify only if an index/relationship is required: `apps/backend/src/tamforge_backend/evidence/models.py`
- Modify: `apps/backend/tests/unit/evidence/test_qualification.py`
- Modify: `apps/backend/tests/unit/evidence/test_evidence_service.py`
- Modify: `apps/backend/tests/unit/evidence/test_evidence_routes.py`
- Modify: `apps/backend/tests/unit/evidence/test_skill_estimate.py`
- Create: `apps/backend/tests/unit/evidence/test_english_dimensions.py`
- Create: `apps/backend/tests/unit/evidence/test_weekly_publication.py`
- Create: `apps/backend/tests/integration/evidence/test_phase1_scoring_lineage.py`

- [ ] Add a red repository test proving that two persisted config releases cannot make `list_skills()` choose the row with the largest ID. It must use `phase_runs.scoring_config_seed_version_id`; with multiple releases and no active pin it fails closed instead of guessing. A legacy owner with exactly one config remains supported.
- [ ] Replace `_latest_config_id` with `_active_scoring_config_id` using the active phase run pin. Do not seed the Phase 1 roadmap bundle and do not duplicate competencies/exercises/rubrics.
- [ ] Add `target_label` to the skill-list response envelope. Continue returning `month_one_target` and `month_one_target_gap` fields unchanged so stored events and generated clients remain compatible.
- [ ] Add regression cases for Phase 1 evidence classification: independent written Attempt A can score only communication effectiveness, accuracy, and vocabulary; fluency and pronunciation require original audio; listening requires an interactive prompt/follow-up artifact; a monologue leaves listening unavailable; same-question Attempt B never qualifies for level; guided/co-created work does not qualify; a fresh no-coaching Saturday assessment can qualify; the sealed Week 6 mock with Codex acting only as interviewer can qualify; and a real interview can qualify only from a post-interview debrief with no live-AI assistance. Persist every unavailable dimension as `not_assessed` with null score, never zero, and reject any accent field.
- [ ] Persist both assessor tracks without substitution. Dimension inputs carry `assessor_kind = self|reviewer`; each immutable evaluation stores both when supplied. For the fourteen weekly skill rows, `self_score` comes from the explicit weekly-review self assessment, `reviewer_score` is the server-derived weighted score from that publication's eligible reviewer events, and `estimated_level` remains the existing prior/evidence formula. Missing self or reviewer evidence is null/`Not assessed`.
- [ ] Implement the already-approved English-dimension aggregator from `docs/superpowers/specs/2026-08-25-tam-forge-product-architecture-design.md` §12.3: compute TAM English only from scored dimensions valid for the evidence modality and renormalize its locked weights over that available subset. Produce **exactly one** `tam_english` evidence contribution per evaluation. When `seed-v1`'s `english_clarity` mapping already creates that contribution, enrich/replace that same contribution with dimension provenance; never append a second impact. Preserve all six dimension rows and availability reasons for inspection. Add a regression test that a single evaluation leaves one TAM English event, one weight contribution, and one estimate impact—not two. This policy must not edit `seed-v1`, create a fifteenth competency, or change any target/confidence/trend/recency constant.
- [ ] Add red tests proving Phase 1 evidence evaluation appends raw rubric/evidence rows and invokes the Task 9 progress hook but creates **no** `SkillSnapshot`; `RecordEvaluationResponse.snapshot_ids` is empty. Preserve the existing per-evaluation snapshot behavior only for an owner whose active roadmap is legacy v1.
- [ ] Add `POST /api/v1/evidence/weekly-publications` and a transaction-scoped `publish_weekly_estimates` service. Its idempotent command requires active phase run, period key, evidence cutoff, immutable weekly-review vault-relative ref, fourteen explicit self-score entries (nullable only as `Not assessed`), and, for `week_6` or `week_7_completion`, the ID of a completed `phase_transition_refresh` imported by Task 7. It locks owner/run, proves the refresh belongs to the same run and raw pinned-schema lineage, captures an evidence-event watermark, computes all fourteen estimates and reviewer scores from eligible events using the pinned scoring seed, writes exactly fourteen linked `SkillSnapshot` rows, stores the six English-dimension self/reviewer availability summaries, and records the publication hash in one transaction. A client-supplied priorities ref without that validated refresh is rejected.
- [ ] Enforce one immutable publication per `(phase_run_id, period_key)`. Allow `week_1` through `week_6` and at most one `week_7_completion`; the latter is required after Week 7 retest evidence before the run can close. Same idempotency key/payload replays the saved response; another payload for a published period returns 409. Late evidence never rewrites a publication and appears in the next one with explicit provenance.
- [ ] Make skill/evidence reads use the latest published weekly snapshot for an active Phase 1 run. Between publications, raw daily evidence and a `pending_next_weekly_publication` count may change, but displayed estimate, confidence, trend, recency, and target gap do not. Daily activity completion, daily scorecards, and Attempt B can never publish or silently refresh an estimate.
- [ ] Require the weekly publication at each Saturday close in the runtime contract tests. Before Week 6 publication, regenerate the canonical Obsidian raw export with a schema-valid completed `next_phase_priorities` object and import it through `refresh-phase-transition`; the publication links that persisted refresh and only then completes the coverage gate through `PhaseProgressService`. If Week 7 activates, regenerate after the retest and require a newer completed refresh linked to the Week 6 refresh. A bare ref, pending refresh, stale refresh, or publication without all four canonical-assessment states cannot close Phase 1; ordinary weekly snapshots may still publish without claiming closure.
- [ ] Extend skill/evidence responses with separate `self_score`, `reviewer_score`, their basis/provenance, and the six English dimension states/scores. Keep formula weights, the fourteen skill targets, confidence, trend, recency, and compatibility field names unchanged.
- [ ] Run:

```bash
uv run pytest \
  apps/backend/tests/unit/evidence/test_qualification.py \
  apps/backend/tests/unit/evidence/test_evidence_service.py \
  apps/backend/tests/unit/evidence/test_evidence_routes.py \
  apps/backend/tests/unit/evidence/test_skill_estimate.py \
  apps/backend/tests/unit/evidence/test_english_dimensions.py \
  apps/backend/tests/unit/evidence/test_weekly_publication.py -q
```

- [ ] Defer the scoring-lineage integration test to Task 13.
- [ ] Commit:

```bash
git add apps/backend/src/tamforge_backend/evidence apps/backend/tests/unit/evidence \
  apps/backend/tests/integration/evidence/test_phase1_scoring_lineage.py
git commit -m "feat: publish Phase 1 estimates weekly"
```

## Task 11: Make the Phase 1 workflow executable in the web UI

**Files:**

- Modify: `apps/backend/src/tamforge_backend/roadmaps/ports.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/routes.py`
- Modify: `apps/backend/src/tamforge_backend/today/schemas.py`
- Modify: `apps/backend/src/tamforge_backend/evidence/schemas.py`
- Regenerate in Task 12: `apps/web/src/api/schema.d.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/features/activities/api.ts`
- Modify: `apps/web/src/features/activities/ActivityWorkspacePage.tsx`
- Modify: `apps/web/src/features/activities/UniversalOutputEditor.tsx`
- Create: `apps/web/src/features/activities/InterviewCyclePanel.tsx`
- Create: `apps/web/src/features/pipeline/PipelineWeekPanel.tsx`
- Create: `apps/web/src/features/evidence/WeeklyPublicationPage.tsx`
- Modify: `apps/web/src/features/evidence/SkillEstimateCard.tsx`
- Modify: `apps/web/src/features/evidence/EvidenceLedgerPage.tsx`
- Modify: `apps/web/src/features/roadmaps/ActivationGate.tsx`
- Modify: `apps/web/src/features/roadmaps/RoadmapImportPage.tsx`
- Modify: `apps/web/src/features/roadmaps/SemanticDiff.tsx`
- Modify: `apps/web/src/features/today/TodayPage.tsx`
- Modify: `apps/web/src/features/today/TaskCard.tsx`
- Create: `scripts/dev/seed_phase1_demo.py`
- Create: `scripts/dev/tests/test_seed_phase1_demo.py`
- Modify: `apps/web/tests/evidence/EvidenceLedgerPage.test.tsx`
- Create: `apps/web/tests/evidence/WeeklyPublicationPage.test.tsx`
- Create: `apps/web/tests/activities/InterviewCyclePanel.test.tsx`
- Create: `apps/web/tests/activities/PipelineOutputEditor.test.tsx`
- Create: `apps/web/tests/pipeline/PipelineWeekPanel.test.tsx`
- Modify: `apps/web/tests/roadmaps/RoadmapImportPage.test.tsx`
- Modify: `apps/web/tests/roadmaps/SemanticDiff.test.tsx`
- Modify: `apps/web/tests/today/TodayPage.test.tsx`
- Create: `apps/web/e2e/phase1-workflow.spec.ts`
- Create: `apps/web/e2e/support/phase1.ts`

- [ ] First update the frontend tests so active v2 responses expect:

  - `TAM Study Phase 1 · Week N · Day N`, never `Month 1`, in Today;
  - `Phase 1 target — six weeks` and `X to Phase 1 target — six weeks` in evidence cards;
  - release/program names on stage, diff, approve, and activate controls;
  - a visible same-month predecessor warning that promises historical preservation, not a previous-month exit gate;
  - coverage summary with orphan/duplicate counts and a disabled activation button until transition import is ready;
  - Week 7 as `available`, `provisional`, or `active`, never as a seventh nominal week;
  - four weekday blocks and the correction-within-roadmap indicator;
  - the next interview queue question without marking elapsed pre-activation questions overdue;
  - an interview-cycle panel that cannot submit the coach handoff before self-review, cannot submit Attempt B before the handoff, and never lets the coach task claim Attempt B;
  - a multi-row pipeline editor plus weekly target/count/gap, application-versus-reply split, stage conversion, excluded reasons, and exact next actions;
  - a weekly-publication form/read view with all fourteen separate self/reviewer scores, level/confidence/trend/recency/gap, six English dimension availability rows, and the latest validated next-phase-priorities refresh state; Week 6/7 submit remains disabled until the required completed refresh exists.

- [ ] Run the focused tests and expect failures against the legacy-only UI/workflow:

```bash
pnpm --filter @tam-forge/web test -- --run \
  tests/evidence/EvidenceLedgerPage.test.tsx \
  tests/evidence/WeeklyPublicationPage.test.tsx \
  tests/activities/InterviewCyclePanel.test.tsx \
  tests/activities/PipelineOutputEditor.test.tsx \
  tests/pipeline/PipelineWeekPanel.test.tsx \
  tests/roadmaps/RoadmapImportPage.test.tsx \
  tests/roadmaps/SemanticDiff.test.tsx \
  tests/today/TodayPage.test.tsx
```

- [ ] Add program metadata to `RoadmapVersionResponse`, Today, and evidence response envelopes. Derive it from the immutable normalized payload/active phase run, not UI string inference from `month_number`.
- [ ] Update the React components to use server-provided `display_name` and `target_label`. Keep legacy rendering as `Month {month_number}` only when program metadata is absent on a historical v1 response.
- [ ] In `SemanticDiff`, render metadata and coverage reconciliation before raw added/removed task counts so the Phase 1 migration is intelligible.
- [ ] In `TaskCard`, label the four v2 blocks as Interview practice, Career pipeline, Roadmap unit, and Daily close while retaining legacy labels for historical tasks.
- [ ] Add typed client calls for coach handoff, interview completion, pipeline stage events, weekly pipeline summary, latest transition-refresh status, and weekly publication. `InterviewCyclePanel` shows the producer-approved fresh-Codex prompt/handoff contract, accepts only a handoff ref after self-review, then separately captures Attempt B recording/transcript/analysis/note refs. It must make the state boundary and nonqualifying Attempt B visible.
- [ ] Make `UniversalOutputEditor` select legacy singular pipeline output only for v1 activities. For the Phase 1 v2 contract, let the learner add one or more independent action rows with all quality fields, preserve excluded actions visibly, and never present two actions as a daily pass/fail gate.
- [ ] Add `PipelineWeekPanel` to Today/weekly review using server-derived counts and stage events, not client counting. Add `WeeklyPublicationPage` for the immutable Saturday publication, separate fourteen-skill self/reviewer inputs/readback, six English-dimension availability, and the latest server-validated transition refresh. Show the exact Codex/CLI refresh action when pending, never accept priority prose or a bare ref in the browser, and send only the returned refresh ID when closure-ready. Week 7 uses `week_7_completion`, not a seventh nominal roadmap week.
- [ ] Add `phase1-workflow.spec.ts` covering the actual browser journey: Attempt A → self-review → coach handoff → separate Attempt B; two different pipeline actions in one block and a later stage transition; Saturday weekly publication with separate self/reviewer results and English `N/A`; refusal to close from a bare priorities ref or pending/stale refresh; successful Week 6 closure after a validated completed raw-export refresh; and, when Week 7 is active, refusal until a newer post-retest refresh exists. Seed only the isolated `tamforge_test` database.
- [ ] Add a fail-closed `seed_phase1_demo.py` used only by the browser test. It must require `TAMFORGE_ENV=test`, the exact local `tamforge_test` database, the validated Phase 1 release and raw regression fixture, and must refuse production-like URLs. It may establish the approved/staged/active fixture state directly for test setup, but it cannot add a test-login or transition-bypass route to the application.
- [ ] Re-run all focused frontend tests and expect green. The Playwright test is written now but runs only in Task 13's approved database gate.
- [ ] Commit backend response and UI source/tests together, but leave generated OpenAPI types for Task 12:

```bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/src/tamforge_backend/today \
  apps/backend/src/tamforge_backend/evidence/schemas.py apps/web/src/App.tsx \
  apps/web/src/features apps/web/tests apps/web/e2e/phase1-workflow.spec.ts \
  apps/web/e2e/support/phase1.ts scripts/dev/seed_phase1_demo.py \
  scripts/dev/tests/test_seed_phase1_demo.py
git commit -m "feat: present six-week Phase 1 in TAM Forge"
```

## Task 12: Regenerate OpenAPI and run all focused non-Docker verification

**Files:**

- Regenerate: `apps/web/src/api/schema.d.ts`
- Modify if needed: `scripts/ci/check_openapi.py`
- Modify if needed: `apps/backend/tests/unit/test_schema_lifecycle.py`

- [ ] Generate the checked-in TypeScript client from FastAPI:

```bash
uv run python scripts/ci/check_openapi.py --write
uv run python scripts/ci/check_openapi.py
```

  Expected final line: `OpenAPI client types match the backend schema.`

- [ ] Review the generated diff. Confirm `month_one_target` and `month_one_target_gap` remain, while target/program/coverage/Week 7 fields are additive.
- [ ] Run the complete focused backend slice without integration markers:

```bash
uv run pytest \
  apps/backend/tests/unit/evidence/test_config_loader.py \
  apps/backend/tests/unit/evidence/test_phase1_config_loader.py \
  apps/backend/tests/unit/evidence/test_qualification.py \
  apps/backend/tests/unit/evidence/test_evidence_service.py \
  apps/backend/tests/unit/evidence/test_skill_estimate.py \
  apps/backend/tests/unit/evidence/test_english_dimensions.py \
  apps/backend/tests/unit/roadmaps \
  apps/backend/tests/unit/learning/test_phase1_interview_workflow.py \
  apps/backend/tests/unit/learning/test_phase1_pipeline.py \
  apps/backend/tests/unit/learning/test_time_policy.py \
  apps/backend/tests/unit/learning/test_timers.py \
  apps/backend/tests/unit/learning/test_scheduling.py \
  apps/backend/tests/unit/today -q
```

  Expected: all selected tests pass; no skip should hide a unit test.

- [ ] Run static verification:

```bash
uv run ruff check apps/backend/src apps/backend/tests scripts/ci/check_openapi.py
uv run mypy apps/backend/src
MYPYPATH=apps/backend/src:packages/protocol/src uv run mypy scripts/dev/seed_phase1_demo.py
pnpm --filter @tam-forge/web lint
pnpm --filter @tam-forge/web typecheck
pnpm --filter @tam-forge/web test -- --run \
  tests/evidence/EvidenceLedgerPage.test.tsx \
  tests/evidence/WeeklyPublicationPage.test.tsx \
  tests/activities/InterviewCyclePanel.test.tsx \
  tests/activities/PipelineOutputEditor.test.tsx \
  tests/pipeline/PipelineWeekPanel.test.tsx \
  tests/roadmaps/RoadmapImportPage.test.tsx \
  tests/roadmaps/SemanticDiff.test.tsx \
  tests/today/TodayPage.test.tsx
uv run python scripts/ci/check_repository_policy.py
```

- [ ] Run the repository's complete non-Docker gate so new files cannot evade an omitted focused list:

```bash
make check
```

- [ ] Re-run the release validators and byte freeze:

```bash
uv run tamforge validate-roadmap-map --config config/tam-roadmap-task-map.yaml
uv run tamforge validate-roadmap-release \
  --release-dir config/releases/phase-1-six-week-v1 \
  --legacy-config-dir config
uv run pytest apps/backend/tests/unit/evidence/test_phase1_config_loader.py -q
```

- [ ] Commit generated types and any deterministic schema-lifecycle adjustment:

```bash
git add apps/web/src/api/schema.d.ts scripts/ci/check_openapi.py \
  apps/backend/tests/unit/test_schema_lifecycle.py
git commit -m "chore: regenerate Phase 1 API contract"
```

## Task 13: Approval-gated PostgreSQL migration and integration verification

This task is deliberately blocked on explicit user approval because it may start Docker/Compose or use a PostgreSQL test service.

- [ ] Before touching Docker, tell the user exactly: `The remaining verification runs Alembic and PostgreSQL integration tests and may start Docker on this 8 GB Mac. May I run that focused database suite now?` Wait for an explicit yes.
- [ ] After approval, start only the repository's test database path. Do not run an unfiltered suite that can start unrelated containers.
- [ ] Run the migration and Phase 1 integration slice:

```bash
uv run pytest -m integration \
  apps/backend/tests/integration/roadmaps/test_phase1_runtime_migration.py \
  apps/backend/tests/integration/roadmaps/test_phase1_transition.py \
  apps/backend/tests/integration/learning/test_phase1_study_day_creation.py \
  apps/backend/tests/integration/learning/test_phase1_pipeline.py \
  apps/backend/tests/integration/evidence/test_phase1_scoring_lineage.py \
  apps/backend/tests/integration/roadmaps/test_phase1_progress_atomicity.py \
  apps/backend/tests/integration/roadmaps/test_import_flow.py \
  apps/backend/tests/integration/test_migrations.py -q
TEST_DATABASE_URL=postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test \
  pnpm --filter @tam-forge/web exec playwright test e2e/phase1-workflow.spec.ts
```

  Expected: all selected integration tests and the complete Phase 1 browser journey pass against the explicitly validated isolated test database.

- [ ] In that focused slice, require explicit assertions for both sides of the closure boundary: pinned-schema drift and a bare/pending/stale priorities ref are refused; a valid completed Week 6 raw refresh closes once; an idempotent replay creates no row; and an active Week 7 refuses the Week 6 refresh until a newer post-retest refresh is imported. Also assert one evaluation with English-dimension metadata creates exactly one `tam_english` evidence impact.

- [ ] Prove upgrade → exercise → downgrade refusal with live Phase 1 data, then remove only the test data through test teardown and prove downgrade/upgrade round-trip on an empty test database.
- [ ] Stop only services started for this task, verify no TAM Forge containers remain, and close Docker Desktop.
- [ ] Record exact test count, elapsed time, database target classification, and cleanup result in the PR description; do not call absent CI green.
- [ ] If integration fixes are required, use a focused commit:

```bash
git add apps/backend apps/web
git commit -m "test: verify Phase 1 runtime migration"
```

## Task 14: Final audit, review, and pull-request handoff

- [ ] Inspect `git diff --check` and `git status --short`; expected result is no whitespace error and only intentional files before the final commit.
- [ ] Re-run `shasum -a 256` for all four root config files and compare with the locked table.
- [ ] Search active Phase 1 release/task/UI text:

```bash
rg -n "Claude|Month 1 target|240|255" \
  config/releases/phase-1-six-week-v1 \
  apps/web/src/features \
  apps/backend/src/tamforge_backend
```

  Classify every hit. Historical v1 compatibility, stored field names, and legacy policy constants may remain; active Phase 1 labels/contracts must have no Claude instruction and no 240/255 budget.

- [ ] Audit the normalized release and **raw, schema-validated** transition input against all 18 design acceptance criteria. In particular, confirm the supplied v1 schema equals the packaged pinned schema byte-for-byte; exact target preservation; six Saturday contracts; all 30 numeric segment assignments with Q30 in segment 6; no retroactive obligations; future-only capacity; no duplicate coverage owner; pending → validated Week 6 → newer Week 7 transition-refresh lineage; six English-dimension availability with separate self/reviewer reporting and exactly one TAM English impact per evaluation; multi-action pipeline target/conversion; executable interview handoff/Attempt B; one-roadmap-unit carryover; and Week 7 closure/publication states.
- [ ] Request an independent code review of the exact final head. Address findings with new focused tests and commits; do not amend already-reviewed history casually.
- [ ] Push the branch and open a PR that links both the approved design and the implemented Obsidian plan. The PR must state:

  - root configuration remained byte-identical;
  - Phase 1 is a roadmap-only release and did not seed scoring;
  - current Day 1–3 evidence was imported without invented time;
  - unit/static/OpenAPI results;
  - database integration result, or clearly `not run — approval not granted`;
  - Docker cleanup result when applicable;
  - activation is not deployment and no production data was changed.

- [ ] Bind reviewer approval and CI to the exact final head. Stop before merge and ask the user for explicit approval.

## Execution order and rollback

Execute Tasks 1–5 first; they are reversible configuration/parser work and cannot change persisted study state. Execute Task 6's migration code next, then Tasks 7–11. Run Task 12 before requesting the Task 13 database approval.

The operational activation sequence after merge is intentionally separate from implementation:

1. Validate the v2 release and canonical Obsidian package locally.
2. Stage the package with `roadmap_release_key=phase-1-six-week-v1`.
3. Inspect the config pin, semantic diff, and zero-orphan coverage report.
4. Approve the immutable roadmap version; do not activate yet.
5. Run the canonical-vault producer in `--write` and `--check` modes, then review the fresh raw schema, raw JSON, and `.sha256` sidecar together; the captured Day 1–3 package remains regression-only.
6. Dry-run those exact three producer artifacts against the live vault source hashes, inspect future-only capacity, and apply the same JSON bytes to create the staged phase run without translation or envelope rewriting.
7. Activate the same-month Phase 1 version atomically.
8. Verify Today resolves the current future session, 180-minute policy, queue ordinal 1, preserved old study history, and the saved Day 3 idempotency checkpoint.
9. Before Week 6 closure, complete the canonical Obsidian priorities gate, regenerate/check the raw export, run `refresh-phase-transition --apply`, and publish only with the returned completed refresh ID.
10. If Week 7 activates, repeat the raw export/check/refresh after the retest and require that newer refresh for `week_7_completion`.

Rollback before activation means reject/leave the new approved version inactive; no history changes. After activation, rollback means activate a separately approved predecessor-compatible version and preserve the Phase 1 run as historical. Never mutate or delete an imported roadmap version, phase-run evidence, coverage progress, study day, attempt, or score to simulate rollback.
