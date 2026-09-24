# Task guide and live coach

Date: 2026-09-23. Status: approved design, first of two pull requests.

## Problem

The activity screen shows a form and a contract, but not what to do first, second and
third, and the Coach only answers after Attempt A is committed and only in `coach` or
`tutor` blocks. On an interview block, whose role is `interviewer`, the contract asks
for a "coaching handoff" that the app refuses. The learner ends up asking an outside
assistant what the task is and how to work through it.

The study system the learner runs today (recall question first, an independent
attempt, hints only when asked, corrections afterwards, everything recorded with the
assistance it used) is what the app should carry. This spec covers the two pieces that
make the screen self-guiding: a step guide and a Coach that is present from the start.

Out of scope, for the second pull request: the voice interviewer inside the task,
Attempt B, the debrief and class-analysis buttons, the 5+5+3+2 close, and importing the
reforecast.

## A. The step guide (macOS only)

A `TaskGuide` panel sits at the top of the activity screen's main column, above the
working output. It lists the block's steps and marks the current one.

Steps are a pure function of the block type, defined in Swift
(`Features/Activities/TaskGuide.swift`). They are the block's procedure spelled out,
not anything the AI produces:

| Block | Steps |
|---|---|
| communication_spoken | Read the question · Independent Attempt A, written or recorded · Commit · Self-review · Coach: two corrections |
| technical_learning | Read the source · Hide the source · Recall attempt · Commit · Self-review · Coach and note |
| sql | Read the problem · Query and run · Explain and business meaning · Commit · Self-review · Coach |
| tam_case | Read the prompt · Discovery and assumptions · Final artifact · Commit · Self-review · Coach |
| career_pipeline | Pick the action · Do it · Record it · Commit |
| correction_warmup | Read the correction · Attempt · Commit · Self-review |
| daily_close | Outputs and actual time, 5 min · Recall items, 5 min · Competency evidence, 3 min · Exact next action, 2 min · Commit |
| saturday_assessment | Read the prompt · Independent attempt, no AI · Commit · Self-review |

The current step is derived from the activity, also in Swift:

- `ready`, `active`, `paused`: the attempt step, or the step before it when the
  block needs the source hidden and it is not (`technical_learning` with
  `sourceHidden == false`).
- `output_committed`: Self-review.
- `self_review_complete` and later: the Coach step when the block has one, otherwise
  the last step (done).
- `incomplete` and `superseded`: no current step; the panel shows the list dimmed.

Each row is a `Text` inside a plain `HStack`; the panel uses `.organicCard` with the
radius the handoff gives the activity cards and `OrganicStatusDot` for the marker.
Identifier `activityTaskGuide` on the panel, `activityTaskGuideStep` on the current
row. No existing identifier changes.

## B. The Coach from the start (backend and macOS)

### Rule change

Today the rule "commit before coaching" is enforced by refusing to speak. It becomes
"coaching before the commit is recorded as assistance". The learner may talk to the
Coach at any point; whatever help arrives before the commit lands on the activity's
`assistance_mode`, the attempt copies it at commit time, and the reviewer and the
evidence service already treat `hint_ladder` as assisted work. Nothing new has to
score or penalise; the field was waiting for a writer.

### Backend

- `agents/roles/contracts.py`: `ROLES_BEFORE_COMMITMENT` gains `AgentRole.COACH`.
  The reviewer, tutor and analyst keep requiring a commit.
- `agents/roles/coach.py`:
  - `COACHING_ROLES` becomes `{"coach", "tutor", "interviewer"}`. `none`, `planner`,
    `reviewer` and `analyst` stay refused, so a sealed assessment stays sealed.
  - `CoachRequest` gains `phase: Literal["before_commit", "after_commit"]`, derived by
    the caller from `committed_attempt` being empty.
  - `CoachTurn` gains `hint_given: bool = False`.
  - `CoachService.turn` no longer refuses an empty `committed_attempt`.
  - `render_coach_prompt` states the phase. Before the commit: open with one recall
    question for the block's objective; answer a request for help with the smallest
    hint that unblocks, never the full answer; say when a hint was given by setting
    `hint_given`. After the commit: unchanged behaviour.
  - `validate_coach_turn` refuses `hint_given: true` after the commit. It does not
    try to detect a full answer in the text; the validator stays structural and the
    prompt carries the rule.
- `agents/sdk_runtime.py`: `COACH_SYSTEM_PROMPT` describes both phases.
- `coaching/service.py`:
  - `send` drops the `output_committed_at is None` conflict.
  - Before the commit, after a successful turn: `assistance_mode` becomes
    `coach_preparation` if it is `none`, and `hint_ladder` if the turn set
    `hint_given`. The write happens on the locked `ActivityInstance` in the same
    transaction as the messages. `hint_ladder` never downgrades back.
  - `next_step_for` returns, before the commit, "Write your independent attempt; ask
    the coach for a hint only when stuck." and keeps the later steps.
  - `CoachThreadResponse` gains `assistance_mode` so the app can show it.
- `coaching/routes.py`: unchanged shape; `committed` stays in the response.

### macOS

- `CoachPanel` renders in the rail for every editable state, not only after the
  commit. Its idle copy becomes "Start with the coach: it asks a recall question first
  and gives hints only when you ask. Help before the commit is recorded as
  assistance." The button stays `coachOpen`. Nothing calls the Coach on task open;
  the first turn is the learner's message.
- `CoachThreadModel.canSend` drops the `committed` requirement.
- When `assistance_mode` is not `none`, the panel shows one line:
  "Recorded as assisted: coach preparation" or "... hint ladder".
- The lock label "AI feedback remains unavailable until a server-backed self-review"
  is removed; the guide's Self-review step carries that meaning.
- `CoachAPIError.notAllowed` copy becomes "This block is sealed: no coaching."

## Data and errors

No migration. `assistance_mode` already allows the two values written here. A Coach
failure before the commit leaves `assistance_mode` untouched, because the write follows
the turn inside one transaction. Claude disabled or the transport missing keeps the
existing `CoachUnavailable` path.

## Testing

Backend unit tests:

- `agents/roles/test_coach.py`: interviewer blocks allowed; `none` refused; a turn with
  an empty committed attempt runs in phase `before_commit`; `hint_given` after the
  commit is refused by the validator.
- `coaching/test_routes.py` or a new `coaching/test_service.py`: send before the
  commit succeeds and sets `coach_preparation`; a turn with `hint_given` sets
  `hint_ladder`; a later turn without a hint keeps `hint_ladder`; a turn after the
  commit leaves `assistance_mode` alone; the attempt committed afterwards carries the
  mode.
- `agents/roles/test_contracts` equivalent: the Coach may prepare a prompt with
  `committed=False`; the reviewer still may not.

macOS unit tests (`TAMForgeTests`):

- `TaskGuideTests`: steps per block; current step for each state, including the
  hidden-source case and the `incomplete` case.
- `CoachThreadModelTests`: `canSend` with `committed == false`.

The UI suite runs in CI only. `git diff --stat origin/main -- apps/macos/TAMForgeUITests/`
must stay empty.

## Not changed

The reviewer, the evidence formulas, the roadmap scheme, the task map, the Today
policy, the state machine, and the OpenAPI cookie parameters. The Coach still cannot
mark anything done; its output shape gains one boolean and nothing else.
