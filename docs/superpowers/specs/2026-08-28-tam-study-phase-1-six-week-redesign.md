# TAM Study Phase 1 — Six-Week Interview-First Redesign

**Date:** 2026-08-28

**Status:** Approved design

**Scope:** Canonical Obsidian roadmap, daily study process, interview practice, evidence, and the corresponding TAM Forge roadmap/configuration version

## 1. Decision summary

The existing four-week, 88-hour Month 1 roadmap becomes a six-week **Phase 1** with a sustainable fixed capacity:

- Monday–Friday: 180 focused minutes per day;
- Saturday: 120 focused minutes;
- Sunday: completely off;
- weekly capacity: 17 hours;
- six-week capacity: 102 hours;
- optional Week 7: completion-only safety week when the evidence or coverage gates are not met.

The Phase 1 clock is anchored to legacy Day 1, not restarted when this redesign is activated. Its nominal six-week calendar is August 24–October 3, 2026, with October 5–10 available as Week 7 when triggered. The 102 hours describe a clean six-week run in which every block uses the new model; they are not 102 additional future hours and are not used to calculate transition capacity. The transition ledger reserves every elapsed calendar block, records known and unknown historical time separately, and schedules future work only into weekday and Saturday blocks that remain through October 3.

The redesign does not lower any competency target or delete any required topic, output, assessment, or exit criterion. It changes the sequencing and weekday task boundaries. The old four-hour weekday packets are decomposed into smaller units, and related case work may continue into the aligned interview block. Time and evidence are counted only once.

First-round interview readiness and an active job pipeline run in parallel with the technical roadmap. The first 60 minutes of every weekday are protected for interview work. The remaining 120 minutes cover the career pipeline, the technical roadmap, and daily close-out.

All coaching and spoken-practice handoffs use **Codex**. Active Phase 1 workflow material must not direct the learner to Claude. This rule does not alter unrelated TAM Forge architecture decisions outside the learning-process scope.

## 2. Context and problem

The original roadmap schedules four focused hours each weekday and two hours on Saturday. In practice, the planned four hours routinely require more than four elapsed hours. At the same time, first-round questions, resume work, applications, recruiter replies, and spoken English practice must begin immediately because interviews commonly appear within roughly one week of entering the pipeline.

Reducing technical coverage or competency targets would undermine the purpose of the plan. Continuing with an overfull daily schedule would create time debt, missed interview preparation, unreliable evidence, and a false sense of falling behind. The solution is to spread the same required learning outcomes across six weeks, integrate related practice deliberately, and finish Phase 1 by evidence rather than calendar passage alone.

The learner is already in legacy Day 3. The redesign resumes from current evidence and checkpoints; it never resets completed work or demands retroactive daily interview cycles. Missing required outputs from Days 1–3 remain visible coverage items and are scheduled deliberately rather than treated as failures for dates that preceded the new operating model.

## 3. Goals

1. Keep the original fourteen competencies, scale, targets, curriculum content, artifacts, and assessments.
2. Make three focused weekday hours sustainable and enforce a hard stop.
3. Prepare one first-round interview answer every weekday through writing, coaching, speaking, and review.
4. Maintain a weekly target of ten quality applications or recruiter replies without rushing low-quality submissions.
5. Produce inspectable independent evidence and distinguish it from coached practice.
6. Measure English development without making correction intrusive or treating accent as a defect.
7. Keep Obsidian as the human-editable source of truth and make notes suitable for later flashcards.
8. Preserve roadmap lineage so every legacy requirement is visibly completed, scheduled, or pending.
9. Adapt when a real interview appears without silently suspending technical development.

## 4. Non-goals

- Lowering Phase 1 or final competency targets.
- Removing an original resource, required exercise, artifact, assessment, or exit criterion.
- Preserving every legacy weekday timebox minute-for-minute. The required work is preserved, but weekday activities are split and recomposed.
- Adding new study courses or a larger resource library during Phase 1.
- Scoring applications, reading, coached answers, or completion itself as demonstrated skill.
- Providing live AI assistance during a real interview.
- Automatically submitting job applications or contacting people without an explicit user action.
- Building a new voice platform or a Codex-to-Codex integration in this roadmap change. A structured manual task handoff is sufficient.

