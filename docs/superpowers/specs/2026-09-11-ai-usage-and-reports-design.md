# Where AI runs, which model, and what the reports say

Date: 2026-09-11. Status: agreed with Frank in brainstorming; feeds milestone M5
(epics #263 Claude in production, #264 Coach, #265 recording, #266 interviews,
#267 English classes, #268 reports, #269 progress).

## Constraints that decide the models

- The backend reaches Claude through the Claude Agent SDK bound to Frank's own
  subscription (`docs/runbooks/claude-subscription.md`). Paid API credentials are
  refused by design. So the model list is whatever the subscription exposes; the
  compatibility probe records `supported_models` and refuses a pin it cannot
  resolve. Pin the strongest Opus-class model the probe resolves today
  (`claude-opus-5` as of this writing) and re-run the probe when a stronger one
  appears in the list.
- One job at a time (`max_concurrent_jobs = 1`, 24 turns, 10 minutes wall time).
  The subscription is not a pool: every AI point below is a job in a queue, so
  cheap points must be short and heavy points must be worth their slot.
- Each study block carries `allowed_ai_role` (none, planner, tutor, coach,
  interviewer, reviewer, analyst). No AI point may run inside a block whose role
  forbids it; Saturday assessments are `none` until the work is committed.
- Speech-to-text and embeddings never leave the machines Frank owns.

## The AI map

| # | Point | Role | Model | Effort | When it runs | Notes |
|---|-------|------|-------|--------|--------------|-------|
| 1 | Transcription | local | whisper.cpp `small.en` q5_1 + Silero VAD on the Mac | n/a | while recording and after upload | already built; upgrade only through the benchmark script |
| 2 | Pronunciation diagnostic | local | existing pipeline on the Mac | n/a | after a spoken attempt | already built |
| 3 | Memory embeddings | local server | pinned embedding model on the host | n/a | after evidence, transcripts, debriefs | already built; a model change re-embeds everything |
| 4 | Planner: generate or reforecast a scheme | `planner` | Opus | high | on demand from Roadmaps, a few times a month | structured output validated by the scheme model; never applied without approval |
| 5 | Coach: daily guide chat | `coach` / `tutor` | Opus | medium; low for short acknowledgements | during a block that allows it, interactive | writes evidence and notes only; refuses in `none` blocks; latency matters more than depth |
| 6 | Evidence capture chores (turn "done, here is my note" into an evidence record, tag transcript turns, extract numbers) | `analyst` | Haiku 4.5 | n/a (no thinking) | inside the Coach flow and after transcripts | high volume, low stakes, keeps the queue moving; validated by schema, never judged by this model |
| 7 | Practice interviewer | `interviewer` | Opus | high | interview blocks only | one question at a time, bounded follow-ups, no coaching |
| 8 | Reviewer: rubric scoring of a spoken attempt or written evidence | `reviewer` | Opus | xhigh | asynchronously after a transcript is finalized or evidence is committed | writes skill score events; fixed prompt and rubric per contract so scores are comparable week to week |
| 9 | Real interview debrief | `reviewer` | Opus | xhigh | once per real interview, on request | long context: whole transcript plus the interview record and the job requirements from the pipeline |
| 10 | English class analysis | `reviewer` | Opus | high | once per class | fluency, vocabulary, recurring errors; compares with previous classes; feeds TAM English |
| 11 | Weekly report | `analyst` | Opus | xhigh | Sunday evening, scheduled | reads structured aggregates plus memory retrieval, not raw audio |
| 12 | Monthly report | `analyst` | Opus | max | last day of the month, scheduled | same inputs plus targets and coverage; the most expensive job of the month and worth it |
| 13 | Saturday assessment | none | no AI | n/a | never during the assessment | reviewer (#8) scores it after commit |

Rules of thumb: anything that judges, plans or writes to Frank runs on Opus.
Anything that only reshapes data into a schema runs on Haiku 4.5 and is validated
by code. Sonnet 5 is not used unless a point proves too slow on Opus and too weak
on Haiku; that is a measured decision, not a default. Effort is tuned per point
and recorded in the prompt registry so a change is a reviewed diff.

Thinking is adaptive on every Opus point. Every point has a structured output
schema and a fixed system prompt cached across jobs. Every job records model,
effort, tokens and duration in `model_runs`, so the weekly report can also say
what the AI cost in quota.

## What the reports say

Both reports have three parts. The past says what happened, the present says
what it means, the future says what to do about it. A report never changes the
plan; every suggestion becomes a proposal Frank approves in the app.

### Weekly report (Sunday evening)

Past, what happened this week:
- Days studied versus planned, minutes real versus planned per block, streak.
- Evidence committed per contract type; recordings made and transcribed; Saturday
  assessment result; real interviews and English classes held.
- Corrections closed and carried over.

Present, what it means:
- The 14 TAM skills with direction (up, flat, down) and the evidence behind each
  move, quoted, not summarized.
- Recurring patterns from transcripts: filler and hedging, missing structure,
  questions asked before proposing fixes, English delivery issues.
- Strongest and weakest contract types this week, and how that compares with the
  previous four weeks (trend, not only the delta).

Future, what to do:
- Next week's plan preview from the active roadmap: days, hours, the interview
  questions due, the Saturday contract.
- Projection per skill against the month-one and final targets at the current
  pace, with the skills at risk first and the estimated week each target is reached.
- Interview readiness: per skill against the requirements of the opportunities in
  the pipeline, and prep suggestions for interviews already scheduled.
- Adjustment proposals: what to repeat, move or drop, offered as a reforecast Frank
  can approve; and one decision Frank has to make this week.
- Risks: backlog, streak at risk, evidence gaps that block a Saturday.

### Monthly report (last day of the month)

Everything the weekly report has, over the month, plus:
- Each skill against baseline, month-one target and final target, with the
  trajectory chart data and the largest gaps first.
- Coverage of the roadmap: requirements covered, missing, and whether the exit
  criteria of the phase are met with evidence.
- The best evidence of the month per skill (portfolio candidates).
- Assessment trend across Saturdays and interview trend across real interviews.
- Recommendation for the next month: keep, reforecast, or change the scheme, with
  the reasoning, and the next-phase priorities.

Delivery: stored in the app under Progress and emailed (epic #268). The email is
the report; the app keeps the history and the links to the evidence.
