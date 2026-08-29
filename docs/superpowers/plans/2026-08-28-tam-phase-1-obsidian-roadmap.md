# TAM Phase 1 Obsidian Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the active four-week Month 1 Obsidian roadmap with the approved six-week Phase 1 roadmap, preserve the exact former roadmap as a checksum-verified archive, preserve Day 1–3 evidence and status honestly, and make every future study session, interview handoff, pipeline action, evidence decision, and flashcard-ready note executable from the vault.

**Architecture:** Obsidian remains the canonical human-editable source. The current `Roadmap/` directory is renamed intact to an immutable archive before a clean active `Roadmap/` tree is created. A coverage ledger maps all 158 legacy stable task IDs to one Phase 1 owner and evidence state; a separate transition ledger owns historical status and future capacity. Six weekly notes own the executable calendar, while the complete-roadmap note and focused templates define shared contracts without duplicating status. A deterministic companion export under vault-root `Exports/` is generated from those Obsidian authorities, schema-validated, content-hashed, and passed to TAM Forge separately from the Markdown/SQL roadmap package. Existing `Docs/` artifacts remain evidence; only their stale roadmap links and explicit lineage pointers change.

**Tech Stack:** Obsidian Flavored Markdown, YAML frontmatter, wikilinks, CommonMark tables and callouts, canonical JSON, JSON Schema Draft 2020-12, SHA-256, POSIX shell read-only checks, `shasum`, `rg`, and Python 3 with PyYAML for deterministic generation and cross-file validation.

---

## Scope, fixed paths, and stop conditions

**Approved design:** `docs/superpowers/specs/2026-08-28-tam-study-phase-1-six-week-redesign.md`

**Vault:** `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice`

**Legacy configuration used only for lineage validation:** `/Users/frank/Documents/ChatGPT/TAM Project/config/tam-roadmap-task-map.yaml`

**Legacy target source used only for value validation:** `/Users/frank/Documents/ChatGPT/TAM Project/config/tam-skills.yaml`

**Canonical TAM Forge transition input:** `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.json`

**Transition schema:** `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.schema.json`

**Transition content hash:** `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/phase-1-transition-v1.json.sha256`

**TAM Forge consumer plan:** `/Users/frank/Documents/ChatGPT/TAM Project/docs/superpowers/plans/2026-08-28-tam-forge-phase-1-sync.md`

**Exact archive destination:** `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2`

**Exact archive checksum file:** `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256`

Non-negotiable execution rules:

- [ ] Do not edit the vault until Task 1 has proved the active source exists, the archive destination does not exist, all source files are readable, and the deterministic source manifest contains exactly 21 files.
- [ ] Stop if iCloud returns an unreadable or zero-byte placeholder, if the archive or checksum path already exists, or if the source has changed from the inspected 21-file Version 2 tree. Reconcile; never overwrite or merge archives.
- [ ] Use `apply_patch` for textual vault changes. `mv` is authorized only for the one exact directory rename below; `cp` is authorized only for byte-identical reuse of the archived `cases/` and `sql/` assets. Do not use shell redirection, `cat`, or an editor script to write prose.
- [ ] Never modify either `Roadmap.backup-20260825-090253` or `Roadmap.backup-20260825-115232`.
- [ ] After the rename, treat `Roadmap.archive-20260828-month1-v2/` as immutable. Every later checkpoint must re-run its checksum verification.
- [ ] The vault is not Git-backed. Do not create commits for vault checkpoints. Use the checksum manifest, validation output, and the active redesign-change note instead.
- [ ] Do not reset completed work, infer unknown historical minutes, manufacture scores, or mark missing spoken artifacts complete.
- [ ] Do not run Docker, Testcontainers, Compose, PostgreSQL setup, or the Docker alternative shown in the archived README. This plan needs only file-level checks.
- [ ] Active Phase 1 learning material must use Codex only. Archived Version 2 may retain historical wording, including its old Claude template.
- [ ] Sunday stays entirely absent from study, catch-up, pipeline, and reminder schedules.
- [ ] Never hand-edit `Exports/phase-1-transition-v1.json` or its `.sha256`. They are deterministic generated artifacts. Change the authoritative Obsidian ledger/schedule note, run the generator, then run its independent `--check` mode.
- [ ] Keep vault-root `Exports/` outside the normal roadmap ZIP. The current TAM Forge package inspector accepts Markdown and SQL, not JSON. The transition JSON and `.sha256` are a separate activation input; the schema and generator remain validation assets and are not uploaded as roadmap-package members.
- [ ] `phase-1-transition-v1.json` has one producer/consumer contract. TAM Forge consumes the exact raw JSON bytes defined in Task 12 after verifying this schema, its sidecar, and live source hashes. Do not rename fields, wrap the payload, redact it into a second envelope, or maintain a parallel transition schema. Runtime normalization may occur only after the raw v1 input validates.

## Canonical active file tree

Create exactly this active structure. The `cases/` and `sql/` files are byte-identical copies from the archive; every other listed active file is created or rewritten for Phase 1.

```text
Roadmap/
├── README.md
├── Phase 1 - Week 1 - Transition, foundations, and baseline.md
├── Phase 1 - Week 2 - Webhooks, discovery, and retry control.md
├── Phase 1 - Week 3 - Distributed failures, incidents, and payments.md
├── Phase 1 - Week 4 - OAuth, observability, and midpoint transfer.md
├── Phase 1 - Week 5 - Implementation, account strategy, and launch judgment.md
├── Phase 1 - Week 6 - QBR, portfolio judgment, and final assessment.md
├── cases/
│   ├── Northstar Case.md
│   └── Portfolio Triage Cases.md
├── docs/
│   ├── Phase 1 - Complete Roadmap.md
│   ├── Coverage Ledger.md
│   ├── Transition Ledger.md
│   ├── Interview Queue.md
│   ├── Next Phase Priorities.md
│   ├── Package Contents.md
│   ├── Portfolio Judgment Track.md
│   └── 2026-08-28 - Phase 1 Six-Week Redesign Changes.md
├── sql/
│   ├── setup.sql
│   └── tasks.md
└── templates/
    ├── account_plan.md
    ├── daily_scorecard.md
    ├── daily_study_index.md
    ├── discovery_notes.md
    ├── evidence_record.md
    ├── incident_update.md
    ├── interview_practice_record.md
    ├── polished_study_note.md
    ├── phase1_assessment.md
    ├── pipeline_action.md
    ├── portfolio_triage.md
    ├── real_interview_debrief.md
    ├── spoken_practice_session.md
    ├── story_catalog.md
    └── weekly_review.md
```

Create this companion tree at the vault root. It is visible from package documentation but is deliberately outside `Roadmap/` and excluded from the normal roadmap ZIP:

```text
Exports/
├── build_phase1_transition_export.py
├── test_phase1_transition_export.py
├── phase-1-transition-v1.schema.json
├── phase-1-transition-v1.json
└── phase-1-transition-v1.json.sha256
```

The active tree must not contain the old four `Week N - ...` filenames, `docs/Month 1 - Complete Roadmap.md`, `docs/Version 2 - Portfolio Judgment Changes.md`, or `templates/month1_assessment.md`. They remain available only in the immutable archive.

## Fixed transition facts

These values are facts, not values to recompute from assumed attendance:

| Item | Fixed value |
|---|---|
| Phase 1 nominal calendar | 2026-08-24 through 2026-10-03 |
| Activation cutoff | End of 2026-08-28 at the saved Day 3 checkpoint |
| First future block | Saturday 2026-08-29 baseline diagnostic, 120 minutes |
| First ordinary `60 + 120` weekday | Monday 2026-08-31 |
| Future weekday blocks | 25, from 2026-08-31 through 2026-10-02 |
| Future Saturday blocks | 6, from 2026-08-29 through 2026-10-03 |
| Future schedulable capacity | `25 × 180 + 6 × 120 = 5,220 minutes = 87 hours` |
| Nominal clean-run capacity | 102 hours; explanatory only, never added to the 87 future hours |
| Optional safety week | 2026-10-05 through 2026-10-10, only when an approved trigger is present |

The five elapsed weekday blocks from August 24–28 are reserved. Verified historical time is reporting evidence only; unknown time stays unknown and is never converted back into future capacity.

---

## Task 1: Prove and archive the exact Version 2 source

**Files:**

- Rename: `.../TAM Practice/Roadmap/` → `.../TAM Practice/Roadmap.archive-20260828-month1-v2/`
- Create with `apply_patch`: `.../TAM Practice/Roadmap.archive-20260828-month1-v2.sha256`

- [ ] **Run the read-only preflight.**

```bash
test -d '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap'
test ! -e '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2'
test ! -e '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256'
find '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap' -type f -size 0 -print
find '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap' -type f | wc -l
```

Expected: all `test` commands exit 0; the zero-byte search prints nothing; the count is exactly `21`. Any other result is a stop condition.

- [ ] **Prove the 21 paths are the inspected Version 2 source, not merely any 21 files.**

```bash
uv run python - <<'PY'
from pathlib import Path

root = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap')
expected = [
    'README.md',
    'Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md',
    'Week 2 - Distributed failures, incidents, and payments.md',
    'Week 3 - OAuth, observability, implementation, and account strategy.md',
    'Week 4 - Integrated interview performance and final assessment.md',
    'cases/Northstar Case.md',
    'cases/Portfolio Triage Cases.md',
    'docs/Month 1 - Complete Roadmap.md',
    'docs/Package Contents.md',
    'docs/Portfolio Judgment Track - Months 1 to 3.md',
    'docs/Version 2 - Portfolio Judgment Changes.md',
    'sql/setup.sql',
    'sql/tasks.md',
    'templates/account_plan.md',
    'templates/daily_scorecard.md',
    'templates/discovery_notes.md',
    'templates/incident_update.md',
    'templates/month1_assessment.md',
    'templates/portfolio_triage.md',
    'templates/spoken_practice_session.md',
    'templates/story_catalog.md',
]
actual = sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())
assert actual == sorted(expected), {
    'missing': sorted(set(expected) - set(actual)),
    'extra': sorted(set(actual) - set(expected)),
}
print('PASS: exact inspected 21-path Version 2 source tree')
PY
```

Expected: `PASS: exact inspected 21-path Version 2 source tree`. A different path set is a stop condition even when its count is 21.

- [ ] **Print the deterministic relative-path checksum manifest without writing yet.**

```bash
cd '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap'
find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256
```

Expected: exactly 21 checksum lines, all commands exit 0, and reading the files hydrates any iCloud placeholders.

- [ ] **Use `apply_patch` to create the `.sha256` file with exactly the 21 printed lines.** Do not put the manifest inside the directory being hashed. Re-run `wc -l` on the manifest; expected `21`.

- [ ] **Verify the source against the saved manifest before moving it.**

```bash
cd '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap'
shasum -a 256 -c '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256'
```

Expected: 21 `OK` lines and no failure.

- [ ] **Perform the one authorized rename, then immediately verify the archive.**

```bash
mv '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2'
cd '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2'
shasum -a 256 -c '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256'
test ! -e '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap'
```

Expected: 21 `OK` lines, no failure, and the old active path is absent. If verification fails after the move, stop; do not create or edit the active tree until the archive has been reconciled.

## Task 2: Scaffold the clean active tree and preserve reusable source assets

**Files:**

- Create directories: `Roadmap/`, `Roadmap/cases/`, `Roadmap/docs/`, `Roadmap/sql/`, `Roadmap/templates/`
- Copy byte-for-byte: archived `cases/*` and `sql/*` to the matching active directories

- [ ] **Create only the empty active directory structure.**

```bash
mkdir -p '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/cases'
mkdir -p '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs'
mkdir -p '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/sql'
mkdir -p '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates'
```

- [ ] **Copy only the case and SQL assets.** These are source data/exercises, not active scheduling prose.

```bash
cp '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/cases/Northstar Case.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/cases/Northstar Case.md'
cp '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/cases/Portfolio Triage Cases.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/cases/Portfolio Triage Cases.md'
cp '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/sql/setup.sql' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/sql/setup.sql'
cp '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/sql/tasks.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/sql/tasks.md'
```

- [ ] **Prove those four files are unchanged and prove the archive is still immutable.**

```bash
diff -u '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/cases/Northstar Case.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/cases/Northstar Case.md'
diff -u '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/cases/Portfolio Triage Cases.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/cases/Portfolio Triage Cases.md'
diff -u '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/sql/setup.sql' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/sql/setup.sql'
diff -u '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2/sql/tasks.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/sql/tasks.md'
cd '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2'
shasum -a 256 -c '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256'
```