## 5. Capacity and accounting

### 5.1 Original allocation

| Category | Four-week allocation |
|---|---:|
| SQL and reconciliation | 15 h |
| Technical concepts | 15 h |
| TAM cases | 20 h |
| Communication | 15 h |
| Pipeline | 10 h |
| Review and notes | 5 h |
| Saturday assessments | 8 h |
| **Total** | **88 h** |

### 5.2 Nominal clean-run allocation

| Category | Six-week allocation |
|---|---:|
| Weekday interview cycle | 30 h |
| Weekday pipeline | 15 h |
| Weekday roadmap units | 37.5 h |
| Weekday notes and evidence | 7.5 h |
| Saturday assessment/control | 12 h |
| **Total** | **102 h** |

This allocation explains the balanced target state of a clean six-week run. Because the redesign activates during Day 3, the transition forecast recalculates the remaining category minutes from unfinished coverage and future calendar blocks. It must not assume that all thirty weekdays remain or that earlier legacy days used the new allocation.

The 37.5-hour roadmap block alone cannot contain the original 50 hours of SQL, technical concepts, and cases. The exact weekday reconciliation is:

| New block | Legacy and new coverage | Time |
|---|---|---:|
| Roadmap | SQL 15 h + technical concepts 15 h + case production 7.5 h | 37.5 h |
| Interview | communication 15 h + aligned case presentation/defense 12.5 h + additional first-round work 2.5 h | 30 h |
| Pipeline | original pipeline 10 h + expanded pipeline 5 h | 15 h |
| Notes/evidence | original review 5 h + expanded evidence close 2.5 h | 7.5 h |
| Saturday | canonical assessments 8 h + new diagnostics 4 h | 12 h |

All 30 interview hours use first-round interview form even when they also fulfill an original communication or case-defense requirement. Saturdays are already fully allocated and cannot also absorb displaced weekday coverage. This is integration, not double-counting: one output has one time record, one coverage record, and separate rubric evidence only for dimensions actually demonstrated.

The additional fourteen hours are not described as fourteen new interview hours. They also fund the expanded pipeline, evidence close-out, and two additional diagnostic Saturdays.

## 6. Phase completion and safety rule

Every required exit criterion has one of three evidence states:

- `Not assessed`: no valid independent attempt exists; the criterion cannot close and activates Week 7.
- `Assessed—not demonstrated`: a valid attempt exists but performance is below the criterion or target.
- `Demonstrated`: qualifying evidence meets the criterion.

Phase 1 is targeted for six weeks. At the end of Week 6, both `Not assessed` and `Assessed—not demonstrated` exit criteria activate Week 7 for one focused remediation and fresh transfer attempt. After Week 7, `Not assessed` still blocks closure. `Assessed—not demonstrated` may close only as **Phase 1 complete with gap** after a valid Week 7 retest; the gap becomes an explicit Phase 2 priority and is never reported as target attainment.

Phase 1 closes only when:

- every required legacy coverage record is complete;
- all four canonical assessments have been attempted under their original constraints;
- every final exit criterion is `Demonstrated` or, after the Week 7 rule above, `Assessed—not demonstrated`;
- the weekly evidence review has set the next-phase priorities.

At each weekly review, planned and actual focused minutes are compared. A variance above 15 percent triggers a reforecast and a provisional Week 7. Week 7 becomes active when required coverage is incomplete or an exit criterion needs assessment/remediation after Week 6. It is a completion week, not a reason to add new material. No target is lowered to avoid it.

No work is moved to Sunday.

## 7. Coverage ledger and migration

The redesign is governed by an explicit coverage ledger. Every required task from the canonical four-week source and `config/tam-roadmap-task-map.yaml` receives exactly one coverage record. Execution may span multiple atomic sessions, but the requirement is represented once and has one completion owner.

Each coverage record contains:

