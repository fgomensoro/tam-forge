---
type: transition-ledger
as-of: 2026-08-28
activation-cutoff: 2026-08-28
phase: 1
roadmap-version: phase-1-six-week-v1
mapping-version: phase-1-transition-v1
status: active
future-app-source: true
---

# Phase 1 Transition Ledger

This ledger anchors Phase 1 to legacy Day 1. It preserves verified activation evidence, reserves every elapsed calendar block, and schedules work only into future blocks through 2026-10-03. [[Roadmap/docs/Coverage Ledger]] remains the single migration authority for legacy requirements.

## Activation accounting rules

- Historical actual time is for reporting only. Unknown historical minutes remain `unknown` and never become schedulable capacity.
- An elapsed day receives neither 180 nor 240 actual minutes merely because that amount was planned.
- Future capacity starts on 2026-08-29 and is calculated only from the explicit future-block calendar below.
- Completed work stays complete. Open work resumes from its saved checkpoint and is not repeated to manufacture time.

## Elapsed blocks

| Date | Calendar state | Known work | Verified time | Scheduling treatment |
|---|---|---|---|---|
| 2026-08-24 | elapsed/reserved | no dated Day note | unknown | zero future capacity |
| 2026-08-25 | elapsed/reserved | Day 1 artifacts | SQL only: 40 focused, 45–50 elapsed; full day unknown | zero future capacity |
| 2026-08-26 | elapsed/reserved | no dated Day note | unknown | zero future capacity |
| 2026-08-27 | elapsed/reserved | Day 2 artifacts | full day unknown | zero future capacity |
| 2026-08-28 | elapsed/reserved; activation cutoff | Day 3 partial artifacts | unknown | zero future capacity |

The five rows above are reserved elapsed blocks. Their unknown time is outside every subtraction in the future forecast.

## Day 1–3 activation status

These tables are the immutable 2026-08-28 activation view. Each legacy row links to its canonical heading in [[Roadmap/docs/Coverage Ledger]]; later execution updates the canonical coverage record without rewriting this snapshot.

### Day 1 — 2026-08-25