Expected: every `diff` is silent; the archive returns 21 `OK` lines.

## Task 3: Create the active index, package contract, and migration record

**Files:**

- Create: `Roadmap/README.md`
- Create: `Roadmap/docs/Package Contents.md`
- Create: `Roadmap/docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md`

- [ ] **Write `Roadmap/README.md` with `apply_patch`.** It must contain:

  - frontmatter: `type: roadmap-index`, `phase: 1`, `version: phase-1-six-week-v1`, `source-revision: 3`, `status: active`, `start: 2026-08-24`, `nominal-end: 2026-10-03`, `future-app-source: true`;
  - the fixed cadence: 180 minutes Monday–Friday, 120 Saturday, Sunday off;
  - a visible distinction between 102 nominal clean-run hours and 87 future schedulable hours at activation;
  - links to all six weekly files, every operating record (`Coverage`, `Transition`, `Interview Queue`, `Next Phase Priorities`, `Portfolio Judgment`, and package/change notes), the complete roadmap, case and SQL assets, every active template including polished study notes and real-interview debriefs, and the separate vault-root transition export/schema/hash;
  - `Current checkpoint`: Day 3 SQLBolt 9–12 reported complete with guided review; idempotency application and teach-back pending; first future block August 29;
  - `Historical source`: a link to `[[Roadmap.archive-20260828-month1-v2/README|Archived Month 1 Version 2]]` and the checksum filename;
  - all seven preserved practice rules from design §7.1, including English output, at least 70% output time, independent work before AI, no new resources, one review/one redo maximum, privacy, and Sunday off;
  - the Phase 1 exit-state definitions and Week 7 activation summary.

- [ ] **Write `Roadmap/docs/Package Contents.md`.** Enumerate the exact active tree above, distinguish byte-identical case/SQL assets from rewritten schedule/templates, and state that the archive is historical and must not be edited. Add a separate `Activation companion, not roadmap ZIP content` section that lists `Exports/phase-1-transition-v1.json`, `.sha256`, `.schema.json`, the generator, and its test. State unambiguously that the regular TAM Forge roadmap ZIP contains only the supported `Roadmap/**/*.md` and `Roadmap/**/*.sql` members; it excludes vault-root `Exports/`. TAM Forge receives the exact raw canonical JSON bytes and their `.sha256` through the separate transition-activation path defined by the synchronization plan; no transformed, redacted, renamed-field, or parallel-envelope transition input is permitted.

- [ ] **Write `Roadmap/docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md`.** Record:

  - approved design path and date;
  - exact archive path and checksum-manifest path;
  - the actual 21-file checksum verification result from Task 1;
  - activation cutoff, first future block, first ordinary weekday, and `5,220 minutes / 87 hours` future capacity;
  - framing change from Month 1/four weeks to Phase 1/six weeks with unchanged numeric targets and unchanged required coverage;
  - Codex-only active spoken workflow;
  - Day 1–3 migration principles: preserve facts, do not infer time, do not retroactively require interview cycles;
  - links to `Coverage Ledger`, `Transition Ledger`, active README, approved design, and archived README;
  - the export boundary: Obsidian Markdown remains authoritative, `Exports/phase-1-transition-v1.json` is the generated TAM Forge transition input, its `.sha256` binds exact bytes, and it is not a roadmap-package member;
  - the single-schema boundary: the TAM Forge importer consumes that raw v1 JSON contract directly, with no second envelope or field translation;
  - a rollback instruction: remove or relocate only the newly created active `Roadmap/` after explicit approval, then rename the verified archive back. Do not execute rollback as part of this plan.

- [ ] **Run the first content check.**

```bash
rg -n 'phase-1-six-week-v1|87 hours|2026-08-29|2026-08-31|Roadmap.archive-20260828-month1-v2' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/README.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md'
rg -n -i '\bclaude\b' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/README.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Package Contents.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md'
```

Expected: the first command finds every fixed transition term; the second prints nothing.

## Task 4: Build the 158-record coverage ledger before writing the future schedule

**Files:**

- Create: `Roadmap/docs/Coverage Ledger.md`
- Read only: `config/tam-roadmap-task-map.yaml`

The ledger is the migration authority. Weekly notes may summarize it but may not invent a second status for a legacy requirement.

- [ ] **Create the ledger header and schema with `apply_patch`.** Use frontmatter:

```yaml
---
title: Phase 1 Coverage Ledger
type: coverage-ledger
phase: 1
roadmap-version: phase-1-six-week-v1
legacy-roadmap-version: month-1-v2
mapping-version: phase-1-transition-v1
status: active
future-app-source: true
---
```

Define exactly these semantics:

| Field | Rule |
|---|---|
| Legacy ID | Exact `stable_id` from `config/tam-roadmap-task-map.yaml`; unique and never renamed |
| Required | Exact legacy required flag; omitted means true |
| Source path | Exact legacy day `source_path`; it must equal the YAML value and one of the four archived weekly filenames |
| Source heading | Exact legacy day `source_heading`; it must equal the YAML value |
| Objective/output | Preserve the legacy objective and contract output; shorter display wording may link to a verbatim detail block |
| Original constraint | Preserve assessment/no-AI/independence/AI-role constraint |
| Status | One of `completed`, `in_progress`, `pending`, `not_assessed` |
| Phase owner | Exactly one atomic Phase 1 owner ID owns completion: an imported owner or one scheduled interview/pipeline/roadmap/close/Saturday session ID |
| Continuation | Either `—` or one exact aligned session ID; never a list and never a second completion owner |
| Planned/actual | Planned is one non-negative integer for the new atomic work; actual is one non-negative integer or `unknown` until measured |
| Evidence | Existing or future Obsidian links |
| Qualification | `qualifying`, `nonqualifying`, `mixed`, `not_assessed`, or `not_applicable` |
| Reconciliation | Why splitting, integration, wording, timing, or optional skip preserves coverage |

- [ ] **Add one machine-readable Markdown row for every legacy ID.** Use this exact column order so validation remains stable:

```markdown
| Legacy ID | Required | Source path | Source heading | Objective/output | Original constraint | Status | Phase owner | Continuation | Planned min | Actual min | Evidence | Qualification | Reconciliation |
|---|---:|---|---|---|---|---|---|---|---:|---:|---|---|---|
| `m1-w1-d01-sql` | true | `Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md` | `Day 1 — Baseline and HTTP` | ... | ... | `completed` | `IMPORT-2026-08-25-D01` | — | 45 | 40 | [[Docs/Day 1 - SQL Foundations Study Notes]] | `mixed` | Completion preserved; only demonstrated dimensions may qualify. |
```

For deterministic parsing, every data row must have exactly fourteen cells. Escape a literal pipe in prose as `\|`; do not use aliased wikilinks inside table cells because their pipe would become a cell delimiter. `Required` is exactly `true` or `false`. `Status` and `Qualification` use only the enums above. `Phase owner` contains one token only—never commas, `+`, `/`, or prose—and must match one of:

```text
IMPORT-2026-08-25-D01
IMPORT-2026-08-27-D02
IMPORT-2026-08-28-D03
P1-YYYY-MM-DD-I60
P1-YYYY-MM-DD-MOCK60
P1-YYYY-MM-DD-P30
P1-YYYY-MM-DD-R75
P1-YYYY-MM-DD-C15
P1-YYYY-MM-DD-SAT120
```

An import owner is valid only for evidence actually present at activation. All other owner IDs must exist in the machine-readable weekly schedule. `Continuation` is `—` or exactly one of those scheduled IDs. Several legacy requirements may be integrated into one atomic scheduled owner, but one legacy row may never claim multiple completion owners.

Every row must also have exactly one matching detail heading `### m1-wN-dNN-slug`. The detail heading is the stable Obsidian backlink target and carries any objective, output, constraint, evidence, or continuation prose that does not fit legibly in the table. A detail block may explain integration, but it may not override the machine-readable status, owner, time, or qualification in the table.

Immediately below every detail heading, add exactly one canonical one-line contract comment:

```markdown
<!-- coverage-contract {"allowed_ai_role":"tutor","constraints":["..."],"contract":"sql","exercise_type":"sql_guided_lesson","legacy_id":"m1-w1-d01-sql","objective":"Complete SQLBolt lessons 1–4 without copying.","pass_criteria":["..."],"required_output":["..."],"timebox_minutes":45} -->
```

Build this object only from the matching task and its referenced contract in `config/tam-roadmap-task-map.yaml`. Serialize it with `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))`; do not reword, omit, or reorder array values. This comment is the exact machine-readable preservation proof for the legacy objective, required outputs, pass criteria, AI/assessment constraints, allowed AI role, exercise type, contract, and original timebox. Human-readable detail may follow it, but cannot replace it.

- [ ] **Populate source facts from YAML, then assign Phase owners from the approved six-week architecture.** Do not hand-invent a stable ID, source heading, objective, required flag, contract, or allowed AI role. The mapping must follow these owner bands:

| Legacy coverage | Phase 1 owner band |
|---|---|
| Days 1–3 completed/current work | Imported transition records in Week 1; unfinished components begin 2026-08-31 |
| Remainder of Days 4–5 and start of Days 7–8 | Week 2, 2026-08-31 through 2026-09-04 |
| Finish Days 8–11 | Week 3, 2026-09-07 through 2026-09-11 plus deliberate continuation into Week 4 where the ledger requires it |
| Days 13–15 and start Day 16 | Week 4, 2026-09-14 through 2026-09-18 |
| Finish Days 16–17 and begin Days 19–20 | Week 5, 2026-09-21 through 2026-09-25 |
| Finish Days 20–23 | Week 6, 2026-09-28 through 2026-10-02 |
| Legacy Day 6 assessment | Saturday 2026-09-05 |
| Legacy Day 12 assessment | Saturday 2026-09-12 |
| Legacy Day 18 assessment | Saturday 2026-09-26 |
| Legacy Day 24 final assessment | Saturday 2026-10-03 |

The two new diagnostic Saturdays have new Phase 1 session IDs, not fabricated legacy IDs. They link to the exit criteria and evidence records separately.

- [ ] **Apply the exact Day 1–3 import states.** Coverage status and evidence qualification are separate.

  **Day 1**

  - SQL: `completed`; only 40 focused minutes and 45–50 elapsed minutes are verified from `Day 1 - SQL Foundations Study Notes`; full-day actual remains unknown.
  - HTTP/technical: `completed`; the artifact was finished across Days 1–2; do not count it twice.
  - Case: case artifact and coached practice `completed`; the missing uninterrupted final recording stays explicitly absent/nonqualifying rather than resetting the completed case artifact.
  - Communication/Tell Me About Yourself: `pending` and `not_assessed`; it was skipped as a one-time exception, receives no retroactive pipeline failure, and returns as Interview Queue `P1-Q01` on 2026-08-31.
  - Pipeline: `completed` as the market-requirements artifact; do not mislabel it as five submitted applications.
  - Close: retrospective record exists, but dimensions are `not_assessed`; actual full-day time unknown.
  - Optional correction: `completed` only if recorded as not due/skipped without replacement; it contributes no evidence.

  **Day 2**

  - SQL joins/`NULL` and HTTP troubleshooting: `completed`.
  - Northstar case: `completed` as guided work; qualification `nonqualifying` for independent performance.
  - Story catalog and story-to-requirements mapping: `completed`.
  - Daily scorecard: `completed`; its accepted scores remain historical evidence and are not silently converted to current competency estimates.
  - Supplemental spoken-practice feedback: `pending`; no returned handoff, recording, or transcript may be inferred.
  - Full-day actual time: `unknown`.

  **Day 3**

  - SQLBolt lessons 9–12: `completed` by learner report with guided validation; elapsed time unknown.
  - Idempotency focused reading and closed-source recall: completed components of an `in_progress` technical record.
  - Idempotency application sequence and teach-back: pending exact checkpoint.
  - Northstar duplicate-order case, three audience-specific recordings, three résumé bullets, and daily close: `pending`.
  - Actual time: `unknown`.

- [ ] **Encode split/integrated work without double-counting.** A legacy case may name a 75-minute roadmap session as completion owner and an aligned interview session as its presentation/defense continuation. Record minutes once in the actual-time record. An interview answer may map evidence to several competencies, but it cannot create a second completion claim for the same legacy ID.

- [ ] **Validate exact ID set and row count.** The ledger table format above is required by this command.