- legacy stable task ID, source path, and heading;
- required objective and output;
- original assessment or AI constraint;
- current status: `completed`, `in_progress`, `pending`, or `not_assessed`;
- new Phase 1 week, session, and block;
- planned and actual minutes;
- continuation checkpoint when split;
- evidence and Obsidian-note links;
- qualifying/nonqualifying evidence status;
- reconciliation note when wording or time changes without changing coverage.

The transition ledger is the first coverage-ledger view. It records:

- verified actual minutes and outputs for completed Days 1–2;
- completed, in-progress, and pending components of Day 3;
- remaining Week 1 requirements;
- the first session governed by the new `60 + 120` structure;
- elapsed calendar blocks, whether their actual time is verified or unknown;
- verified historical actual time for reporting only;
- unknown historical time as unknown, never as schedulable capacity;
- future schedulable capacity as `remaining weekday blocks × 180 minutes + remaining Saturday blocks × 120 minutes` through October 3;
- a remaining-category forecast built from unfinished coverage and those future blocks.

The weekly pipeline target is not applied retroactively. The transition week records actions actually completed; the ten-action target begins with the first full week operated under this design.

Validation must report:

- no orphaned required task;
- no duplicate completion claim;
- no assessment moved into coached mode;
- no completed current work reset to pending;
- no uncovered exit criterion.

Known current progress is imported from the existing Obsidian notes and learner confirmation. In particular, legacy Day 3 SQLBolt lessons 9–12 are complete, while the Day 3 idempotency application/case sequence continues from its saved checkpoint. Other status is taken from the existing Day 1–3 indices and notes, not inferred from calendar dates.

Historical imported roadmap versions remain immutable. The six-week roadmap is a new staged version. The human-facing term becomes **Phase 1 target — six weeks**. Existing stored `month_one_target` values may remain as compatibility fields until a separate migration changes their schema, but new active displays and notes use the Phase 1 label.

### 7.1 Preserved practice contract

The original non-negotiable learning rules remain active:

1. Required spoken and written outputs are in English.
2. At least 70 percent of focused time produces an output: a query, diagram, answer, decision, update, plan, or recording.
3. SQL, TAM cases, and interview Attempt A are committed before AI critique; AI does not create the first answer.
4. No new course or study-resource collection is added during Phase 1.
5. A spoken answer is recorded, reviewed once, and redone at most once; there is no endless polishing.
6. Only fictional, public, assigned-case, or safely redacted personal material is used. Credentials, confidential payloads, customer data, and employer-derived confidential material are excluded.
7. Sunday remains completely off, including from catch-up and study reminders.

## 8. Weekday operating model

### 8.1 First 60 minutes — interview cycle

| Phase | Time | Required result |
|---|---:|---|
| Select and frame | 5 min | One question, audience, purpose, and time limit |
| Independent Attempt A | 15 min | Written answer or structured answer plan committed before help |
| Self-review | 5 min | Strong point, weak point, and uncertainty |
| Codex practice task | 20 min | Interviewer/coach exchange under the approved prompt contract |
| Final Attempt B | 5 min | One uninterrupted spoken answer after coaching |
| Save handoff | 10 min | Feedback, evidence classification, transcript/recording status, and next correction |

Attempt A may qualify when it is independent, rubric-scored, and mapped through an approved exercise type. Same-question Attempt B is coached improvement evidence and cannot raise a competency estimate. A fresh later question is required to demonstrate transfer.

When the interview question is aligned to the day's TAM case, oral presentation or defense may satisfy the relevant case requirement. The coverage ledger names that relationship and prevents the minutes from being counted in both blocks.

### 8.2 Next 120 minutes — pipeline and roadmap

| Phase | Time | Required result |
|---|---:|---|
| Pipeline | 30 min | One or more saved quality actions with company, role, stage, and next action |
| Roadmap unit | 75 min | Assigned SQL, technical, case, artifact, or transfer unit with an exact checkpoint |
| Close-out | 15 min | Obsidian notes, evidence mapping, actual time, and next action |

A due correction may consume the first ten minutes of the roadmap unit. Exactly one correction is allowed. It never extends the day and does not affect demonstrated skill until transfer appears in a new independent scenario.

