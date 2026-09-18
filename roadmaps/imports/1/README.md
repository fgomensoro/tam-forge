---
type: roadmap-index
phase: 1
version: phase-1-six-week-v1
source-revision: 3
status: active
start: 2026-08-24
nominal-end: 2026-10-03
future-app-source: true
---

# Phase 1 — Six-Week TAM Interview Roadmap

> [!important] SQL platform amendment — September 15
> [[Docs/2026-09-15 - SQL Platform Plan]] controls all future SQL reading, practice and assessment across the six weeks. Use SQLBolt for foundations and DataLemur for progressive browser exercises. Older Northstar task references and SQL contract text below are retained as coverage lineage, not active platform assignments. Preserve completed evidence, skill objectives, time limits and independence rules.


> [!important] Active execution dates
> [[Docs/2026-09-08 - Active Study Reforecast]] supersedes the baseline dates below for future study. Use its stream-by-stream mapping; retain these dates and owner tokens as planning history.


This is the active index for Phase 1. Obsidian Markdown is the authoritative human source for the roadmap.

## Cadence and capacity

| Day | Fixed focused time |
|---|---:|
| Monday-Friday | 180 minutes per day |
| Saturday | 120 minutes |
| Sunday | Entirely off |

The nominal clean-run capacity is **102 hours** across six complete weeks. Because this version activates after elapsed Day 1–3 calendar blocks, the future schedulable capacity at activation is **5,220 minutes / 87 hours**. These figures are intentionally distinct: 102 hours describes the clean six-week model, while 87 hours is the actual future capacity remaining after the 2026-08-28 cutoff.

Sunday is entirely off. No study, catch-up, displaced work, or reminders move into Sunday.

## Current checkpoint

Current study checkpoint: [[Docs/2026-09-15 - SQL Platform Plan]]. September 15 resumes catch-up SQL with DataLemur Cities With Completed Trades. Subquery/union checks are complete with coaching; the browser exercise is pending. See [[Docs/2026-09-14 - Study Index]] for interview and technical assessment evidence.

## Six-week schedule

1. [[Roadmap/Phase 1 - Week 1 - Transition, foundations, and baseline.md|Week 1 — Transition, foundations, and baseline]]
2. [[Roadmap/Phase 1 - Week 2 - Webhooks, discovery, and retry control.md|Week 2 — Webhooks, discovery, and retry control]]
3. [[Roadmap/Phase 1 - Week 3 - Distributed failures, incidents, and payments.md|Week 3 — Distributed failures, incidents, and payments]]
4. [[Roadmap/Phase 1 - Week 4 - OAuth, observability, and midpoint transfer.md|Week 4 — OAuth, observability, and midpoint transfer]]
5. [[Roadmap/Phase 1 - Week 5 - Implementation, account strategy, and launch judgment.md|Week 5 — Implementation, account strategy, and launch judgment]]
6. [[Roadmap/Phase 1 - Week 6 - QBR, portfolio judgment, and final assessment.md|Week 6 — QBR, portfolio judgment, and final assessment]]

## Operating records

- [[Roadmap/docs/Coverage Ledger.md|Coverage Ledger]]
- [[Roadmap/docs/Transition Ledger.md|Transition Ledger]]
- [[Roadmap/docs/Interview Queue.md|Interview Queue]]
- [[Roadmap/docs/Next Phase Priorities.md|Next Phase Priorities]]
- [[Roadmap/docs/Portfolio Judgment Track.md|Portfolio Judgment Track]]
- [[Roadmap/docs/Package Contents.md|Package Contents]]
- [[Roadmap/docs/2026-08-28 - Phase 1 Six-Week Redesign Changes.md|2026-08-28 — Phase 1 Six-Week Redesign Changes]]
- [[Roadmap/docs/Phase 1 - Complete Roadmap.md|Phase 1 — Complete Roadmap]]

## Active practice assets

### Cases

- [[Roadmap/cases/Northstar Case.md|Northstar Case]]
- [[Roadmap/cases/Portfolio Triage Cases.md|Portfolio Triage Cases]]

### SQL

- [[Docs/2026-09-15 - SQL Platform Plan]] — active SQL assignments across all six weeks.
- SQLBolt for reading/foundation practice; DataLemur for progressive browser exercises.
- [[Roadmap/sql/tasks]] and [[Roadmap/sql/setup.sql]] — historical reference, not required execution.