```bash
uv run python - <<'PY'
from collections import Counter
import json
from pathlib import Path
import re
import yaml

config_path = Path('/Users/frank/Documents/ChatGPT/TAM Project/config/tam-roadmap-task-map.yaml')
ledger_path = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Coverage Ledger.md')
config = yaml.safe_load(config_path.read_text())
text = ledger_path.read_text()

def cells(line):
    values = re.split(r'(?<!\\)\|', line.strip()[1:-1])
    return [value.strip().replace(r'\|', '|') for value in values]

expected = {}
for day in config['days']:
    for task in day['tasks']:
        contract = config['contracts'][task['contract']]
        expected[task['stable_id']] = {
            'required': str(task.get('required', config['default_required'])).lower(),
            'source_path': day['source_path'],
            'source_heading': day['source_heading'],
            'contract_payload': {
                'allowed_ai_role': task['allowed_ai_role'],
                'constraints': contract['constraints'],
                'contract': task['contract'],
                'exercise_type': task.get('exercise_type'),
                'legacy_id': task['stable_id'],
                'objective': task['objective'],
                'pass_criteria': contract['pass_criteria'],
                'required_output': contract['required_output'],
                'timebox_minutes': task['timebox_minutes'],
            },
        }

rows = {}
for line in text.splitlines():
    if not re.match(r'^\| `m1-w[1-4]-d\d{2}-[a-z0-9-]+` \|', line):
        continue
    row = cells(line)
    assert len(row) == 14, (len(row), line)
    legacy_id = row[0].strip('`')
    assert legacy_id not in rows, legacy_id
    rows[legacy_id] = row

assert len(expected) == len(rows) == 158
assert set(rows) == set(expected), {
    'missing': sorted(set(expected) - set(rows)),
    'extra': sorted(set(rows) - set(expected)),
}

statuses = {'completed', 'in_progress', 'pending', 'not_assessed'}
qualifications = {'qualifying', 'nonqualifying', 'mixed', 'not_assessed', 'not_applicable'}
owner_pattern = re.compile(
    r'^(?:IMPORT-2026-08-(?:25-D01|27-D02|28-D03)|'
    r'P1-\d{4}-\d{2}-\d{2}-(?:I60|MOCK60|P30|R75|C15|SAT120))$'
)
for legacy_id, row in rows.items():
    required = row[1]
    source_path = row[2].strip('`')
    source_heading = row[3].strip('`')
    status = row[6].strip('`')
    owner = row[7].strip('`')
    continuation = row[8].strip('`')
    planned = row[9]
    actual = row[10]
    evidence = row[11]
    qualification = row[12].strip('`')
    reconciliation = row[13]
    fact = expected[legacy_id]
    assert required == fact['required'], (legacy_id, required, fact['required'])
    assert source_path == fact['source_path'], (legacy_id, source_path, fact['source_path'])
    assert source_heading == fact['source_heading'], (legacy_id, source_heading, fact['source_heading'])
    assert status in statuses, (legacy_id, status)
    assert qualification in qualifications, (legacy_id, qualification)
    assert owner_pattern.fullmatch(owner), (legacy_id, owner)
    assert continuation == '—' or owner_pattern.fullmatch(continuation), (legacy_id, continuation)
    assert re.fullmatch(r'\d+', planned) and int(planned) >= 0, (legacy_id, planned)
    assert actual == 'unknown' or (re.fullmatch(r'\d+', actual) and int(actual) >= 0), (legacy_id, actual)
    assert row[4] and row[5] and reconciliation, legacy_id
    if status == 'not_assessed':
        assert qualification == 'not_assessed', (legacy_id, status, qualification)
    if status == 'pending':
        assert qualification in {'not_assessed', 'not_applicable'}, (legacy_id, status, qualification)
    if status == 'completed':
        assert evidence != '—', (legacy_id, status, evidence)

detail_ids = re.findall(r'^### (m1-w[1-4]-d\d{2}-[a-z0-9-]+)$', text, re.M)
assert Counter(detail_ids) == Counter(expected.keys()), {
    'missing_or_duplicate_detail_headings': sorted(set(expected) ^ set(detail_ids)),
}

contract_comments = {}
for raw in re.findall(r'^<!-- coverage-contract (\{.*\}) -->$', text, re.M):
    payload = json.loads(raw)
    legacy_id = payload.get('legacy_id')
    assert legacy_id and legacy_id not in contract_comments, legacy_id
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert raw == canonical, legacy_id
    contract_comments[legacy_id] = payload
assert set(contract_comments) == set(expected), {
    'missing': sorted(set(expected) - set(contract_comments)),
    'extra': sorted(set(contract_comments) - set(expected)),
}
for legacy_id, fact in expected.items():
    assert contract_comments[legacy_id] == fact['contract_payload'], legacy_id

print('PASS: 158 coverage rows preserve exact source facts, objective/output/constraints, valid fields, one owner, and one stable detail anchor')
PY
```

Expected: `PASS: 158 coverage rows preserve exact source facts, objective/output/constraints, valid fields, one owner, and one stable detail anchor`.

## Task 5: Create the transition ledger with honest historical status and 87-hour future capacity

**Files:**

- Create: `Roadmap/docs/Transition Ledger.md`
- Link: `Docs/Day 1 ...`, `Docs/Day 2 ...`, and `Docs/Day 3 ...`

- [ ] **Create `Transition Ledger.md` with frontmatter** `type: transition-ledger`, `as-of: 2026-08-28`, `activation-cutoff: 2026-08-28`, `phase: 1`, `roadmap-version: phase-1-six-week-v1`, `mapping-version: phase-1-transition-v1`, `status: active`, and `future-app-source: true`.

- [ ] **Add an elapsed-block table for August 24–28.** It must reserve all five weekday blocks and distinguish evidence from assumptions:

| Date | Calendar state | Known work | Verified time | Scheduling treatment |
|---|---|---|---|---|
| 2026-08-24 | elapsed/reserved | no dated Day note | unknown | zero future capacity |
| 2026-08-25 | elapsed/reserved | Day 1 artifacts | SQL only: 40 focused, 45–50 elapsed; full day unknown | zero future capacity |
| 2026-08-26 | elapsed/reserved | no dated Day note | unknown | zero future capacity |
| 2026-08-27 | elapsed/reserved | Day 2 artifacts | full day unknown | zero future capacity |
| 2026-08-28 | elapsed/reserved; activation cutoff | Day 3 partial artifacts | unknown | zero future capacity |

Do not assign 180 or 240 minutes to an elapsed day merely because it was planned.

- [ ] **Add the exact Day 1–3 status tables from Task 4.** Link the current notes and the relevant ledger headings. Missing Attempt B, supplemental voice feedback, or teach-back must remain `pending`/`not_assessed`.

- [ ] **Add the future-capacity calculation as arithmetic, not prose only.**

```text
25 future weekdays × 180 minutes = 4,500 minutes
6 future Saturdays × 120 minutes = 720 minutes
Total future schedulable capacity = 5,220 minutes = 87 hours
```

List the 25 weekday dates and six Saturday dates explicitly in one strictly formatted table:

```markdown
| Date | Kind | Planned min | Capacity state |
|---|---|---:|---|
| 2026-08-29 | saturday | 120 | future-schedulable |
| 2026-08-31 | weekday | 180 | future-schedulable |
```

Continue through October 3 with exactly 31 rows, sorted by date. Allowed `Kind` values are `weekday` and `saturday`; planned minutes must be 180 and 120 respectively; every row is `future-schedulable`. No Sunday row is permitted. The first future item is the August 29 baseline diagnostic. The first `60 + 120` weekday is August 31.

- [ ] **Add a remaining-category forecast table.** Its inputs are unfinished ledger records and future blocks, not `102h - historical time`. Show planned future minutes, available future minutes, variance, one permitted carryover, and exact next checkpoint. Unknown historical minutes stay outside the subtraction.

- [ ] **Add transition policy.** No retroactive interview cycles; no retroactive ten-action pipeline failure; the ten-action target begins Week 2, the first full week under the model; Saturdays cannot absorb displaced weekdays; Week 7 is provisional when variance exceeds 15% and active only under the approved completion/evidence triggers.

- [ ] **Validate the fixed arithmetic.**

```bash
uv run python - <<'PY'
from datetime import date, timedelta
from pathlib import Path

start = date(2026, 8, 29)
end = date(2026, 10, 3)
dates = []
current = start
while current <= end:
    dates.append(current)
    current += timedelta(days=1)
weekdays = [item for item in dates if item.weekday() < 5]
saturdays = [item for item in dates if item.weekday() == 5]
assert weekdays[0] == date(2026, 8, 31)
assert len(weekdays) == 25, weekdays
assert len(saturdays) == 6, saturdays
assert len(weekdays) * 180 + len(saturdays) * 120 == 5220
text = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Transition Ledger.md').read_text()
for required in ('2026-08-28', '2026-08-29', '2026-08-31', '5,220', '87 hours', '25', '6'):
    assert required in text, required
print('PASS: transition dates and 87-hour future capacity are exact')
PY
```

Expected: `PASS: transition dates and 87-hour future capacity are exact`.

## Task 6: Create the 30-question interview queue and pipeline operating contract

**Files:**

- Create: `Roadmap/docs/Interview Queue.md`
- Create: `Roadmap/templates/pipeline_action.md`

- [ ] **Create `Interview Queue.md` with frontmatter** `type: interview-queue`, `phase: 1`, `roadmap-version: phase-1-six-week-v1`, `mapping-version: phase-1-transition-v1`, `status: active`, and `future-app-source: true`, followed by 30 ordered records `P1-Q01` through `P1-Q30`.

Each record uses the heading `### P1-QNN — <exact title>` and exactly these machine-readable field labels before any optional notes:

```markdown
- Exact question: Tell me about yourself.
- Segment: 1
- Default audience: recruiter
- Answer limit: 120 seconds
- Story source: not yet selected
- Coverage IDs: m1-w1-d01-communication
- Baseline date: 2026-08-31
- Baseline session: P1-2026-08-31-I60
- Actual date: —
- Actual session: —
- Attempt status: pending
- Qualification: not_assessed
- Evidence: —
- Exact next action: Write independent Attempt A before opening the coaching task.
```

Allowed attempt statuses are `pending`, `attempt_a_committed`, `coaching_complete`, `attempt_b_saved`, `completed`, and `overridden`. Allowed qualifications are `not_assessed`, `qualifying`, `nonqualifying`, and `mixed`. Baseline date/session are immutable planning lineage. A real-interview override changes only actual date/session/status and the debrief link; it never rewrites the baseline mapping. `Coverage IDs` is `—` or a comma-separated list of exact legacy IDs.

`Segment` is the numeric interview-progression segment, never a free-form category: Q01–Q05 use `1`, Q06–Q10 use `2`, Q11–Q15 use `3`, Q16–Q20 use `4`, Q21–Q25 use `5`, and Q26–Q30 use `6`. In particular, the fixed final mock Q30 must export `segment: 6`. Optional human-readable segment names may appear in prose, but they cannot replace this numeric field.

Use these exact immutable heading titles and ordered sets:

| ID | Exact heading title |
|---|---|
| P1-Q01 | Tell me about yourself |
| P1-Q02 | Current role and scope |
| P1-Q03 | Why TAM |
| P1-Q04 | Why change now |
| P1-Q05 | Strongest relevant achievement |
| P1-Q06 | Why this company |
| P1-Q07 | Difficult customer |
| P1-Q08 | Conflict |
| P1-Q09 | Failure and learning |
| P1-Q10 | Ambiguity and prioritization |
| P1-Q11 | Major incident |
| P1-Q12 | API troubleshooting |
| P1-Q13 | Uncertain ETA |
| P1-Q14 | Payments and reconciliation |
| P1-Q15 | Competing customers |
| P1-Q16 | Explain APIs and webhooks |
| P1-Q17 | OAuth and security |
| P1-Q18 | Idempotency and retries |
| P1-Q19 | Observability and SLOs |
| P1-Q20 | Architecture trade-offs |
| P1-Q21 | Implementation leadership |
| P1-Q22 | Launch decision |
| P1-Q23 | Proactive account strategy |
| P1-Q24 | Executive communication |
| P1-Q25 | Influence without authority |
| P1-Q26 | Company-specific recruiter screen |
| P1-Q27 | Fresh behavioral round |
| P1-Q28 | Technical TAM round |
| P1-Q29 | Portfolio and customer simulation |
| P1-Q30 | 45-minute final mock |