### 8.3 Hard-stop and carryover policy

- Stop at 180 focused minutes.
- Save the exact next observable action rather than writing “continue later.”
- Carry over at most one unfinished roadmap unit.
- Do not create a hidden backlog or compensate on Sunday.
- Do not invent work to fill unused time when the required output finishes early.
- When a task repeatedly exceeds its estimate, split or reforecast it at the weekly review.

### 8.4 Final-mock exception

The Week 6 final 45-minute behavioral mock replaces the ordinary weekday interview cycle for that day:

| Phase | Time |
|---|---:|
| Setup and seal prompt set | 5 min |
| Independent mock with live follow-ups | 45 min |
| Self-review, evidence save, and handoff | 10 min |

Codex may act as interviewer but provides no coaching before or during the sealed mock. There is no same-session Attempt B. The recording is qualifying mock-interview evidence when rubric-scored; feedback and any correction occur later.

## 9. Pipeline operating model

The target is ten quality applications or recruiter replies per week. Two weekday actions are the default, not a daily pass/fail rule. A carefully tailored application may use the whole 30-minute block and count as one; another weekday may contain more short, substantive replies or follow-ups.

Applications and recruiter replies are tracked separately. A quality pipeline action has:

- company and role;
- saved job-description snapshot or recruiter context;
- relevance and known gap;
- resume/story version used;
- completed action and date;
- current stage and exact next action.

A simple acknowledgement does not count as a recruiter reply. Research alone counts only when it creates the concrete artifact required by the legacy roadmap, such as a product analysis, evidence-gap map, company-specific answer, resume version, or interview-question set.

Weekly review considers conversion as well as volume:

- applications/replies;
- recruiter screens;
- hiring-manager interviews;
- next-round invitations;
- rejections or no response;
- recurring evidence gaps.

## 10. Six-week coverage architecture

Legacy weekday boundaries are not preserved. The following table is the coverage sequence; the detailed ledger owns the atomic mapping.

| New week | Canonical coverage | Saturday |
|---|---|---|
| 1 | Legacy Days 1–3 and start Day 4: SQL foundations through lesson 12, HTTP, diagnostics, idempotency, TMAY, story inventory, audience switching, and the beginning of webhooks | New baseline transfer assessment and fresh mock |
| 2 | Finish Days 4–5 and begin Days 7–8: webhooks, discovery, CARL story, retries, indeterminate outcomes, and backlog control | Canonical legacy Week 1 assessment |
| 3 | Finish Days 8–11: DLQs, payments, incident command, postmortem, and business value | Canonical legacy Week 2 assessment |
| 4 | Days 13–15 and start Day 16: OAuth, PKCE, webhook security, observability, SLOs, and the beginning of implementation planning | New midpoint transfer assessment and fresh mock |
| 5 | Finish Days 16–17 and begin Days 19–20: implementation, account strategy, TAM payment design, and launch judgment | Canonical legacy Week 3 assessment |
| 6 | Finish Days 20–23: launch decision, QBR, cross-functional conflict, portfolio judgment, dress rehearsal, and final behavioral mock | Canonical final assessment |

## 11. Saturday contracts

The two new diagnostic Saturdays use the control loop. The four legacy assessments retain their exact no-coaching structures.

| Saturday | Structure | Total |
|---|---|---:|
| Week 1 baseline | 35 min fresh mock; 45 min technical transfer; 20 min evidence scoring; 10 min pipeline review; 10 min next-week plan | 120 min |
| Legacy Week 1 | 30 min no-AI SQL; 50 min integrated case; 25 min behavioral; 15 min scoring | 120 min |
| Legacy Week 2 | 30 min no-AI SQL; 35 min case; 20 min portfolio; 20 min writing; 15 min scoring | 120 min |
| Week 4 midpoint | 35 min fresh mock; 45 min technical transfer; 20 min evidence scoring; 10 min pipeline review; 10 min next-week plan | 120 min |
| Legacy Week 3 | 30 min no-AI SQL; 35 min case; 20 min portfolio; 20 min executive/behavioral; 15 min scoring | 120 min |
| Final | 30 min no-AI SQL; 55 min portfolio-to-depth gauntlet; 20 min writing; 15 min scoring | 120 min |

