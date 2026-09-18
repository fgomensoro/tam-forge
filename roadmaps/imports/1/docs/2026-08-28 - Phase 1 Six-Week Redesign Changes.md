---
type: roadmap-migration-record
phase: 1
version: phase-1-six-week-v1
date: 2026-08-28
status: active
future-app-source: true
---

# Phase 1 Six-Week Redesign Changes

## Approved design

- Date: 2026-08-28
- Approved design path: `/Users/frank/Documents/ChatGPT/TAM Project/docs/superpowers/specs/2026-08-28-tam-study-phase-1-six-week-redesign.md`
- Active index: [[Roadmap/README|Phase 1 active README]]
- Historical source: [[Roadmap.archive-20260828-month1-v2/README|Archived Month 1 Version 2]]

Framing change: Month 1/four weeks to Phase 1/six weeks. All numerical competency targets, required legacy coverage, outputs, assessments, resources, practice rules, and exit criteria remain unchanged. No target is lowered.

## Archive and Task 1 result

- Archive path: `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2`
- External manifest path: `/Users/frank/Library/Mobile Documents/iCloud~md~obsidian/Documents/Frank/Personal/TAM Practice/Roadmap.archive-20260828-month1-v2.sha256`
- Task 1 archived the exact 21-file source set; both pre-rename and post-rename checks returned 21/21 OK; the old active path was absent afterward.

The archive and its external manifest are historical verification material and remain immutable.

## Transition accounting

- Activation cutoff: 2026-08-28.
- First future block: 2026-08-29.
- First ordinary weekday: 2026-08-31.
- Future schedulable capacity through 2026-10-03: **5,220 minutes / 87 hours**.

Day 1-3 migration preserves recorded facts and evidence. Unknown historical time remains unknown. The redesign does not invent retroactive interview cycles and does not mark retroactive pipeline failure. Current coverage and the transition forecast are recorded in [[Roadmap/docs/Coverage Ledger|Coverage Ledger]] and [[Roadmap/docs/Transition Ledger|Transition Ledger]].

## Active workflow boundary

Active spoken practice uses Codex only. The active workflow preserves independent Attempt A before critique, labels coached work accurately, and requires fresh independent evidence for transfer.

## Export and TAM Forge boundary

Obsidian Markdown is the authoritative human source. These vault-root activation artifacts carry that source into TAM Forge:

- [[Exports/phase-1-transition-v1.json|Exports/phase-1-transition-v1.json]] is generated from the authoritative Obsidian Markdown.
- [[Exports/phase-1-transition-v1.json.sha256|Exports/phase-1-transition-v1.json.sha256]] is the sidecar that binds the exact JSON bytes.
- [[Exports/phase-1-transition-v1.schema.json|Exports/phase-1-transition-v1.schema.json]] defines the raw v1 contract.

None of these activation artifacts are normal roadmap ZIP members.

Single-schema boundary: TAM Forge consumes the raw v1 JSON directly. There is no second envelope, field translation, transformed copy, renamed-field variant, or parallel input contract.

Refresh/version rule: never edit the JSON or sidecar directly. Any edit to one of the eleven authoritative source notes invalidates `--check` until the producer runs in `--write` and `--check` modes again and the sidecar is verified. Immediately before TAM Forge activation or refresh, require exact `phase-1-six-week-v1` / `phase-1-transition-v1` versions, the same checked-in schema bytes, current source hashes, canonical JSON bytes, and matching sidecar. Ordinary status/evidence changes preserve v1 but produce a new content hash. Any backward-incompatible field or semantic change requires a new export/schema filename and mapping version.

## Rollback instruction — do not execute

Rollback requires explicit user approval. Do not execute it as part of activation or verification.

1. Preflight all sibling paths. Require the current active `Roadmap/`, `Roadmap.archive-20260828-month1-v2/`, and `Roadmap.archive-20260828-month1-v2.sha256` to exist. Require `Roadmap.rollback-quarantine-phase1-six-week-v1` not to exist. Abort immediately on any collision or failed preflight; never merge or overwrite paths.
2. Move, never delete, the current active `Roadmap/` to the exact sibling destination `Roadmap.rollback-quarantine-phase1-six-week-v1`.
3. From inside `Roadmap.archive-20260828-month1-v2/`, verify all 21 archived files against the external `../Roadmap.archive-20260828-month1-v2.sha256` manifest. Require 21/21 OK; abort immediately if any check fails.
4. Confirm the destination `Roadmap/` is absent, then rename the verified `Roadmap.archive-20260828-month1-v2/` directory to `Roadmap/`. Abort rather than merge or overwrite if the destination exists.
5. From inside the restored `Roadmap/`, verify all restored bytes again against the same external `../Roadmap.archive-20260828-month1-v2.sha256` manifest. Require 21/21 OK and abort immediately on any failure.
6. Retain both `Roadmap.rollback-quarantine-phase1-six-week-v1/` and `Roadmap.archive-20260828-month1-v2.sha256`. Never touch either older backup: `Roadmap.backup-20260825-090253/` or `Roadmap.backup-20260825-115232/`.

## Obsidian navigation review

- Successful review: 2026-08-28 19:38 PDT in Obsidian 1.13.7.
- All README Markdown targets opened with their exact expected Obsidian note titles: six weeks, eight operating records, both cases, SQL tasks, all 15 templates, and the archived README.
- The six non-Markdown targets (`setup.sql` and the five vault-root export/schema/script artifacts) did not create a blank or untitled note. Their paths also passed the full static target-resolution check.
- The Day 3 index, SQL note, idempotency note, archived source, transition ledger, and coverage ledger all opened in Obsidian. The saved next action remains the idempotency application sequence, not repeated SQL lessons.
- Each of the 11 migrated legacy-day notes opened together with its archived source and current coverage target. Historical prose/status remains unchanged.
- The remaining activation review passed: exact weekday and Saturday budgets, no Saturday backlog carryover, the uncoached final mock, Codex coaching before a separate Attempt B, main-task transcript/analysis handoff, weekly scoring dimensions, the `5+5+3+2` close, adaptation rules, `0`–`4` scale, six English dimensions, monologue/listening semantics, accent exclusion, the `Phase 1 target — six weeks` label, and the single-owner pending `GATE-NEXT-PHASE-PRIORITIES` contract.
- No link correction was required during the live review. AppleScript was used only as the approved fallback after Obsidian's accessibility state became stale during repeated navigation.