- [ ] **Assign the calendar without retroactive or compressed sessions.** The baseline mapping is exact:

  - `P1-Q01` through `P1-Q24` map in order to the 24 weekdays from 2026-08-31 through 2026-10-01. Each session ID is `P1-<date>-I60`.
  - `P1-Q25` through `P1-Q29` use baseline date `Week 7 / maintenance` and unique baseline sessions `P1-MAINT-Q25` through `P1-MAINT-Q29`, preserving that order without inventing calendar dates.
  - `P1-Q30` maps to 2026-10-02 and baseline session `P1-2026-10-02-MOCK60`.

The fixed Week 6 final mock interrupts the queue on October 2. Do not schedule two questions on one weekday to force completion.

- [ ] **Define queue override behavior.** An interview within 72 hours replaces that day's question with company/role-specific preparation, records the override, and returns to the earliest unmet queue item later. A real interview during the block counts as interview time but never as live-AI work. The final fixed mock uses `5 + 45 + 10`, has no coaching or Attempt B, and may qualify only when sealed and rubric-scored.

- [ ] **Create `pipeline_action.md`.** Required fields:

  - `action-type`: `application` or `recruiter-reply` as the two counted types, plus `legacy-artifact` as visible but separately counted;
  - company, role, source URL/context snapshot, relevance, known gap, resume/story version, date, completed action, stage, exact next action;
  - quality checklist and `counts-toward-weekly-target: true|false`;
  - recruiter acknowledgement exclusion;
  - research-only exclusion unless it creates the exact legacy artifact;
  - redaction/privacy check;
  - outcome/conversion fields.

State that the target is ten quality applications or substantive recruiter replies per full operating week, not two rushed applications every day. Week 1 transition is actuals-only; the target begins Week 2.

- [ ] **Validate queue cardinality, exact titles, baseline dates/sessions, and active terminology.** The later cross-file validator also proves that every dated queue item matches the corresponding weekly interview block.

```bash
uv run python - <<'PY'
from pathlib import Path
from datetime import date, timedelta
import re

path = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Interview Queue.md')
text = path.read_text()
expected_titles = [
    'Tell me about yourself', 'Current role and scope', 'Why TAM', 'Why change now',
    'Strongest relevant achievement', 'Why this company', 'Difficult customer', 'Conflict',
    'Failure and learning', 'Ambiguity and prioritization', 'Major incident',
    'API troubleshooting', 'Uncertain ETA', 'Payments and reconciliation',
    'Competing customers', 'Explain APIs and webhooks', 'OAuth and security',
    'Idempotency and retries', 'Observability and SLOs', 'Architecture trade-offs',
    'Implementation leadership', 'Launch decision', 'Proactive account strategy',
    'Executive communication', 'Influence without authority',
    'Company-specific recruiter screen', 'Fresh behavioral round', 'Technical TAM round',
    'Portfolio and customer simulation', '45-minute final mock',
]
headings = re.findall(r'^### (P1-Q\d{2}) — (.+)$', text, re.M)
expected_ids = [f'P1-Q{number:02d}' for number in range(1, 31)]
assert headings == list(zip(expected_ids, expected_titles)), headings

records = re.split(r'^### P1-Q\d{2} — .+$', text, flags=re.M)[1:]
def field(record, name):
    match = re.search(rf'^- {re.escape(name)}: (.+)$', record, re.M)
    assert match, name
    return match.group(1).strip()

cursor = date(2026, 8, 31)
dated = []
while cursor <= date(2026, 10, 1):
    if cursor.weekday() < 5:
        dated.append(cursor.isoformat())
    cursor += timedelta(days=1)
expected_dates = dated + ['Week 7 / maintenance'] * 5 + ['2026-10-02']
expected_sessions = (
    [f'P1-{item}-I60' for item in dated]
    + [f'P1-MAINT-Q{number:02d}' for number in range(25, 30)]
    + ['P1-2026-10-02-MOCK60']
)
for ordinal, (record, expected_date, expected_session) in enumerate(zip(records, expected_dates, expected_sessions), 1):
    assert field(record, 'Segment') == str(((ordinal - 1) // 5) + 1)
    assert field(record, 'Baseline date') == expected_date
    assert field(record, 'Baseline session') == expected_session
    assert field(record, 'Attempt status') in {
        'pending', 'attempt_a_committed', 'coaching_complete', 'attempt_b_saved', 'completed', 'overridden'
    }
    assert field(record, 'Qualification') in {'not_assessed', 'qualifying', 'nonqualifying', 'mixed'}
assert not re.search(r'\bClaude\b', text, re.I)
assert field(records[29], 'Segment') == '6'
print('PASS: 30 interview questions have exact order, numeric segments, dates, sessions, fields, and Codex-only wording')
PY
```

Expected: `PASS: 30 interview questions have exact order, numeric segments, dates, sessions, fields, and Codex-only wording`.

## Task 7: Write the six executable weekly files and the complete roadmap

**Files:**

- Create all six `Roadmap/Phase 1 - Week N - ...md` files listed in the canonical tree
- Create: `Roadmap/docs/Phase 1 - Complete Roadmap.md`
- Create: `Roadmap/docs/Next Phase Priorities.md`

- [ ] **Use one shared weekly-note structure.** Every file needs frontmatter (`phase`, `week`, `start`, `end`, `planned-minutes`, `status`, `roadmap-version`, `future-app-source`) and these sections:

  1. outcome and canonical legacy coverage;
  2. transition/import status when applicable;
  3. date-by-date sessions;
  4. interview queue item and any aligned case-defense mapping;
  5. pipeline requirement;
  6. 75-minute roadmap checkpoint;
  7. 15-minute close requirement;
  8. Saturday contract;
  9. evidence/pass conditions;
  10. exact next start.

Each ordinary weekday must total exactly 180 planned minutes as `5 + 15 + 5 + 20 + 5 + 10` for interview and `30 + 75 + 15` afterward. A due correction can replace only the first ten minutes of the 75-minute roadmap unit and never makes the day 190 minutes.

Every ordinary weekday close session must use the exact internal vector `5 + 5 + 3 + 2`: five minutes to record outputs and actual time, five minutes to produce one to three card-ready recall items, three minutes to map evidence to competencies, and two minutes to save the exact next action. State the vector beside each `C15` narrative and in the shared contract. Do not rebalance these minutes silently.

Every future weekday must also appear exactly once in a strict machine-readable table row using this column order:

```markdown
| Date | Interview session | Interview min | Queue ID | Pipeline session | Pipeline min | Roadmap session | Roadmap min | Close session | Close min | Total min |
|---|---|---:|---|---|---:|---|---:|---|---:|---:|
| 2026-08-31 | P1-2026-08-31-I60 | 60 | P1-Q01 | P1-2026-08-31-P30 | 30 | P1-2026-08-31-R75 | 75 | P1-2026-08-31-C15 | 15 | 180 |
```

The October 2 row uses `P1-2026-10-02-MOCK60` and `P1-Q30`, with the same `60,30,75,15,180` numeric vector. The validator treats the interview sub-vector (`5,15,5,20,5,10`) and final-mock sub-vector (`5,45,10`) as contracts in the date narrative while the schedule table records their common 60-minute total. No Sunday date may appear in any executable-session table.

Each Saturday must appear exactly once in this strict table shape:

```markdown
| Date | Saturday session | Segment keys | Minutes vector | Total min |
|---|---|---|---|---:|
| 2026-08-29 | P1-2026-08-29-SAT120 | fresh_mock,technical_transfer,evidence_scoring,pipeline_review,next_week_planning | 35,45,20,10,10 | 120 |
```

Use these exact segment-key/minute-vector pairs, in date order:

| Date | Segment keys | Exact vector |
|---|---|---|
| 2026-08-29 | `fresh_mock,technical_transfer,evidence_scoring,pipeline_review,next_week_planning` | `35,45,20,10,10` |
| 2026-09-05 | `no_ai_sql,integrated_case,behavioral,scoring` | `30,50,25,15` |
| 2026-09-12 | `no_ai_sql,case,portfolio,writing,scoring` | `30,35,20,20,15` |
| 2026-09-19 | `fresh_mock,technical_transfer,evidence_scoring,pipeline_review,next_week_planning` | `35,45,20,10,10` |
| 2026-09-26 | `no_ai_sql,case,portfolio,executive_behavioral,scoring` | `30,35,20,20,15` |
| 2026-10-03 | `no_ai_sql,portfolio_to_depth_gauntlet,writing,scoring` | `30,55,20,15` |

- [ ] **Write Week 1 (2026-08-24 through 2026-08-29) as a transition week, not a fictional new-model week.** Preserve the elapsed Day 1–3 facts and unknown times via links to the transition ledger. Include the unique headings `## Day 1 — Historical transition record` through `## Day 5 — Historical transition record` for the normalized roadmap package, but label every one `elapsed/reserved — transition import only`; show the nominal four-block shape only as versioned source metadata and explicitly say it must not be executed, backfilled, or counted as missed work for Francisco. Schedule only the future Saturday baseline:

  - 35 minutes fresh mock;
  - 45 minutes technical transfer;
  - 20 minutes evidence scoring;
  - 10 minutes pipeline review;
  - 10 minutes next-week planning.

The mock and technical transfer are fresh/unrehearsed and receive no coaching during the attempt.

- [ ] **Write Week 2 (2026-08-31 through 2026-09-05).** Start with the exact Day 3 checkpoint: finish idempotency application/teach-back, then continue the duplicate-order case, audience switching, résumé bullets, and remaining Days 4–5/Days 7–8 coverage as assigned in the ledger. `P1-Q01` begins August 31. Saturday is the canonical legacy Week 1 assessment:

  - 30 minutes no-AI SQL;
  - 50 minutes integrated case;
  - 25 minutes behavioral;
  - 15 minutes scoring.

- [ ] **Write Week 3 (2026-09-07 through 2026-09-12).** Cover the ledger-owned remainder of Days 8–11: DLQs, payments, incident command, postmortem, and business value. Saturday is the canonical legacy Week 2 assessment:

  - 30 minutes no-AI SQL;
  - 35 minutes case;
  - 20 minutes portfolio;
  - 20 minutes writing;
  - 15 minutes scoring.

- [ ] **Write Week 4 (2026-09-14 through 2026-09-19).** Cover Days 13–15 and start Day 16: OAuth, PKCE, webhook security, observability, SLOs, and implementation planning. Saturday is the midpoint diagnostic:

  - 35 minutes fresh mock;
  - 45 minutes technical transfer;
  - 20 minutes evidence scoring;
  - 10 minutes pipeline review;
  - 10 minutes next-week planning.

- [ ] **Write Week 5 (2026-09-21 through 2026-09-26).** Finish Days 16–17 and begin Days 19–20: implementation, account strategy, TAM payment design, and launch judgment. Saturday is the canonical legacy Week 3 assessment:

  - 30 minutes no-AI SQL;
  - 35 minutes case;
  - 20 minutes portfolio;
  - 20 minutes executive/behavioral;
  - 15 minutes scoring.

- [ ] **Write Week 6 (2026-09-28 through 2026-10-03).** Finish Days 20–23: launch decision, QBR, cross-functional conflict, portfolio judgment, dress rehearsal, and final behavioral mock. On October 2, replace the ordinary interview cycle with the sealed `5 + 45 + 10` final mock and keep the remaining 120-minute pipeline/roadmap/close block unchanged. Saturday is the canonical final assessment:

  - 30 minutes no-AI SQL;
  - 55 minutes portfolio-to-depth gauntlet;
  - 20 minutes writing;
  - 15 minutes scoring.

- [ ] **Preserve exact assessment constraints.** The four canonical assessments retain their original tasks, outputs, no-coaching/no-mid-attempt-AI rules, and stopping times. The two diagnostics use fresh transfer prompts and may produce qualifying evidence only after independent rubric scoring. Saturday never absorbs weekday carryover.

