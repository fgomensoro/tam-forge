# Flexible roadmap scheme

Date: 2026-09-11. Status: approved in brainstorming with Frank; tracked by the
"Flexible roadmap scheme" epic on GitHub.

## Problem

The study plan's structure (which blocks a day has, their minutes, the Obsidian file
and heading each block points at) lives in server configuration
(`config/tam-roadmap-task-map.yaml`, `config/releases/*`), not in the learner's
package. The importer only accepts schema 1 and hard-codes 24 study days, exactly
240 weekday minutes and at most 120 Saturday minutes (`roadmaps/parser.py`,
`learning/time_policy.py`, `learning/scheduling.py`, `today/repository.py`,
`RoadmapTaskConfig`). Frank's real plan is the six-week Phase 1 (60 interview + 30
pipeline + 75 learning + 15 close on weekdays, 120 on Saturdays). It cannot be
imported, and a change such as "two hours a day from tomorrow" needs a code release.

## Decisions (from the brainstorming)

1. Mixed authorship. An explicit scheme file in the Obsidian folder is the contract
   the app executes. AI generates or updates it on request; Frank always approves it
   before it runs.
2. Mid-plan changes are reforecasts: finished work stays as evidence, remaining days
   are redistributed from today under the new scheme, as a new roadmap version with
   lineage.
3. Fixed contract vocabulary. A block picks one of the existing contract types
   (sql, technical, pipeline, correction, case, communication, close and the
   Saturday contracts) and sets minutes and source. New types are added in the repo.
4. The app is the system of record (PostgreSQL and MinIO on the Hetzner host).
   Obsidian is only where the plan lives today: a package is imported once, and
   from then on the scheme, the notes and the evidence are created and edited in
   the app. Markdown export stays available as a readable backup, never as the
   source. (Revised the same evening: the first draft had the approved scheme
   written back into the vault.)
5. Version 1 models blocks and pointers only. The interview queue, the coverage
   ledger and exit criteria stay as prose; the interview block of a day points at
   the question that is due.

## The scheme file

`roadmap.yaml` is the import and export format of the scheme. On import it sits at
the root of the package (ZIP or folder); after import the scheme is stored with the
roadmap version and is edited in the app, and an export regenerates the file.

```yaml
schema_version: 1
program:
  key: tam_phase_1
  title: TAM Study Phase 1
rest_weekdays: [sunday]          # calendar days that never carry a study day
days:                             # ordered study days; dates come from the calendar
  - id: p1-w1-d01
    kind: weekday                 # weekday | assessment
    budget_minutes: 180
    blocks:
      - id: p1-w1-d01-interview
        type: communication       # one of the contract types in the release
        minutes: 60
        source: {file: docs/Interview Queue.md, heading: P1-Q01}
        objective: Answer P1-Q01 without notes; second attempt unscripted.
      - id: p1-w1-d01-pipeline
        type: pipeline
        minutes: 30
        source: {file: Phase 1 - Week 1 - Transition, foundations, and baseline.md, heading: Day 1}
        objective: One quality application or follow-up.
      - {id: p1-w1-d01-learning, type: technical, minutes: 75, source: {...}, objective: ...}
      - {id: p1-w1-d01-close, type: close, minutes: 15, source: {...}, objective: ...}
  - id: p1-w1-d06
    kind: assessment
    budget_minutes: 120
    blocks: [...]
```

Rules, all generic:

- Every `source.file` exists in the package and `source.heading` is a heading in it.
- Block `type` is a contract type of the release; `correction` blocks may be
  optional (`required: false`), every other block is required.
- Required minutes of a day sum to `budget_minutes`. No fixed totals anywhere.
- Ids are unique inside the package and match `^[a-z0-9][a-z0-9-]{2,63}$`.
- Wikilinks and Markdown links that leave the package are allowed as long as they
  are not the block's `source`; the parser stops rejecting them.
- Any number of days and weeks. `rest_weekdays` may be empty.

The contract types keep living in the release config (`tam-exercise-types.yaml`,
`tam-rubrics.yaml`, `tam-skills.yaml` and the contract section of the task map).
The `days:` section of the server-side task map retires once both known plans ship
as packages with their own `roadmap.yaml`.

## Calendar

`study_start_date` (from learner settings, set on activation) maps `days[0]` to the
first non-rest date on or after it; each following study day takes the next non-rest
date. `learning/scheduling.py` replaces "weeks times six plus weekday" with that walk,
and drops the Monday-start requirement. `time_policy.py` takes the day budget from
the stored day instead of `DayBudget("weekday", 240, ...)`; the Today
`target_minutes` cap becomes the day budget.

## Import pipeline

`parse_roadmap` gains a v2 path: when the package contains `roadmap.yaml` it is parsed
and validated with the rules above and projected onto the existing
`ParsedRoadmap` (tasks, contracts, resources, exit criteria). `TaskDefinition` and
`CurriculumNode` keep their shapes; `stable_id` comes from the scheme, day nodes get
`budget_minutes` and `kind`. The legacy v1 path stays until the old Month 1 map is
converted, then it is deleted together with the fixed-number checks.

`RoadmapTaskConfig` loses the Month 1 patterns (`m1-w[1-4]-d..`, `week <= 4`,
`day <= 24`) in favour of the scheme ids.

## AI assistance

A new agent role `planner` with a structured output that is exactly the scheme
model. Two operations, both started from the Roadmaps screen and both producing a
proposal the learner reviews before anything is written:

- Generate: input is the imported package files (already stored as an immutable
  snapshot in the object store) plus an optional instruction ("three hours a day,
  Saturdays are assessments"); output is a full scheme.
- Reforecast: input is the active version, the evidence of what is done, today's
  date and the instruction ("two hours a day from tomorrow"); output is a new scheme
  whose `days` are the remaining work redistributed from today, with
  `lineage.predecessor_version` set.

Validation runs on the proposal before it is shown; an invalid proposal is refused
and reported, never repaired silently. The role uses the existing bounded runtime,
subscription credential, quota and attestation gates; it is unavailable while
Claude is disabled and the screen says so.

## The macOS app

Import stays as it is: choose a ZIP or folder, review, approve, activate. The Review
step shows the scheme summary (days, budget per day, blocks per day, sources
resolved) beside the existing diff. When the package has no `roadmap.yaml`, the
Review step offers Generate: the planner proposes a scheme from the imported
files and the instruction, Frank edits or accepts it in the app, and the approved
scheme is stored with the version. Reforecast starts from the Roadmaps screen on
the active version and produces a new version the same way. Nothing is written
into the vault; Export produces a package (Markdown plus `roadmap.yaml`) for
backup or for reading in Obsidian.

## Migration

- A script converts `config/tam-roadmap-task-map.yaml` and
  `config/releases/phase-1-six-week-v1` into two packages with `roadmap.yaml`;
  both become test fixtures. Frank's vault folder (`Personal/TAM Practice`) is
  imported once with the generated scheme; the app owns it from then on.
- Existing roadmap versions in the database keep working; nothing is rewritten.

## Testing

- Parser v2 unit tests: both converted packages parse; missing file, missing
  heading, budget mismatch, duplicate id, unknown type each fail with a named issue.
- Scheduling tests: rest days, non-Monday start, reforecast lineage.
- Integration: import, approve, activate and open Today for a 180-minute day and for
  a 120-minute assessment day.
- Planner role tests with a fake transport: valid proposal accepted, invalid
  proposal refused, disabled Claude reported.
- Native parity fixture updated for the scheme summary, Generate and Export.

## Out of scope for this epic

Interview queue tracking, coverage ledger, the daily AI guide, progress statistics.
Each has its own epic.