Fresh diagnostic questions are not rehearsed variants of the weekday coached prompt. No Coach Mode or mid-attempt AI is allowed during a canonical assessment.

## 12. Interview progression

Interview progression is an ordered queue that starts with the first session governed by the new `60 + 120` model. It is not retroactively attached to elapsed calendar weekdays. The first ten operating weekdays front-load questions expected in recruiter and initial hiring-manager interviews. Later queue segments integrate technical TAM reasoning and senior judgment.

| Queue segment | Ordered five-question set |
|---|---|
| 1 | Tell me about yourself; current role and scope; why TAM; why change now; strongest relevant achievement |
| 2 | Why this company; difficult customer; conflict; failure and learning; ambiguity and prioritization |
| 3 | Major incident; API troubleshooting; uncertain ETA; payments/reconciliation; competing customers |
| 4 | Explain APIs/webhooks; OAuth/security; idempotency/retries; observability/SLOs; architecture trade-offs |
| 5 | Implementation leadership; launch decision; proactive account strategy; executive communication; influence without authority |
| 6 | Company-specific recruiter screen; fresh behavioral round; technical TAM round; portfolio/customer simulation; 45-minute final mock |

Each segment advances after five ordinary interview sessions, not after a calendar boundary. Existing pre-activation work may satisfy a queue item only when its saved evidence meets the same independent-attempt requirements. Otherwise the earliest unmet question remains next. The scheduled Week 6 final mock is a fixed roadmap event and may interrupt the queue; the queue resumes afterward. Any queue items that do not fit before October 3 continue in Week 7 or the ongoing interview-maintenance cycle rather than being compressed or deleted.

Answers are learned as flexible evidence and decision points, not memorized scripts. The same true story may support several questions, but each answer must address the actual prompt. Codex must not invent experience, metrics, decisions, or technical evidence.

When an interview is scheduled within 72 hours, the first 60-minute block becomes company- and role-specific. The protected 75-minute roadmap block remains. If the real interview occurs during study time, it counts toward the interview block; any additional displacement is recorded and reforecast rather than hidden.

After a real interview, the learner records:

- questions remembered;
- a concise reconstruction of each answer;
- difficult moments and missing evidence;
- interviewer signals and explicit feedback;
- outcome and next step.

No live AI answer assistance is allowed. Real-company or interviewer material is redacted before being saved or analyzed when necessary.

## 13. Codex spoken-practice contract

The main study task prepares a ready-to-use prompt for a fresh Codex task. The learner may open the new task directly or explicitly ask Codex to create it. The practice task acts as interviewer, customer, and low-intrusion English coach.

Every practice prompt specifies:

- role, company/scenario, audience, and question;
- total practice duration and phase timeboxes;
- the learner's permitted true story/context;
- the instruction to wait until the learner finishes;
- at most two routine follow-ups;
- no mid-answer correction;
- at most one content/structure correction and one English/delivery correction;
- an explicit end to coaching before the learner makes a separate uninterrupted recording;
- the required handoff format for the main study task.

English correction should preserve conversational flow. It targets only the highest-impact issue and does not interrupt an answer for small grammar errors.

The practice task returns:

1. question and duration;
2. concise attempt summary;
3. strongest demonstrated behavior;
4. one content or structure correction;
5. one English or delivery correction;
6. follow-up difficulty;
7. coaching completion and the target for the separate final recording;
8. one recommended transfer prompt;
9. a compact handoff suitable for the main study task.

After the coaching task returns this handoff, the learner records the separate uninterrupted Attempt B and sends its recording or transcript to the main study task. The main task analyzes it and completes the Obsidian record. The main study task remains the source of truth for progress and scoring; the practice task does not independently advance competency estimates.

## 14. Evidence and scoring

### 14.1 Competency scale