- [ ] **Write `Phase 1 - Complete Roadmap.md` as the shared contract, not a competing status ledger.** Include:

  - phase framing, dates, cadence, nominal 102h and transition 87h distinction;
  - the clean-run allocation and exact 37.5/30/15/7.5/12-hour reconciliation;
  - daily interview/pipeline/roadmap/close contract and hard stop, including exact close vector `5 + 5 + 3 + 2`;
  - all six weekly summaries and exact Saturday table;
  - interview queue link and first-ten priority;
  - ten-action pipeline quality contract and conversion review;
  - all 14 competency target rows under the label `Phase 1 target — six weeks`;
  - the exact competency scale lines: `0: not demonstrated or no practical knowledge`, `1: heavily assisted or basic concepts`, `2: developing performance in a straightforward scenario`, `3: independent performance under ambiguity and generally interview-ready`, and `4: strong under pressure and at professional depth`;
  - all six English dimensions—communication effectiveness, fluency, accuracy, vocabulary, pronunciation/intelligibility, and listening—plus these exact semantics: unavailable dimensions are `N/A`, listening is normally `N/A` for a monologue, accent is never scored, and daily coaching gives at most one high-impact English/delivery correction;
  - Attempt A/Attempt B/transfer/assessment qualification rules;
  - exit states, final closure, 15% reforecast trigger, and Week 7;
  - the independent `GATE-NEXT-PHASE-PRIORITIES` closure gate: Phase 1 cannot close until the final weekly evidence review has completed `Next Phase Priorities`; after a Week 7 retest, the gate must be refreshed before closure;
  - all seven preserved practice rules and privacy rule;
  - the complete approved adaptation table: task overrun saves an exact checkpoint and stops; one tailored application may consume the full 30 minutes and count once; voice/recording failure preserves written work and leaves spoken dimensions `Not assessed`; inaccurate transcripts preserve raw text and create a distinct corrected reviewed version; coaching before commitment makes evidence coached/nonqualifying; a booked real interview uses the first 60 minutes for company-specific preparation while preserving the 75-minute roadmap floor; extra real-interview displacement consumes forecast capacity or Week 7 with no hidden debt; variance above 15% causes re-splitting and provisional Week 7; absent required evidence stays `Not assessed`; unfinished Saturday work continues the following week and never on Sunday;
  - all legacy resource assignments/links or an explicit link to the exact active session carrying each one;
  - a `Legacy resource index preserved verbatim` section containing all 50 exact `(resource code, title, URL)` entries from the archived complete roadmap;
  - a `Legacy exit criteria coverage` table with columns `Exit ID | Legacy criterion | Phase 1 evidence owner | Exit state` and exactly ten stable rows `EXIT-SQL`, `EXIT-TECHNICAL`, `EXIT-DISCOVERY`, `EXIT-INCIDENTS`, `EXIT-COMMUNICATION`, `EXIT-ACCOUNT-STRATEGY`, `EXIT-PORTFOLIO-JUDGMENT`, `EXIT-WRITING`, `EXIT-BEHAVIORAL`, and `EXIT-ENGLISH`; each row contains the archived criterion text verbatim, one exact Phase 1 evidence owner/session, and exactly one of `Not assessed`, `Assessed—not demonstrated`, or `Demonstrated`;
  - links to the active ledgers, six week files, templates, archive, and approved design.

- [ ] **Create `Next Phase Priorities.md` as a separate closure-gate artifact, not an eleventh exit criterion.** Use frontmatter `type: next-phase-priorities`, `phase: 1`, `roadmap-version: phase-1-six-week-v1`, `gate-id: GATE-NEXT-PHASE-PRIORITIES`, `owner-session: P1-2026-10-03-SAT120`, `status: pending|completed`, and `future-app-source: true`. The body contains exactly one canonical one-line record:

```markdown
<!-- next-phase-priorities {"gate_id":"GATE-NEXT-PHASE-PRIORITIES","owner_session":"P1-2026-10-03-SAT120","priorities":[],"review_date":null,"review_ref":null,"status":"pending"} -->
```

Serialize with `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))`. Each completed priority object contains exactly `competency`, `demonstrated_gap`, `supporting_evidence`, `excluded_evidence`, `phase_2_action`, and `fresh_transfer_check`; preserve list order. Before the final review, keep status `pending`, evidence/date null, and priorities empty. Mark `completed` only after the final weekly evidence review saves at least one evidence-backed priority; if Week 7 runs, update the same gate after its retest rather than creating a second gate. Phase closure is invalid while this gate is pending, duplicated, ownerless, or completed with no priority.

Completing the Markdown record is not by itself a TAM Forge completion event. After the Week 6 review changes the canonical object to `completed`, rerun the pinned producer `--write` and `--check` commands plus the sidecar check, then use TAM Forge's `refresh-phase-transition` command to import those exact raw schema/JSON/sidecar bytes and all current source hashes. The Week 6 publication must link the returned validated refresh ID; a bare `review_ref` is invalid. If Week 7 activates, repeat the full export/check/refresh sequence after the retest so its completion publication links a newer validated refresh with explicit predecessor lineage and a later review date.

- [ ] **Verify that no legacy external resource or resource identity was dropped.** First compare the exact 50 `(code, title, URL)` triples in the archived and active complete-roadmap resource indexes. Then compare unique HTTP(S) links across the four archived weekly files plus archived complete roadmap against the active six weekly files plus active complete roadmap. The active set may have additional links; both legacy-minus-active sets must be empty.

```bash
uv run python - <<'PY'
from pathlib import Path
import re

vault = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice')
archive = vault / 'Roadmap.archive-20260828-month1-v2'
active = vault / 'Roadmap'
legacy_files = sorted(archive.glob('Week *.md')) + [archive / 'docs/Month 1 - Complete Roadmap.md']
active_files = sorted(active.glob('Phase 1 - Week *.md')) + [active / 'docs/Phase 1 - Complete Roadmap.md']
url_pattern = re.compile(r'https?://[^\s)>]+')
resource_pattern = re.compile(r'^- \*\*([A-Z]+\d+)\*\* \[([^\]]+)\]\((https?://[^)]+)\)', re.M)
legacy_resources = resource_pattern.findall((archive / 'docs/Month 1 - Complete Roadmap.md').read_text())
active_resources = resource_pattern.findall((active / 'docs/Phase 1 - Complete Roadmap.md').read_text())
assert len(legacy_resources) == 50, len(legacy_resources)
assert active_resources == legacy_resources, {
    'missing_or_reordered_resources': sorted(set(legacy_resources) - set(active_resources)),
    'extra_or_changed_resources': sorted(set(active_resources) - set(legacy_resources)),
}
legacy_urls = {url.rstrip('.,') for path in legacy_files for url in url_pattern.findall(path.read_text())}
active_urls = {url.rstrip('.,') for path in active_files for url in url_pattern.findall(path.read_text())}
missing = sorted(legacy_urls - active_urls)
assert not missing, missing
assert len(list(active.glob('Phase 1 - Week *.md'))) == 6
print(f'PASS: six weekly files preserve all 50 resource identities and {len(legacy_urls)} legacy URLs')
PY
```

Expected: a pass line and no missing or changed resource triples/URLs.

## Task 8: Create the evidence, interview, daily, weekly, and assessment templates

**Files:**

- Copy byte-identically, then update only links/Phase 1 terminology when necessary: `account_plan.md`, `discovery_notes.md`, `incident_update.md`, `portfolio_triage.md`, `story_catalog.md`
- Create: `daily_study_index.md`, `evidence_record.md`, `interview_practice_record.md`, `polished_study_note.md`, `real_interview_debrief.md`, `phase1_assessment.md`, `pipeline_action.md`, `weekly_review.md`
- Rewrite: `daily_scorecard.md`, `spoken_practice_session.md`
- Omit from active tree: `month1_assessment.md`

- [ ] **Copy the five domain templates from the archive, verify their copy hashes, then use `apply_patch` only for active-path links or Phase 1 wording required by the new workflow.** Do not remove any domain fields.

- [ ] **Create `daily_study_index.md` with the four fixed block budgets and these required fields:** date/session, queue ID, planned and actual focused minutes, output-producing minutes and 70% check, completed outputs, coverage-ledger status/links, topic note links, interview record link, real-interview debrief link when applicable, pipeline action links, strongest evidence, repeated mistake, unfinished classification, at most one roadmap carryover, and exact next observable action. Its close section uses exactly `5` minutes record outputs/actual time, `5` minutes create one to three card-ready recall items, `3` minutes map evidence, and `2` minutes save the next action; include a machine-readable `close-vector: 5,5,3,2` field.

- [ ] **Rewrite `daily_scorecard.md`.** Keep daily evidence separate from weekly level updates. Include planned/actual by block, independent/coached classification, self score versus reviewer score, strongest evidence, repeated mistake, one due correction, Attempt B status, all six named English dimensions with `N/A`, output percentage, carryover, and hard-stop confirmation. State that listening is normally `N/A` for a monologue and accent is never scored. Never infer a level from completion.

- [ ] **Create `evidence_record.md`.** Include exercise type and mapping version, competencies tested, independent/coached/sealed state, prompt version, source facts versus assumptions, self and reviewer scores, six English dimensions, recording/raw transcript/reviewed transcript versions, qualification reason, excluded/discounted evidence reason, confidence, recency, and linked coverage IDs.

- [ ] **Create `polished_study_note.md` as the required topic-note and future-flashcard contract.** Use frontmatter `type: polished-study-note`, `status: draft|validated`, `topic`, `date`, `coverage-ids`, `source-links`, `reviewer`, `validated-at`, `future-app-source: true`, and `flashcard-source: false|true`. The body must have these sections in this exact order:

  1. `## Raw learner attempt` — preserve the learner's original answer verbatim, plus timestamp, prompt, and assistance state; never silently rewrite or delete it.
  2. `## Review findings` — what was correct, what needs correction, and what remains uncertain.
  3. `## Corrected and validated note` containing all five required subsections: `### Concise rule`, `### Plain-English explanation`, `### Practical TAM example`, `### Boundary or common mistake`, and `### Card-ready Q/A`.
  4. `## Validation evidence` — source links, reviewer, validation state, mapped coverage IDs, and exact next transfer check.

The card section uses one fact per card in the stable form below; no raw attempt or unvalidated claim becomes a card:

```markdown
#### Card 1
Q: <one retrieval question>
A: <concise validated answer>
Why it matters for a TAM: <one practical sentence>
```

Set `flashcard-source: true` only when status is `validated` and every corrected-note subsection is present. Future flashcards must be generated from the corrected validated section, never from raw conversation transcripts or the raw learner attempt. Keep true personal/customer details redacted. The SQL `WHERE`/`HAVING` note and the idempotency note are exemplars to preserve, not raw material to overwrite during template creation.

- [ ] **Create `interview_practice_record.md`.** It must capture the full ordinary 60-minute cycle:

  - 5-minute frame: queue ID, question, role/scenario, audience, purpose, limit, permitted true context;
  - 15-minute independent written Attempt A or structured plan committed before help;
  - 5-minute self-review: strongest point, weak point, uncertainty;
  - 20-minute Codex practice-task prompt and returned handoff;
  - 5-minute separate uninterrupted spoken Attempt B after coaching;
  - 10-minute main-task save: recording/transcript status, one content correction, one English/delivery correction, transfer prompt, qualification, competency mapping, and exact next action.

Attempt A may qualify only for demonstrated written dimensions after rubric scoring. Same-question Attempt B is coached improvement evidence and cannot raise a level. Spoken fluency, pronunciation, and listening cannot be inferred from a written attempt.

- [ ] **Create `real_interview_debrief.md` for an actual recruiter, hiring-manager, technical, customer-simulation, or final interview.** Required fields are:

  - date, company, role, stage, format, actual duration, and redacted interviewer role/name;
  - job-description/resume/story-catalog version used;
  - queue item displaced, baseline session retained, actual session, and resume point in the ordered queue;
  - exact questions and follow-ups as recalled, clearly labeled as recollection rather than transcript when no recording exists;
  - concise answer outline and true evidence/story used for each question;
  - strongest demonstrated behavior, weakest answer, technical/content gap, and English/delivery friction;
  - interviewer signals as observed facts only, separated from the learner's interpretation;
  - objections, unanswered questions, promises/commitments, owner, and due date;
  - thank-you/follow-up action, pipeline-stage update, next-contact date, and outcome status (`unknown` until verified);
  - privacy/redaction check, recording/transcript availability, and explicit `no live AI used during interview` attestation;
  - one content transfer prompt, one English transfer prompt, qualification decision, evidence links, and exact next action.

Real-interview evidence may be qualifying only for dimensions actually demonstrated and only after the debrief is evidence-reviewed. Do not infer tone, pronunciation, listening, interviewer sentiment, or an outcome from memory alone. Link the completed debrief from the day's interview record, pipeline action, daily index, and weekly review.

- [ ] **Rewrite `spoken_practice_session.md` as Codex-only.** The copy-paste prompt must be self-contained and explicitly say:

```text
You are the interviewer/customer and a low-intrusion English coach in a fresh Codex task.
Total coaching-task time: 20 minutes — 2 minutes setup, 10 minutes answer plus at most two routine follow-ups, 5 minutes feedback, 3 minutes handoff.
Wait until I finish each answer. Do not interrupt or correct me mid-answer.
Use only the true/redacted context supplied. Do not invent experience, metrics, decisions, or technical facts.
Give at most one content/structure correction and one English/delivery correction.
End coaching before I make my separate uninterrupted Attempt B in the main study workflow.
Return the nine-field handoff exactly as requested.
```

