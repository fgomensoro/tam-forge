---
type: roadmap-package-contract
phase: 1
version: phase-1-six-week-v1
status: active
future-app-source: true
---

# Phase 1 Package Contents

The planned active `Roadmap/` tree contains exactly **34 files**: 7 at the roadmap root, 2 cases, 8 docs, 2 SQL assets, and 15 templates.

## Planned active tree

### Roadmap root — 7 files

- [[Roadmap/README.md|README.md]]
- [[Roadmap/Phase 1 - Week 1 - Transition, foundations, and baseline.md|Phase 1 - Week 1 - Transition, foundations, and baseline.md]]
- [[Roadmap/Phase 1 - Week 2 - Webhooks, discovery, and retry control.md|Phase 1 - Week 2 - Webhooks, discovery, and retry control.md]]
- [[Roadmap/Phase 1 - Week 3 - Distributed failures, incidents, and payments.md|Phase 1 - Week 3 - Distributed failures, incidents, and payments.md]]
- [[Roadmap/Phase 1 - Week 4 - OAuth, observability, and midpoint transfer.md|Phase 1 - Week 4 - OAuth, observability, and midpoint transfer.md]]
- [[Roadmap/Phase 1 - Week 5 - Implementation, account strategy, and launch judgment.md|Phase 1 - Week 5 - Implementation, account strategy, and launch judgment.md]]
- [[Roadmap/Phase 1 - Week 6 - QBR, portfolio judgment, and final assessment.md|Phase 1 - Week 6 - QBR, portfolio judgment, and final assessment.md]]

### `cases/` — 2 files

- [[Roadmap/cases/Northstar Case.md|cases/Northstar Case.md]]
- [[Roadmap/cases/Portfolio Triage Cases.md|cases/Portfolio Triage Cases.md]]

### `docs/` — 8 files

- [[Roadmap/docs/Phase 1 - Complete Roadmap.md|docs/Phase 1 - Complete Roadmap.md]]
- [[Roadmap/docs/Coverage Ledger.md|docs/Coverage Ledger.md]]
- [[Roadmap/docs/Transition Ledger.md|docs/Transition Ledger.md]]
- [[Roadmap/docs/Interview Queue.md|docs/Interview Queue.md]]
- [[Roadmap/docs/Next Phase Priorities.md|docs/Next Phase Priorities.md]]
- [[Roadmap/docs/Package Contents.md|docs/Package Contents.md]]
- [[Roadmap/docs/Portfolio Judgment Track.md|docs/Portfolio Judgment Track.md]]
- [[Roadmap/docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md|docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md]]

### `sql/` — 2 files

- [[Roadmap/sql/setup.sql|sql/setup.sql]]
- [[Roadmap/sql/tasks.md|sql/tasks.md]]

### `templates/` — 15 files

- [[Roadmap/templates/account_plan.md|templates/account_plan.md]]
- [[Roadmap/templates/daily_scorecard.md|templates/daily_scorecard.md]]
- [[Roadmap/templates/daily_study_index.md|templates/daily_study_index.md]]
- [[Roadmap/templates/discovery_notes.md|templates/discovery_notes.md]]
- [[Roadmap/templates/evidence_record.md|templates/evidence_record.md]]
- [[Roadmap/templates/incident_update.md|templates/incident_update.md]]
- [[Roadmap/templates/interview_practice_record.md|templates/interview_practice_record.md]]
- [[Roadmap/templates/polished_study_note.md|templates/polished_study_note.md]]
- [[Roadmap/templates/phase1_assessment.md|templates/phase1_assessment.md]]
- [[Roadmap/templates/pipeline_action.md|templates/pipeline_action.md]]
- [[Roadmap/templates/portfolio_triage.md|templates/portfolio_triage.md]]
- [[Roadmap/templates/real_interview_debrief.md|templates/real_interview_debrief.md]]
- [[Roadmap/templates/spoken_practice_session.md|templates/spoken_practice_session.md]]
- [[Roadmap/templates/story_catalog.md|templates/story_catalog.md]]
- [[Roadmap/templates/weekly_review.md|templates/weekly_review.md]]

## Provenance and rewrite boundary

Four active assets are byte-identical copies of their archived versions:

- [[Roadmap/cases/Northstar Case.md|cases/Northstar Case.md]]
- [[Roadmap/cases/Portfolio Triage Cases.md|cases/Portfolio Triage Cases.md]]
- [[Roadmap/sql/setup.sql|sql/setup.sql]]
- [[Roadmap/sql/tasks.md|sql/tasks.md]]

The six-week schedule, ledgers, supporting docs, README, and templates are rewritten or new Phase 1 material. They do not overwrite or modify the archived Month 1 package.

## Historical archive contract

`Roadmap.archive-20260828-month1-v2/` is historical, immutable, and verified by its adjacent 21-line `Roadmap.archive-20260828-month1-v2.sha256` manifest. Manifest paths are relative to the archive root, so verification runs from inside `Roadmap.archive-20260828-month1-v2/` against the adjacent manifest.

## Activation companion, not roadmap ZIP content

These artifacts live at the TAM Practice vault root, outside `Roadmap/`:

- [[Exports/phase-1-transition-v1.json|Exports/phase-1-transition-v1.json]]
- [[Exports/phase-1-transition-v1.json.sha256|Exports/phase-1-transition-v1.json.sha256]]
- [[Exports/phase-1-transition-v1.schema.json|Exports/phase-1-transition-v1.schema.json]]
- [[Exports/build_phase1_transition_export.py|Exports/build_phase1_transition_export.py]]
- [[Exports/test_phase1_transition_export.py|Exports/test_phase1_transition_export.py]]

The normal TAM Forge roadmap ZIP contains only supported `Roadmap/**/*.md` and `Roadmap/**/*.sql` files. It excludes vault-root `Exports/`. The separate transition activation path receives the exact raw canonical JSON bytes plus the matching `.sha256` file.

TAM Forge consumes that canonical v1 JSON directly. No transformed, redacted, renamed-field, or parallel-envelope input is accepted.

The producer is the only writer for the JSON and sidecar. Editing any of its eleven authoritative Markdown sources requires rerunning `--write`, `--check`, and the sidecar verification before handoff. TAM Forge must validate the checked-in producer schema byte-for-byte, verify every current `source_hashes` entry and the sidecar, require exact roadmap/mapping versions `phase-1-six-week-v1` / `phase-1-transition-v1`, and consume the raw root fields without translation. A backward-incompatible v1 change requires a new schema/export filename and mapping version; ordinary evidence/status refreshes retain v1 and receive a new deterministic content hash.