- 0: not demonstrated or no practical knowledge;
- 1: heavily assisted or basic concepts;
- 2: developing performance in a straightforward scenario;
- 3: independent performance under ambiguity and generally interview-ready;
- 4: strong under pressure and at professional depth.

### 14.2 Preserved targets

The human-facing middle column is renamed from Month 1 target to **Phase 1 target — six weeks**. Numerical values do not change.

| Competency | Baseline | Phase 1 target | Final target |
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

Portfolio Judgment remains a derived composite, not a fifteenth competency.

### 14.3 Attempt classification

- Daily independent written Attempt A may qualify after rubric scoring only for competencies and English dimensions actually demonstrated in writing; it cannot demonstrate spoken fluency, pronunciation, or listening.
- A same-question recording after coaching is Attempt B and cannot raise the estimated level.
- A new independent scenario is required to demonstrate transfer.
- A fresh Saturday mock or timed assessment may qualify.
- A real interview may qualify only from post-interview evidence; live AI help is forbidden.
- Reading, applications, completion, exposure, and guided practice remain visible but do not change skill level.
- Codex acting only as an interviewer during a sealed independent attempt is not coaching; feedback must wait until commitment.

Self-score and Codex rubric score remain separate. Neither is silently substituted for the other. Daily work records evidence; estimated levels are updated during the weekly review to avoid noisy daily score changes.

The weekly view shows:

- estimated level;
- Phase 1 target and gap;
- confidence;
- trend;
- recency;
- contributing evidence;
- excluded or discounted evidence;
- missing evidence as `Not assessed`.

### 14.4 English dimensions

TAM English retains six separate dimensions:

- communication effectiveness;
- fluency;
- accuracy;
- vocabulary;
- pronunciation/intelligibility;
- listening.

Unavailable dimensions are `N/A`. Listening is normally unavailable for a monologue. Accent is never scored. Daily coaching mentions at most one high-impact English or delivery correction.

## 15. Obsidian notes and handoffs

Obsidian remains the canonical human-editable learning source. Active roadmap material is versioned into a six-week Phase 1, while earlier imported snapshots remain historical.

The note system uses four connected record types.

### 15.1 Daily study index

- planned and actual focused minutes;
- completed outputs;
- coverage-ledger status;
- links to topic and interview notes;
- strongest evidence and repeated mistake;
- unfinished-work classification;
- exact next action.

### 15.2 Polished study notes

Each validated concept contains:

- concise rule;
- plain-English explanation;
- practical TAM example;
- boundary or common mistake;
- card-ready recall question and answer.

Rough learner attempts remain available as evidence, but the study section stores a corrected, card-ready model answer after review.

### 15.3 Interview-practice record

- prompt, audience, purpose, and time limit;
- independent written Attempt A;
- self-review;
- Codex practice-task handoff;
- final recording/transcript as Attempt B;
- one content correction;
- one English correction;
- one future transfer prompt;
- evidence qualification and competency mapping.

### 15.4 Evidence and pipeline records

- exercise type and mapping version;
- competencies tested;
- independent/coached status;
- self and reviewer scores;
- English dimensions assessed;
- recording/transcript version when present;
- application/recruiter action, stage, and next step.

The daily 15-minute close is fixed:

| Close phase | Time |
|---|---:|
| Record outputs and actual time | 5 min |
| Produce one to three card-ready recall items | 5 min |
| Map evidence to competencies | 3 min |
| Save the exact next action | 2 min |

If recording, transcription, or analysis is unfinished, the item is marked `pending` and the day stops. Raw transcripts are preserved; corrected transcripts create a distinct reviewed version.

## 16. Failure and adaptation rules