The required handoff fields are: question/duration, concise attempt summary, strongest demonstrated behavior, one content/structure correction, one English/delivery correction, follow-up difficulty, coaching-complete flag plus Attempt B target, one fresh transfer prompt, and compact main-task handoff. The coach task must not claim the separate Attempt B was recorded or analyzed.

- [ ] **Create `weekly_review.md`.** Include planned versus actual focused minutes and variance formula, 15% trigger, coverage status, at most one carried roadmap unit, ten-action pipeline counts split by applications/replies, conversion stages, and a 14-skill evidence review that separately records estimated level, `Phase 1 target — six weeks`, target gap, confidence, trend, recency, contributing evidence, excluded evidence, self score, and reviewer score. Include all six named English dimensions and their `N/A`/monologue/accent semantics, exit-state audit, Week 7 provisional/active decision, exact next-week start, and a link to `GATE-NEXT-PHASE-PRIORITIES`. The final weekly review must complete that gate with evidence-backed next-phase priorities; a Week 7 review refreshes the same gate after retest.

- [ ] **Create `phase1_assessment.md`.** Include the three exit states verbatim, the exact `0`–`4` competency-scale definitions, all six named English dimensions with the approved `N/A`/monologue/accent semantics, the `GATE-NEXT-PHASE-PRIORITIES` closure requirement, and the 14 unchanged competency rows:

| Competency | Baseline | Phase 1 target — six weeks | Final target |
|---|---:|---:|---:|
| API and integration architecture | 3.0 | 3.0 | 3.25 |
| Structured troubleshooting | 2.0 | 2.5 | 3.0 |
| SQL and reconciliation | 1.0 | 2.0 | 2.75 |
| Distributed systems and reliability | 2.0 | 2.5 | 3.0 |
| Payments and fintech systems | 2.0 | 2.5 | 3.0 |
| Technical discovery | 2.0 | 2.5 | 3.0 |
| Incident and escalation management | 2.0 | 2.5 | 3.0 |
| Implementation and project management | 2.0 | 2.5 | 2.75 |
| Proactive account strategy | 2.0 | 2.5 | 2.75 |
| Executive communication | 1.0 | 2.0 | 3.0 |
| Cross-functional influence | 2.0 | 2.5 | 2.75 |
| Business and value framing | 1.0 | 2.0 | 3.0 |
| Technical writing | 1.0 | 2.0 | 2.75 |
| TAM English | 1.0 | 2.0 | 2.75 |

For each row provide estimated level, target gap, confidence, trend, recency, qualifying evidence, excluded evidence, and next transfer. Add the six English dimensions separately. Portfolio Judgment stays derived, not a fifteenth skill. Include each Saturday variant and the Week 7 retest/`complete with gap` rule.

- [ ] **Validate Codex-only active templates and target cardinality.**

```bash
uv run python - <<'PY'
from pathlib import Path
import json
import re
import yaml

project_targets = yaml.safe_load(Path('/Users/frank/Documents/ChatGPT/TAM Project/config/tam-skills.yaml').read_text())['skills']
assessment = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/phase1_assessment.md').read_text()
study_note = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/polished_study_note.md').read_text()
debrief = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/real_interview_debrief.md').read_text()
daily_index = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/daily_study_index.md').read_text()
weekly_review = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/weekly_review.md').read_text()
complete = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Phase 1 - Complete Roadmap.md').read_text()
priorities_text = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Next Phase Priorities.md').read_text()
for skill in project_targets:
    row = f"| {skill['name']} | {skill['baseline']} | {skill['month_one_target']} | {skill['final_target']} |"
    assert row in assessment, row
assert len(project_targets) == 14
assert '| Competency | Baseline | Phase 1 target — six weeks | Final target |' in assessment
for level_text in (
    '0: not demonstrated or no practical knowledge',
    '1: heavily assisted or basic concepts',
    '2: developing performance in a straightforward scenario',
    '3: independent performance under ambiguity and generally interview-ready',
    '4: strong under pressure and at professional depth',
):
    assert level_text in assessment and level_text in complete, level_text
for dimension in (
    'communication effectiveness', 'fluency', 'accuracy', 'vocabulary',
    'pronunciation/intelligibility', 'listening',
):
    assert dimension in assessment and dimension in weekly_review and dimension in complete, dimension
for semantic in ('Accent is never scored', 'Listening is normally N/A for a monologue'):
    assert semantic.lower() in assessment.lower(), semantic
    assert semantic.lower() in weekly_review.lower(), semantic
    assert semantic.lower() in complete.lower(), semantic
assert 'close-vector: 5,5,3,2' in daily_index
for adaptation in (
    'voice/recording failure', 'inaccurate transcripts', 'coaching before commitment',
    '75-minute roadmap floor', 'variance above 15%', 'unfinished Saturday work',
):
    assert adaptation.lower() in complete.lower(), adaptation
for heading in (
    '## Raw learner attempt', '## Review findings', '## Corrected and validated note',
    '### Concise rule', '### Plain-English explanation', '### Practical TAM example',
    '### Boundary or common mistake', '### Card-ready Q/A', '## Validation evidence',
):
    assert heading in study_note, heading
for field in (
    'queue item displaced', 'exact questions', 'strongest demonstrated behavior',
    'interviewer signals', 'outcome status', 'no live AI used during interview',
    'content transfer prompt', 'English transfer prompt', 'exact next action',
):
    assert field.lower() in debrief.lower(), field
gate_matches = re.findall(r'^<!-- next-phase-priorities (\{.*\}) -->$', priorities_text, re.M)
assert len(gate_matches) == 1, gate_matches
gate_raw = gate_matches[0]
gate = json.loads(gate_raw)
assert gate_raw == json.dumps(gate, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
assert gate['gate_id'] == 'GATE-NEXT-PHASE-PRIORITIES'
assert gate['owner_session'] == 'P1-2026-10-03-SAT120'
if gate['status'] == 'pending':
    assert gate['review_ref'] is None and gate['review_date'] is None and gate['priorities'] == []
elif gate['status'] == 'completed':
    assert gate['review_ref'] and gate['review_date'] and gate['priorities']
else:
    raise AssertionError(gate['status'])
assert gate['status'] in {'pending', 'completed'}
assert (gate['status'] == 'pending' and gate['review_ref'] is None and gate['review_date'] is None and gate['priorities'] == []) or (
    gate['status'] == 'completed' and gate['review_ref'] and gate['review_date'] and gate['priorities']
)
active = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap')
claude_hits = []
for path in active.rglob('*.md'):
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if re.search(r'\bClaude\b', line, re.I):
            claude_hits.append(f'{path}:{number}:{line}')
assert not claude_hits, claude_hits
print('PASS: targets/scale/English/close/adaptation/gate contracts and zero Claude references')
PY
```

Expected: `PASS: targets/scale/English/close/adaptation/gate contracts and zero Claude references`.

## Task 9: Create the active portfolio-judgment track without rewriting later-phase history

**Files:**

- Create: `Roadmap/docs/Portfolio Judgment Track.md`
- Reference: archived `docs/Portfolio Judgment Track - Months 1 to 3.md`

- [ ] **Create the active note with the complete decision dimensions from Version 2.** Preserve customer/end-user impact, financial/data/security/compliance risk, severity/blast radius, urgency, workaround, launch/contract/migration dependencies, strategic context, delegation capacity, and diagnostic confidence.

- [ ] **Map Phase 1 exercises to the actual six-week calendar.** The active required portfolio assessments are the legacy Week 2 assessment on September 12, legacy Week 3 assessment on September 26, and final portfolio-to-depth gauntlet on October 3. Fresh diagnostic Saturdays may assess prioritization but do not replace those three required exercises.

- [ ] **Preserve the original pass standard and final-gauntlet behavior.** Explicit ranking, control/ownership for every account, reversal evidence, reprioritization after new facts, and at least 16/20 remain. The gauntlet begins with breadth and then drills into the selected highest-priority customer.

- [ ] **Do not silently redesign Months 2–3.** Link the archived track as the historical downstream source and state that later-phase naming/scheduling is outside this implementation. The active file may refer to “later phases” but may not claim approved new schedules that do not exist.

## Task 10: Create Day 3 control notes at the saved checkpoint

**Files:**

- Create: `Docs/Day 3 - Study Index.md`
- Create: `Docs/Day 3 - Daily Scorecard.md`
- Preserve: `Docs/Day 3 - SQL Aggregation and Query Execution Study Notes.md`
- Preserve: `Docs/Day 3 - Idempotency and Retry Safety Study Notes.md`

- [ ] **Create `Day 3 - Study Index.md`.** Use frontmatter `date: 2026-08-28`, `type: daily-study-index`, `status: in-progress-at-phase1-transition`, `future-app-source: true`. Link both the archived Day 3 source heading and the current coverage/transition headings.

The completion table must say exactly:

| Block | Status | Evidence/next action |
|---|---|---|
| SQLBolt 9–12 | reported complete with guided validation; time unknown | existing SQL note |
| Idempotency reading/recall | completed with guided correction | existing idempotency note |
| Idempotency application | pending | write the duplicate-after-timeout sequence from the saved checkpoint |
| Idempotency teach-back | pending | explain API key vs idempotency key, same-key retry, new-key risk, and inbound webhook dedupe |
| Northstar duplicate-order case | pending | resume from the idempotency application, not from SQL |
| Three audience recordings | pending/not assessed | engineer, VP Engineering, CFO; no artifact inferred |
| Pipeline | pending | rewrite three résumé bullets as scope, action, measurable outcome |
| Close | pending | complete after the future work; actual time stays unknown |

The exact next roadmap action is the idempotency application sequence; the first scheduled future block overall is the August 29 diagnostic, and the first ordinary weekday continuation is August 31.

- [ ] **Create `Day 3 - Daily Scorecard.md`.** Use `status: in-progress-not-assessed`. Record planned legacy context separately from new schedule, actual full-day time `unknown`, SQL/idempotency evidence links, no invented score, pending spoken dimensions, strongest retained rule (`WHERE` filters rows; `HAVING` filters groups), repeated SQL correction (include the missing `JOIN` and correct `WHERE`/`HAVING` boundary), and exact next action. Daily evidence may be recorded, but competency levels wait for weekly review.

- [ ] **Do not rewrite the polished SQL/idempotency bodies.** Only Task 11 may change their stale legacy roadmap link and add lineage. Preserve card-ready content and the learner's existing evidence/status language.

## Task 11: Repair all stale roadmap backlinks while preserving historical prose

**Files:**

- Modify the discovered set under `Docs/*.md` containing `[[Roadmap/Week 1 - ...]]`, currently 11 files
- Keep `Docs/HTTP, TCP, and TLS - TAM Interview Question Bank.md` linked to the new active `Roadmap/README`

- [ ] **Discover the set immediately before editing.** Do not rely only on the inspected count.

```bash
rg -l '\[\[Roadmap/Week [1-4] -' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Docs' | sort
rg -l '\[\[Roadmap/' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Docs' | sort
```

Inspected baseline: 11 files point to a legacy `Roadmap/Week ...` path; 12 files contain any `[[Roadmap/` link because the HTTP/TCP/TLS question bank points to `Roadmap/README`. If live results differ, inspect the delta and patch every real stale link; never force the old count.

- [ ] **Use `apply_patch` to replace each stale legacy week target with the exact archived path while preserving its heading fragment and display alias.** Example:

```markdown
Legacy roadmap: [[Roadmap.archive-20260828-month1-v2/Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory#Day 3 — Aggregation, idempotency, and audience switching|Archived Version 2 — Day 3]]
Current Phase 1 coverage: [[Roadmap/docs/Coverage Ledger#m1-w1-d03-technical|m1-w1-d03-technical]]
```

Do not edit historical results, timestamps, scores, attempts, status claims, or learner prose.

- [ ] **Use these exact current-ledger mappings.** Notes that summarize a whole day link to the first stable-ID detail and state that the surrounding detail section covers the entire day.