| Coverage item | Legacy ID and ledger heading | Activation status | Actual min | Current evidence | Qualification and boundary | Exact continuation |
|---|---|---|---:|---|---|---|
| SQL foundations | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-sql]] | `completed` | 40 | [[Docs/Day 1 - SQL Foundations Study Notes]] | `mixed`; guided validation limits qualification | none; preserve completion |
| HTTP foundations | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-technical]] | `completed` | unknown | [[Docs/HTTP, TCP, and TLS - TAM Interview Question Bank]], [[Docs/HTTP Troubleshooting Checklist - Headers and Status Codes]], [[Docs/Day 1 - Study Index]] | `mixed`; one cross-day HTTP completion claim | none; preserve completion |
| Career pipeline | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-pipeline]] | `completed` | unknown | [[Docs/2026-08-25 - API and Fintech TAM Market Requirements]] | `qualifying`; saved market-requirements artifact, not five submitted applications | none; preserve completion |
| Optional correction | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-correction]] | `pending` | unknown | [[Docs/Day 1 - Study Index]] | `not_applicable`; no due correction or explicit skip is proven | `P1-2026-08-31-R75`; zero extra minutes unless due within the block |
| Integration case | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-case]] | `completed` | unknown | [[Docs/Shopify to Odoo Integration Case]], [[Docs/Day 1 - Study Index]] | `mixed`; case artifact and coached practice complete, uninterrupted final recording absent and nonqualifying | none; preserve artifact completion |
| Tell Me About Yourself | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-communication]] | `pending` | unknown | [[Docs/Day 1 - Tell Me About Yourself Practice Status]] | `not_assessed`; both the first recording and unscripted Attempt B are absent | `P1-2026-08-31-I60`; resume as P1-Q01 without retroactive failure |
| Daily close | [[Roadmap/docs/Coverage Ledger#m1-w1-d01-close]] | `completed` | unknown | [[Docs/Day 1 - Daily Scorecard]] | `not_assessed`; retrospective record exists, but no score is inferred | none; preserve record |

Day 1 full-day actual time remains unknown. Only the SQL note verifies 40 focused minutes and 45–50 elapsed minutes.

### Day 2 — 2026-08-27

| Coverage item | Legacy ID and ledger heading | Activation status | Actual min | Current evidence | Qualification and boundary | Exact continuation |
|---|---|---|---:|---|---|---|
| SQL joins and `NULL` | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-sql]] | `completed` | unknown | [[Docs/Day 2 - SQL Joins and NULLs Study Notes]] | `mixed`; completed with guided validation | none; preserve completion |
| HTTP troubleshooting | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-technical]] | `completed` | unknown | [[Docs/HTTP Troubleshooting Checklist - Headers and Status Codes]], [[Docs/Day 2 - Study Index]] | `qualifying`; no second claim for the Day 1 HTTP artifact | none; preserve completion |
| Story-to-requirements mapping | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-pipeline]] | `completed` | unknown | [[Docs/Day 2 - Story to TAM Requirements Mapping]] | `qualifying`; no application submission is inferred | none; preserve completion |
| Optional correction | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-correction]] | `pending` | unknown | [[Docs/Day 2 - Study Index]] | `not_applicable`; no due correction or explicit skip is proven | `P1-2026-09-02-R75`; zero extra minutes unless due within the block |
| Northstar case | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-case]] | `completed` | unknown | [[Docs/Northstar Scenario 1 - API Down but Monitoring Green]], [[Docs/Day 2 - Study Index]] | `nonqualifying`; guided artifact completion is not independent performance | none; preserve artifact completion |
| Story catalog and communication | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-communication]] | `completed` | unknown | [[Docs/Day 2 - Behavioral Story Catalog]], [[Docs/Day 2 - Story to TAM Requirements Mapping]], [[Docs/Day 2 - Spoken Practice Handoff]] | `mixed`; written catalog and mapping complete | none for the legacy row; supplemental voice feedback remains separate |
| Daily close | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-close]] | `completed` | unknown | [[Docs/Day 2 - Daily Scorecard]] | `mixed`; historical scores do not become current competency estimates | none; preserve record |
| Supplemental spoken-practice feedback | [[Roadmap/docs/Coverage Ledger#m1-w1-d02-communication]] | `pending` | unknown | [[Docs/Day 2 - Spoken Practice Handoff]] | `not_assessed`; no returned handoff, final uninterrupted recording, transcript, or two corrections exist | wait for a returned handoff; this creates no additional legacy coverage row |

Day 2 full-day actual time remains unknown. Missing supplemental feedback stays pending and cannot qualify the guided Northstar artifact.

### Day 3 — 2026-08-28

| Coverage item | Legacy ID and ledger heading | Activation status | Actual min | Current evidence | Qualification and boundary | Exact continuation |
|---|---|---|---:|---|---|---|
| SQL aggregation | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-sql]] | `completed` | unknown | [[Docs/Day 3 - SQL Aggregation and Query Execution Study Notes]] | `mixed`; SQLBolt 9–12 complete with guided validation | none; do not redo SQL |
| Idempotency and retry safety | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-technical]] | `in_progress` | unknown | [[Docs/Day 3 - Idempotency and Retry Safety Study Notes]] | `mixed`; reading and committed recall complete, application sequence and teach-back `pending`/`not_assessed` | `P1-2026-08-31-R75`; write the duplicate-producing application sequence, then teach back |
| Résumé bullets | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-pipeline]] | `pending` | unknown | no activation artifact | `not_assessed`; no prior output inferred | `P1-2026-08-31-P30`; rewrite three bullets as scope, action, and measurable outcome |
| Optional correction | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-correction]] | `pending` | unknown | no activation artifact | `not_applicable`; no due correction is proven | `P1-2026-09-01-R75`; zero extra minutes and only within the block if due |
| Duplicate-order case | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-case]] | `pending` | unknown | no activation artifact | `not_assessed`; no independent case output exists | `P1-2026-09-01-R75`; produce the case, with presentation aligned to `P1-2026-09-01-I60` |
| Audience-switching recordings | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-communication]] | `pending` | unknown | no activation artifact | `not_assessed`; all three recordings and any Attempt B are absent | `P1-2026-09-01-I60`; explain the incident separately to engineer, VP Engineering, and CFO |
| Daily close | [[Roadmap/docs/Coverage Ledger#m1-w1-d03-close]] | `pending` | unknown | no activation artifact | `not_assessed`; no close or actual-time record exists | `P1-2026-09-01-C15`; remove details that do not serve each audience and save the next action |

Day 3 resumes from idempotency application, then teach-back. Completed SQL is not reopened.

## Future schedulable capacity

```text
25 future weekdays × 180 minutes = 4,500 minutes
6 future Saturdays × 120 minutes = 720 minutes
Total future schedulable capacity = 5,220 minutes = 87 hours
```

The first future item is the 2026-08-29 baseline diagnostic. The first weekday governed by the `60 + 120` structure is 2026-08-31.

| Date | Kind | Planned min | Capacity state |
|---|---|---:|---|
| 2026-08-29 | saturday | 120 | future-schedulable |
| 2026-08-31 | weekday | 180 | future-schedulable |
| 2026-09-01 | weekday | 180 | future-schedulable |
| 2026-09-02 | weekday | 180 | future-schedulable |
| 2026-09-03 | weekday | 180 | future-schedulable |
| 2026-09-04 | weekday | 180 | future-schedulable |
| 2026-09-05 | saturday | 120 | future-schedulable |
| 2026-09-07 | weekday | 180 | future-schedulable |
| 2026-09-08 | weekday | 180 | future-schedulable |
| 2026-09-09 | weekday | 180 | future-schedulable |
| 2026-09-10 | weekday | 180 | future-schedulable |
| 2026-09-11 | weekday | 180 | future-schedulable |
| 2026-09-12 | saturday | 120 | future-schedulable |
| 2026-09-14 | weekday | 180 | future-schedulable |
| 2026-09-15 | weekday | 180 | future-schedulable |
| 2026-09-16 | weekday | 180 | future-schedulable |
| 2026-09-17 | weekday | 180 | future-schedulable |
| 2026-09-18 | weekday | 180 | future-schedulable |
| 2026-09-19 | saturday | 120 | future-schedulable |
| 2026-09-21 | weekday | 180 | future-schedulable |
| 2026-09-22 | weekday | 180 | future-schedulable |
| 2026-09-23 | weekday | 180 | future-schedulable |
| 2026-09-24 | weekday | 180 | future-schedulable |
| 2026-09-25 | weekday | 180 | future-schedulable |
| 2026-09-26 | saturday | 120 | future-schedulable |
| 2026-09-28 | weekday | 180 | future-schedulable |
| 2026-09-29 | weekday | 180 | future-schedulable |
| 2026-09-30 | weekday | 180 | future-schedulable |
| 2026-10-01 | weekday | 180 | future-schedulable |
| 2026-10-02 | weekday | 180 | future-schedulable |
| 2026-10-03 | saturday | 120 | future-schedulable |

No Sunday is schedulable.

## Remaining-category forecast

The forecast starts with all unfinished coverage records that have future owners in [[Roadmap/docs/Coverage Ledger]], then reserves the rest of each future block category for the Phase 1 operating model. It does not calculate `102 hours - historical time`. The 1,630 minutes not yet mapped to legacy rows are reserved future capacity, not free time or a retrospective completion claim.

| Future category | Unfinished legacy mapped min | Reserved future min not mapped to legacy rows | Planned future min | Available future min | Variance, available minus planned | Permitted carryover | Exact next checkpoint |
|---|---:|---:|---:|---:|---:|---|---|
| Interview cycle | 690 | 810 | 1,500 | 1,500 | 0 | none | `P1-2026-08-31-I60`: complete independent P1-Q01 Tell Me About Yourself cycle |
| Pipeline | 540 | 210 | 750 | 750 | 0 | none | `P1-2026-08-31-P30`: rewrite three résumé bullets as scope, action, and measurable outcome |
| Roadmap | 1,610 | 265 | 1,875 | 1,875 | 0 | at most one unfinished R75 unit | `P1-2026-08-31-R75`: idempotency application sequence, then teach-back; do not redo SQL |
| Close-out | 270 | 105 | 375 | 375 | 0 | none | `P1-2026-08-31-C15`: record outputs, actual time, evidence, and exact next action |
| Saturday assessment/control | 480 | 240 | 720 | 720 | 0 | none | `P1-2026-08-29-SAT120`: complete the baseline diagnostic |
| **Total** | **3,590** | **1,630** | **5,220** | **5,220** | **0** | **one roadmap unit maximum** | **Start `P1-2026-08-29-SAT120`; then `P1-2026-08-31-I60`** |

Owner-family reconciliation from the Coverage Ledger is exact:

- Interview legacy allocation: 655 minutes in `I60` owners plus 35 minutes in `MOCK60` = 690 minutes.
- Pipeline legacy allocation: 540 minutes in `P30` owners.
- Roadmap legacy allocation: 1,610 minutes in `R75` owners.
- Close-out legacy allocation: 270 minutes in `C15` owners.
- Saturday legacy allocation: 480 minutes in canonical `SAT120` assessment owners.
- Total unfinished legacy allocation: 3,590 minutes.
- Full future capacity reconciliation: 3,590 mapped + 1,630 reserved = 5,220 minutes.

Unknown historical minutes are excluded from both sides of this forecast. A weekly review replaces forecast values with recorded future actuals; it never estimates the elapsed August 24–28 blocks.

## Transition policy

1. No interview cycle is created retroactively for an elapsed block. Missing Day 1–3 interview evidence stays visible as pending or not assessed and receives a future owner only where the Coverage Ledger assigns one.
2. The learner does not receive a retroactive ten-action pipeline failure. The ten-quality-action target begins in Week 2, the first full week under this operating model, starting 2026-08-31.
3. A Saturday cannot absorb a displaced weekday or its unfinished work. Sunday remains entirely off.
4. Stop a weekday at 180 focused minutes and save one exact next observable action. At most one unfinished roadmap unit may carry forward; no interview, pipeline, close-out, or Saturday backlog is hidden behind that allowance.
5. Planned and actual focused minutes are compared at each weekly review. Variance above 15% requires reforecasting and makes Week 7 provisional.
6. Week 7 becomes active only after Week 6 when required coverage is incomplete or an exit criterion is `Not assessed` or `Assessed—not demonstrated` and needs assessment or remediation. It is completion-only: no new material, compressed evidence, or lowered target.
7. After a valid Week 7 retest, `Assessed—not demonstrated` may close only as Phase 1 complete with gap. `Not assessed` still blocks closure.

## Immediate handoff

- First future session: `P1-2026-08-29-SAT120`, baseline diagnostic.
- First `60 + 120` weekday: 2026-08-31.
- First Roadmap checkpoint: finish the idempotency application sequence, then teach it back from [[Docs/Day 3 - Idempotency and Retry Safety Study Notes]].
- SQL checkpoint: [[Docs/Day 3 - SQL Aggregation and Query Execution Study Notes]] is complete; do not repeat SQLBolt 9–12.