### Templates

- [[Roadmap/templates/account_plan.md|account_plan]]
- [[Roadmap/templates/daily_scorecard.md|daily_scorecard]]
- [[Roadmap/templates/daily_study_index.md|daily_study_index]]
- [[Roadmap/templates/discovery_notes.md|discovery_notes]]
- [[Roadmap/templates/evidence_record.md|evidence_record]]
- [[Roadmap/templates/incident_update.md|incident_update]]
- [[Roadmap/templates/interview_practice_record.md|interview_practice_record]]
- [[Roadmap/templates/polished_study_note.md|polished_study_note]]
- [[Roadmap/templates/phase1_assessment.md|phase1_assessment]]
- [[Roadmap/templates/pipeline_action.md|pipeline_action]]
- [[Roadmap/templates/portfolio_triage.md|portfolio_triage]]
- [[Roadmap/templates/real_interview_debrief.md|real_interview_debrief]]
- [[Roadmap/templates/spoken_practice_session.md|spoken_practice_session]]
- [[Roadmap/templates/story_catalog.md|story_catalog]]
- [[Roadmap/templates/weekly_review.md|weekly_review]]

## Activation exports

These artifacts live at the vault-root `Exports/` path. They are activation companions, not members of `Roadmap/`.

- [[Exports/phase-1-transition-v1.json|phase-1-transition-v1.json]]
- [[Exports/phase-1-transition-v1.json.sha256|phase-1-transition-v1.json.sha256]]
- [[Exports/phase-1-transition-v1.schema.json|phase-1-transition-v1.schema.json]]
- [[Exports/build_phase1_transition_export.py|build_phase1_transition_export.py]]
- [[Exports/test_phase1_transition_export.py|test_phase1_transition_export.py]]

Never edit the generated JSON or sidecar directly. Any edit to one of the eleven authoritative source notes makes the producer's `--check` fail until `--write` and `--check` are rerun. Run `--check` immediately before TAM Forge handoff and reject activation unless `roadmap_version` is `phase-1-six-week-v1` and `mapping_version` is `phase-1-transition-v1`. Ordinary status/evidence updates keep v1 and generate new deterministic bytes and a new content hash; a backward-incompatible field or semantic change requires a new schema/export filename and mapping version.

## Preserved practice rules

1. Required spoken and written outputs are in English.
2. At least 70% of focused time produces an output: a query, diagram, answer, decision, update, plan, or recording.
3. SQL, TAM cases, and interview Attempt A are committed before AI critique; AI does not create the first answer.
4. No new course or resource collection is added during Phase 1.
5. Record once, review once, and redo at most once; no endless polishing.
6. Use only fictional, public, assigned, or safely redacted material. Never use credentials, confidential payloads, customer data, or employer-derived confidential material.
7. Sunday is fully off, including catch-up and reminders.

Active spoken-practice work uses Codex only. Independent attempts must remain independent, and coached work must remain labeled as coached.

## Exit states and Week 7

Every exit criterion has one of three states:

- `Not assessed`: no valid independent attempt exists; the criterion cannot close and activates Week 7.
- `Assessed—not demonstrated`: a valid attempt exists but performance is below the criterion or target; the criterion activates Week 7 and may close only as **Phase 1 complete with gap** after a valid Week 7 retest.
- `Demonstrated`: qualifying evidence meets the criterion.

A weekly planned-versus-actual variance above 15% triggers a reforecast and makes Week 7 provisional. Week 7 becomes active only after Week 6 when required coverage remains incomplete or an exit criterion needs assessment or remediation. It is a completion and remediation week, not permission to add material, compress evidence, or lower targets. **No target is lowered.**

## Historical source

- [[Roadmap.archive-20260828-month1-v2/README|Archived Month 1 Version 2]]
- Archive checksum manifest: `Roadmap.archive-20260828-month1-v2.sha256`

The archive is historical and immutable. Active progress and evidence belong in this Phase 1 package and its linked operating records.

## Standing task-budget updates

Apply [[AGENTS]] for every study task: show the remaining task list and assigned minutes at day start and after each task; show measured actuals/variance or unknown; flag overruns before extending. Reading, coaching and validation share the stated task budget. Separate the real date from carryover labels.