| Existing Docs note | Current ledger anchor |
|---|---|
| `2026-08-25 - API and Fintech TAM Market Requirements.md` | `m1-w1-d01-pipeline` |
| `Day 1 - Daily Scorecard.md` | `m1-w1-d01-close` |
| `Day 1 - Study Index.md` | `m1-w1-d01-sql` plus day summary |
| `Day 1 - Tell Me About Yourself Practice Status.md` | `m1-w1-d01-communication` |
| `Day 2 - Behavioral Story Catalog.md` | `m1-w1-d02-communication` |
| `Day 2 - Daily Scorecard.md` | `m1-w1-d02-close` |
| `Day 2 - SQL Joins and NULLs Study Notes.md` | `m1-w1-d02-sql` |
| `Day 2 - Study Index.md` | `m1-w1-d02-sql` plus day summary |
| `Day 3 - Idempotency and Retry Safety Study Notes.md` | `m1-w1-d03-technical` |
| `Day 3 - SQL Aggregation and Query Execution Study Notes.md` | `m1-w1-d03-sql` |
| `Northstar Scenario 1 - API Down but Monitoring Green.md` | `m1-w1-d02-case` |

- [ ] **Preserve the general HTTP question-bank link to the active README.** It is not a stale historical-day link. Add no archive pointer unless its prose specifically claims a Version 2 day assignment.

- [ ] **Prove no stale active-week target remains and all current/archived targets resolve.**

```bash
test -z "$(rg -l '\[\[Roadmap/Week [1-4] -' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Docs' || true)"
rg -l '\[\[Roadmap.archive-20260828-month1-v2/Week [1-4] -' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Docs' | wc -l
```

Expected: the stale search is empty; the inspected-baseline archive-link count is 11. If the live discovered set changed, expected archive links equal the live pre-edit stale set, not a forced 11.

## Task 12: Generate the canonical transition export for separate TAM Forge activation

**Files:**

- Create with `apply_patch`: `Exports/phase-1-transition-v1.schema.json`
- Create with `apply_patch`: `Exports/build_phase1_transition_export.py`
- Create with `apply_patch`: `Exports/test_phase1_transition_export.py`
- Generate mechanically: `Exports/phase-1-transition-v1.json`
- Generate mechanically: `Exports/phase-1-transition-v1.json.sha256`

This task creates the only machine-readable transition input TAM Forge may consume. Markdown remains the human authority. The normal roadmap ZIP excludes all of vault-root `Exports/`; the JSON and `.sha256` travel through the separate activation input defined by the TAM Forge synchronization plan. The importer consumes this exact raw v1 schema and these exact bytes after verification. It must not expect `export_schema_version`, `export_sha256`, `source_pins`, `coverage_progress`, `interview_items`, or any other renamed/transformed parallel envelope unless this producer contract receives a new backward-incompatible version first.

- [ ] **Write the generator tests first.** The tests must build temporary Markdown fixtures and independently prove all of these failures before the implementation is accepted:

  - missing, extra, renamed, or duplicated member in the exact archived 21-path set;
  - coverage row with wrong source path/heading/required flag, invalid status/qualification, two owners, missing owner, invalid minutes, duplicated ID, or missing detail anchor;
  - missing, altered, duplicated, non-canonical, or reordered coverage-contract data for any legacy objective, required output, pass criterion, AI/assessment constraint, allowed AI role, contract, exercise type, or timebox;
  - owner or continuation ID absent from the active schedule/import-owner allowlist;
  - queue title/order/numeric-segment/date/session drift, duplicate session, invalid status/qualification, Q25–Q29 compression, or Q30 whose segment is not `6`;
  - missing/duplicate future weekday, any weekday vector other than `60,30,75,15,180`, any close vector other than `5,5,3,2`, any Sunday executable row, or October 2 not mapped to Q30/MOCK60;
  - any Saturday whose date, segment key order, vector, or 120-minute total differs from the six exact contracts;
  - missing/changed/reordered one of the 50 legacy resource triples or any legacy URL assignment missing from active content;
  - missing/changed/duplicated one of the ten verbatim legacy exit criteria or missing Phase 1 evidence owner;
  - missing/duplicated/invalid `GATE-NEXT-PHASE-PRIORITIES`, wrong owner, completed gate without review evidence or priorities, or a closure claim while the gate remains pending;
  - valid pending, valid Week 6 completed, and valid later Week 7 completed gate fixtures must all pass Draft 2020-12 plus semantic validation; changing the gate must change its authoritative source hash, raw JSON bytes, and sidecar hash while preserving the same schema/export versions;
  - missing or changed `0`–`4` scale definition, six-dimension English contract, accent/listening semantics, exact `Phase 1 target — six weeks` label, or any approved adaptation rule;
  - roadmap/mapping/schema version mismatch, source-hash staleness, non-canonical JSON bytes, or `.sha256` mismatch.

Run the red test:

```bash
uv run --with 'jsonschema>=4.23,<5' python '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/test_phase1_transition_export.py'
```

Expected before implementation: fail because `build_phase1_transition_export.py` is absent or incomplete. A test that passes without exercising the real parser is invalid.

- [ ] **Create `phase-1-transition-v1.schema.json` using JSON Schema Draft 2020-12.** The producer scripts import `jsonschema.Draft202012Validator`, call `Draft202012Validator.check_schema(...)` before validating any payload, and run with the pinned ephemeral dependency `jsonschema>=4.23,<5`; they do not depend on TAM Forge having installed a validator later. The schema must set `$id` to `phase-1-transition-v1.schema.json`, use `additionalProperties: false` at the root and record levels, and require this exact root contract:

```json
{
  "$schema": "phase-1-transition-v1.schema.json",
  "schema_version": 1,
  "export_version": "phase-1-transition-v1",
  "roadmap_version": "phase-1-six-week-v1",
  "mapping_version": "phase-1-transition-v1",
  "activation_cutoff": "2026-08-28",
  "schema_sha256": "<64 lowercase hex>",
  "source_hashes": {"<vault-relative authoritative Markdown path>": "<64 lowercase hex>"},
  "transition": {},
  "coverage": [],
  "interview_queue": [],
  "weekday_sessions": [],
  "saturday_sessions": [],
  "resources": [],
  "exit_criteria": [],
  "next_phase_priorities": {
    "gate_id": "GATE-NEXT-PHASE-PRIORITIES",
    "owner_session": "P1-2026-10-03-SAT120",
    "status": "pending",
    "review_ref": null,
    "review_date": null,
    "priorities": []
  }
}
```

The schema constrains `coverage` to exactly 158 records, `interview_queue` to 30, `weekday_sessions` to 25, `saturday_sessions` to six, `resources` to 50, and `exit_criteria` to ten. Every queue record requires integer `segment` in `1..6`; semantic validation requires five consecutive records per segment and Q30 in segment `6`. It requires exactly one `next_phase_priorities` object with the fixed gate ID and owner. Pending requires null review fields and an empty priorities array; completed requires a review reference/date and at least one priority whose record has exactly `competency`, `demonstrated_gap`, `supporting_evidence`, `excluded_evidence`, `phase_2_action`, and `fresh_transfer_check`. It uses the status/qualification enums and ID/date/minute patterns already defined in Tasks 4, 6, and 7. `transition` requires the 25/6 counts and `5,220` future minutes. Every weekday record carries exact interview, pipeline, roadmap, close, total, and internal close-vector values. The schema is the single raw producer/consumer contract; semantic validation still performs uniqueness, ordering, cross-reference, legacy-source, exact-contract, closure-gate, and exact-vector checks that JSON Schema alone cannot express.

- [ ] **Implement `build_phase1_transition_export.py` with `build`, `--write`, and `--check` behavior.** The canonical payload is parsed from these exact eleven authoritative active Obsidian notes, in this fixed order:

```text
Roadmap/docs/Coverage Ledger.md
Roadmap/docs/Transition Ledger.md
Roadmap/docs/Interview Queue.md
Roadmap/docs/Phase 1 - Complete Roadmap.md
Roadmap/docs/Next Phase Priorities.md
Roadmap/Phase 1 - Week 1 - Transition, foundations, and baseline.md
Roadmap/Phase 1 - Week 2 - Webhooks, discovery, and retry control.md
Roadmap/Phase 1 - Week 3 - Distributed failures, incidents, and payments.md
Roadmap/Phase 1 - Week 4 - OAuth, observability, and midpoint transfer.md
Roadmap/Phase 1 - Week 5 - Implementation, account strategy, and launch judgment.md
Roadmap/Phase 1 - Week 6 - QBR, portfolio judgment, and final assessment.md
```

The project YAML and immutable archive are validation oracles only; they are never substituted for missing active-ledger data. The generated arrays sort only by their canonical keys: legacy ID, queue number, date, Saturday date, resource order, and exit-criterion order. Serialize with:

```python
canonical = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
```

Do not include wall-clock `generated_at`, random IDs, absolute machine paths, filesystem mtimes, or unordered sets. `source_hashes` contains raw UTF-8 SHA-256 for all eleven notes. `schema_sha256` contains the raw schema-file hash. The `.sha256` file contains exactly one line, `<json sha256><two spaces>phase-1-transition-v1.json`, plus a trailing newline. This sidecar is the only full-file content-hash envelope; do not add a self-hash or generate a second payload for TAM Forge.

`--write` is the sole exception to the prose-edit rule: it may mechanically replace only the canonical JSON and its `.sha256` after every semantic assertion passes. It must write to temporary sibling files and atomically replace the two outputs only after both bytes are ready. `--check` writes nothing; it rebuilds expected bytes in memory, validates the checked-in schema contract, compares the JSON byte-for-byte, checks every source hash and cross-reference, and verifies the `.sha256` line.

- [ ] **Run the green tests, generate once, and prove reproducibility.**

```bash
uv run --with 'jsonschema>=4.23,<5' python '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/test_phase1_transition_export.py'
uv run --with 'jsonschema>=4.23,<5' python '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/build_phase1_transition_export.py' --write --vault '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice' --project '/Users/frank/Documents/ChatGPT/TAM Project'
uv run --with 'jsonschema>=4.23,<5' python '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/build_phase1_transition_export.py' --check --vault '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice' --project '/Users/frank/Documents/ChatGPT/TAM Project'
cd '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports'
shasum -a 256 -c phase-1-transition-v1.json.sha256
```

Expected: tests pass; `--check` prints one pass line naming 158 exact coverage contracts, 30 queue records, 25 weekdays with `5,5,3,2` closes, six Saturdays, 50 resources, ten exit criteria, and one next-phase-priorities gate; `shasum` prints `phase-1-transition-v1.json: OK`.

- [ ] **Enforce refresh and version rules in README, Package Contents, and the redesign-change note.** Any edit to one of the eleven authoritative source notes makes `--check` fail until `--write` and `--check` are rerun. Never edit the JSON/hash directly. Run `--check` immediately before handing the exact raw input to TAM Forge and reject activation when its embedded roadmap/mapping versions do not equal `phase-1-six-week-v1` / `phase-1-transition-v1`. The TAM Forge consumer must validate this same checked-in JSON Schema and sidecar and accept the raw root fields without translation; add a cross-plan contract test before activation. A backward-incompatible field or semantic change requires a new export/schema filename and mapping version; never silently mutate v1. Ordinary status/evidence updates keep v1, regenerate deterministic bytes, and produce a new content hash.

## Task 13: Run deterministic cross-file acceptance checks

**Files:** all active `Roadmap/` Markdown, the checksum archive, and changed/new `Docs/` notes

- [ ] **Re-verify the immutable archive.**

```bash
cd '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2'
shasum -a 256 -c '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256'
```

Expected: 21 `OK` lines.

- [ ] **Run the combined semantic validator.** It validates structure, links, IDs, question order, target values, Saturday timeboxes, active terminology, and transition capacity. It is read-only.