| Situation | Required behavior |
|---|---|
| A task exceeds its block | Save an exact checkpoint and stop; reforecast during weekly review |
| One tailored application consumes 30 minutes | Count the one quality action; redistribute the weekly target |
| Voice or recording fails | Preserve the written attempt; mark spoken dimensions `Not assessed` |
| Transcript is inaccurate | Preserve raw transcript and create a corrected reviewed version |
| Coaching happens before commitment | Mark the output coached/nonqualifying |
| Real interview is booked | Use the first 60 minutes for company-specific preparation; keep the roadmap floor |
| Real interview displaces more time | Record actual minutes and consume forecast capacity or Week 7; create no hidden debt |
| Weekly actual time is over estimate by more than 15% | Re-split work and provisionally activate the safety week |
| Required evidence is absent | Show `Not assessed`, activate the approved completion rule, and do not infer a score from confidence or completion |
| Saturday work is unfinished | Record the gap and continue the following week; Sunday remains off |

## 17. Source versioning and implementation surfaces

Implementation will require coordinated changes in two sources without rewriting history:

1. **Obsidian canonical roadmap**
   - replace active four-week Month 1 framing with six-week Phase 1 framing;
   - create the six weekly schedules and coverage ledger;
   - update the daily, weekly, spoken-practice, scorecard, and assessment templates;
   - preserve and link existing Day 1–3 notes;
   - ensure active spoken-practice material names Codex only.

2. **TAM Forge roadmap/configuration**
   - create a new roadmap/configuration version rather than mutating an imported historical snapshot;
   - map legacy stable task IDs to new atomic sessions with lineage;
   - expose the Phase 1 target label while preserving numerical values and historical compatibility;
   - represent the two new diagnostic Saturdays and Week 7 safety state;
   - update validation and tests for coverage, time budgets, scoring qualification, and source lineage.

The implementation plan must decide the exact file/package names and compatibility migration. This design fixes behavior and invariants, not the mechanical migration sequence.

## 18. Acceptance criteria

The redesign is complete only when all of the following are true:

1. Active Phase 1 is six weeks at 180 weekday minutes, 120 Saturday minutes, and Sunday off.
2. Every original required task, output, assessment, resource assignment, and exit criterion has one traceable coverage record.
3. Existing Day 1–3 progress is preserved and the learner resumes from the current Day 3 checkpoint.
4. All fourteen Phase 1 and final competency targets are numerically unchanged.
5. Ordinary weekdays implement the approved 60-minute independent-attempt, Codex-practice, and final-recording cycle; the final mock uses the sealed `5 + 45 + 10` exception.
6. Active spoken-practice prompts and notes use Codex, not Claude.
7. The first ten operating weekdays cover the ordered core recruiter and hiring-manager questions without retroactive or compressed sessions.
8. The weekly pipeline target is ten quality applications or recruiter replies, tracked separately with stages and next actions.
9. The four canonical Saturday assessments retain their required timeboxes and no-coaching rules.
10. The two added Saturdays provide fresh transfer evidence and weekly control without replacing canonical assessments.
11. Attempt A, Attempt B, transfer, and assessment evidence are classified correctly; coached work cannot raise skill estimates.
12. Weekly reporting separates level, confidence, trend, recency, self-score, reviewer score, and target gap.
13. Obsidian notes include corrected card-ready study answers while preserving original attempts as evidence.
14. No day creates hidden time debt, and no unfinished work is moved to Sunday.
15. Week 7 activates when required coverage/evidence remains incomplete or the approved reforecast rule requires it, and `Not assessed` cannot close the phase.
16. The transition ledger anchors Phase 1 to legacy Day 1, reserves elapsed blocks, separates verified and unknown historical time, and calculates capacity only from future calendar blocks.
17. The original English, output-production, independent-attempt, resource, privacy, redo, and Sunday rules remain enforceable.
18. Historical roadmap snapshots and evidence remain immutable and attributable to their original versions.

## 19. Approved design decisions

The user approved the following decisions in sequence:

- six-week Phase 1 with unchanged targets;
- three focused weekday hours, two Saturday hours, Sunday off;
- daily `60 + 120` structure;
- ten weekly quality applications/recruiter replies;
- one weekday question through writing, coaching, speaking, and handoff;
- evidence-based scoring across the original fourteen competencies;
- separate English dimensions and low-intrusion correction;
- six-week coverage map and Week 7 safety rule;
- Codex-only spoken-practice tasks;
- Obsidian notes designed for evidence and later flashcards.