```bash
uv run python - <<'PY'
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
import json
import re
import yaml

vault = Path('/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice')
active = vault / 'Roadmap'
archive = vault / 'Roadmap.archive-20260828-month1-v2'
project = Path('/Users/frank/Documents/ChatGPT/TAM Project')

weekly = sorted(active.glob('Phase 1 - Week *.md'))
assert len(weekly) == 6, weekly
assert archive.is_dir()
assert (vault / 'Roadmap.archive-20260828-month1-v2.sha256').is_file()

required_active = [
    active / 'README.md',
    active / 'docs/Phase 1 - Complete Roadmap.md',
    active / 'docs/Coverage Ledger.md',
    active / 'docs/Transition Ledger.md',
    active / 'docs/Interview Queue.md',
    active / 'docs/Next Phase Priorities.md',
    active / 'docs/Package Contents.md',
    active / 'docs/Portfolio Judgment Track.md',
    active / 'docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md',
    active / 'templates/daily_scorecard.md',
    active / 'templates/daily_study_index.md',
    active / 'templates/evidence_record.md',
    active / 'templates/interview_practice_record.md',
    active / 'templates/phase1_assessment.md',
    active / 'templates/pipeline_action.md',
    active / 'templates/spoken_practice_session.md',
    active / 'templates/weekly_review.md',
    vault / 'Docs/Day 3 - Study Index.md',
    vault / 'Docs/Day 3 - Daily Scorecard.md',
]
missing_files = [str(path) for path in required_active if not path.is_file()]
assert not missing_files, missing_files

for forbidden in [
    active / 'Week 1 - SQL foundations, HTTP, troubleshooting, and story inventory.md',
    active / 'Week 2 - Distributed failures, incidents, and payments.md',
    active / 'Week 3 - OAuth, observability, implementation, and account strategy.md',
    active / 'Week 4 - Integrated interview performance and final assessment.md',
    active / 'docs/Month 1 - Complete Roadmap.md',
    active / 'docs/Version 2 - Portfolio Judgment Changes.md',
    active / 'templates/month1_assessment.md',
]:
    assert not forbidden.exists(), forbidden

mapping = yaml.safe_load((project / 'config/tam-roadmap-task-map.yaml').read_text())
expected_ids = [task['stable_id'] for day in mapping['days'] for task in day['tasks']]
ledger_text = (active / 'docs/Coverage Ledger.md').read_text()
actual_ids = re.findall(r'^\| `(m1-w[1-4]-d\d{2}-[a-z0-9-]+)` \|', ledger_text, re.M)
assert len(expected_ids) == len(actual_ids) == 158
assert Counter(actual_ids) == Counter(expected_ids)

queue_text = (active / 'docs/Interview Queue.md').read_text()
queue_ids = re.findall(r'^### (P1-Q\d{2}) —', queue_text, re.M)
assert queue_ids == [f'P1-Q{number:02d}' for number in range(1, 31)]
queue_records = re.split(r'^### P1-Q\d{2} — .+$', queue_text, flags=re.M)[1:]
segments = []
for record in queue_records:
    match = re.search(r'^- Segment: ([1-6])$', record, re.M)
    assert match, record[:120]
    segments.append(int(match.group(1)))
assert segments == [((ordinal - 1) // 5) + 1 for ordinal in range(1, 31)]
assert segments[29] == 6

skills = yaml.safe_load((project / 'config/tam-skills.yaml').read_text())['skills']
assert len(skills) == 14
assessment = (active / 'templates/phase1_assessment.md').read_text()
complete = (active / 'docs/Phase 1 - Complete Roadmap.md').read_text()
for skill in skills:
    row = f"| {skill['name']} | {skill['baseline']} | {skill['month_one_target']} | {skill['final_target']} |"
    assert row in assessment, row
    assert row in complete, row
assert '| Competency | Baseline | Phase 1 target — six weeks | Final target |' in assessment
for level_text in (
    '0: not demonstrated or no practical knowledge',
    '1: heavily assisted or basic concepts',
    '2: developing performance in a straightforward scenario',
    '3: independent performance under ambiguity and generally interview-ready',
    '4: strong under pressure and at professional depth',
):
    assert level_text in assessment and level_text in complete, level_text
for semantic in ('Accent is never scored', 'Listening is normally N/A for a monologue'):
    assert semantic.lower() in assessment.lower() and semantic.lower() in complete.lower(), semantic

priorities_text = (active / 'docs/Next Phase Priorities.md').read_text()
gate_matches = re.findall(r'^<!-- next-phase-priorities (\{.*\}) -->$', priorities_text, re.M)
assert len(gate_matches) == 1, gate_matches
gate_raw = gate_matches[0]
gate = json.loads(gate_raw)
assert gate_raw == json.dumps(gate, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
assert gate['gate_id'] == 'GATE-NEXT-PHASE-PRIORITIES'
assert gate['owner_session'] == 'P1-2026-10-03-SAT120'

future_dates = []
cursor = date(2026, 8, 29)
while cursor <= date(2026, 10, 3):
    future_dates.append(cursor)
    cursor += timedelta(days=1)
weekdays = [item for item in future_dates if item.weekday() < 5]
saturdays = [item for item in future_dates if item.weekday() == 5]
assert len(weekdays) == 25
assert len(saturdays) == 6
assert 180 * len(weekdays) + 120 * len(saturdays) == 5220
transition = (active / 'docs/Transition Ledger.md').read_text()
assert all(term in transition for term in ('2026-08-28', '2026-08-29', '2026-08-31', '5,220', '87 hours'))

saturday_contracts = {
    '2026-08-29': [35, 45, 20, 10, 10],
    '2026-09-05': [30, 50, 25, 15],
    '2026-09-12': [30, 35, 20, 20, 15],
    '2026-09-19': [35, 45, 20, 10, 10],
    '2026-09-26': [30, 35, 20, 20, 15],
    '2026-10-03': [30, 55, 20, 15],
}
all_weekly = '\n'.join(path.read_text() for path in weekly)
assert all_weekly.count('5,5,3,2') == 25
for day, minutes in saturday_contracts.items():
    assert day in all_weekly, day
    assert sum(minutes) == 120, (day, minutes)
    for value in set(minutes):
        assert re.search(rf'\b{value}\s*(?:min|minutes)', all_weekly, re.I), (day, value)

claude_hits = []
for path in active.rglob('*.md'):
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if re.search(r'\bClaude\b', line, re.I):
            claude_hits.append(f'{path}:{number}:{line}')
assert not claude_hits, claude_hits

assert not list((vault / 'Docs').glob('*.md')) or not any(
    re.search(r'\[\[Roadmap/Week [1-4] -', path.read_text())
    for path in (vault / 'Docs').glob('*.md')
)

# Resolve explicit Roadmap wikilink file targets in active roadmap and changed Docs notes.
link_pattern = re.compile(r'\[\[((?:Roadmap|Roadmap\.archive-20260828-month1-v2)/[^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]')
link_sources = list(active.rglob('*.md')) + list((vault / 'Docs').glob('*.md'))
unresolved = []
for source in link_sources:
    for target in link_pattern.findall(source.read_text()):
        candidate = vault / target
        if candidate.suffix == '':
            candidate = candidate.with_suffix('.md')
        if not candidate.exists():
            unresolved.append((str(source), target))
assert not unresolved, unresolved

print('PASS: Phase 1 Obsidian structure, lineage, capacity, coverage, queue, targets, close vectors, closure gate, links, and terminology')
PY
```

Immediately follow that structural pass with the authoritative export/consumer-contract check:

```bash
uv run --with 'jsonschema>=4.23,<5' python '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Exports/build_phase1_transition_export.py' --check --vault '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice' --project '/Users/frank/Documents/ChatGPT/TAM Project'
```

Expected: both pass lines. The second check proves exact legacy objective/output/constraint preservation, adaptation/scale/English semantics, raw v1 schema bytes, and the next-phase-priorities gate. Any failure blocks activation; fix the authoritative content with `apply_patch`, regenerate when needed, and rerun both checks.

- [ ] **Run focused plain-text invariants.**

```bash
rg -n 'WHERE.*filters rows.*HAVING.*filters groups' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Docs/Day 3 - SQL Aggregation and Query Execution Study Notes.md'
rg -n 'application sequence: pending|Application sequence: pending|Teach-back: pending' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Docs/Day 3 - Idempotency and Retry Safety Study Notes.md'
rg -n 'Not assessed|Assessed.not demonstrated|Demonstrated' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Phase 1 - Complete Roadmap.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/phase1_assessment.md'
rg -n '60|120|180|Sunday' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/README.md'
rg -n 'Phase 1 target — six weeks|Accent is never scored|Listening is normally N/A for a monologue|GATE-NEXT-PHASE-PRIORITIES' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Phase 1 - Complete Roadmap.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/docs/Next Phase Priorities.md' '/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap/templates/phase1_assessment.md'
```

Expected: each invariant appears in its authoritative note. Inspect results; counts alone are not semantic proof.

## Task 14: Perform an Obsidian navigation and activation review

**Files:** read-only review of the completed active vault

- [ ] Open `Roadmap/README.md` in Obsidian and click each of the six week links, the complete roadmap, every operating record including `Next Phase Priorities`, both case files, SQL tasks, every template, and each vault-root export/schema/hash link. No link should create a blank note.
- [ ] From the new Day 3 Study Index, click the SQL note, idempotency note, archived Day 3 source, transition ledger, and current coverage anchors. Confirm the exact next action is the idempotency application—not repeated SQL lessons.
- [ ] From each of the 11 migrated legacy-day notes discovered in Task 11, click both the archived source and current coverage anchor. Confirm historical prose/status is unchanged.
- [ ] Search active `Roadmap/` for `Claude`, `4 hours Monday`, `88 focused hours`, `Month 1 target`, and `move ... Sunday`. Expected: no active workflow instruction uses those old contracts. Historical archive hits are allowed.
- [ ] Inspect Week 2 Monday, Week 6 final-mock day, and all six Saturdays. Confirm daily totals are exact, the final mock has no coach/Attempt B, and no Saturday carries weekday backlog.
- [ ] Inspect the interview prompt. Confirm coaching ends before a separate uninterrupted Attempt B and the handoff returns to the main Codex study task for transcript/analysis and Obsidian completion.
- [ ] Inspect weekly review and Phase 1 assessment. Confirm daily evidence does not directly update levels; weekly review separates level, confidence, trend, recency, self score, reviewer score, gap, and excluded evidence.
- [ ] Inspect Complete Roadmap, daily index, weekly review, and Phase 1 assessment. Confirm the exact `5+5+3+2` close, all approved adaptation rules, exact `0`–`4` scale, six English dimensions, monologue/listening rule, accent exclusion, and `Phase 1 target — six weeks` label. Confirm `GATE-NEXT-PHASE-PRIORITIES` has one owner and remains pending until an evidence-backed final review completes it.
- [ ] Re-run the archive checksum, Task 13 structural validator, and Task 12 export `--check` after the visual review. Save the successful date/time and any corrected links in `2026-08-28 - Phase 1 Six-Week Redesign Changes.md` using `apply_patch`, then re-run all applicable checks one final time. The change note is not one of the eleven hashed authorities, so its timestamp alone does not require regeneration; regenerate whenever the review changed any authoritative source.

## Completion evidence

This plan is complete only when all of the following are true:

- [ ] The exact former `Roadmap/` is present at `Roadmap.archive-20260828-month1-v2/`, its 21-file manifest verifies, and no archived byte changed.
- [ ] The clean active `Roadmap/` contains six weekly files, all core ledgers/tracks including `Next Phase Priorities`, package/change notes, the complete roadmap, byte-identical case/SQL assets, and all required templates.
- [ ] All 158 legacy stable IDs appear exactly once in the coverage ledger with status, owner, evidence, qualification, and reconciliation.
- [ ] All 158 canonical coverage-contract comments exactly preserve legacy objective, required output, pass criteria, AI/assessment constraints, allowed AI role, exercise type, contract, and timebox.
- [ ] Transition capacity is based only on 25 future weekdays and six future Saturdays: 5,220 minutes / 87 hours.
- [ ] Day 1–3 statuses match evidence exactly; unknown time and missing audio remain unknown/not assessed.
- [ ] The first future block is August 29, the first ordinary 60+120 weekday is August 31, and no pre-activation daily interview cycle is invented.
- [ ] The 30 interview questions are ordered; the first ten are recruiter/hiring-manager core questions; overflow is not compressed.
- [ ] Active learning material names Codex only, and the separate final Attempt B returns to the main task for analysis.
- [ ] The ten-action weekly pipeline rule starts with the first full operating week and distinguishes applications from substantive replies.
- [ ] All six Saturday contracts and four original no-coaching assessments retain exact timeboxes.
- [ ] All fourteen numeric targets are unchanged and use the active label `Phase 1 target — six weeks`.
- [ ] Every future weekday uses the exact `5,5,3,2` close; active contracts contain all approved adaptation rules, the exact `0`–`4` scale, and the six English dimensions with monologue/listening and accent semantics.
- [ ] `GATE-NEXT-PHASE-PRIORITIES` exists exactly once, is owned by `P1-2026-10-03-SAT120`, blocks closure while pending, and cannot complete without review evidence plus at least one Phase 2 priority.
- [ ] All legacy external resource links, case assets, SQL assets, output requirements, assessment constraints, and exit criteria remain traceable.
- [ ] All changed wikilinks resolve, no `Docs/` note points at a removed active Week 1–4 filename, and historical prose remains intact.
- [ ] The full semantic validator passes after the last textual and visual change.
- [ ] TAM Forge validates and consumes the exact raw `phase-1-transition-v1.json` root schema and sidecar; no parallel transformed transition envelope exists.
